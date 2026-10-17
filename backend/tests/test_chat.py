import json
import uuid

import httpx
from app.services import model_gateway
import pytest
from fastapi import HTTPException

from app.api import chat as chat_api
from app.api.documents import require_vector_database
from app.core.config import settings
from app.main import app
from app.schemas.documents import SearchResult
from app.services import generation
from test_ingestion import owner


@pytest.fixture
def passage():
    return SearchResult(chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), filename="paper.pdf",
                        page=7, chunk_index=0, similarity=0.8, metadata={},
                        content="The study uses a small sample. It only evaluates English text.")


def supported_output():
    return json.dumps({"claims": [{"text": "The study has a small sample.",
                                  "evidence": [{"source_id": 1, "quote": "The study uses a small sample."}]}]})


def test_chat_cites_server_metadata_and_returns_actual_context(client, monkeypatch, passage):
    headers, workspace = owner(client)
    app.dependency_overrides[require_vector_database] = lambda: None
    def retrieve(message, top_k, workspace_id, db):
        assert message == "Limitations?" and top_k == 5 and str(workspace_id) == workspace
        return [passage]
    monkeypatch.setattr(chat_api, "retrieve_passages", retrieve)
    monkeypatch.setattr(generation, "complete", lambda *_: supported_output())
    response = client.post(f"/workspaces/{workspace}/chat", headers=headers, json={"message": " Limitations? "})
    assert response.status_code == 200
    result = response.json()
    assert result["answer"] == "The study has a small sample. [1]"
    assert result["sources"][0]["document"] == "paper.pdf"
    assert result["sources"][0]["page"] == 7
    assert result["sources"][0]["chunk_id"] == str(passage.chunk_id)
    assert result["retrieved_chunks"][0]["content"] == passage.content


def test_chat_ownership_prevents_retrieval_and_generation(client, monkeypatch):
    headers, workspace = owner(client)
    other, _ = owner(client, "other@example.com")
    app.dependency_overrides[require_vector_database] = lambda: None
    def forbidden(*args):
        pytest.fail("Unauthorized request reached retrieval or generation")
    monkeypatch.setattr(chat_api, "retrieve_passages", forbidden)
    monkeypatch.setattr(chat_api, "generate_answer", forbidden)
    path = f"/workspaces/{workspace}/chat"
    assert client.post(path, json={"message": "Question"}).status_code == 401
    assert client.post(path, headers=other, json={"message": "Question"}).status_code == 404
    assert client.post(f"/workspaces/{uuid.uuid4()}/chat", headers=headers, json={"message": "Question"}).status_code == 404


@pytest.mark.parametrize("message", ["", "  ", "x" * 1025])
def test_chat_message_validation(client, message):
    headers, workspace = owner(client)
    app.dependency_overrides[require_vector_database] = lambda: None
    assert client.post(f"/workspaces/{workspace}/chat", headers=headers, json={"message": message}).status_code == 422


def test_empty_context_skips_provider(monkeypatch):
    monkeypatch.setattr(generation, "complete", lambda *_: pytest.fail("Empty context must skip LLM"))
    answer = generation.generate_answer("What is missing?", [])
    assert answer.status == "insufficient_evidence" and answer.sources == []


def test_model_abstention_preserves_retrieval_for_debugging(monkeypatch, passage):
    monkeypatch.setattr(generation, "complete", lambda *_: '{"claims": []}')
    answer = generation.generate_answer("Unknown?", [passage])
    assert answer.status == "insufficient_evidence" and answer.sources == []
    assert answer.retrieved_chunks == [passage]


@pytest.mark.parametrize("output", [
    "not JSON", '{"answer": "unsupported"}',
    '{"claims": [{"text": "Unsupported", "evidence": []}]}',
    '{"claims": [{"text": "Unsupported", "evidence": [{"source_id": 2, "quote": "The study"}]}]}',
    '{"claims": [{"text": "Unsupported", "evidence": [{"source_id": 1, "quote": "invented quote"}]}]}',
    '{"claims": [{"text": "Unsupported [99]", "evidence": [{"source_id": 1, "quote": "The study"}]}]}',
    '{"claims": [{"text": " ", "evidence": [{"source_id": 1, "quote": "The study"}]}]}',
    '{"claims": [{"text": "Unsupported", "evidence": [{"source_id": true, "quote": "The study"}]}]}',
])
def test_invalid_evidence_fails_closed(monkeypatch, passage, output):
    monkeypatch.setattr(generation, "complete", lambda *_: output)
    with pytest.raises(generation.GenerationError):
        generation.generate_answer("Limitations?", [passage])


def test_repeated_evidence_has_stable_citation_numbers(monkeypatch, passage):
    payload = json.loads(supported_output())
    payload["claims"] *= 2
    monkeypatch.setattr(generation, "complete", lambda *_: json.dumps(payload))
    answer = generation.generate_answer("Limitations?", [passage])
    assert len(answer.sources) == 1 and answer.answer.count("[1]") == 2


def test_provider_request_and_prompt_boundary(monkeypatch, passage):
    monkeypatch.setattr(settings, "LLM_MODEL", "test-model")
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    original_client = httpx.Client
    def handle(request):
        payload = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path.endswith("/chat/completions")
        assert payload["model"] == "test-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"][0]["role"] == "system"
        context = json.loads(payload["messages"][1]["content"])
        assert context["passages"] == [{"source_id": 1, "text": passage.content}]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": supported_output()}}]})
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    assert generation.generate_answer("Limitations?", [passage]).status == "answered"


@pytest.mark.parametrize("failure", ["timeout", "http", "malformed", "truncated", "invalid_choice"])
def test_provider_errors_are_safe(monkeypatch, passage, failure):
    monkeypatch.setattr(settings, "LLM_MODEL", "test-model")
    original_client = httpx.Client
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret provider detail", request=request)
        if failure == "http":
            return httpx.Response(401, text="secret provider detail")
        if failure == "truncated":
            return httpx.Response(200, json={"choices": [{"finish_reason": "length"}]})
        if failure == "invalid_choice":
            return httpx.Response(200, json={"choices": [None]})
        return httpx.Response(200, json={"private": "secret provider detail"})
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(generation.GenerationError) as error:
        generation.generate_answer("Limitations?", [passage])
    assert "secret" not in str(error.value)


def test_unconfigured_model(monkeypatch, passage):
    monkeypatch.setattr(settings, "LLM_MODEL", "")
    with pytest.raises(generation.GenerationError, match="not configured"):
        generation.generate_answer("Question?", [passage])


@pytest.mark.parametrize("stage", ["retrieval", "generation"])
def test_chat_reports_failure_stage(client, monkeypatch, passage, stage):
    headers, workspace = owner(client)
    app.dependency_overrides[require_vector_database] = lambda: None
    def retrieve(*args):
        if stage == "retrieval":
            raise HTTPException(503, "Embedding model unavailable")
        return [passage]
    def generate(*args):
        raise generation.GenerationError("Generation timed out. Please try again.")
    monkeypatch.setattr(chat_api, "retrieve_passages", retrieve)
    monkeypatch.setattr(chat_api, "generate_answer", generate)
    result = client.post(f"/workspaces/{workspace}/chat", headers=headers, json={"message": "Question?"})
    assert result.status_code == (503 if stage == "retrieval" else 502)
    assert result.json()["detail"].lower().startswith(stage)


def test_chat_requires_postgresql(client):
    headers, workspace = owner(client)
    response = client.post(f"/workspaces/{workspace}/chat", headers=headers, json={"message": "Question?"})
    assert response.status_code == 503


def test_multiple_documents_and_unused_context(monkeypatch, passage):
    second = passage.model_copy(update={"chunk_id": uuid.uuid4(), "document_id": uuid.uuid4(),
                                       "filename": "inference.pdf", "page": 11,
                                       "content": "Inference requires substantial memory."})
    unused = passage.model_copy(update={"chunk_id": uuid.uuid4(), "filename": "unused.pdf"})
    payload = json.loads(supported_output())
    payload["claims"].append({"text": "Inference needs substantial memory.",
                              "evidence": [{"source_id": 2, "quote": second.content}]})
    monkeypatch.setattr(generation, "complete", lambda *_: json.dumps(payload))
    result = generation.generate_answer("Limitations?", [passage, second, unused])
    assert [(source.id, source.document, source.page) for source in result.sources] == [
        (1, "paper.pdf", 7), (2, "inference.pdf", 11)]
    assert "[1]" in result.answer and "[2]" in result.answer
    assert len(result.retrieved_chunks) == 3
