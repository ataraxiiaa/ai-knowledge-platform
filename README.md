# AI Knowledge Platform — Phase 1: Production Backend Foundation

A robust, production-ready backend foundation built with FastAPI, PostgreSQL (SQLAlchemy 2.0), and Pydantic.

## Architecture

```text
               Internet / Client
                       │
                       ▼
            FastAPI Backend (:8000)
            ├── /health
            ├── /auth (register, login)
            └── /workspaces (CRUD)
                       │
                       ▼
             PostgreSQL (:5432)
            ├── users
            ├── workspaces
            └── documents
```

---

## Features Implemented

### 1. Database Schema
- **`users`**: `id` (UUID), `email` (unique index), `password_hash`, `created_at`
- **`workspaces`**: `id` (UUID), `user_id` (FK -> users.id, cascade), `name`, `description`, `created_at`
- **`documents`**: `id` (UUID), `workspace_id` (FK -> workspaces.id, cascade), `filename`, `status`, `created_at`

### 2. REST Endpoints
| Method | Path | Description | Auth Required |
|---|---|---|---|
| `GET` | `/health` | Service health status check | No |
| `POST` | `/auth/register` | Register a new user | No |
| `POST` | `/auth/login` | Authenticate and obtain JWT bearer token | No |
| `POST` | `/workspaces` | Create a new user-owned workspace | Yes (Bearer) |
| `GET` | `/workspaces` | List current user's workspaces | Yes (Bearer) |
| `GET` | `/workspaces/{id}` | Get workspace details by ID | Yes (Bearer) |
| `DELETE` | `/workspaces/{id}` | Delete workspace (cascades documents) | Yes (Bearer) |

---

## Getting Started

### Prerequisites
- Python 3.12+
- Docker & Docker Compose (optional, for containerized run)

### Local Setup (SQLite fallback or local Postgres)
1. Copy environment variables:
   ```bash
   cp .env.example .env
   ```
2. Install dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```
3. Start the FastAPI development server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
4. Access interactive API documentation:
   - Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
   - ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
   - Healthcheck: [http://localhost:8000/health](http://localhost:8000/health)

---

## Running with Docker Compose

Run the API and PostgreSQL in isolated containers:
```bash
docker compose up --build
```
The API will be available at `http://localhost:8000` and PostgreSQL on port `5432`.

---

## Running Tests

Run the test suite with pytest:
```bash
cd backend
pytest
```
The test suite runs against an isolated, fast in-memory SQLite database and covers:
- Service healthchecks
- User registration and validation
- Duplicate email rejection
- JWT authentication and bad password handling
- Workspace CRUD operations
- Tenancy isolation (users cannot see or delete others' workspaces)

---

## Deployment Guide (Public Endpoint)

To get a public endpoint returning `{"status": "healthy"}` at `/health`:

### Option A: Railway / Render
1. Push this repository to GitHub.
2. Link repository to Railway or Render.
3. Add a PostgreSQL database service.
4. Set environment variables on the backend service:
   - `DATABASE_URL`: Your managed PostgreSQL connection string
   - `SECRET_KEY`: A cryptographically secure random string
5. Deploy. The healthcheck endpoint is immediately available at `https://<your-service-url>/health`.
