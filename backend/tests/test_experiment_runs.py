import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.models.experiments import ExperimentRun


def run_record(**overrides):
    now = datetime.now(UTC)
    values = {"dataset_id": "synthetic-regression-v1", "corpus_sha256": "a" * 64,
              "split_sha256": "b" * 64, "code_version": "test-commit",
              "configuration": {"strategy": "vector", "chunk_size": 512},
              "status": "completed", "started_at": now, "completed_at": now}
    values.update(overrides)
    return ExperimentRun(**values)


def test_run_preserves_unknown_metrics_and_measured_zero(db_session):
    record = run_record(recall_at_5=0.0, prompt_tokens=0)
    db_session.add(record)
    db_session.commit()
    loaded = db_session.scalar(select(ExperimentRun).where(ExperimentRun.id == record.id))
    assert loaded.recall_at_5 == 0.0 and loaded.prompt_tokens == 0
    assert loaded.citation_accuracy is None and loaded.answer_quality is None
    assert loaded.p95_latency_ms is None and loaded.total_tokens is None
    assert loaded.dataset_id == "synthetic-regression-v1"


def test_terminal_status_and_metric_bounds(db_session):
    db_session.add(run_record(status="running"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    db_session.add(run_record(recall_at_5=1.1))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_orm_refuses_update_and_delete(db_session):
    record = run_record(status="failed", error="Provider timeout")
    db_session.add(record)
    db_session.commit()
    record.error = "Changed error"
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(record)
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()


def test_migrated_database_blocks_core_updates_and_deletes(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{(tmp_path / 'experiments.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=backend,
                       env=env, check=True, capture_output=True)

    migrate("upgrade", "head")
    migrate("check")
    engine = create_engine(url)
    identifier = uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO experiment_runs
            (id,dataset_id,corpus_sha256,split_sha256,code_version,configuration,status,started_at,completed_at)
            VALUES (:id,'synthetic-regression-v1',:corpus,:split,'test','{}','completed',:started,:completed)"""),
            {"id": identifier, "corpus": "a" * 64, "split": "b" * 64,
             "started": datetime.now(UTC), "completed": datetime.now(UTC)})
    with pytest.raises(IntegrityError, match="append-only"), engine.begin() as connection:
        connection.execute(text("UPDATE experiment_runs SET status='failed' WHERE id=:id"), {"id": identifier})
    with pytest.raises(IntegrityError, match="append-only"), engine.begin() as connection:
        connection.execute(text("DELETE FROM experiment_runs WHERE id=:id"), {"id": identifier})
    review_id = uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO experiment_reviews
            (id,run_id,report_sha256,rubric_version,reviewer,reviewer_type,review_payload)
            VALUES (:id,:run_id,:hash,'answer_quality_v1','Test','human','{}')"""),
            {"id": review_id, "run_id": identifier, "hash": "a" * 64})
    with pytest.raises(IntegrityError, match="append-only"), engine.begin() as connection:
        connection.execute(text("UPDATE experiment_reviews SET reviewer='Changed' WHERE id=:id"),
                           {"id": review_id})
    with pytest.raises(IntegrityError, match="append-only"), engine.begin() as connection:
        connection.execute(text("DELETE FROM experiment_reviews WHERE id=:id"), {"id": review_id})
    engine.dispose()
    migrate("downgrade", "0006")
    engine = create_engine(url)
    assert "experiment_runs" not in inspect(engine).get_table_names()
    assert "experiment_reviews" not in inspect(engine).get_table_names()
    engine.dispose()
