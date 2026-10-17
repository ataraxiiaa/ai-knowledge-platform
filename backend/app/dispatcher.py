"""Publish durable document work; run separately from the API and worker."""
import argparse
from datetime import timedelta
import logging
from pathlib import Path
import time

from sqlalchemy import and_, delete, or_, select, update
from app.db.session import SessionLocal
from app.models.documents import Document, IngestionDispatch
from app.services.ingestion import now, retry_delay_seconds
from app.services.queue import ingestion_queue

logger = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/ingestion-dispatcher-heartbeat")
RECOVERY_SCAN_SECONDS = 30
ACTIVE_STATUSES = ("processing", "chunking", "embedding")


def recover_expired_leases() -> int:
    """Fence abandoned attempts and schedule their replacement from durable state."""
    recovered = 0
    for _ in range(20):
        with SessionLocal() as db:
            document = db.scalar(select(Document).where(
                Document.status.in_(ACTIVE_STATUSES),
                Document.lease_expires_at <= now(),
            ).order_by(Document.lease_expires_at).with_for_update(skip_locked=True).limit(1))
            if document is None:
                break
            if document.attempt_count < document.max_attempts:
                retry_at = now() + timedelta(seconds=retry_delay_seconds(document.attempt_count))
                scheduled = db.execute(update(IngestionDispatch).where(
                    IngestionDispatch.document_id == document.id,
                ).values(due_at=retry_at, published_at=None)).rowcount
                if scheduled != 1:
                    db.rollback()
                    raise RuntimeError(f"Missing durable dispatch for expired lease {document.id}")
                document.status = "retrying"
                document.error = "Processing was interrupted. Retrying automatically."
                document.next_retry_at = retry_at
                document.finished_at = None
            else:
                document.status = "failed"
                document.error = "Processing was interrupted. Please upload again."
                document.next_retry_at = None
                document.finished_at = now()
                db.execute(delete(IngestionDispatch).where(IngestionDispatch.document_id == document.id))
            document.lease_token = None
            document.lease_expires_at = None
            document.updated_at = now()
            db.commit()
            recovered += 1
            logger.warning("Recovered expired ingestion lease for %s on attempt %s/%s",
                           document.id, document.attempt_count, document.max_attempts)
    return recovered


def dispatch_once() -> int:
    published = 0
    # One short transaction per record. Multiple dispatchers skip locked records.
    for _ in range(20):
        with SessionLocal() as db:
            dispatch = db.scalar(select(IngestionDispatch).join(Document).where(
                or_(Document.status == "queued", and_(
                    Document.status == "retrying",
                    Document.next_retry_at <= now(),
                    Document.attempt_count < Document.max_attempts,
                )), IngestionDispatch.due_at <= now()
            ).order_by(IngestionDispatch.due_at).with_for_update(skip_locked=True, of=IngestionDispatch).limit(1))
            if dispatch is None:
                break
            if db.execute(update(Document).where(
                Document.id == dispatch.document_id,
                Document.status == "retrying",
                Document.next_retry_at <= now(),
                Document.attempt_count < Document.max_attempts,
            ).values(status="queued", next_retry_at=None, updated_at=now())).rowcount:
                db.flush()
            elif db.scalar(select(Document.status).where(Document.id == dispatch.document_id)) != "queued":
                db.rollback()
                continue
            dispatch.publish_attempts += 1
            dispatch.due_at = now() + timedelta(seconds=60)
            try:
                ingestion_queue().enqueue("app.services.ingestion.process_document",
                    str(dispatch.document_id), str(dispatch.id), result_ttl=300, failure_ttl=86400,
                    ttl=120)
                dispatch.published_at = now()
                published += 1
            except Exception as exc:
                logger.warning("Dispatch unavailable (%s)", type(exc).__name__)
                db.commit()
                break
            db.commit()
            # Keep intent until the worker completes. Republish queued jobs after
            # 60s, including acknowledged messages lost from Redis. Claims dedupe.
    return published


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        raise SystemExit(0 if HEARTBEAT.exists() and time.time() - HEARTBEAT.stat().st_mtime < 120 else 1)
    logging.basicConfig(level=logging.INFO)
    last_recovery = 0.0
    while True:
        try:
            if args.once or time.monotonic() - last_recovery >= RECOVERY_SCAN_SECONDS:
                recover_expired_leases()
                last_recovery = time.monotonic()
            dispatch_once()
            HEARTBEAT.touch()
        except Exception as exc:
            logger.warning("Dispatcher database unavailable (%s)", type(exc).__name__)
        if args.once:
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
