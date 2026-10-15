# Repository Guidelines

## Project Structure & Module Organization

- `backend/app/` contains FastAPI routes (`api/`), configuration, SQLAlchemy models, Pydantic schemas, and PDF ingestion/embedding services.
- `backend/migrations/` holds Alembic schema revisions; `backend/tests/` contains pytest tests.
- `backend/scripts/` provides retrieval experiments and PostgreSQL verification; `backend/experiments/` stores the corpus and recorded results.
- `frontend/app/` contains Next.js routes; `components/`, `context/`, `lib/`, and `types/` hold shared UI, authentication state, API helpers, and TypeScript contracts. Static assets belong in `frontend/public/`.
- `README.md` documents setup and deployment; `LEARNING.md` explains architecture and experiments.

## Build, Test, and Development Commands

Run backend commands from `backend/`:

- `uv sync --locked` installs pinned dependencies.
- `uv run --locked alembic upgrade head` applies migrations to the configured database.
- `uv run --locked uvicorn app.main:app --reload --port 8000` starts the API.
- `uv run --locked pytest` runs isolated tests.

Run frontend commands from `frontend/`:

- `npm ci` installs locked dependencies; `npm run dev` starts development.
- `npm run lint` checks ESLint rules; `npx tsc --noEmit` checks types.
- `npm run build` verifies the production build.

## Coding Style & Naming Conventions

Follow existing patterns: Python uses four-space indentation, type hints, `snake_case` functions/modules, and `PascalCase` classes. TypeScript uses two-space indentation, `camelCase` functions, and `PascalCase` components/types; shared component filenames use kebab-case. ESLint extends Next.js and TypeScript rules. Read `frontend/AGENTS.md` and the relevant bundled Next.js documentation before frontend edits.

## Testing Guidelines

Use pytest files named `test_*.py` and functions named `test_*`. Add regression coverage for changed behavior, especially ownership checks, validation, ingestion failures, and migrations. No numeric coverage threshold is configured. Tests use isolated SQLite databases; real vector retrieval requires PostgreSQL. Run `scripts/verify_pgvector.py` only with `PHASE3_TEST_DATABASE_URL` pointing to an empty disposable database.

## Commit & Pull Request Guidelines

History mixes informal messages with Conventional Commits; prefer descriptive prefixes such as `feat(backend):`, `fix(frontend):`, and `refactor(frontend):`. Keep commits focused. PRs should explain the problem, resulting behavior, validation performed, and migration/configuration changes. Link relevant issues and include screenshots for UI changes.

## Security & Configuration

Copy `.env.example` to the root `.env`; never commit secrets. Configure a generated `SECRET_KEY` and PostgreSQL with pgvector for ingestion/search. Preserve workspace ownership checks. Keep uploaded PDFs and model caches untracked, and review migrations before applying them to existing databases.
