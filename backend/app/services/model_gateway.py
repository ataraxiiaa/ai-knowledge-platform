"""Provider-neutral inference routing. Application services use only this module."""
from dataclasses import dataclass
from collections.abc import Iterator
import json
import logging
import math
from time import perf_counter
import uuid
import time
from typing import Literal, Protocol
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.services import cache
from app.services import observability

logger = logging.getLogger(__name__)
Task = Literal["chat", "research_plan", "research_draft"]


class ModelError(Exception):
    def __init__(self, message: str, *, transient: bool = False,
                 retry_after: float | None = None, kind: str = "provider"):
        super().__init__(message)
        self.transient = transient
        self.retry_after = retry_after
        self.kind = kind


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class Generation:
    text: str
    provider: str
    model: str
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class StreamChunk:
    text: str = ""
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class GenerateRequest:
    system_prompt: str
    user_prompt: str
    max_tokens: int
    json_mode: bool = True


class Provider(Protocol):
    def generate(self, model: str, request: GenerateRequest) -> Generation: ...
    def stream(self, model: str, request: GenerateRequest) -> Iterator[StreamChunk]: ...
    def health(self, model: str) -> bool: ...


def _usage(value: object, input_key: str, output_key: str) -> TokenUsage | None:
    if not isinstance(value, dict):
        return None
    input_count, output_count = value.get(input_key), value.get(output_key)
    return TokenUsage(input_count if isinstance(input_count, int) and input_count >= 0 else None,
                      output_count if isinstance(output_count, int) and output_count >= 0 else None)


def _response_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 429:
        try:
            delay = float(response.headers.get("retry-after", ""))
        except ValueError:
            delay = None
        raise ModelError("Model provider rate limited the request.", transient=True,
                         retry_after=delay if delay is not None and math.isfinite(delay) and delay >= 0 else None,
                         kind="rate_limit")
    if response.status_code >= 500:
        raise ModelError("Model provider temporarily unavailable.", transient=True,
                         kind="unavailable")
    raise ModelError("Model provider rejected the request.", kind="rejected")


def _transport_error(exc: Exception) -> ModelError:
    if isinstance(exc, httpx.TimeoutException):
        return ModelError("Model provider timed out.", transient=True, kind="timeout")
    return ModelError("Model provider temporarily unavailable.", transient=True,
                      kind="unavailable")


def _events(lines: Iterator[str]) -> Iterator[dict]:
    for line in lines:
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            event = json.loads(data)
        except ValueError as exc:
            raise ModelError("Model provider returned an invalid stream.", kind="invalid_response") from exc
        if not isinstance(event, dict):
            raise ModelError("Model provider returned an invalid stream.", kind="invalid_response")
        yield event


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, timeout: float):
        self.base_url, self.api_key, self.timeout = base_url, api_key, timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _body(self, model: str, request: GenerateRequest, stream: bool) -> dict:
        body = {"model": model, "stream": stream,
                settings.OPENAI_TOKEN_LIMIT_FIELD: request.max_tokens,
                "messages": [{"role": "system", "content": request.system_prompt},
                             {"role": "user", "content": request.user_prompt}]}
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    def generate(self, model: str, request: GenerateRequest) -> Generation:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.post(f"{self.base_url}/chat/completions",
                    headers=self._headers(), json=self._body(model, request, False))
            _response_error(response)
            payload = response.json()
            choice = payload["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ModelError("Model generation did not complete.", kind="incomplete")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content")
            return Generation(content, self.name, model,
                              _usage(payload.get("usage"), "prompt_tokens", "completion_tokens"))
        except httpx.TransportError as exc:
            raise _transport_error(exc) from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ModelError("Model provider returned an invalid response.", kind="invalid_response") from exc

    def stream(self, model: str, request: GenerateRequest) -> Iterator[StreamChunk]:
        try:
            finished = False
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                with client.stream("POST", f"{self.base_url}/chat/completions",
                    headers=self._headers(), json=self._body(model, request, True)) as response:
                    _response_error(response)
                    for event in _events(response.iter_lines()):
                        usage = _usage(event.get("usage"), "prompt_tokens", "completion_tokens")
                        choices = event.get("choices") or []
                        if choices:
                            reason = choices[0].get("finish_reason")
                            if reason == "stop":
                                finished = True
                            elif reason is not None:
                                raise ModelError("Model generation did not complete.", kind="incomplete")
                        text = choices[0].get("delta", {}).get("content") if choices else None
                        if text is not None and not isinstance(text, str):
                            raise ModelError("Model provider returned an invalid stream.", kind="invalid_response")
                        if text or usage:
                            yield StreamChunk(text or "", usage)
            if not finished:
                raise ModelError("Model generation did not complete.", kind="incomplete")
        except httpx.TransportError as exc:
            raise _transport_error(exc) from exc

    def health(self, model: str) -> bool:
        try:
            with httpx.Client(timeout=min(self.timeout, 5), follow_redirects=False) as client:
                response = client.get(f"{self.base_url}/models", headers=self._headers())
            return response.status_code == 200
        except httpx.TransportError:
            return False


class GeminiProvider:
    name = "gemini"

    def __init__(self, base_url: str, api_key: str, timeout: float):
        self.base_url, self.api_key, self.timeout = base_url, api_key, timeout

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}

    def _body(self, request: GenerateRequest) -> dict:
        config = {"maxOutputTokens": request.max_tokens}
        if request.json_mode:
            config["responseMimeType"] = "application/json"
        return {"systemInstruction": {"parts": [{"text": request.system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": request.user_prompt}]}],
                "generationConfig": config}

    def _url(self, model: str, action: str) -> str:
        return f"{self.base_url}/models/{quote(model, safe='')}:{action}"

    def _chunk(self, payload: dict) -> StreamChunk:
        candidates = payload.get("candidates") or []
        if candidates:
            candidate = candidates[0]
            if candidate.get("finishReason") not in (None, "STOP"):
                raise ModelError("Model generation did not complete.", kind="incomplete")
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts)
            if not isinstance(text, str):
                raise TypeError("text")
        else:
            text = ""
        return StreamChunk(text, _usage(payload.get("usageMetadata"),
                                        "promptTokenCount", "candidatesTokenCount"))

    def generate(self, model: str, request: GenerateRequest) -> Generation:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.post(self._url(model, "generateContent"),
                    headers=self._headers(), json=self._body(request))
            _response_error(response)
            chunk = self._chunk(response.json())
            if not chunk.text:
                raise ModelError("Model provider returned an empty response.", kind="invalid_response")
            return Generation(chunk.text, self.name, model, chunk.usage)
        except httpx.TransportError as exc:
            raise _transport_error(exc) from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ModelError("Model provider returned an invalid response.", kind="invalid_response") from exc

    def stream(self, model: str, request: GenerateRequest) -> Iterator[StreamChunk]:
        try:
            finished = False
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                with client.stream("POST", self._url(model, "streamGenerateContent"),
                    params={"alt": "sse"}, headers=self._headers(),
                    json=self._body(request)) as response:
                    _response_error(response)
                    for event in _events(response.iter_lines()):
                        candidates = event.get("candidates") or []
                        if candidates and candidates[0].get("finishReason") == "STOP":
                            finished = True
                        try:
                            chunk = self._chunk(event)
                        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                            raise ModelError("Model provider returned an invalid stream.",
                                             kind="invalid_response") from exc
                        if chunk.text or chunk.usage:
                            yield chunk
            if not finished:
                raise ModelError("Model generation did not complete.", kind="incomplete")
        except httpx.TransportError as exc:
            raise _transport_error(exc) from exc

    def health(self, model: str) -> bool:
        try:
            with httpx.Client(timeout=min(self.timeout, 5), follow_redirects=False) as client:
                response = client.get(f"{self.base_url}/models/{quote(model, safe='')}",
                    headers=self._headers())
            return response.status_code == 200
        except httpx.TransportError:
            return False


class LocalEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        from app.services.embeddings import embed_texts
        return embed_texts(texts)

    def health(self) -> bool:
        from app.services.embeddings import _model
        try:
            _model()
            return True
        except Exception:
            return False


def _route(task: Task) -> tuple[str, str]:
    provider_field, model_field = {
        "chat": (settings.CHAT_PROVIDER, settings.CHAT_MODEL),
        "research_plan": (settings.RESEARCH_PLAN_PROVIDER, settings.RESEARCH_PLAN_MODEL),
        "research_draft": (settings.RESEARCH_DRAFT_PROVIDER, settings.RESEARCH_DRAFT_MODEL),
    }[task]
    if provider_field == "gemini":
        return provider_field, model_field
    return "openai_compatible", model_field or settings.LLM_MODEL


def configured(task: Task) -> bool:
    provider, model = _route(task)
    return bool(model.strip() and (provider != "gemini" or settings.GEMINI_API_KEY.strip()))


def _provider(name: str) -> Provider:
    if name == "openai_compatible":
        return OpenAICompatibleProvider(settings.LLM_BASE_URL, settings.LLM_API_KEY,
                                        settings.LLM_TIMEOUT_SECONDS)
    if name == "gemini" and settings.GEMINI_API_KEY.strip():
        return GeminiProvider(settings.GEMINI_BASE_URL, settings.GEMINI_API_KEY,
                              settings.LLM_TIMEOUT_SECONDS)
    raise ModelError("Model provider is not configured.", kind="configuration")


def _routes(task: Task) -> list[tuple[str, str]]:
    primary = _route(task)
    if not primary[1].strip():
        raise ModelError("Generation is not configured.", kind="configuration")
    routes = [primary]
    fallback = (settings.MODEL_FALLBACK_PROVIDER, settings.MODEL_FALLBACK_MODEL)
    if fallback[0] and fallback[1].strip() and fallback != primary:
        routes.append(fallback)
    return routes


def _pause(error: ModelError, attempt: int) -> None:
    delay = error.retry_after if error.retry_after is not None else \
        settings.GATEWAY_RETRY_BASE_SECONDS * 2 ** (attempt - 1)
    time.sleep(min(delay, 5))


def generate(task: Task, request: GenerateRequest) -> Generation:
    routes = _routes(task)
    for route_index, (provider_name, model) in enumerate(routes):
        provider = _provider(provider_name)
        for attempt in range(1, settings.GATEWAY_MAX_ATTEMPTS + 1):
            started = perf_counter()
            try:
                with observability.span("llm.generate", {"app.model.task": task,
                        "gen_ai.provider.name": provider_name, "gen_ai.request.model": model,
                        "retry.attempt": attempt}) as span:
                    result = provider.generate(model, request)
                    if span is not None:
                        span.set_attribute("outcome", "success")
                observability.record_model(result.provider, result.model, task,
                                           perf_counter() - started, usage=result.usage)
                logger.info("Model generation task=%s provider=%s model=%s input_tokens=%s output_tokens=%s",
                    task, result.provider, result.model,
                    result.usage.input_tokens if result.usage else None,
                    result.usage.output_tokens if result.usage else None)
                return result
            except ModelError as exc:
                observability.record_model(provider_name, model, task, perf_counter() - started,
                                           error=exc.kind)
                if not exc.transient:
                    raise
                if attempt < settings.GATEWAY_MAX_ATTEMPTS:
                    _pause(exc, attempt)
                elif route_index == len(routes) - 1:
                    raise
                else:
                    logger.warning("Model fallback task=%s failed_provider=%s kind=%s",
                                   task, provider_name, exc.kind)
    raise AssertionError("Unreachable gateway route")


def stream(task: Task, request: GenerateRequest) -> Iterator[StreamChunk]:
    """Internal streaming; fallback is allowed only before the first event."""
    routes = _routes(task)
    for route_index, (provider_name, model) in enumerate(routes):
        provider = _provider(provider_name)
        for attempt in range(1, settings.GATEWAY_MAX_ATTEMPTS + 1):
            emitted = False
            started = perf_counter()
            first_token = None
            usage = None
            try:
                with observability.span("llm.stream", {"app.model.task": task,
                        "gen_ai.provider.name": provider_name, "gen_ai.request.model": model,
                        "retry.attempt": attempt}) as span:
                    for chunk in provider.stream(model, request):
                        emitted = True
                        if chunk.text and first_token is None:
                            first_token = perf_counter() - started
                        if chunk.usage is not None:
                            usage = chunk.usage
                        yield chunk
                    if span is not None:
                        span.set_attribute("outcome", "success")
                observability.record_model(provider_name, model, task, perf_counter() - started,
                                           usage=usage, ttft=first_token)
                return
            except ModelError as exc:
                observability.record_model(provider_name, model, task, perf_counter() - started,
                                           usage=usage, error=exc.kind, ttft=first_token)
                if emitted or not exc.transient:
                    raise
                if attempt < settings.GATEWAY_MAX_ATTEMPTS:
                    _pause(exc, attempt)
                elif route_index == len(routes) - 1:
                    raise
                else:
                    logger.warning("Model stream fallback task=%s failed_provider=%s kind=%s",
                                   task, provider_name, exc.kind)


def embed(texts: list[str], workspace_id: uuid.UUID | None = None) -> list[list[float]]:
    if not texts:
        return []
    if workspace_id is None:
        return LocalEmbeddingProvider().embed(texts)
    from app.services.embeddings import DIMENSIONS, MODEL_NAME
    vectors: list[list[float] | None] = [None] * len(texts)
    missing: dict[str, tuple[str, list[int]]] = {}
    for index, value in enumerate(texts):
        cache_key = cache.key("embedding", workspace_id, MODEL_NAME, DIMENSIONS, value)
        entry = cache.get("embedding", workspace_id, cache_key)
        vector = entry.get("data") if entry else None
        if isinstance(vector, list) and len(vector) == DIMENSIONS and all(
                isinstance(item, (int, float)) and math.isfinite(item) for item in vector):
            vectors[index] = vector
        elif cache_key in missing:
            missing[cache_key][1].append(index)
        else:
            missing[cache_key] = (value, [index])
    if missing:
        started = perf_counter()
        try:
            computed = LocalEmbeddingProvider().embed([item[0] for item in missing.values()])
        except Exception:
            observability.record_embedding(perf_counter() - started, 0, outcome="error")
            raise
        observability.record_embedding(perf_counter() - started, len(computed), outcome="success")
        elapsed_ms = (perf_counter() - started) * 1000 / len(missing)
        for (cache_key, (_, indices)), vector in zip(missing.items(), computed, strict=True):
            for index in indices:
                vectors[index] = vector
            cache.put("embedding", workspace_id, cache_key, vector,
                      settings.EMBEDDING_CACHE_TTL_SECONDS, elapsed_ms)
    return [vector for vector in vectors if vector is not None]


def health(task: Task) -> bool:
    if not configured(task):
        return False
    provider_name, model = _route(task)
    return _provider(provider_name).health(model)


def embedding_health() -> bool:
    return LocalEmbeddingProvider().health()
