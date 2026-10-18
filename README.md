ï»¿# AI Knowledge Platform

A FastAPI and Next.js foundation for a workspace-based knowledge platform.
Authentication and workspace creation/listing/retrieval/deletion are implemented.
Phase 3 adds PDF ingestion, local CPU embeddings, pgvector storage, and semantic
passage search. Phase 4 adds evidence-backed RAG chat with a configurable LLM.
Research jobs now produce cited reports from indexed workspace documents. This is
not yet production-ready.

## Structure

- `frontend/`: Next.js, React, TypeScript, and Tailwind UI.
- `backend/app/`: FastAPI routes, SQLAlchemy models, schemas, and JWT authentication.
- `backend/migrations/`: Alembic migrations for users, workspaces, documents, and vector chunks.
- `backend/experiments/`: reproducible chunk-size corpus and recorded measurements.
- `backend/tests/`: isolated API and migration tests.

The frontend calls FastAPI, which scopes workspace queries to the authenticated
user. Document ingestion/search require PostgreSQL with pgvector. SQLite remains
available for the authentication/workspace foundation and isolated tests only.

## Local setup

Requires Python 3.12+, uv, and Node.js compatible with the frontend.

1. Copy `.env.example` to `.env` at the repository root.
2. Generate a key with `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   and set `SECRET_KEY` in `.env`. Missing, short, and known placeholder keys are
   rejected. Changing an existing key signs out users. Never commit `.env`.
3. Set `DATABASE_URL` to a PostgreSQL database with pgvector available. The backend always
   reads the root `.env`, regardless of working directory. Process environment
   variables override the file. Move any settings from an old `backend/.env` into
   the root file; `backend/.env` is no longer loaded.
4. Install, migrate a new database, and start the backend:

   ```sh
   cd backend
   uv sync --locked
   uv run --locked alembic upgrade head
   uv run --locked uvicorn app.main:app --reload --port 8000
   ```

5. In another terminal:

   ```sh
   cd frontend
   npm ci
   npm run dev
   ```

For another API host, set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` before
starting/building the frontend. It defaults to `http://localhost:8000`.
`CORS_ORIGINS` accepts explicit HTTP(S) origins as a comma-separated string or JSON
array. Wildcards are rejected.

Registration requires at least six characters and at most 72 UTF-8 bytes, matching
bcrypt's limit. Existing bcrypt hashes remain compatible. Oversized login attempts
return an authentication error instead of crashing.

## Database migrations

Server startup no longer creates or changes tables. For an empty database, run
`uv run --locked alembic upgrade head` from `backend` before starting the API.

For databases created by the previous startup behavior, back up the database and
compare its tables, columns, indexes, and foreign keys with
`backend/migrations/versions/0001_initial.py`. Only if the schema matches, run:

```sh
uv run --locked alembic stamp 0001
uv run --locked alembic check
uv run --locked alembic upgrade head
```

Stamping records a version; it does not repair tables. Resolve schema differences
before adopting the baseline. Existing databases are not automatically stamped,
reset, or deleted. For future changes, generate and review a migration with
`uv run --locked alembic revision --autogenerate -m "describe change"`.
Run migrations once before starting production workers. Downgrades can delete data.

## Docker

Set the generated `SECRET_KEY` in the root `.env`, then run:

```sh
docker compose up --build
```

Compose starts PostgreSQL, Redis, the API, ingestion and research RQ workers, and the dispatcher;
it applies migrations before the processing services start. Check their status
and logs with `docker compose ps` and `docker compose logs -f worker dispatcher`.
Existing database volumes require the baseline procedure above first. The frontend
runs separately. Compose database credentials are for local development, and the
PostgreSQL port is bound to `127.0.0.1`; use appropriate credentials for deployment.

## API

| Method | Path | Behavior |
|---|---|---|
| GET | `/health` | Process liveness, without database access |
| GET | `/ready` | Database connectivity and required tables; 503 on failure |
| POST | `/auth/register` | Register with JSON email/password |
| POST | `/auth/login` | Return JWT bearer token |
| POST | `/workspaces` | Create workspace |
| GET | `/workspaces` | List owned workspaces |
| GET | `/workspaces/{id}` | Get owned workspace |
| DELETE | `/workspaces/{id}` | Delete owned workspace and its documents |
| POST | `/workspaces/{id}/documents` | Accept a PDF with 202; process it in the background |
| GET | `/workspaces/{id}/documents` | List documents, statuses, errors, and chunk counts |
| GET | `/workspaces/{id}/documents/{document_id}` | Get document status |
| DELETE | `/workspaces/{id}/documents/{document_id}` | Remove document, chunks, and source PDF |
| POST | `/workspaces/{id}/search` | Return top-k passages using vector (default), BM25, or hybrid retrieval |
| POST | `/workspaces/{id}/chat` | Generate an answer with validated source quotations |
| POST | `/workspaces/{id}/research-jobs` | Accept a staged research request with 202 |
| GET | `/workspaces/{id}/research-jobs` | List the latest 50 workspace jobs |
| GET | `/workspaces/{id}/research-jobs/{job_id}` | Read stage, evidence, and completed report |

Workspace endpoints require `Authorization: Bearer <token>`. API docs are at
`/docs` and `/redoc`. Workspace updates are not implemented.

## Tests and dependencies

```sh
cd backend
uv sync --locked
uv run --locked pytest
```

Tests set database/key configuration before importing the app. API tests use
in-memory SQLite; migration tests use temporary databases, never your `.env` database.

```sh
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

`backend/pyproject.toml` declares dependencies and `backend/uv.lock` pins them.
Docker installs generated, pinned requirements. After dependency changes:

```sh
cd backend
uv lock
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
```

## Phase 3: ingestion and retrieval

The processing pipeline is PDF upload -> pypdf page extraction -> whitespace
cleaning -> fixed character windows -> FastEmbed CPU inference -> pgvector.
`BAAI/bge-small-en-v1.5` produces 384-dimensional English text embeddings. The model
downloads on first use; document text is processed locally, not sent to a remote API.
The first indexing job can be slow, so optionally warm the model before serving traffic:

```sh
cd backend
uv run --locked python -m app.services.embeddings
```

Model input is limited to 512 tokens. We check untruncated token counts and reject
oversized chunks instead of silently embedding only part of their text. Chunk size
is measured in **Unicode characters, not tokens**. The default is 1024 characters
with 64-character overlap, selected from the small experiment below; it is provisional.
Windows stay within a page, and metadata records model, dimensions, chunk settings,
cleaned-text offsets, parser, and cleaning version. Original PDFs are stored under
UUID-generated relative paths; client filenames never choose a storage location.

Upload with a bearer token (shell variables below represent your own API URL,
workspace ID, and login token):

```sh
curl -X POST "$API_URL/workspaces/$WORKSPACE_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@document.pdf" -F "chunk_size=1024" -F "chunk_overlap=64"
```

A 202 response means the PDF and a durable dispatch intent were accepted. Poll the
document URL in the `Location` header. `ready` means all chunks and vectors were
committed; `retrying` includes the next retry time, and `failed` includes a safe
error message. Parsing and embedding run in the RQ worker, with bounded retries
and expired-lease recovery.

```sh
curl -X POST "$API_URL/workspaces/$WORKSPACE_ID/search" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"How does this work?","top_k":5}'
```

Search returns filename, page, chunk text, cosine similarity, and metadata. It only
searches ready documents in the authenticated user's workspace. Top-k is capped at
20. Generated answers use the separate chat endpoint. There is no approximate vector index: exact search
provides a baseline before measuring whether HNSW is needed.

Defaults: 10 MiB uploads, 100 pages, 1 million cleaned characters, 5000 chunks.
Encrypted PDFs and files without extractable text fail clearly. OCR, complex layout
reconstruction, and object-storage uploads are not implemented. Parsing and model
work run in the background worker; begin with small text-based PDFs and one worker
on a memory-appropriate host.

## Phase 4: your first RAG system

The chat path is question -> local embedding -> exact pgvector search -> top-k
passages -> structured LLM context -> answer with numbered evidence. Search and
chat share `backend/app/services/retrieval.py`; the default remains five chunks.
The Chat tab now calls the API and shows sources, quotations, loading/errors, and
an expandable view of the retrieved context. Each question is independent; no
conversation history is sent to the model or persisted.

Configure the root `.env` with a provider that supports OpenAI-compatible
`/chat/completions` and `response_format: {"type": "json_object"}`. For local Ollama:

```dotenv
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.1:8b
LLM_API_KEY=
LLM_TIMEOUT_SECONDS=60
RAG_TOP_K=5
```

Use an installed model supported by your hardware. The model name above is an
example, not an automatic download. See [Ollama's compatibility documentation](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx).
For another compatible provider, configure its base URL, model, and server-side
key. Questions and retrieved text are sent to that configured endpoint. The
backend defaults to local Ollama with no selected model and reports an explicit
configuration error until `LLM_MODEL` is set. Never put the key in a `NEXT_PUBLIC_`
variable. In Docker, `localhost` refers to the backend container; configure a
reachable model server address instead. Install dependencies with `uv sync --locked`.
No database migration is added by Phase 4.

```sh
curl -X POST "$API_URL/workspaces/$WORKSPACE_ID/chat" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"What are the main limitations of the proposed approach?"}'
```

A successful answer includes:

```json
{
  "answer": "The evaluation used a small sample. [1]",
  "sources": [
    {"id": 1, "document": "paper.pdf", "page": 7,
     "document_id": "...", "chunk_id": "...",
     "quote": "The evaluation used only twelve documents."}
  ],
  "retrieved_chunks": [],
  "status": "answered"
}
```

The example abbreviates `retrieved_chunks`; real answers include the actual
passages supplied to the LLM, with their IDs, ranks (array order), scores, and text.
The model returns individual claims with source IDs and exact quotations. The
server validates these against retrieved chunks and constructs citation numbers
and document/page metadata itself. Unsupported IDs, missing citations, fabricated
quotes, invalid JSON, and truncated completions fail with a safe generation error;
no unvalidated answer is returned. Repeated use of the same passage/quote shares a
citation number. Multiple quotes from one page may have different numbers.

When there are no retrieved chunks, the LLM is skipped. When the LLM judges the
context insufficient, it returns no claims. Both cases produce a fixed abstention,
`status: "insufficient_evidence"`, and an empty source list. An abstention makes no
factual document claim and therefore has no fabricated citation. There is no
uncalibrated similarity cutoff. Exact quotes establish provenance, **not semantic
entailment**: a model can still misinterpret a real quote. Evaluate claim support
and abstentions manually before trusting answers. Document instructions are treated
as untrusted data in the prompt; prompt separation is not a complete injection defense.

### Debug retrieval separately from generation

1. Inspect `retrieved_chunks` (or the Chat tab's passage inspector). If the needed
   evidence is absent, investigate ingestion, chunk boundaries, query wording, and
   retrieval ranking. Compare `/search` with the same question and `RAG_TOP_K`.
2. If the necessary evidence is present but the answer is wrong or abstains,
   investigate generation: the prompt, selected model, interpretation, and citations.
3. Retrieval errors are labeled `Retrieval failed`; provider and citation-validation
   errors are labeled `Generation ...` (HTTP 502). Authentication and database
   prerequisite errors keep their normal status codes. INFO logs record stage
   timing/counts without logging questions, document text, credentials, or provider
   response bodies. For generation errors, use `/search` to inspect the context.

Run isolated tests with `uv run --locked pytest`. To verify the database and model
path directly without RQ,
configure an **empty disposable** `PHASE3_TEST_DATABASE_URL`, plus the LLM settings,
and run from `backend/`:

```sh
uv run --locked python scripts/verify_pgvector.py --chat
```

This uploads a synthetic PDF, invokes ingestion directly, uses real local embeddings and PostgreSQL retrieval,
calls the configured LLM, validates quote/source mappings, and checks tenant
isolation and an empty workspace. It leaves migrated tables in the disposable
database; use a new empty database for each run. The existing command without
`--chat` remains a retrieval-only check. LLM output is nondeterministic; passing a
smoke test is not a retrieval or citation-accuracy benchmark.

## Render deployment for Phase 3

1. Keep the PostgreSQL `DATABASE_URL` and existing generated `SECRET_KEY`.
   Set `CORS_ORIGINS=https://research-agent-phi-drab.vercel.app`.
2. Install the updated `requirements.txt`. Migration `0002` runs
   `CREATE EXTENSION IF NOT EXISTS vector` and adds the new schema. The database
   role must be allowed to enable the extension, or an administrator must enable it.
   Render documents pgvector support at https://render.com/docs/postgresql-extensions.
3. Run `alembic upgrade head` from `backend` before starting the service. For the
   existing pre-migration schema, follow the baseline procedure above first.
   A simple single-instance start command is:
   `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Attach persistent storage and set `UPLOAD_DIR` to its uploads subdirectory, such
   as `/var/data/uploads`. Set `EMBEDDING_CACHE_DIR=/var/data/models` on that same disk
   to avoid downloading the model after each restart. Create/cache it at runtime;
   attached disks are not available during the build.
5. Set the health-check path to `/ready` to check the migrated tables.

Render's default filesystem is ephemeral. Without a persistent disk, uploaded PDFs
can disappear on restart/redeploy even though PostgreSQL retains their chunks.
See https://render.com/docs/disks. Free web services cannot attach persistent disks;
see https://render.com/docs/free. This implementation needs persistent disk storage
for durable original PDFs, or a future object-storage adapter.

Compose now uses `pgvector/pgvector:pg16` and separate persistent database and ingestion
volumes. Do not delete an existing database volume when switching images.

## Experiments and integration verification

The [Phase 5 evaluation dataset](backend/experiments/evaluation/README.md) contains
45 source-grounded examples: 40 answerable and five abstention checks, split into
33 development and 12 held-out questions. It uses the existing five-page authored
corpus. Validate annotations with
`uv run --locked python scripts/validate_evaluation_dataset.py` from `backend/`.
The [step 3 evaluation runner](backend/experiments/evaluation/RUNNER.md) records
vector-only Recall@5, MRR, latency, generation failures, abstentions, and a manual
citation-review worksheet. It defaults to development; held-out scoring requires
an explicit opt-in. [Step 4 adds BM25](backend/experiments/evaluation/BM25_RESULTS.md)
to the search API (`"method":"bm25"`) and Documents panel. Vector remains the default
and chat retrieval method. BM25 returns `bm25_score` with `similarity: null`, uses
ready chunks in the owned workspace, and returns no hits for no token overlap.
No migration is needed. `BM25_MAX_CHUNKS=20000` bounds the per-request in-memory
index; larger workspaces receive 503 instead of truncated rankings.

On the same development questions, BM25 matched vector evidence Recall@5 (0.9833)
and improved MRR from 0.9000 to 0.9833. This small synthetic comparison is not a
general quality claim. [Step 5 adds hybrid retrieval](backend/experiments/evaluation/HYBRID_RESULTS.md):
`"method":"hybrid"` merges up to `HYBRID_CANDIDATES=20` candidates per branch with
reciprocal rank fusion (`HYBRID_RRF_K=60`), deduplicates by chunk ID, and returns
top-k. The Documents selector supports hybrid. Chat can opt in with
`RAG_RETRIEVAL_METHOD=hybrid`; its default remains vector. Hybrid achieved the same
Recall@5 and MRR **0.9500**, between vector and BM25 on this development set.
[Step 6 adds a local cross-encoder](backend/experiments/evaluation/RERANK_RESULTS.md).
Use `"method":"hybrid_reranked"` for search or
`RAG_RETRIEVAL_METHOD=hybrid_reranked` for chat: fuse candidates, rerank up to
`RERANK_CANDIDATES=20`, then pass the best five to the LLM. Warm the model with
`uv run --locked python -m app.services.reranking` from `backend/`.
Failures explicitly return hybrid order with `rerank_status: "fallback"`.
Development MRR rose from 0.9500 to **0.9833**, with Recall@5 unchanged at
**0.9833** and median local retrieval latency **671 ms**. BM25 matched this MRR
on the small corpus; the vector default remains unchanged pending final review.

The [development baseline](backend/experiments/evaluation/RESULTS.md) measured
evidence Recall@5 **0.9833** and MRR **0.9000** on 30 answerable questions. Across
all 33 development questions, generation returned 26 answers, six validation
errors, and one abstention. Agent-reviewed citation support was **45/50 (90%)**;
independent human review is pending. These results expose generation failures
despite strong retrieval. The 12 held-out questions have now been scored in the final comparison below.

### Final held-out comparison

[Step 7 results and failure analysis](backend/experiments/evaluation/FINAL_RESULTS.md)
compare all four methods with fixed settings on 12 held-out questions (10
answerable, two unanswerable):

| Strategy | Recall@5 | MRR | Median retrieval | Citation support, agent review |
|---|---:|---:|---:|---:|
| Vector | 0.95 | 1.00 | 15.71 ms | 20/20 (100%) |
| BM25 | 0.95 | 0.90 | 0.15 ms | 10/12 (83.3%) |
| Hybrid | 0.95 | 1.00 | 19.72 ms | 20/21 (95.2%) |
| Hybrid + reranker | 0.95 | 1.00 | 753.06 ms | 8/10 (80%) |

**Decision: retain vector as the default.** Hybrid and reranking did not improve
held-out retrieval here. These are single local offline runs on ten synthetic
chunks, not production benchmarks. Generation failed on 4, 4, 6 and 5 of the
12 requests respectively. Citation support excludes those failures and does not
measure completeness or relevance; independent human review is pending.
The shared 0.95 recall ceiling comes from a required evidence sentence crossing
a chunk boundary. The held-out split is now consumed; use fresh data for future
tuning. Phase 5 is complete, with generation reliability and broader evaluation
identified as the next priorities.

The [Phase 5 step 1 review](backend/experiments/PHASE5_STEP1_REVIEW.md) records a
passing real PDF -> PostgreSQL -> local LLM -> validated citation smoke test and
a fresh vector-only baseline. The default chunk size achieved evidence Hit@5 of
1.000 and MRR of 0.875 on eight synthetic questions. These are smoke measurements,
not a general quality benchmark. Steps 1 and 2 are complete; step 3 adds the
evaluation runner before retrieval improvements. The [earlier readiness review](backend/experiments/PHASE5_BASELINE.md)
preserves the gaps found before Phase 4 implementation.

```sh
cd backend
uv run --locked python scripts/chunk_experiment.py
```

The experiment embeds an authored corpus with 256/512/1024-character windows and
fixed overlap 64. It records chunk count, duplicated characters, vector payload,
warm embedding time, evidence hit@1/3/5, reciprocal rank, and retrieved passages in
`experiments/results.json`. See `experiments/RESULTS.md` for interpretation and
`LEARNING.md` at the repository root for explanations. To evaluate your own PDF,
pass `--pdf path.pdf --corpus queries.json --output results.json`; the query JSON
must contain a `queries` array with `query` and exact cleaned `evidence` strings.

`scripts/verify_pgvector.py` performs a real PDF/CPU/vector/search smoke test. Set
`PHASE3_TEST_DATABASE_URL` to an **empty disposable PostgreSQL database** with the
vector extension available, then run `uv run --locked python scripts/verify_pgvector.py`. It refuses
nonempty databases and never uses `DATABASE_URL` from your `.env` as its target.

Before production use, further work includes rate limiting, parser process isolation,
reviewing session storage (tokens currently use localStorage), background ingestion,
and evaluation on representative documents and queries.


## Phase 6: background processing

[Step 1 design](docs/PHASE6_BACKGROUND_PROCESSING.md) defines the queue lifecycle.
[Step 2 infrastructure](docs/PHASE6_STEP2_REVIEW.md) adds Redis, a separate RQ
worker, JSON jobs, worker healthchecks and a reproducible shared-storage smoke
test. [Step 3](docs/PHASE6_STEP3_REVIEW.md) moves parsing, chunking and embedding
to the RQ worker. Upload now returns 202 after recording a durable PostgreSQL
dispatch intent, and document detail includes queued/processing/ready/failed
state. [Step 4](docs/PHASE6_STEP4_REVIEW.md) adds stage labels and polling with
backoff, pauses requests in background tabs, and gates search until a document is
indexed. [Step 5](docs/PHASE6_STEP5_REVIEW.md) adds bounded retries for classified
transient failures. [Step 6](docs/PHASE6_STEP6_REVIEW.md) recovers expired worker
leases and republishes lost Redis jobs, with a guarded orphan-PDF cleanup command.
[Step 7](docs/PHASE6_STEP7_REVIEW.md) validates the full queue-to-cited-chat path
with real embeddings and records acceptance time separately from indexing time.

The dispatcher scans expired leases every 30 seconds. Workers renew their
two-minute lease while running; if a worker dies, the dispatcher retries within
the document's saved attempt budget or marks it failed. The outbox republishes
queued jobs after 60 seconds if Redis loses a delivery. Run a dry-run orphan scan
in the backend container before explicitly applying removal of untracked PDFs
older than one hour:

```sh
docker compose exec backend python scripts/cleanup_orphan_pdfs.py
docker compose exec backend python scripts/cleanup_orphan_pdfs.py --apply
```

For a disposable integration run, prewarm `backend/.cache/embeddings`, set a
generated root `.env` `SECRET_KEY`, and use a unique Compose project name:

```sh
docker build -t knowledge-phase6-step3-check backend
docker compose -p phase6-e2e -f docker-compose.ingestion-test.yml up -d db redis migrate worker dispatcher
docker compose -p phase6-e2e -f docker-compose.ingestion-test.yml run --rm --no-deps --entrypoint python probe scripts/verify_end_to_end.py
docker compose -p phase6-e2e -f docker-compose.ingestion-test.yml down -v
```

The probe uses a real PDF, worker, embedding model, pgvector search and chat API.
It uses a deterministic local OpenAI-compatible provider to verify the citation
contract, so it does not measure language-model answer quality. The test Compose
file has no host ports or production volumes; `down -v` removes only the named
disposable project.

## Phase 7: research jobs

Research jobs turn one workspace question into two to four planned subquestions,
retrieve up to five passages per question from ready documents, draft bounded
claims, and verify exact evidence quotes before publishing a report. The
application controls the stages `PLANNING`, `RETRIEVING`, `SYNTHESIZING`,
`VERIFYING`, `SAVING`, and `COMPLETED`; the LLM performs the plan and draft operations.
This is one deterministic workflow, not a collection of agent personalities.

Start a job and poll the URL returned in `Location`:

```sh
curl -X POST "$API_URL/workspaces/$WORKSPACE_ID/research-jobs" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"Compare the approaches in these papers for reducing LLM inference memory usage."}'
```

Set `LLM_MODEL` and a `LLM_BASE_URL` reachable **from the research worker
container**. The research queue is separate from ingestion; the dispatcher
publishes both queues from durable database intents. Jobs retry transient provider
or retrieval failures up to three attempts and resume from the last saved stage.
`docker compose ps research_worker dispatcher` and
`docker compose logs -f research_worker dispatcher` help diagnose processing.

Reports retain exact cited quotes when a source document is later deleted.
Deleting a source during an active job fails that job; deleting its workspace
removes all reports. Verification checks source identity and exact quote presence,
but cannot establish that a quote semantically supports a claim. Review reports
accordingly. [Architecture and validation details](docs/PHASE7_RESEARCH_JOBS.md).

## Phase 8: checkpoints and recovery

Each research stage now has a `research_job_steps` record with status, input,
output, attempt count, timing, and a safe error summary. `VERIFYING` saves a
checked report, while `SAVING` publishes it in a separate transaction. If SAVE
fails or its worker crashes, the retry starts at SAVE without rerunning the LLM.
Completed reports discard full retrieved chunks and draft snapshots; step status
and attempt history remain visible in job detail and on the research page.

Transient provider, embedding/retrieval, and database errors use bounded retries
with exponential delays. Invalid JSON gets one retry. Expired worker leases are
recovered by the dispatcher; a duplicate delivery cannot claim a completed job.
An interrupted stage may execute again if its output was not committed, so
external operations must tolerate at-least-once execution. See
[checkpoint and fault testing details](docs/PHASE8_CHECKPOINTING.md).

## Phase 9: model gateway

Chat, research planning, research drafting, and embeddings call one model
gateway. The default route keeps the existing `LLM_BASE_URL`/`LLM_MODEL`
OpenAI-compatible setup, including Ollama or vLLM servers. Set the task-specific
`CHAT_*`, `RESEARCH_PLAN_*`, or `RESEARCH_DRAFT_*` provider and model variables to
route a task to Gemini or another model. Gemini requires `GEMINI_API_KEY` and
uses `GEMINI_BASE_URL`; keys remain server-side. An explicitly configured
`MODEL_FALLBACK_PROVIDER` and `MODEL_FALLBACK_MODEL` are used only after transient
generation failures. No fallback is used for rejected or malformed responses.

The gateway normalizes provider errors and token counts, honors short `Retry-After`
delays, and offers internal streaming. The public chat endpoint still returns a
complete citation-checked answer; it does not expose unchecked partial text.
Embeddings remain on the existing local model. Changing that model requires
reindexing documents because a matching vector dimension alone does not mean
matching vector semantics. [Gateway configuration and behavior](docs/PHASE9_MODEL_GATEWAY.md).

## Phase 10: caching and cost measurement

Redis caches workspace-scoped local embeddings, retrieval results, and validated
chat model output. Retrieval and chat keys include a durable workspace corpus
revision, incremented when a document becomes searchable or is deleted. Cache
failures fall back to normal processing. An owner can inspect current UTC-day
hits, misses, estimated latency and token savings at
`GET /workspaces/{id}/cache-metrics`. API cost savings are estimated only when
`CACHE_MODEL_PRICES_JSON` provides rates for the actual provider and model.
Research drafts and incomplete model streams are not cached. See
[cache design, invalidation, and benchmark](docs/PHASE10_CACHING.md).

## Phase 11: observability

FastAPI, model calls, retrieval, research stages, workers, and the dispatcher
emit OpenTelemetry signals. The local Compose stack routes traces through the
Collector to Tempo and metrics through the Collector to Prometheus. Grafana
provisions the AI Knowledge Platform dashboard at `http://localhost:3001`;
Prometheus is at `http://localhost:9090`. Configure a unique
`GRAFANA_ADMIN_PASSWORD` in `.env` before starting the stack. Container CPU and
memory come from cAdvisor. Enable the optional `gpu` Compose profile to collect
NVIDIA GPU and VRAM metrics. See [Phase 11 setup and signal details](docs/PHASE11_OBSERVABILITY.md).

# Production deployment

Phase 12 adds an isolated HTTPS Docker Compose deployment with Caddy, persistent PostgreSQL/Redis, S3-compatible PDF storage, offsite database backups, health checks, secret files, and bounded service logs. Follow [the production runbook](docs/PHASE12_PRODUCTION.md) before deploying to a Linux host. No cloud resources or domain are provisioned by this repository.

## CI/CD

Phase 13 adds pull-request quality/security gates, a disposable PostgreSQL/worker integration test, SHA-tagged GHCR images, and a manual production deployment with migration, backup, health verification, and image rollback. See [the CI/CD setup and merge-protection guide](docs/PHASE13_CICD.md). GitHub environment secrets, branch protection, and the VPS must be configured before deployment.

## Evaluation runs

Phase 14 freezes the synthetic regression fixture and adds append-only `experiment_runs` storage for completed or failed evaluations. See the [dataset contract](backend/experiments/evaluation/PHASE14_CONTRACT.md), [run storage design](backend/experiments/evaluation/PHASE14_STEP2.md), [quality-review rubric](backend/experiments/evaluation/PHASE14_STEP4.md), [stored-run comparison](backend/experiments/evaluation/PHASE14_STEP5.md), and [CI regression gate](backend/experiments/evaluation/PHASE14_STEP6.md).

The [evaluation runner](backend/experiments/evaluation/RUNNER.md) can record a completed run with `--persist` when `DATABASE_URL` points at a migrated database. JSON output remains the default and retains per-question retrieval, generation, total latency, actual provider/model, and reported token usage. Reviews and comparisons are separate append-only/read-only operations.

The [Phase 14 regression snapshot](backend/experiments/evaluation/PHASE14_STEP7.md) compares vector, BM25, hybrid, and reranked hybrid on both frozen splits. Each method reached 0.9833 development and 0.95 historical held-out evidence Recall@5. The runs were retrieval-only, so answer quality and citation accuracy remain unmeasured; the synthetic corpus cannot establish production quality.

## Phase 15: load testing

The [load-test runbook and measured results](docs/PHASE15_LOAD_TESTING.md) cover a disposable PostgreSQL/Redis/model stack, a two-document indexed fixture, and chat and research ladders at 1, 5, 10, 25, 50, and 100 concurrent clients. The harness records successful throughput, P50/P95/P99 latency, errors, queue depth, database connections, and container memory. In the synthetic 100-user chat run, releasing the read transaction before model generation reduced errors from 41/300 to 0/300. Research throughput improved from 0.43 to 1.59 completed jobs/second with four research workers and four API processes; that comparison used different polling intervals, as detailed in the runbook. These results are local capacity evidence, not production SLOs.
