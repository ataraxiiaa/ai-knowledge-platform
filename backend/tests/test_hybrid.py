import uuid

import pytest
from fastapi import HTTPException

from app.api import chat as chat_api
from app.api.documents import require_vector_database
from app.core.config import settings
from app.main import app
from app.schemas.chat import ChatResponse
from app.schemas.documents import SearchResult
from app.services import retrieval
from app.services.hybrid import reciprocal_rank_fusion
from test_ingestion import owner
from test_bm25 import add_document


def hit(number, **kwargs):
    return SearchResult(chunk_id=uuid.UUID(int=number), document_id=uuid.UUID(int=99),
                        filename="paper.pdf", content=f"Text {number}", page=number,
                        chunk_index=number, metadata={"original": True}, **kwargs)


def test_rrf_math_overlap_and_source_preservation():
    a, b, c = hit(1, similarity=.8), hit(2, similarity=.7), hit(3, bm25_score=100)
    lexical_a = a.model_copy(update={"similarity": None, "bm25_score": 10})
    result = reciprocal_rank_fusion([a, b], [c, lexical_a])
    assert [r.chunk_id.int for r in result] == [1, 3, 2]
    first = result[0]
    assert first.fusion_score == pytest.approx(1/61 + 1/62)
    assert first.vector_rank == 1 and first.bm25_rank == 2
    assert first.similarity == .8 and first.bm25_score == 10
    assert first.metadata == a.metadata and first.page == a.page and first.content == a.content
    assert first.retrieval_method == "hybrid" and a.retrieval_method == "vector"


def test_duplicates_count_once_per_branch_and_same_text_keeps_distinct_ids():
    a, b = hit(1), hit(2)
    b.content = a.content
    result = reciprocal_rank_fusion([a, a, b], [a, a])
    assert len(result) == 2
    assert result[0].fusion_score == pytest.approx(2/61)
    assert result[1].vector_rank == 2


def test_raw_score_scale_does_not_change_fusion_and_ties_use_uuid():
    a, b = hit(1, similarity=-.9), hit(2, bm25_score=1000000)
    result = reciprocal_rank_fusion([b, a], [a, b])
    assert [r.chunk_id.int for r in result] == [1, 2]
    b.bm25_score = .000001
    assert [r.chunk_id for r in reciprocal_rank_fusion([b, a], [a, b])] == [r.chunk_id for r in result]


def test_empty_lists_and_nondefault_constant():
    assert reciprocal_rank_fusion([], []) == []
    assert reciprocal_rank_fusion([hit(1)], [], 10)[0].fusion_score == pytest.approx(1/11)
    assert reciprocal_rank_fusion([], [hit(2)])[0].vector_rank is None
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], [], 0)


def test_candidate_limit_before_fusion_and_top_k_after(monkeypatch):
    seen = []
    def dense(query, count, workspace, db):
        seen.append((query, count, workspace, db))
        return [hit(1), hit(2)]
    def lexical(query, count, workspace, db):
        seen.append((query, count, workspace, db))
        return [hit(2), hit(3)]
    monkeypatch.setattr(settings, "HYBRID_CANDIDATES", 40)
    monkeypatch.setattr(retrieval, "retrieve_passages", dense)
    monkeypatch.setattr(retrieval, "retrieve_bm25", lexical)
    workspace = uuid.uuid4()
    result = retrieval.retrieve_hybrid("term", 1, workspace, None)
    assert seen == [("term", 40, workspace, None)] * 2
    assert len(result) == 1 and result[0].chunk_id.int == 2


def test_branch_failure_is_not_silently_relabelled_hybrid(monkeypatch):
    monkeypatch.setattr(retrieval, "retrieve_passages", lambda *args: [hit(1)])
    def fail(*args):
        raise HTTPException(503, "BM25 limit")
    monkeypatch.setattr(retrieval, "retrieve_bm25", fail)
    with pytest.raises(HTTPException, match="BM25 limit"):
        retrieval.retrieve_hybrid("term", 1, uuid.uuid4(), None)


def test_endpoint_ownership_and_real_lexical_filtering(client, db_session, monkeypatch):
    headers, workspace = owner(client)
    other_headers, other_workspace = owner(client, "other@example.com")
    own = add_document(db_session, workspace, "hybridkeyword")
    add_document(db_session, other_workspace, "hybridkeyword")
    add_document(db_session, workspace, "hybridkeyword", status="failed")
    app.dependency_overrides[require_vector_database] = lambda: None
    calls = []
    def dense(query, count, workspace_id, db):
        calls.append(workspace_id)
        return []  # SQLite lacks cosine; lexical SQL remains real.
    monkeypatch.setattr(retrieval, "retrieve_passages", dense)
    url = f"/workspaces/{workspace}/search"
    payload = {"query": "hybridkeyword", "method": "hybrid"}
    assert client.post(url, headers=other_headers, json=payload).status_code == 404
    assert client.post(url, json=payload).status_code == 401
    assert calls == []
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 200
    assert [r["chunk_id"] for r in response.json()] == [str(own.id)]
    assert response.json()[0]["retrieval_method"] == "hybrid"
    assert calls == [uuid.UUID(workspace)]


def test_chat_uses_configured_hybrid_context(client, monkeypatch):
    headers, workspace = owner(client)
    app.dependency_overrides[require_vector_database] = lambda: None
    monkeypatch.setattr(settings, "RAG_RETRIEVAL_METHOD", "hybrid")
    passages = reciprocal_rank_fusion([hit(1)], [hit(1)])
    monkeypatch.setattr(chat_api, "retrieve_hybrid", lambda *args: passages)
    monkeypatch.setattr(chat_api, "retrieve_passages", lambda *args: pytest.fail("Wrong retriever"))
    def generate(question, context, *args):
        assert context == passages
        return ChatResponse(answer="Insufficient evidence", sources=[], retrieved_chunks=context,
                            status="insufficient_evidence")
    monkeypatch.setattr(chat_api, "generate_answer", generate)
    response = client.post(f"/workspaces/{workspace}/chat", headers=headers, json={"message": "Question?"})
    assert response.status_code == 200 and response.json()["retrieved_chunks"][0]["fusion_score"] > 0
