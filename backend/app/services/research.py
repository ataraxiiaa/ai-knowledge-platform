"""Durable, resumable research state machine executed by an RQ worker."""
from datetime import timedelta
import logging
from threading import Event, Thread
import uuid

from sqlalchemy import delete, exists, select, update
from sqlalchemy.exc import DisconnectionError, OperationalError, TimeoutError as DatabaseTimeoutError

from app.db.session import SessionLocal
from app.models.research import ResearchDispatch, ResearchJob, ResearchJobSource
from app.services.ingestion import now, retry_delay_seconds
from app.services.research_logic import (
    ResearchError, ResearchTransientError, draft_report, ensure_live_sources,
    plan_questions, retrieve_evidence, verify_report,
)

logger = logging.getLogger(__name__)
LEASE_SECONDS = 120


def owned_job(job_id: uuid.UUID, token: uuid.UUID):
    return (ResearchJob.id == job_id, ResearchJob.status == "running",
            ResearchJob.lease_token == token, ResearchJob.lease_expires_at > now())


def touch(job_id: uuid.UUID, token: uuid.UUID) -> bool:
    with SessionLocal() as db:
        changed = db.execute(update(ResearchJob).where(*owned_job(job_id, token)).values(
            updated_at=now(), lease_expires_at=now() + timedelta(seconds=LEASE_SECONDS))).rowcount
        db.commit()
        return bool(changed)


def checkpoint(job_id: uuid.UUID, token: uuid.UUID, stage: str,
               next_stage: str, payload: dict | list) -> bool:
    field = {"PLANNING": "plan", "RETRIEVING": "evidence", "SYNTHESIZING": "draft"}[stage]
    with SessionLocal() as db:
        changed = db.execute(update(ResearchJob).where(*owned_job(job_id, token),
            ResearchJob.current_stage == stage).values(
                current_stage=next_stage, updated_at=now(),
                lease_expires_at=now() + timedelta(seconds=LEASE_SECONDS), **{field: payload})).rowcount
        if not changed:
            db.rollback()
            return False
        if stage == "RETRIEVING":
            ensure_live_sources(payload, db)
            for document_id in {uuid.UUID(item["document_id"]) for item in payload}:
                db.add(ResearchJobSource(job_id=job_id, document_id=document_id))
        db.commit()
        return True


def complete_job(job_id: uuid.UUID, token: uuid.UUID) -> bool:
    with SessionLocal() as db:
        changed = db.execute(update(ResearchJob).where(*owned_job(job_id, token),
            ResearchJob.current_stage == "VERIFYING").values(updated_at=now())).rowcount
        if not changed:
            db.rollback()
            return False
        job = db.get(ResearchJob, job_id)
        result = verify_report(job.plan, job.evidence or [], job.draft, db)
        job.result = result
        # The finished report retains only the exact cited quotes, not full chunks.
        job.evidence = None
        job.draft = None
        job.status = "completed"
        job.current_stage = "COMPLETED"
        job.error = None
        job.completed_at = now()
        job.lease_token = None
        job.lease_expires_at = None
        db.execute(delete(ResearchDispatch).where(ResearchDispatch.job_id == job_id))
        db.commit()
        return True


def process_research_job(job_id: str, dispatch_id: str) -> None:
    job_id, dispatch_id = uuid.UUID(job_id), uuid.UUID(dispatch_id)
    token = uuid.uuid4()
    with SessionLocal() as db:
        claimed = db.execute(update(ResearchJob).where(
            ResearchJob.id == job_id, ResearchJob.status == "queued",
            ResearchJob.attempt_count < ResearchJob.max_attempts,
            exists(select(ResearchDispatch.id).where(
                ResearchDispatch.id == dispatch_id, ResearchDispatch.job_id == job_id)),
        ).values(status="running", error=None, lease_token=token,
                 lease_expires_at=now() + timedelta(seconds=LEASE_SECONDS),
                 attempt_count=ResearchJob.attempt_count + 1, updated_at=now())).rowcount
        if not claimed:
            db.rollback()
            return
        job = db.get(ResearchJob, job_id)
        attempt_count, max_attempts = job.attempt_count, job.max_attempts
        db.commit()

    stopped, lost = Event(), Event()
    def heartbeat():
        while not stopped.wait(30):
            try:
                if not touch(job_id, token):
                    lost.set()
                    return
            except Exception:
                lost.set()
                logger.warning("Research heartbeat failed for %s", job_id)
                return
    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        for _ in range(4):
            if lost.is_set():
                return
            with SessionLocal() as db:
                job = db.get(ResearchJob, job_id)
                if job is None or job.status != "running" or job.lease_token != token:
                    return
                stage, query, workspace_id = job.current_stage, job.query, job.workspace_id
                method, plan, evidence = job.retrieval_method, job.plan, job.evidence
            if stage == "PLANNING":
                if not checkpoint(job_id, token, stage, "RETRIEVING", plan_questions(query)):
                    return
            elif stage == "RETRIEVING":
                if not checkpoint(job_id, token, stage, "SYNTHESIZING",
                                  retrieve_evidence(plan, workspace_id, method)):
                    return
            elif stage == "SYNTHESIZING":
                if not checkpoint(job_id, token, stage, "VERIFYING",
                                  draft_report(query, plan, evidence or [])):
                    return
            elif stage == "VERIFYING":
                complete_job(job_id, token)
                return
            else:
                raise ResearchError("Research job has an invalid stage.")
    except Exception as exc:
        transient = isinstance(exc, (ResearchTransientError, OperationalError,
                                     DisconnectionError, DatabaseTimeoutError))
        retry = transient and attempt_count < max_attempts
        logger.warning("Research job %s on attempt %s/%s (%s)",
                       "retry scheduled" if retry else "failed", attempt_count,
                       max_attempts, type(exc).__name__)
        with SessionLocal() as db:
            retry_at = now() + timedelta(seconds=retry_delay_seconds(attempt_count)) if retry else None
            changed = db.execute(update(ResearchJob).where(*owned_job(job_id, token)).values(
                status="retrying" if retry else "failed",
                error="Temporary research problem. Retrying automatically." if retry else
                    str(exc) if isinstance(exc, ResearchError) else
                    "Research failed. Please try again or contact the administrator.",
                next_retry_at=retry_at, updated_at=now(),
                completed_at=None if retry else now(),
                lease_token=None, lease_expires_at=None)).rowcount
            if changed:
                if retry:
                    scheduled = db.execute(update(ResearchDispatch).where(
                        ResearchDispatch.job_id == job_id).values(
                        due_at=retry_at, published_at=None)).rowcount
                    if scheduled != 1:
                        db.rollback()
                        raise RuntimeError("Missing durable research dispatch for retry")
                else:
                    db.execute(update(ResearchJob).where(ResearchJob.id == job_id).values(
                        evidence=None, draft=None))
                    db.execute(delete(ResearchDispatch).where(ResearchDispatch.job_id == job_id))
            db.commit()
    finally:
        stopped.set()
        thread.join(timeout=5)
