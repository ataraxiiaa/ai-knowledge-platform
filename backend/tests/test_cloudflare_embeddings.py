import json

import httpx
import pytest

from app.core.config import settings
from app.services import embeddings
from app.services.ingestion import retryable_failure

ORIGINAL_CLIENT = httpx.Client


def _mock_client(monkeypatch, handler):
    monkeypatch.setattr(embeddings.httpx, "Client", lambda **kwargs: ORIGINAL_CLIENT(
        transport=httpx.MockTransport(handler), **kwargs))


def _vector():
    return [1.0] + [0.0] * 383


def test_cloudflare_batches_vectors_without_loading_local_model(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "cloudflare")
    monkeypatch.setattr(settings, "CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2)
    monkeypatch.setattr(embeddings, "_model", lambda: pytest.fail("Local model loaded"))

    def handle(request):
        body = json.loads(request.content)
        assert request.url.path == "/client/v4/accounts/account123/ai/run/@cf/baai/bge-small-en-v1.5"
        assert request.headers["authorization"] == "Bearer secret-token"
        assert body["pooling"] == "mean"
        calls.append(body["text"])
        return httpx.Response(200, json={"success": True,
            "result": {"data": [_vector() for _ in body["text"]]}})

    _mock_client(monkeypatch, handle)
    vectors = embeddings.embed_texts(["one", "two", "three"])

    assert calls == [["one", "two"], ["three"]]
    assert vectors == [_vector()] * 3
    assert embeddings.embedding_model_id() == "cloudflare:@cf/baai/bge-small-en-v1.5:mean"


def test_cloudflare_quota_and_invalid_vectors_fail_without_local_fallback(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "cloudflare")
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 1)
    monkeypatch.setattr(embeddings, "_model", lambda: pytest.fail("Local fallback used"))
    _mock_client(monkeypatch, lambda request: httpx.Response(429))
    with pytest.raises(embeddings.EmbeddingServiceError, match="limit reached"):
        embeddings.embed_texts(["one"])

    _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"success": True,
        "result": {"data": [[0.0] * 384]}}))
    with pytest.raises(embeddings.EmbeddingServiceError, match="invalid embedding vectors"):
        embeddings.embed_texts(["one"])


def test_cloudflare_server_error_can_retry_ingestion(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "cloudflare")
    _mock_client(monkeypatch, lambda request: httpx.Response(503))
    with pytest.raises(ConnectionError) as error:
        embeddings.embed_texts(["one"])
    assert retryable_failure(error.value, "embedding")
