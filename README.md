# AI Knowledge Platform

A FastAPI and Next.js foundation for a workspace-based knowledge platform.
Authentication and workspace creation/listing/retrieval/deletion are implemented.
Phase 3 adds PDF ingestion, local CPU embeddings, pgvector storage, and semantic
passage search. Phase 4 adds evidence-backed RAG chat with a configurable LLM.
Research notes remain a preview. This is not yet production-ready.

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

Compose starts PostgreSQL and the backend, applies migrations, and checks `/ready`.
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
| POST | `/workspaces/{id}/documents` | Multipart PDF upload and synchronous ingestion |
| GET | `/workspaces/{id}/documents` | List documents, statuses, errors, and chunk counts |
| GET | `/workspaces/{id}/documents/{document_id}` | Get document status |
| DELETE | `/workspaces/{id}/documents/{document_id}` | Remove document, chunks, and source PDF |
| POST | `/workspaces/{id}/search` | Return top-k passages using exact cosine search |
| POST | `/workspaces/{id}/chat` | Generate an answer with validated source quotations |

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

The synchronous pipeline is PDF upload -> pypdf page extraction -> whitespace
cleaning -> fixed character windows -> FastEmbed CPU inference -> pgvector.
`BAAI/bge-small-en-v1.5` produces 384-dimensional English text embeddings. The model
downloads on first use; document text is processed locally, not sent to a remote API.
The first upload can be slow, so optionally warm the model before serving traffic:

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

A 201 response means the document record was created. Check `status`: `ready` means
all chunks and vectors were committed; `failed` includes a safe error message and
no partial chunks. `processing` is persisted before extraction starts. If a process
dies during ingestion it can remain `processing`; refresh the list before retrying,
then delete/reupload a stale document. There is no task queue or automatic retry yet.

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
reconstruction, background jobs, and object-storage uploads are not implemented.
Synchronous parsing/model work can exceed hosting request timeouts for large files;
begin with small text-based PDFs and one server worker on a memory-appropriate host.

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

Run isolated tests with `uv run --locked pytest`. To verify the entire live path,
configure an **empty disposable** `PHASE3_TEST_DATABASE_URL`, plus the LLM settings,
and run from `backend/`:

```sh
uv run --locked python scripts/verify_pgvector.py --chat
```

This uploads a synthetic PDF, uses real local embeddings and PostgreSQL retrieval,
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

The [Phase 5 readiness review](backend/experiments/PHASE5_BASELINE.md) records the
vector-only baseline and gaps found before Phase 4 implementation. Phase 4 now adds
generation and citations; a full PostgreSQL + LLM smoke test remains required before
declaring the end-to-end gate verified. Hybrid retrieval work has not started.

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
