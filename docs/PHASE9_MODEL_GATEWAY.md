# Phase 9: model gateway

`app.services.model_gateway` is the application boundary for inference. It
defines generation requests/results, token usage, stream chunks, normalized
errors, a provider interface, task routes, `embed`, and `health`. Chat and
research no longer own provider HTTP logic. Ingestion and retrieval use the
gateway's local embedding entry point. The 384-dimensional
`BAAI/bge-small-en-v1.5` index remains unchanged.

The OpenAI-compatible adapter uses Chat Completions JSON mode and works with the
project's existing Ollama-compatible default. The Gemini adapter uses native
`generateContent` and `streamGenerateContent` with JSON response MIME type.
Provider-specific token counts map to input/output counts when available; no
token estimate is invented when a provider omits usage. Internal health probes
are separate from database readiness and are not exposed to anonymous clients.
`OPENAI_TOKEN_LIMIT_FIELD` defaults to the legacy `max_tokens` request field;
set it to `max_completion_tokens` for models that require the newer field.

| Task | Provider setting | Model setting | Default |
|---|---|---|---|
| Chat | `CHAT_PROVIDER` | `CHAT_MODEL` | OpenAI-compatible `LLM_MODEL` |
| Research planning | `RESEARCH_PLAN_PROVIDER` | `RESEARCH_PLAN_MODEL` | OpenAI-compatible `LLM_MODEL` |
| Research drafting | `RESEARCH_DRAFT_PROVIDER` | `RESEARCH_DRAFT_MODEL` | OpenAI-compatible `LLM_MODEL` |
| Embedding | Fixed local adapter | Fixed model | Existing FastEmbed model |

Provider values are `openai_compatible` and `gemini`. A Gemini route must name
its model explicitly; it never inherits the OpenAI-compatible default model.
The OpenAI-compatible
endpoint/key come from `LLM_BASE_URL` and `LLM_API_KEY`; Gemini uses
`GEMINI_BASE_URL` and `GEMINI_API_KEY`. To enable fallback, set both
`MODEL_FALLBACK_PROVIDER` and `MODEL_FALLBACK_MODEL`. A route retries transient
timeouts, 429, and 5xx responses at most `GATEWAY_MAX_ATTEMPTS` times before
using the fallback. Delay is exponential or a capped `Retry-After`, at most five
seconds. Research's durable job retry remains the outer recovery layer.

The `stream` operation is internal. Fallback is possible before its first
emitted chunk, never after partial output. Public chat streaming is deferred
because its citation checks require a complete, validated answer. Provider
responses and keys are never copied into API error text. The gateway logs task,
provider, model, and token counts without prompts or document contents.

Mock-provider tests cover request shape, usage, streaming, routing, bounded
rate-limit retry, fallback, and refusal to fallback after partial output.
Live provider credentials are not needed for the test suite.

Provider contracts were checked against the official
[OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat)
and [Gemini generate-content reference](https://ai.google.dev/api/generate-content).
