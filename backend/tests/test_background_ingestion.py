import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from app import dispatcher
from app.models.chunks import Chunk
from app.models.documents import Document, IngestionDispatch
from app.services import ingestion
from conftest import TestingSessionLocal
from test_ingestion import ingestion_client, owner, pdf_bytes, finish_job


def accept(client):
    headers, workspace = owner(client)
    response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                           files={"file": ("paper.pdf", pdf_bytes())})
    assert response.status_code == 202
    return headers, response


def test_acceptance_does_not_parse_embed_or_enqueue(ingestion_client, monkeypatch, db_session):
    def forbidden(*args, **kwargs):
        raise AssertionError("Slow or external work entered the upload request")
    monkeypatch.setattr(ingestion, "extract_pages", forbidden)
    monkeypatch.setattr(dispatcher, "ingestion_queue", forbidden)
    _, response = accept(ingestion_client)
    assert response.json()["status"] == "queued"
    assert response.json()["attempt_count"] == 0
    assert db_session.scalar(select(func.count()).select_from(IngestionDispatch)) == 1
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0


def test_dispatch_recovers_after_queue_outage(ingestion_client, monkeypatch, db_session):
    accept(ingestion_client)
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSessionLocal)
    def offline():
        raise ConnectionError("Redis offline")
    monkeypatch.setattr(dispatcher, "ingestion_queue", offline)
    assert dispatcher.dispatch_once() == 0
    db_session.expire_all()
    job = db_session.scalar(select(IngestionDispatch))
    assert job.publish_attempts == 1 and job.published_at is None
    job.due_at = ingestion.now() - timedelta(seconds=1)
    db_session.commit()
    calls = []
    class Queue:
        def enqueue(self, *args, **kwargs):
            calls.append((args, kwargs))
    monkeypatch.setattr(dispatcher, "ingestion_queue", Queue)
    assert dispatcher.dispatch_once() == 1
    assert len(calls) == 1 and calls[0][0][0] == "app.services.ingestion.process_document"
    db_session.expire_all()
    assert db_session.scalar(select(IngestionDispatch)).published_at is not None
    assert db_session.scalar(select(Document)).status == "queued"


def test_duplicate_delivery_cannot_add_chunks(ingestion_client, db_session):
    headers, response = accept(ingestion_client)
    dispatch_id = str(db_session.scalar(select(IngestionDispatch.id)))
    result = finish_job(ingestion_client, headers, response, db_session)
    ingestion.process_document(result["id"], dispatch_id)
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == result["chunk_count"]
    assert db_session.scalar(select(Document)).attempt_count == 1


def test_delete_before_execution_is_noop(ingestion_client, db_session):
    headers, response = accept(ingestion_client)
    dispatch_id = str(db_session.scalar(select(IngestionDispatch.id)))
    assert ingestion_client.delete(response.headers["location"], headers=headers).status_code == 204
    ingestion.process_document(response.json()["id"], dispatch_id)
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert db_session.scalar(select(func.count()).select_from(IngestionDispatch)) == 0


def test_delete_during_embedding_cannot_recreate_document(ingestion_client, db_session, monkeypatch):
    headers, response = accept(ingestion_client)
    def embed(texts):
        assert ingestion_client.delete(response.headers["location"], headers=headers).status_code == 204
        return [[1.] + [0.] * 383 for _ in texts]
    monkeypatch.setattr(ingestion, "embed_texts", embed)
    result = finish_job(ingestion_client, headers, response, db_session)
    assert result["detail"] == "Document not found"
    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0


def test_superseded_worker_cannot_publish(ingestion_client, db_session, monkeypatch):
    headers, response = accept(ingestion_client)
    def embed(texts):
        with TestingSessionLocal() as db:
            db.execute(update(Document).values(lease_token=uuid.uuid4()))
            db.commit()
        return [[1.] + [0.] * 383 for _ in texts]
    monkeypatch.setattr(ingestion, "embed_texts", embed)
    result = finish_job(ingestion_client, headers, response, db_session)
    assert result["status"] == "embedding"
    assert result["chunk_count"] == 0


def due_now(db):
    past = ingestion.now() - timedelta(seconds=1)
    db.execute(update(Document).values(next_retry_at=past))
    db.execute(update(IngestionDispatch).values(due_at=past))
    db.commit()


def test_transient_model_failure_waits_then_succeeds_once(ingestion_client, db_session, monkeypatch):
    headers, response = accept(ingestion_client)
    document_id = response.json()["id"]
    dispatch_id = str(db_session.scalar(select(IngestionDispatch.id)))
    calls = 0
    def sometimes_fails(texts):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("private model cache path")
        return [[1.] + [0.] * 383 for _ in texts]
    monkeypatch.setattr(ingestion, "embed_texts", sometimes_fails)
    ingestion.process_document(document_id, dispatch_id)
    db_session.expire_all()
    record = db_session.scalar(select(Document))
    assert record.status == "retrying" and record.attempt_count == 1 and record.max_attempts == 3
    assert "private" not in record.error
    assert 29 <= (record.next_retry_at.replace(tzinfo=ingestion.now().tzinfo) - ingestion.now()).total_seconds() <= 31
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    ingestion.process_document(document_id, dispatch_id)
    db_session.expire_all()
    assert db_session.scalar(select(Document)).attempt_count == 1 and calls == 1
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSessionLocal)
    assert dispatcher.dispatch_once() == 0
    due_now(db_session)
    published = []
    class Queue:
        def enqueue(self, *args, **kwargs):
            published.append(args)
    monkeypatch.setattr(dispatcher, "ingestion_queue", Queue)
    assert dispatcher.dispatch_once() == 1
    db_session.expire_all()
    assert db_session.scalar(select(Document)).status == "queued"
    assert len(published) == 1
    ingestion.process_document(document_id, dispatch_id)
    db_session.expire_all()
    record = db_session.scalar(select(Document))
    assert record.status == "ready" and record.attempt_count == 2
    count = db_session.scalar(select(func.count()).select_from(Chunk))
    assert count > 0 and db_session.scalar(select(func.count()).select_from(IngestionDispatch)) == 0
    ingestion.process_document(document_id, dispatch_id)
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == count


def test_second_retry_delay_then_exhausted(ingestion_client, db_session, monkeypatch):
    _, response = accept(ingestion_client)
    document_id = response.json()["id"]
    dispatch_id = str(db_session.scalar(select(IngestionDispatch.id)))
    def unavailable(texts):
        raise OSError("model unavailable")
    monkeypatch.setattr(ingestion, "embed_texts", unavailable)
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSessionLocal)
    class Queue:
        def enqueue(self, *args, **kwargs):
            return None
    monkeypatch.setattr(dispatcher, "ingestion_queue", Queue)
    for attempt, delay in ((1, 30), (2, 120)):
        ingestion.process_document(document_id, dispatch_id)
        db_session.expire_all()
        record = db_session.scalar(select(Document))
        assert record.status == "retrying" and record.attempt_count == attempt
        remaining = (record.next_retry_at.replace(tzinfo=ingestion.now().tzinfo) - ingestion.now()).total_seconds()
        assert delay - 1 <= remaining <= delay + 1
        due_now(db_session)
        assert dispatcher.dispatch_once() == 1
    ingestion.process_document(document_id, dispatch_id)
    db_session.expire_all()
    record = db_session.scalar(select(Document))
    assert record.status == "failed" and record.attempt_count == 3 and record.next_retry_at is None
    assert db_session.scalar(select(func.count()).select_from(IngestionDispatch)) == 0
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0


def test_database_publish_failure_rolls_back_and_retries(ingestion_client, db_session, monkeypatch):
    _, response = accept(ingestion_client)
    document_id = response.json()["id"]
    dispatch_id = str(db_session.scalar(select(IngestionDispatch.id)))
    from sqlalchemy.orm import Session
    original_commit = Session.commit
    failed_once = False
    def fail_publish_once(session):
        nonlocal failed_once
        if not failed_once and any(isinstance(item, Chunk) for item in session.new):
            failed_once = True
            session.flush()
            raise OperationalError("INSERT chunks", {}, RuntimeError("database unavailable"))
        original_commit(session)
    monkeypatch.setattr(Session, "commit", fail_publish_once)
    ingestion.process_document(document_id, dispatch_id)
    db_session.expire_all()
    assert failed_once and db_session.scalar(select(Document)).status == "retrying"
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert db_session.scalar(select(func.count()).select_from(IngestionDispatch)) == 1
    due_now(db_session)
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSessionLocal)
    class Queue:
        def enqueue(self, *args, **kwargs):
            return None
    monkeypatch.setattr(dispatcher, "ingestion_queue", Queue)
    assert dispatcher.dispatch_once() == 1
    ingestion.process_document(document_id, dispatch_id)
    db_session.expire_all()
    assert db_session.scalar(select(Document)).status == "ready"
    assert db_session.scalar(select(func.count()).select_from(Chunk)) > 0


def test_unknown_error_and_bad_pdf_are_permanent(ingestion_client, db_session, monkeypatch):
    _, response = accept(ingestion_client)
    document_id = response.json()["id"]
    dispatch_id = str(db_session.scalar(select(IngestionDispatch.id)))
    def unknown(texts):
        raise RuntimeError("private details")
    monkeypatch.setattr(ingestion, "embed_texts", unknown)
    ingestion.process_document(document_id, dispatch_id)
    db_session.expire_all()
    record = db_session.scalar(select(Document))
    assert record.status == "failed" and record.attempt_count == 1
    assert "private" not in record.error
    assert db_session.scalar(select(func.count()).select_from(IngestionDispatch)) == 0


@pytest.mark.parametrize("error,stage,expected", [
    (ingestion.IngestionError("bad PDF"), "parsing", False),
    (OSError("missing model"), "embedding", True),
    (OSError("bad PDF path"), "parsing", False),
    (RuntimeError("unknown"), "embedding", False),
    (OperationalError("SELECT", {}, Exception("offline")), "publishing", True),
])
def test_retry_classification(error, stage, expected):
    assert ingestion.retryable_failure(error, stage) is expected


def test_expired_lease_recovery_fences_old_worker_and_requeues(ingestion_client, db_session, monkeypatch):
    _, response = accept(ingestion_client)
    document_id = response.json()["id"]
    old_token = uuid.uuid4()
    db_session.execute(update(Document).values(
        status="embedding", attempt_count=1, lease_token=old_token,
        lease_expires_at=ingestion.now() - timedelta(seconds=1),
    ))
    db_session.commit()
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSessionLocal)
    assert dispatcher.recover_expired_leases() == 1
    db_session.expire_all()
    record = db_session.scalar(select(Document))
    assert record.status == "retrying" and record.attempt_count == 1
    assert record.lease_token is None and record.lease_expires_at is None
    assert 29 <= (record.next_retry_at.replace(tzinfo=ingestion.now().tzinfo) - ingestion.now()).total_seconds() <= 31
    assert not ingestion.touch(uuid.UUID(document_id), old_token, status="embedding")
    assert dispatcher.recover_expired_leases() == 0
    assert dispatcher.dispatch_once() == 0
    due_now(db_session)
    class Queue:
        def enqueue(self, *args, **kwargs):
            return None
    monkeypatch.setattr(dispatcher, "ingestion_queue", Queue)
    assert dispatcher.dispatch_once() == 1
    assert db_session.scalar(select(Document)).attempt_count == 1


def test_expired_last_lease_fails_and_removes_dispatch(ingestion_client, db_session, monkeypatch):
    accept(ingestion_client)
    db_session.execute(update(Document).values(
        status="chunking", attempt_count=3,
        lease_token=uuid.uuid4(), lease_expires_at=ingestion.now() - timedelta(seconds=1),
    ))
    db_session.commit()
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSessionLocal)
    assert dispatcher.recover_expired_leases() == 1
    db_session.expire_all()
    record = db_session.scalar(select(Document))
    assert record.status == "failed" and record.finished_at is not None
    assert record.lease_token is None and record.next_retry_at is None
    assert db_session.scalar(select(func.count()).select_from(IngestionDispatch)) == 0


def test_recovery_skips_live_or_deleted_documents(ingestion_client, db_session, monkeypatch):
    headers, response = accept(ingestion_client)
    db_session.execute(update(Document).values(
        status="processing", attempt_count=1,
        lease_token=uuid.uuid4(), lease_expires_at=ingestion.now() + timedelta(minutes=1),
    ))
    db_session.commit()
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSessionLocal)
    assert dispatcher.recover_expired_leases() == 0
    assert ingestion_client.delete(response.headers["location"], headers=headers).status_code == 204
    assert dispatcher.recover_expired_leases() == 0
