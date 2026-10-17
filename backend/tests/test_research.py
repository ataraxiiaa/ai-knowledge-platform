import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app import dispatcher
from app.core.config import settings
from app.models.chunks import Chunk
from app.models.research import ResearchDispatch, ResearchJob, ResearchJobSource
from app.schemas.documents import SearchResult
from app.services import research, research_logic
from conftest import TestingSessionLocal
from test_ingestion import finish_job, ingestion_client, owner, pdf_bytes


@pytest.fixture
def research_client(ingestion_client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "research-test-model")
    monkeypatch.setattr(research, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(research_logic, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSessionLocal)
    return ingestion_client


def ready_document(client, db_session):
    headers, workspace = owner(client)
    response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                           files={"file": ("paper.pdf", pdf_bytes())})
    document = finish_job(client, headers, response, db_session)
    chunk = db_session.scalar(select(Chunk))
    return headers, workspace, document, chunk


def create_job(client, headers, workspace, query="Compare the approaches in these papers."):
    response = client.post(f"/workspaces/{workspace}/research-jobs", headers=headers,
                           json={"query": query})
    assert response.status_code == 202, response.text
    return response


def fake_operations(monkeypatch, chunk, document):
    def retrieve(question, top_k, workspace_id, db):
        return [SearchResult(chunk_id=chunk.id, document_id=chunk.document_id,
            filename=document["filename"], page=chunk.page, chunk_index=chunk.chunk_index,
            content=chunk.content, similarity=.9, metadata={})]
    monkeypatch.setattr(research_logic, "retrieve_passages", retrieve)
    def complete(system, payload, max_tokens):
        if system == research_logic.PLAN_PROMPT:
            return json.dumps({"questions": ["What approach is proposed?", "What are its limits?",
                                            "How do the approaches compare?"]})
        return json.dumps({"sections": [
            {"question_index": 1, "claims": [{"text": "A puppy is a young dog.",
                "evidence": [{"source_id": 1, "quote": "A puppy is a young dog."}]}]},
            {"question_index": 2, "claims": []},
            {"question_index": 3, "claims": [{"text": "The approach concerns puppies.",
                "evidence": [{"source_id": 1, "quote": "A puppy is a young dog."}]}]},
        ]})
    monkeypatch.setattr(research_logic, "complete_json", complete)


def test_research_acceptance_ownership_and_validation(research_client, db_session, monkeypatch):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    other, other_workspace = owner(research_client, "other-research@example.com")
    assert research_client.post(f"/workspaces/{other_workspace}/research-jobs", headers=other,
        json={"query": "Compare papers"}).status_code == 422
    assert research_client.post(f"/workspaces/{workspace}/research-jobs", headers=other,
        json={"query": "Compare papers"}).status_code == 404
    assert research_client.post(f"/workspaces/{workspace}/research-jobs",
        json={"query": "Compare papers"}).status_code == 401
    for query in (" ", "x" * 1025):
        assert research_client.post(f"/workspaces/{workspace}/research-jobs", headers=headers,
            json={"query": query}).status_code == 422
    monkeypatch.setattr(settings, "LLM_MODEL", "")
    assert research_client.post(f"/workspaces/{workspace}/research-jobs", headers=headers,
        json={"query": "Compare papers"}).status_code == 503
    monkeypatch.setattr(settings, "LLM_MODEL", "research-test-model")
    response = create_job(research_client, headers, workspace)
    assert response.json()["status"] == "queued" and response.json()["current_stage"] == "PLANNING"
    assert response.json()["attempt_count"] == 0 and response.json()["result"] is None
    assert db_session.scalar(select(func.count()).select_from(ResearchDispatch)) == 1
    assert research_client.get(response.headers["location"], headers=other).status_code == 404
    assert research_client.get(response.headers["location"], headers=headers).status_code == 200
    assert len(research_client.get(f"/workspaces/{workspace}/research-jobs", headers=headers).json()) == 1
    assert research_client.get(f"/workspaces/{other_workspace}/research-jobs", headers=other).json() == []


def test_research_pipeline_citations_and_completed_retention(research_client, db_session, monkeypatch):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    fake_operations(monkeypatch, chunk, document)
    response = create_job(research_client, headers, workspace)
    job_id = response.json()["id"]
    dispatch_id = str(db_session.scalar(select(ResearchDispatch.id)))
    research.process_research_job(job_id, dispatch_id)
    result = research_client.get(response.headers["location"], headers=headers).json()
    assert result["status"] == "completed" and result["current_stage"] == "COMPLETED"
    assert result["attempt_count"] == 1 and result["evidence"] is None
    assert result["result"]["sections"][0]["claims"][0]["citation_ids"] == [1]
    assert result["result"]["sources"][0]["page"] == 1
    assert result["result"]["sources"][0]["quote"] == "A puppy is a young dog."
    assert result["result"]["gaps"] == ["What are its limits?"]
    research.process_research_job(job_id, dispatch_id)
    db_session.expire_all()
    assert db_session.scalar(select(ResearchJob)).attempt_count == 1
    assert db_session.scalar(select(func.count()).select_from(ResearchDispatch)) == 0
    assert db_session.scalar(select(func.count()).select_from(ResearchJobSource)) == 1
    assert research_client.delete(f"/workspaces/{workspace}/documents/{document['id']}",
        headers=headers).status_code == 204
    retained = research_client.get(response.headers["location"], headers=headers).json()
    assert retained["status"] == "completed" and retained["result"] == result["result"]


def test_deleted_source_invalidates_running_research(research_client, db_session, monkeypatch):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    fake_operations(monkeypatch, chunk, document)
    response = create_job(research_client, headers, workspace)
    dispatch_id = str(db_session.scalar(select(ResearchDispatch.id)))
    def delete_during_draft(query, plan, evidence):
        assert research_client.delete(f"/workspaces/{workspace}/documents/{document['id']}",
            headers=headers).status_code == 204
        return {"sections": [{"question_index": 1, "claims": []},
                             {"question_index": 2, "claims": []}]}
    monkeypatch.setattr(research, "draft_report", delete_during_draft)
    research.process_research_job(response.json()["id"], dispatch_id)
    result = research_client.get(response.headers["location"], headers=headers).json()
    assert result["status"] == "failed" and "deleted" in result["error"]
    assert result["result"] is None
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(ResearchDispatch)) == 0


def test_transient_research_failure_retries_from_saved_stage(research_client, db_session, monkeypatch):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    fake_operations(monkeypatch, chunk, document)
    response = create_job(research_client, headers, workspace)
    job_id = response.json()["id"]
    dispatch_id = str(db_session.scalar(select(ResearchDispatch.id)))
    original_draft = research.draft_report
    calls = 0
    def fail_once(query, plan, evidence):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise research_logic.ResearchTransientError("secret provider detail")
        return original_draft(query, plan, evidence)
    monkeypatch.setattr(research, "draft_report", fail_once)
    research.process_research_job(job_id, dispatch_id)
    db_session.expire_all()
    job = db_session.scalar(select(ResearchJob))
    assert job.status == "retrying" and job.current_stage == "SYNTHESIZING"
    assert job.plan and job.evidence and "secret" not in job.error
    assert job.attempt_count == 1
    research.process_research_job(job_id, dispatch_id)
    db_session.expire_all()
    assert db_session.scalar(select(ResearchJob)).attempt_count == 1
    past = research.now() - timedelta(seconds=1)
    db_session.execute(update(ResearchJob).values(next_retry_at=past))
    db_session.execute(update(ResearchDispatch).values(due_at=past))
    db_session.commit()
    class Queue:
        def enqueue(self, *args, **kwargs):
            return None
    monkeypatch.setattr(dispatcher, "research_queue", Queue)
    assert dispatcher.dispatch_research_once() == 1
    research.process_research_job(job_id, dispatch_id)
    db_session.expire_all()
    job = db_session.scalar(select(ResearchJob))
    assert job.status == "completed" and job.attempt_count == 2 and calls == 2


def test_invalid_citation_fails_without_report(research_client, db_session, monkeypatch):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    fake_operations(monkeypatch, chunk, document)
    monkeypatch.setattr(research, "draft_report", lambda *_: {"sections": [
        {"question_index": 1, "claims": [{"text": "Invented fact", "evidence": [
            {"source_id": 1, "quote": "fabricated quote"}]}]},
        {"question_index": 2, "claims": []},
        {"question_index": 3, "claims": []}]})
    response = create_job(research_client, headers, workspace)
    dispatch_id = str(db_session.scalar(select(ResearchDispatch.id)))
    research.process_research_job(response.json()["id"], dispatch_id)
    result = research_client.get(response.headers["location"], headers=headers).json()
    assert result["status"] == "failed" and result["result"] is None
    assert result["attempt_count"] == 1


def test_expired_research_lease_is_recovered(research_client, db_session, monkeypatch):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    response = create_job(research_client, headers, workspace)
    old_token = uuid.uuid4()
    db_session.execute(update(ResearchJob).values(status="running", attempt_count=1,
        lease_token=old_token, lease_expires_at=research.now() - timedelta(seconds=1)))
    db_session.commit()
    assert dispatcher.recover_expired_research() == 1
    db_session.expire_all()
    job = db_session.scalar(select(ResearchJob))
    assert job.status == "retrying" and job.current_stage == "PLANNING"
    assert not research.touch(uuid.UUID(response.json()["id"]), old_token)


def test_research_dispatch_survives_redis_outage(research_client, db_session, monkeypatch):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    response = create_job(research_client, headers, workspace)
    def offline():
        raise ConnectionError("Redis unavailable")
    monkeypatch.setattr(dispatcher, "research_queue", offline)
    assert dispatcher.dispatch_research_once() == 0
    db_session.expire_all()
    dispatch = db_session.scalar(select(ResearchDispatch))
    assert dispatch.publish_attempts == 1 and dispatch.published_at is None
    dispatch.due_at = research.now() - timedelta(seconds=1)
    db_session.commit()
    sent = []
    class Queue:
        def enqueue(self, *args, **kwargs):
            sent.append(args)
    monkeypatch.setattr(dispatcher, "research_queue", Queue)
    assert dispatcher.dispatch_research_once() == 1
    assert sent[0][0] == "app.services.research.process_research_job"
    assert research_client.get(response.headers["location"], headers=headers).json()["status"] == "queued"


def test_research_recovery_exhaustion_is_terminal(research_client, db_session):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    response = create_job(research_client, headers, workspace)
    db_session.execute(update(ResearchJob).values(status="running", attempt_count=3,
        lease_token=uuid.uuid4(), lease_expires_at=research.now() - timedelta(seconds=1),
        current_stage="SYNTHESIZING", plan={"questions": ["one", "two"]}))
    db_session.commit()
    assert dispatcher.recover_expired_research() == 1
    db_session.expire_all()
    job = db_session.scalar(select(ResearchJob))
    assert job.status == "failed" and job.current_stage == "SYNTHESIZING"
    assert job.completed_at is not None and job.lease_token is None
    assert db_session.scalar(select(func.count()).select_from(ResearchDispatch)) == 0


def test_source_deleted_during_retrieval_cannot_enter_report(research_client, db_session, monkeypatch):
    headers, workspace, document, chunk = ready_document(research_client, db_session)
    fake_operations(monkeypatch, chunk, document)
    response = create_job(research_client, headers, workspace)
    dispatch_id = str(db_session.scalar(select(ResearchDispatch.id)))
    original = research_logic.retrieve_passages
    def stale_hit(question, top_k, workspace_id, db):
        result = original(question, top_k, workspace_id, db)
        if research_client.get(f"/workspaces/{workspace}/documents/{document['id']}",
                               headers=headers).status_code == 200:
            research_client.delete(f"/workspaces/{workspace}/documents/{document['id']}",
                                   headers=headers)
        return result
    monkeypatch.setattr(research_logic, "retrieve_passages", stale_hit)
    research.process_research_job(response.json()["id"], dispatch_id)
    result = research_client.get(response.headers["location"], headers=headers).json()
    assert result["status"] == "failed" and result["result"] is None
    assert result["evidence"] is None


def test_comparison_plan_has_comparative_question(monkeypatch):
    monkeypatch.setattr(research_logic, "complete_json", lambda *_: json.dumps({
        "questions": ["How does caching work?", "How does quantization work?"]}))
    plan = research_logic.plan_questions("Compare caching and quantization for memory use.")
    assert len(plan["questions"]) == 3
    assert "compare" in plan["questions"][-1].lower()
