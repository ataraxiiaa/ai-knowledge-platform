# Phase 4 implementation review

Date: 2026-10-16. Phase 5 remains paused for review.

## Implemented

- Authenticated `POST /workspaces/{id}/chat` with a nonblank `message` up to 1024
  characters; workspace ownership is checked before retrieval/generation.
- Shared exact dense retrieval for search and chat: ready documents in the owned
  workspace, default top-k 5, stable tie ordering, original source metadata.
- Configurable OpenAI-compatible chat-completions provider with JSON mode, bounded
  output, timeout, and safe provider errors. No saved `.env` secrets were changed.
- Per-claim evidence contract. Source IDs and exact quotes are checked against
  context; citation numbers and document/page metadata are resolved by the server.
- Abstention when context is empty or the model finds insufficient evidence.
  Invalid evidence fails closed instead of returning an unsupported answer.
- Real frontend chat with loading/errors, source quotations, and passage inspection.
- README setup/API documentation and retrieval-versus-generation learning notes.
- Optional `--chat` mode for the existing disposable PostgreSQL integration script.

## Validation

Backend regression tests cover the endpoint, ownership before provider access,
input validation, empty-context short circuit, abstention, bad citations/quotes,
provider request shape, safe errors, multiple documents, and citation numbering.
Final result: **79 passed** in 21.42s, with one upstream Starlette/httpx deprecation
warning. Provider HTTP calls in the isolated tests use mocked transport; SQLite
does not exercise pgvector cosine SQL. `git diff --check` also passed.

Frontend ESLint, TypeScript, and production build passed. The build reports the
existing multiple-lockfile workspace-root warning. No browser visual QA was run.

A real local Ollama `llama3.1:8b` smoke test used a synthetic passage on page 7:

> The proposed approach was evaluated on only twelve English-language documents.
> Its main limitations are the small evaluation sample and the lack of multilingual testing.

For the limitations question, the model returned two cited claims (small sample;
no multilingual testing), both supported by the exact second sentence. Server
validation resolved the source to `synthetic-paper.pdf`, page 7. For an exact GPU
purchase-price question, it abstained with no sources. This test called the real
generation service but supplied the passage directly; it is not a full retrieval
test, a benchmark, or proof that all claims will be semantically correct.

## Remaining verification and scope

`PHASE3_TEST_DATABASE_URL` was unset and Docker's Linux engine was unavailable.
The real PDF -> pgvector -> LLM -> citation integration test was therefore not run.
Run `scripts/verify_pgvector.py --chat` with an empty disposable PostgreSQL database
and configured LLM before declaring the full end-to-end prerequisite verified.

An exact quote proves source provenance, not semantic entailment. Human evaluation
of claim support and abstention remains necessary. No conversation persistence,
streaming, hybrid retrieval, reranking, or Phase 5 dataset was added. Each chat
question is independent. Defaults remain local Ollama with an explicitly configured
model; the installed local model was used only for the synthetic smoke test.
