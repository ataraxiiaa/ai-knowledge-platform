from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from rq.serializers import JSONSerializer

from app import worker
from app.core.config import settings
from app.services.queue import ingestion_queue, redis_connection
from app.services.queue_smoke import inspect_shared_file


def test_queue_creation_does_not_contact_redis(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    connection = redis_connection()
    queue = ingestion_queue(connection)
    assert queue.connection is connection
    assert queue.serializer is JSONSerializer
    assert queue.create_job(inspect_shared_file, args=["probe"]).timeout == settings.RQ_JOB_TIMEOUT
    assert not connection.connection_pool.connection_kwargs.get("decode_responses", False)


@pytest.mark.parametrize("age, expected", [(0, True), (121, False)])
def test_health_requires_recent_worker_heartbeat(monkeypatch, age, expected):
    record = SimpleNamespace(last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=age))
    monkeypatch.setattr(worker.Worker, "find_by_key", lambda *args, **kwargs: record)
    assert worker.healthy(None) is expected


def test_missing_worker_is_unhealthy(monkeypatch):
    monkeypatch.setattr(worker.Worker, "find_by_key", lambda *args, **kwargs: None)
    assert worker.healthy(None) is False


def test_probe_rejects_path_input():
    with pytest.raises(ValueError):
        inspect_shared_file("../../private")
