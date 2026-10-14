# AI Knowledge Platform

A FastAPI and Next.js foundation for a workspace-based knowledge platform.
Authentication and workspace creation/listing/retrieval/deletion are implemented.
Document uploads, chat, and research notes are previews: files and notes are not
persisted, and chat does not call a model. This is not yet production-ready.

## Structure

- `frontend/`: Next.js, React, TypeScript, and Tailwind UI.
- `backend/app/`: FastAPI routes, SQLAlchemy models, schemas, and JWT authentication.
- `backend/migrations/`: Alembic migrations for users, workspaces, and documents.
- `backend/tests/`: isolated API and migration tests.

The frontend calls FastAPI, which scopes workspace queries to the authenticated
user. Docker uses PostgreSQL; local development defaults to `backend/app.db`.

## Local setup

Requires Python 3.12+, uv, and Node.js compatible with the frontend.

1. Copy `.env.example` to `.env` at the repository root.
2. Generate a key with `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   and set `SECRET_KEY` in `.env`. Missing, short, and known placeholder keys are
   rejected. Changing an existing key signs out users. Never commit `.env`.
3. Leave `DATABASE_URL` unset for SQLite or set a PostgreSQL URL. The backend always
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

Before production use, further work includes rate limiting, reviewing session
storage (tokens currently use localStorage), PostgreSQL integration tests, and
implementing document storage and AI processing.
