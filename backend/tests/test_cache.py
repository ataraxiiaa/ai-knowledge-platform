import json
import uuid

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from app.core.config import settings
from app.models.workspaces import Workspace
from app.schemas.documents import SearchResult
from app.services import cache, generation, model_gateway, retrieval
from test_ingestion import finish_job, ingestion_client, owner, pdf_bytes


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.hashes = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)

    def pipeline(self, transaction=False):
        return self

    def hincrby(self, key, field, amount):
        counts = self.hashes.setdefault(key, {})
        counts[field] = counts.get(field, 0) + amount
        return self

    def expire(self, key, seconds):
        return self

    def execute(self):
        return []

    def hgetall(self, key):
        return {field.encode(): str(value).encode()
                for field, value in self.hashes.get(key, {}).items()}


@pytest.fixture
def memory_cache(monkeypatch):
    redis = MemoryRedis()
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(cache, "_unavailable_until", 0)
    monkeypatch.setattr(cache, "_redis", lambda: redis)
    return redis


def test_embedding_cache_is_workspace_scoped(memory_cache, monkeypatch):
    calls = []
    def embed(self, texts):
        calls.append(texts)
        return [[1.0] + [0.0] * 383 for _ in texts]
    monkeypatch.setattr(model_gateway.LocalEmbeddingProvider, "embed", embed)
    first, second = uuid.uuid4(), uuid.uuid4()
    assert model_gateway.embed(["same text"], first) == model_gateway.embed(["same text"], first)
    model_gateway.embed(["same text"], second)
    assert calls == [["same text"], ["same text"]]
    assert cache.metrics(first)["layers"]["embedding"]["hits"] == 1


def test_retrieval_cache_changes_with_corpus_revision(ingestion_client, db_session,
                                                      memory_cache, monkeypatch):
    headers, workspace_id = owner(ingestion_client)
    response = ingestion_client.post(f"/workspaces/{workspace_id}/documents", headers=headers,
        files={"file": ("paper.pdf", pdf_bytes())})
    document = finish_job(ingestion_client, headers, response, db_session)
    assert document["status"] == "ready"
    workspace_uuid = uuid.UUID(workspace_id)
    db_session.expire_all()
    assert db_session.scalar(select(Workspace.corpus_revision)) == 1
    calls = 0
    original_scores = retrieval.BM25Index.scores
    def count_scores(self, query):
        nonlocal calls
        calls += 1
        return original_scores(self, query)
    monkeypatch.setattr(retrieval.BM25Index, "scores", count_scores)
    first = retrieval.retrieve_bm25("puppy", 5, workspace_uuid, db_session)
    second = retrieval.retrieve_bm25("puppy", 5, workspace_uuid, db_session)
    assert first == second and calls == 1
    assert ingestion_client.delete(f"/workspaces/{workspace_id}/documents/{document['id']}",
                                   headers=headers).status_code == 204
    db_session.expire_all()
    assert db_session.scalar(select(Workspace.corpus_revision)) == 2
    assert retrieval.retrieve_bm25("puppy", 5, workspace_uuid, db_session) == []
    assert calls == 2
    metrics = cache.metrics(workspace_uuid)["layers"]["retrieval"]
    assert metrics["hits"] == 1 and metrics["misses"] == 2


def test_chat_cache_rechecks_citations_and_estimates_savings(memory_cache, monkeypatch):
    workspace_id = uuid.uuid4()
    passage = SearchResult(chunk_id=uuid.uuid4(), document_id=uuid.uuid4(),
        filename="paper.pdf", page=7, chunk_index=0, similarity=.8,
        metadata={}, content="The study uses a small sample.")
    content = json.dumps({"claims": [{"text": "The study has a small sample.",
        "evidence": [{"source_id": 1, "quote": passage.content}]}]})
    calls = []
    def complete(message, passages):
        calls.append(message)
        return model_gateway.Generation(content, "openai_compatible", "priced-model",
            model_gateway.TokenUsage(100, 50))
    monkeypatch.setattr(generation, "complete", complete)
    monkeypatch.setattr(settings, "CACHE_MODEL_PRICES_JSON",
        json.dumps({"openai_compatible:priced-model": {"input": 1, "output": 2}}))
    first = generation.generate_answer("What is the limitation?", [passage], workspace_id, 1)
    second = generation.generate_answer("What is the limitation?", [passage], workspace_id, 1)
    assert first == second and calls == ["What is the limitation?"]
    metrics = cache.metrics(workspace_id)["layers"]["chat"]
    assert metrics["hits"] == 1 and metrics["input_tokens_saved"] == 100
    assert metrics["output_tokens_saved"] == 50
    assert metrics["estimated_api_cost_saved_usd"] == 0.0002
    changed = passage.model_copy(update={"content": "A different passage."})
    with pytest.raises(generation.GenerationError):
        generation.generate_answer("What is the limitation?", [changed], workspace_id, 1)
    assert len(calls) == 2


def test_corrupt_chat_cache_falls_back_to_model(memory_cache, monkeypatch):
    workspace_id = uuid.uuid4()
    passage = SearchResult(chunk_id=uuid.uuid4(), document_id=uuid.uuid4(),
        filename="paper.pdf", page=1, chunk_index=0, similarity=.8,
        metadata={}, content="Valid quote.")
    content = json.dumps({"claims": [{"text": "Valid claim.",
        "evidence": [{"source_id": 1, "quote": "Valid quote."}]}]})
    calls = []
    monkeypatch.setattr(generation, "complete", lambda *args: calls.append(1) or
        model_gateway.Generation(content, "openai_compatible", "test-model"))
    generation.generate_answer("Question?", [passage], workspace_id, 1)
    assert len(memory_cache.values) == 1
    key = next(iter(memory_cache.values))
    entry = json.loads(memory_cache.values[key])
    entry["data"] = '{"claims":[{"text":"Wrong","evidence":[{"source_id":1,"quote":"invented"}]}]}'
    memory_cache.values[key] = json.dumps(entry).encode()
    result = generation.generate_answer("Question?", [passage], workspace_id, 1)
    assert result.status == "answered" and calls == [1, 1]


def test_cache_is_fail_open_when_redis_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(cache, "_unavailable_until", 0)
    class Offline:
        def get(self, key):
            raise RedisConnectionError("private redis details")
    monkeypatch.setattr(cache, "_redis", lambda: Offline())
    workspace_id = uuid.uuid4()
    assert cache.get("embedding", workspace_id, "key") is None
    assert cache.metrics(workspace_id)["available"] is False
    calls = []
    monkeypatch.setattr(model_gateway.LocalEmbeddingProvider, "embed",
                        lambda self, texts: calls.append(texts) or [[1.0] + [0.0] * 383])
    assert len(model_gateway.embed(["text"], workspace_id)[0]) == 384
    assert calls == [["text"]]


def test_cache_metrics_require_workspace_owner(client, memory_cache):
    headers, workspace_id = owner(client)
    other, _ = owner(client, "other-cache@example.com")
    path = f"/workspaces/{workspace_id}/cache-metrics"
    assert client.get(path, headers=headers).status_code == 200
    assert client.get(path, headers=other).status_code == 404
    assert client.get(path).status_code == 401
