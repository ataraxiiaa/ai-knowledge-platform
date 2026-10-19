import math
import uuid

import pytest

from app.core.config import settings
from app.services import reranking, retrieval
from test_hybrid import hit


def test_scores_reorder_without_changing_sources(monkeypatch):
    candidates = [hit(2, fusion_score=.03), hit(1, fusion_score=.02), hit(3)]
    monkeypatch.setattr(reranking, "score_passages", lambda q, texts: [-4., 2., 2.])
    result = reranking.rerank_passages("question", candidates)
    assert [p.chunk_id.int for p in result] == [1, 3, 2]
    assert result[0].metadata == candidates[1].metadata
    assert result[0].content == candidates[1].content and result[0].page == 1
    assert result[0].fusion_score == .02 and result[0].rerank_score == 2
    assert all(p.rerank_status == "applied" for p in result)
    assert candidates[1].rerank_score is None


@pytest.mark.parametrize("scores", [[1.], [math.nan, 1.], [1., math.inf]])
def test_invalid_scores_fall_back_without_partial_ranking(monkeypatch, scores):
    monkeypatch.setattr(reranking, "score_passages", lambda *args: scores)
    result = reranking.rerank_passages("q", [hit(2), hit(1)])
    assert [p.chunk_id.int for p in result] == [2, 1]
    assert all(p.rerank_status == "fallback" and p.rerank_score is None
               and p.retrieval_method == "hybrid" for p in result)


def test_model_failure_and_empty_input(monkeypatch):
    def fail(*args):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(reranking, "score_passages", fail)
    assert reranking.rerank_passages("q", []) == []
    assert reranking.rerank_passages("q", [hit(1)])[0].rerank_status == "fallback"


def test_reranking_can_be_disabled_without_loading_model(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    monkeypatch.setattr(reranking, "score_passages", lambda *args: pytest.fail("Reranker loaded"))
    result = reranking.rerank_passages("q", [hit(2), hit(1)])
    assert [item.chunk_id.int for item in result] == [2, 1]
    assert all(item.rerank_status == "fallback" and item.retrieval_method == "hybrid"
               for item in result)


def test_candidate_budget_then_top_k(monkeypatch):
    seen = []
    def hybrid(query, count, workspace, db):
        seen.append(count)
        return [hit(i) for i in range(1, 31)]
    def scores(query, texts):
        assert len(texts) == 20
        return list(range(20))
    monkeypatch.setattr(settings, "RERANK_CANDIDATES", 20)
    monkeypatch.setattr(retrieval, "retrieve_hybrid", hybrid)
    monkeypatch.setattr(reranking, "score_passages", scores)
    result = retrieval.retrieve_reranked("q", 5, uuid.uuid4(), None)
    assert seen == [20] and [p.chunk_id.int for p in result] == [20, 19, 18, 17, 16]


def test_pair_limit_prevents_silent_truncation(monkeypatch):
    class Tokenizer:
        def encode(self, query, text):
            return type("Encoding", (), {"ids": [0] * 513})()
    class Model:
        def rerank(self, *args, **kwargs):
            pytest.fail("Oversized pair reached inference")
    monkeypatch.setattr(reranking, "_model", lambda: (Model(), Tokenizer()))
    with pytest.raises(ValueError, match="512-token"):
        reranking.score_passages("query", ["passage"])


def test_chat_and_search_reranked_ownership(client, monkeypatch):
    from app.api import chat as chat_api
    from app.api.documents import require_vector_database
    from app.main import app
    from app.schemas.chat import ChatResponse
    from test_ingestion import owner
    headers, workspace = owner(client)
    other, _ = owner(client, "other@example.com")
    app.dependency_overrides[require_vector_database] = lambda: None
    monkeypatch.setattr(settings, "RAG_RETRIEVAL_METHOD", "hybrid_reranked")
    passages = [hit(1, retrieval_method="hybrid_reranked", rerank_status="applied", rerank_score=3.)]
    monkeypatch.setattr(chat_api, "retrieve_reranked", lambda *args: passages)
    def generate(question, context, *args):
        assert context == passages
        return ChatResponse(answer="Insufficient evidence", sources=[], retrieved_chunks=context,
                            status="insufficient_evidence")
    monkeypatch.setattr(chat_api, "generate_answer", generate)
    assert client.post(f"/workspaces/{workspace}/chat", headers=headers,
                       json={"message": "Question?"}).json()["retrieved_chunks"][0]["rerank_status"] == "applied"
    assert client.post(f"/workspaces/{workspace}/search", headers=other,
                       json={"query": "q", "method": "hybrid_reranked"}).status_code == 404
