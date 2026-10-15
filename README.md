# AI Knowledge Platform

A FastAPI and Next.js foundation for a workspace-based knowledge platform.
Authentication and workspace creation/listing/retrieval/deletion are implemented.
Phase 3 adds PDF ingestion, local CPU embeddings, pgvector storage, and semantic
passage search. Chat and research notes remain previews. This is not yet production-ready.

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
20. There is no generated answer yet and no approximate vector index: exact search
provides a baseline before measuring whether HNSW is needed.

Defaults: 10 MiB uploads, 100 pages, 1 million cleaned characters, 5000 chunks.
Encrypted PDFs and files without extractable text fail clearly. OCR, complex layout
reconstruction, background jobs, and object-storage uploads are not implemented.
Synchronous parsing/model work can exceed hosting request timeouts for large files;
begin with small text-based PDFs and one server worker on a memory-appropriate host.

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
