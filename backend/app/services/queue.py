"""Lazy queue connections; API imports never require Redis to be available."""
from redis import Redis
from rq import Queue
from rq.serializers import JSONSerializer

from app.core.config import settings


def redis_connection() -> Redis:
    # Keep binary responses: RQ decodes its own protocol fields.
    return Redis.from_url(settings.REDIS_URL, socket_connect_timeout=5, socket_timeout=5)


def ingestion_queue(connection: Redis | None = None) -> Queue:
    return Queue(settings.RQ_QUEUE_NAME, connection=connection if connection is not None else redis_connection(),
                 serializer=JSONSerializer, default_timeout=settings.RQ_JOB_TIMEOUT)


def research_queue(connection: Redis | None = None) -> Queue:
    return Queue(settings.RESEARCH_QUEUE_NAME,
                 connection=connection if connection is not None else redis_connection(),
                 serializer=JSONSerializer, default_timeout=settings.RESEARCH_JOB_TIMEOUT)
