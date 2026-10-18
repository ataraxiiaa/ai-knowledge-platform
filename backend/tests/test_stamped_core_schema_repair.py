"""A stamped but unmigrated database must be repaired without losing core rows."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


BACKEND_DIR = Path(__file__).resolve().parents[1]


def migrate(url, *args, succeeds=True):
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR,
                            env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True)
    assert (result.returncode == 0) == succeeds, result.stderr
    return result


def test_repair_rebuilds_skipped_schema_and_preserves_existing_rows(tmp_path):
    url = f"sqlite:///{(tmp_path / 'stamped.db').as_posix()}"
    migrate(url, "upgrade", "0001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id,email,password_hash) "
                                "VALUES (:id,'owner@example.com','hash')"), {"id": "1" * 32})
        connection.execute(text("INSERT INTO workspaces (id,user_id,name) "
                                "VALUES (:id,:owner,'Research')"),
                           {"id": "2" * 32, "owner": "1" * 32})
        connection.execute(text("INSERT INTO documents (id,workspace_id,filename,status) "
                                "VALUES (:id,:workspace,'paper.pdf','ready')"),
                           {"id": "3" * 32, "workspace": "2" * 32})
        connection.execute(text("ALTER TABLE workspaces ADD COLUMN corpus_revision INTEGER NOT NULL DEFAULT 0"))
    migrate(url, "stamp", "0009")
    migrate(url, "upgrade", "head")
    migrate(url, "check")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM workspaces")) == "Research"
        assert connection.execute(text("SELECT filename, status, attempt_count FROM documents")).one() == (
            "paper.pdf", "ready", 0)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010"
    assert {"chunks", "research_jobs", "research_job_steps", "experiment_runs"} <= set(
        inspect(engine).get_table_names())
    engine.dispose()


def test_repair_is_noop_for_complete_schema(tmp_path):
    url = f"sqlite:///{(tmp_path / 'complete.db').as_posix()}"
    migrate(url, "upgrade", "0009")
    migrate(url, "upgrade", "head")
    migrate(url, "check")


def test_repair_rejects_unexpected_partial_schema(tmp_path):
    url = f"sqlite:///{(tmp_path / 'partial.db').as_posix()}"
    migrate(url, "upgrade", "0001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE workspaces ADD COLUMN corpus_revision INTEGER NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE documents ADD COLUMN error TEXT"))
    migrate(url, "stamp", "0009")
    result = migrate(url, "upgrade", "head", succeeds=False)
    assert "Unexpected partial schema" in result.stderr
    assert "chunks" not in inspect(engine).get_table_names()
    engine.dispose()
