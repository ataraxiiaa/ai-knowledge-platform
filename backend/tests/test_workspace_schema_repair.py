"""The repair migration must preserve both healthy and drifted databases."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_repair_adds_missing_corpus_revision_without_losing_workspaces(tmp_path):
    url = f"sqlite:///{(tmp_path / 'drifted.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR,
                       env=env, check=True, capture_output=True)

    migrate("upgrade", "0008")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id,email,password_hash) "
                                "VALUES (:id,'owner@example.com','hash')"), {"id": "1" * 32})
        connection.execute(text("INSERT INTO workspaces (id,user_id,name) "
                                "VALUES (:id,:owner,'Existing workspace')"),
                           {"id": "2" * 32, "owner": "1" * 32})
        connection.execute(text("ALTER TABLE workspaces DROP COLUMN corpus_revision"))
    assert "corpus_revision" not in {column["name"] for column in inspect(engine).get_columns("workspaces")}

    migrate("upgrade", "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT name, corpus_revision FROM workspaces")).one()
        assert row == ("Existing workspace", 0)
    migrate("upgrade", "head")
    engine.dispose()


def test_repair_leaves_existing_corpus_revision_unchanged(tmp_path):
    url = f"sqlite:///{(tmp_path / 'healthy.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR,
                       env=env, check=True, capture_output=True)

    migrate("upgrade", "0008")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id,email,password_hash) "
                                "VALUES (:id,'owner@example.com','hash')"), {"id": "1" * 32})
        connection.execute(text("INSERT INTO workspaces (id,user_id,name,corpus_revision) "
                                "VALUES (:id,:owner,'Existing workspace',7)"),
                           {"id": "2" * 32, "owner": "1" * 32})
    migrate("upgrade", "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT corpus_revision FROM workspaces")) == 7
    engine.dispose()
