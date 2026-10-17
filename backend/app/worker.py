"""Separate Linux RQ worker; python -m app.worker [--burst|--healthcheck]."""
import argparse
from datetime import datetime, timezone
import os
import socket

from rq import Worker
from rq.serializers import JSONSerializer

from app.services.queue import ingestion_queue, research_queue, redis_connection
from app.core.config import settings
from app.services import observability


def worker_name() -> str:
    prefix = "research" if settings.RQ_QUEUE_NAME == settings.RESEARCH_QUEUE_NAME else "ingestion"
    return f"{prefix}-{socket.gethostname()}"


def healthy(connection) -> bool:
    worker = Worker.find_by_key(f"rq:worker:{worker_name()}", connection=connection,
                                serializer=JSONSerializer)
    return bool(worker and worker.last_heartbeat and
                (datetime.now(timezone.utc) - worker.last_heartbeat).total_seconds() < 120)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--burst", action="store_true", help="Exit after draining queued work")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    connection = redis_connection()
    if args.healthcheck:
        try:
            raise SystemExit(0 if healthy(connection) else 1)
        except Exception:
            raise SystemExit(1) from None
    if os.name == "nt":
        parser.error("Run the worker in the Linux Docker service; native Windows is not configured.")
    connection.ping()
    observability.initialize("ai-knowledge-worker")
    observability.observe_rq_queues(connection, settings.RQ_QUEUE_NAME, settings.RESEARCH_QUEUE_NAME)
    queue = research_queue(connection) if settings.RQ_QUEUE_NAME == settings.RESEARCH_QUEUE_NAME else ingestion_queue(connection)
    worker = Worker([queue], connection=connection,
                    serializer=JSONSerializer, name=worker_name(), worker_ttl=90)
    worker.work(burst=args.burst)


if __name__ == "__main__":
    main()
