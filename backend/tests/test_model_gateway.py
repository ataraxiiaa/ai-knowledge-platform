import json

import httpx
import pytest

from app.core.config import settings
from app.services import model_gateway as gateway


REQUEST = gateway.GenerateRequest("Return JSON", '{"question":"Why?"}', 100)
ORIGINAL_HTTPX_CLIENT = httpx.Client


def mock_client(monkeypatch, handler):
    monkeypatch.setattr(gateway.httpx, "Client",
        lambda **kwargs: ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler), **kwargs))


def test_task_routing_preserves_legacy_default(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "legacy-model")
    assert gateway._route("chat") == ("openai_compatible", "legacy-model")
    monkeypatch.setattr(settings, "RESEARCH_PLAN_PROVIDER", "gemini")
    assert not gateway.configured("research_plan")
    monkeypatch.setattr(settings, "RESEARCH_PLAN_MODEL", "planning-model")
    assert gateway._route("research_plan") == ("gemini", "planning-model")
    assert gateway._route("research_draft") == ("openai_compatible", "legacy-model")


def test_openai_compatible_request_usage_and_stream(monkeypatch):
    def handle(request):
        body = json.loads(request.content)
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["model"] == "test-model"
        assert body["response_format"] == {"type": "json_object"}
        if body["stream"]:
            assert body["stream_options"] == {"include_usage": True}
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"{\\"ok\\""}}]}\n\n'
                'data: {"choices":[{"delta":{"content":":true}"}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n'
                'data: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2}})
    mock_client(monkeypatch, handle)
    provider = gateway.OpenAICompatibleProvider("https://example.test/v1", "test-key", 5)
    result = provider.generate("test-model", REQUEST)
    assert result.text == '{"ok":true}'
    assert result.usage == gateway.TokenUsage(4, 2)
    chunks = list(provider.stream("test-model", REQUEST))
    assert "".join(chunk.text for chunk in chunks) == '{"ok":true}'
    assert chunks[-1].usage == gateway.TokenUsage(4, 2)


def test_openai_token_limit_field_can_use_newer_name(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_TOKEN_LIMIT_FIELD", "max_completion_tokens")
    body = gateway.OpenAICompatibleProvider("https://example.test/v1", "", 5)._body(
        "test-model", REQUEST, False)
    assert body["max_completion_tokens"] == 100
    assert "max_tokens" not in body


def test_gemini_request_usage_and_stream(monkeypatch):
    def handle(request):
        body = json.loads(request.content)
        assert request.headers["x-goog-api-key"] == "test-key"
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["systemInstruction"]["parts"][0]["text"] == "Return JSON"
        payload = {"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]},
                                  "finishReason": "STOP"}],
                   "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3}}
        if request.url.path.endswith(":streamGenerateContent"):
            assert request.url.params["alt"] == "sse"
            return httpx.Response(200, text=f"data: {json.dumps(payload)}\n\n")
        assert request.url.path.endswith("/models/test-model:generateContent")
        return httpx.Response(200, json=payload)
    mock_client(monkeypatch, handle)
    provider = gateway.GeminiProvider("https://example.test/v1beta", "test-key", 5)
    result = provider.generate("test-model", REQUEST)
    assert result.text == '{"ok":true}'
    assert result.usage == gateway.TokenUsage(5, 3)
    assert list(provider.stream("test-model", REQUEST))[0].text == '{"ok":true}'


def test_http_rate_limit_and_incomplete_stream_are_normalized(monkeypatch):
    def limited(request):
        return httpx.Response(429, headers={"Retry-After": "2"}, text="private quota details")
    mock_client(monkeypatch, limited)
    provider = gateway.OpenAICompatibleProvider("https://example.test/v1", "", 5)
    with pytest.raises(gateway.ModelError) as caught:
        provider.generate("test-model", REQUEST)
    assert caught.value.kind == "rate_limit" and caught.value.retry_after == 2
    assert "private" not in str(caught.value)

    def truncated(request):
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
                              'data: [DONE]\n\n')
    mock_client(monkeypatch, truncated)
    with pytest.raises(gateway.ModelError) as caught:
        list(provider.stream("test-model", REQUEST))
    assert caught.value.kind == "incomplete"


def test_rate_limit_retries_then_explicit_fallback(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "primary")
    monkeypatch.setattr(settings, "MODEL_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "MODEL_FALLBACK_MODEL", "fallback")
    monkeypatch.setattr(settings, "GATEWAY_MAX_ATTEMPTS", 2)
    delays = []
    monkeypatch.setattr(gateway.time, "sleep", delays.append)
    calls = []
    class Primary:
        def generate(self, model, request):
            calls.append(("primary", model))
            raise gateway.ModelError("rate limited", transient=True, retry_after=1, kind="rate_limit")
    class Fallback:
        def generate(self, model, request):
            calls.append(("fallback", model))
            return gateway.Generation("{}", "gemini", model)
    monkeypatch.setattr(gateway, "_provider", lambda name: Primary() if name == "openai_compatible" else Fallback())
    assert gateway.generate("chat", REQUEST).model == "fallback"
    assert calls == [("primary", "primary"), ("primary", "primary"), ("fallback", "fallback")]
    assert delays == [1]


def test_no_fallback_for_rejected_request_or_partial_stream(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "primary")
    monkeypatch.setattr(settings, "MODEL_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "MODEL_FALLBACK_MODEL", "fallback")
    calls = []
    class Primary:
        def generate(self, model, request):
            raise gateway.ModelError("rejected", kind="rejected")
        def stream(self, model, request):
            yield gateway.StreamChunk("partial")
            raise gateway.ModelError("down", transient=True)
    class Fallback:
        def generate(self, model, request):
            calls.append("fallback")
        def stream(self, model, request):
            calls.append("fallback")
            yield gateway.StreamChunk("different")
    monkeypatch.setattr(gateway, "_provider", lambda name: Primary() if name == "openai_compatible" else Fallback())
    with pytest.raises(gateway.ModelError, match="rejected"):
        gateway.generate("chat", REQUEST)
    iterator = gateway.stream("chat", REQUEST)
    assert next(iterator).text == "partial"
    with pytest.raises(gateway.ModelError, match="down"):
        next(iterator)
    assert calls == []


def test_embedding_stays_on_local_adapter(monkeypatch):
    called = []
    monkeypatch.setattr(gateway.LocalEmbeddingProvider, "embed",
                        lambda self, texts: called.append(texts) or [[1.0] * 384])
    assert len(gateway.embed(["example"])[0]) == 384
    assert called == [["example"]]


def test_health_is_internal_and_provider_specific(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "test-model")
    mock_client(monkeypatch, lambda request: httpx.Response(200) if
                request.url.path == "/v1/models" else httpx.Response(404))
    assert gateway.health("chat") is True
    monkeypatch.setattr(settings, "CHAT_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "CHAT_MODEL", "gemini-model")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    assert gateway.health("chat") is False
