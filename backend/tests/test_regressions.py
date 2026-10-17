import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from app.core.config import BACKEND_DIR, Settings


@pytest.mark.parametrize("driver, module", [
    ("postgresql+psycopg", "psycopg"),
    ("postgresql+psycopg2", "psycopg2"),
])
def test_postgresql_drivers_load_without_connecting(driver, module):
    # Engine construction loads the DBAPI, matching the Render startup failure.
    engine = create_engine(f"{driver}://user:password@localhost/test")
    try:
        assert engine.dialect.dbapi.__name__ == module
    finally:
        engine.dispose()


@pytest.mark.parametrize("password", ["a" * 73, "é" * 37])
def test_oversized_password_returns_validation_error(client, password):
    response = client.post("/auth/register", json={"email": "long@example.com", "password": password})
    assert response.status_code == 422
    assert "72 UTF-8 bytes" in response.text


@pytest.mark.parametrize("password", ["a" * 72, "é" * 36])
def test_password_at_byte_limit_can_login(client, password):
    payload = {"email": "boundary@example.com", "password": password}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/login", json=payload).status_code == 200
    assert client.post("/auth/login", json={**payload, "password": password + "x"}).status_code == 401


@pytest.mark.parametrize("secret", ["short", " " * 40, "development-secret-key-change-in-production-min-32-chars"])
def test_placeholder_secrets_rejected(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, SECRET_KEY=secret)


def test_secret_required(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("origins", ["*", "http://localhost:3000,*", '["*"]', "", '[42]'])
def test_wildcard_or_invalid_cors_rejected(origins):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CORS_ORIGINS=origins)


def test_env_file_is_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Path(Settings.model_config["env_file"]) == BACKEND_DIR.parent / ".env"


def test_migrations_and_startup_do_not_mutate_schema(tmp_path):
    database = tmp_path / "migration.db"
    url = f"sqlite:///{database.as_posix()}"
    env = {**os.environ, "DATABASE_URL": url}

    # Starting the app must not create tables or touch the configured database.
    subprocess.run([
        sys.executable, "-c",
        "from fastapi.testclient import TestClient\nfrom app.main import app\n"
        "with TestClient(app) as client:\n"
        "    assert client.get('/health').status_code == 200\n",
    ], cwd=BACKEND_DIR, env=env, check=True, capture_output=True)
    assert not database.exists()

    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, check=True, capture_output=True)

    migrate("upgrade", "head")

    migrate("check")
    engine = create_engine(url)
    assert {"users", "workspaces", "documents", "chunks"} <= set(inspect(engine).get_table_names())
    engine.dispose()
    migrate("downgrade", "base")
    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()
    migrate("upgrade", "head")


def test_background_migration_preserves_terminal_documents(tmp_path):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": url}
    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR,
                       env=env, check=True, capture_output=True)
    migrate("upgrade", "0002")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id,email,password_hash) VALUES (:id,'legacy@example.com','hash')"), {"id": "1" * 32})
        db.execute(text("INSERT INTO workspaces (id,user_id,name) VALUES (:id,:user,'legacy')"), {"id": "2" * 32, "user": "1" * 32})
        for i, status in enumerate(("ready", "failed", "processing", "pending"), 3):
            db.execute(text("INSERT INTO documents (id,workspace_id,filename,status) VALUES (:id,:workspace,'old.pdf',:status)"),
                       {"id": str(i) * 32, "workspace": "2" * 32, "status": status})
    migrate("upgrade", "head")
    migrate("check")
    with engine.connect() as db:
        rows = db.execute(text("SELECT status, error, chunk_size FROM documents ORDER BY id")).all()
        assert [row.status for row in rows] == ["ready", "failed", "failed", "failed"]
        assert rows[0].error is None and rows[1].error is None
        assert "interrupted" in rows[2].error
        assert all(row.chunk_size is None for row in rows)
    engine.dispose()
