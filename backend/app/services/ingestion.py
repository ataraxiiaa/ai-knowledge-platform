"""Claimed background ingestion; chunks become searchable in one transaction."""
from datetime import datetime, timedelta, timezone
import logging
from threading import Event, Thread
from time import perf_counter
import uuid

import httpx
from sqlalchemy import delete, exists, select, update
from sqlalchemy.exc import DisconnectionError, OperationalError, TimeoutError as DatabaseTimeoutError
from app.db.session import SessionLocal
from app.models.chunks import Chunk
from app.models.documents import Document, IngestionDispatch
from app.models.workspaces import Workspace
from app.services.embeddings import MODEL_NAME, validate_vectors
from app.services.model_gateway import embed as embed_texts
from app.services.storage import StorageUnavailable, open_document
from app.services.text import IngestionError, chunk_pages, extract_pages
from app.core.config import settings
from app.services import observability

logger = logging.getLogger(__name__)
LEASE_SECONDS = 120
RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 480


def retry_delay_seconds(attempt_count: int) -> int:
    """First and second retries wait 30 and 120 seconds respectively."""
    return min(RETRY_BASE_SECONDS * 4 ** (attempt_count - 1), RETRY_MAX_SECONDS)


def retryable_failure(exc: Exception, stage: str) -> bool:
    """Only transport/model availability and database availability merit replay."""
    if isinstance(exc, IngestionError):
        return False
    if isinstance(exc, (OperationalError, DisconnectionError, DatabaseTimeoutError, StorageUnavailable)):
        return True
    return stage == "embedding" and isinstance(
        exc, (OSError, ConnectionError, TimeoutError, httpx.TransportError)
    )


def now():
    return datetime.now(timezone.utc)


def owned_claim(document_id, token):
    return (Document.id == document_id, Document.lease_token == token,
            Document.lease_expires_at > now(),
            Document.status.in_(["processing", "chunking", "embedding"]))


def touch(document_id, token, **values):
    with SessionLocal() as db:
        changed = db.execute(update(Document).where(*owned_claim(document_id, token)).values(
            updated_at=now(), lease_expires_at=now() + timedelta(seconds=LEASE_SECONDS), **values)).rowcount
        db.commit()
        return bool(changed)


@observability.job_span("ingestion", "document_ingestion")
def process_document(document_id: str, dispatch_id: str) -> None:
    job_started = perf_counter()
    job_outcome = "abandoned"
    document_id, dispatch_id = uuid.UUID(document_id), uuid.UUID(dispatch_id)
    token = uuid.uuid4()
    with SessionLocal() as db:
        changed = db.execute(update(Document).where(
            Document.id == document_id, Document.status == "queued",
            Document.attempt_count < Document.max_attempts,
            exists(select(IngestionDispatch.id).where(IngestionDispatch.id == dispatch_id,
                   IngestionDispatch.document_id == document_id)),
        ).values(status="processing", lease_token=token,
                 lease_expires_at=now() + timedelta(seconds=LEASE_SECONDS),
                 attempt_count=Document.attempt_count + 1, started_at=now(), updated_at=now())).rowcount
        if not changed:
            db.rollback()
            return
        document = db.get(Document, document_id)
        workspace_id, size, overlap = document.workspace_id, document.chunk_size, document.chunk_overlap
        version, model = document.pipeline_version, document.embedding_model
        attempt_count, max_attempts = document.attempt_count, document.max_attempts
        db.commit()

    stopped, lost = Event(), Event()
    def heartbeat():
        while not stopped.wait(30):
            try:
                if not touch(document_id, token):
                    lost.set()
                    return
            except Exception:
                lost.set()
                logger.warning("Ingestion heartbeat failed for %s", document_id)
                return
    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    stage = "parsing"
    try:
        if version != 1 or model != MODEL_NAME or size is None or overlap is None:
            raise IngestionError("Unsupported saved ingestion configuration. Please upload again.")
        with open_document(workspace_id, document_id) as path:
            pages = extract_pages(path)
        if lost.is_set() or not touch(document_id, token, status="chunking"):
            return
        stage = "chunking"
        chunks = chunk_pages(pages, size, overlap, settings.MAX_DOCUMENT_CHUNKS)
        if not touch(document_id, token, status="embedding"):
            return
        stage = "embedding"
        vectors = embed_texts([chunk.content for chunk in chunks], workspace_id)
        validate_vectors(vectors, len(chunks))
        if lost.is_set():
            return
        stage = "publishing"
        with SessionLocal() as db:
            # Conditional UPDATE locks the document until the complete index commits.
            changed = db.execute(update(Document).where(*owned_claim(document_id, token)).values(
                status="ready", error=None, updated_at=now(), finished_at=now(),
                lease_token=None, lease_expires_at=None)).rowcount
            if not changed:
                db.rollback()
                return
            db.execute(delete(Chunk).where(Chunk.document_id == document_id))
            db.add_all([Chunk(document_id=document_id, content=chunk.content, page=chunk.page,
                chunk_index=chunk.chunk_index, embedding=vector, chunk_metadata={
                    "embedding_model": model, "embedding_dimensions": 384,
                    "chunk_unit": "characters", "chunk_size": size, "chunk_overlap": overlap,
                    "start_char": chunk.start, "end_char": chunk.end,
                    "cleaning_version": version, "parser": "pypdf",
                }) for chunk, vector in zip(chunks, vectors, strict=True)])
            db.execute(delete(IngestionDispatch).where(IngestionDispatch.document_id == document_id))
            db.execute(update(Workspace).where(Workspace.id == workspace_id).values(
                corpus_revision=Workspace.corpus_revision + 1))
            db.commit()
        job_outcome = "completed"
    except Exception as exc:
        retry = retryable_failure(exc, stage) and attempt_count < max_attempts
        job_outcome = "retrying" if retry else "failed"
        if retry:
            observability.record_retry("ingestion", "document_ingestion")
        logger.warning("Document ingestion %s for %s on attempt %s/%s (%s)",
                       "retry scheduled" if retry else "failed", document_id,
                       attempt_count, max_attempts, type(exc).__name__)
        with SessionLocal() as db:
            retry_at = now() + timedelta(seconds=retry_delay_seconds(attempt_count)) if retry else None
            changed = db.execute(update(Document).where(*owned_claim(document_id, token)).values(
                status="retrying" if retry else "failed",
                error="Temporary processing problem. Retrying automatically." if retry else
                    str(exc) if isinstance(exc, IngestionError) else
                    "Ingestion failed. Please upload again or contact the administrator.",
                next_retry_at=retry_at, updated_at=now(),
                finished_at=None if retry else now(), lease_token=None, lease_expires_at=None)).rowcount
            if changed:
                if retry:
                    scheduled = db.execute(update(IngestionDispatch).where(
                        IngestionDispatch.document_id == document_id).values(
                        due_at=retry_at, published_at=None)).rowcount
                    if scheduled != 1:
                        db.rollback()
                        raise RuntimeError("Missing durable dispatch for retry")
                else:
                    db.execute(delete(IngestionDispatch).where(IngestionDispatch.document_id == document_id))
            db.commit()
    finally:
        stopped.set()
        thread.join(timeout=5)
        observability.record_job("ingestion", "document_ingestion", job_outcome,
                                 perf_counter() - job_started)
