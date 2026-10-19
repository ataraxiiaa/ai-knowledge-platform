"""Single-process testing runner for free web hosts without a separate worker."""
import logging
from datetime import timedelta
from threading import Event, Thread

from sqlalchemy import and_, delete, or_, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.dispatcher import recover_expired_leases, recover_expired_research
from app.models.documents import Document, IngestionDispatch
from app.models.research import ResearchDispatch, ResearchJob
from app.services.ingestion import now, process_document
from app.services.research import process_research_job
from app.services.storage import document_path

logger = logging.getLogger(__name__)
POLL_SECONDS = 5
RESERVATION_SECONDS = 60


def _next_document() -> tuple[str, str] | None:
    with SessionLocal() as db:
        dispatch = db.scalar(select(IngestionDispatch).join(Document).where(
            or_(Document.status == "queued", and_(
                Document.status == "retrying", Document.next_retry_at <= now(),
                Document.attempt_count < Document.max_attempts,
            )), IngestionDispatch.due_at <= now(),
        ).order_by(IngestionDispatch.due_at).with_for_update(
            skip_locked=True, of=IngestionDispatch).limit(1))
        if dispatch is None:
            return None
        document = db.get(Document, dispatch.document_id)
        if settings.STORAGE_BACKEND == "local" and not document_path(
                document.workspace_id, document.id).is_file():
            document.status = "failed"
            document.error = "Uploaded PDF was lost when the web service restarted. Please upload it again."
            document.updated_at = now()
            document.finished_at = now()
            document.next_retry_at = None
            db.execute(delete(IngestionDispatch).where(IngestionDispatch.id == dispatch.id))
            db.commit()
            logger.warning("Local PDF missing for queued document %s", document.id)
            return None
        if document.status == "retrying":
            document.status = "queued"
            document.next_retry_at = None
            document.updated_at = now()
        dispatch.due_at = now() + timedelta(seconds=RESERVATION_SECONDS)
        dispatch.publish_attempts += 1
        document_id, dispatch_id = str(document.id), str(dispatch.id)
        db.commit()
        return document_id, dispatch_id


def _next_research() -> tuple[str, str] | None:
    with SessionLocal() as db:
        dispatch = db.scalar(select(ResearchDispatch).join(ResearchJob).where(
            or_(ResearchJob.status == "queued", and_(
                ResearchJob.status == "retrying", ResearchJob.next_retry_at <= now(),
                ResearchJob.attempt_count < ResearchJob.max_attempts,
            )), ResearchDispatch.due_at <= now(),
        ).order_by(ResearchDispatch.due_at).with_for_update(
            skip_locked=True, of=ResearchDispatch).limit(1))
        if dispatch is None:
            return None
        job = db.get(ResearchJob, dispatch.job_id)
        if job.status == "retrying":
            job.status = "queued"
            job.next_retry_at = None
            job.updated_at = now()
        dispatch.due_at = now() + timedelta(seconds=RESERVATION_SECONDS)
        dispatch.publish_attempts += 1
        job_id, dispatch_id = str(job.id), str(dispatch.id)
        db.commit()
        return job_id, dispatch_id


def run_once() -> bool:
    """Process at most one job; durable dispatch rows survive process restarts."""
    recover_expired_leases()
    recover_expired_research()
    document = _next_document()
    if document is not None:
        process_document(*document)
        return True
    research = _next_research()
    if research is not None:
        process_research_job(*research)
        return True
    return False


def _loop(stop: Event) -> None:
    logger.warning("Web-local job runner enabled; storage_backend=%s", settings.STORAGE_BACKEND)
    while not stop.is_set():
        try:
            if run_once():
                continue
        except Exception:
            logger.exception("Web-local job runner failed; retrying")
        stop.wait(POLL_SECONDS)


def start() -> tuple[Event, Thread]:
    stop = Event()
    thread = Thread(target=_loop, args=(stop,), name="web-local-jobs", daemon=True)
    thread.start()
    return stop, thread
