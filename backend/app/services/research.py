"""Durable, resumable research state machine executed by an RQ worker."""
from datetime import timedelta
import logging
from threading import Event, Thread
from time import perf_counter
import uuid

from sqlalchemy import delete, exists, select, update
from sqlalchemy.exc import DisconnectionError, OperationalError, TimeoutError as DatabaseTimeoutError

from app.db.session import SessionLocal
from app.models.research import ResearchDispatch, ResearchJob, ResearchJobSource, ResearchJobStep
from app.services.ingestion import now, retry_delay_seconds
from app.services.research_logic import (
    ResearchError, ResearchInvalidJSON, ResearchTransientError, draft_report, ensure_live_sources,
    plan_questions, retrieve_evidence, verify_report,
)
from app.services import observability

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
    field = {"PLANNING": "plan", "RETRIEVING": "evidence", "SYNTHESIZING": "draft",
             "VERIFYING": "verified_result"}[stage]
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
        step = db.get(ResearchJobStep, (job_id, stage))
        if step is None:
            step = ResearchJobStep(job_id=job_id, stage=stage, attempt_count=1)
            db.add(step)
        step.status = "completed"
        step.output = payload
        step.completed_at = now()
        step.error = None
        db.commit()
        return True


def begin_step(job_id: uuid.UUID, token: uuid.UUID, stage: str, payload: dict | list) -> bool:
    with SessionLocal() as db:
        if db.scalar(select(ResearchJob.id).where(*owned_job(job_id, token),
                ResearchJob.current_stage == stage)) is None:
            return False
        step = db.get(ResearchJobStep, (job_id, stage))
        if step is None:
            step = ResearchJobStep(job_id=job_id, stage=stage, attempt_count=0)
            db.add(step)
        if step.status == "completed":
            return False
        step.status = "running"
        step.input = payload
        step.attempt_count += 1
        step.started_at = now()
        step.error = None
        db.commit()
        return True


def complete_job(job_id: uuid.UUID, token: uuid.UUID) -> bool:
    with SessionLocal() as db:
        changed = db.execute(update(ResearchJob).where(*owned_job(job_id, token),
            ResearchJob.current_stage == "SAVING").values(updated_at=now())).rowcount
        if not changed:
            db.rollback()
            return False
        job = db.get(ResearchJob, job_id)
        if job.verified_result is None:
            raise ResearchError("Research verification checkpoint is missing.")
        ensure_live_sources(job.evidence or [], db)
        job.result = job.verified_result
        # The finished report retains only the exact cited quotes, not full chunks.
        job.evidence = None
        job.draft = None
        job.verified_result = None
        job.status = "completed"
        job.current_stage = "COMPLETED"
        job.error = None
        job.completed_at = now()
        job.lease_token = None
        job.lease_expires_at = None
        step = db.get(ResearchJobStep, (job_id, "SAVING"))
        step.status = "completed"
        step.output = {"published": True}
        step.completed_at = now()
        # Completed reports retain only quoted evidence, not source chunks.
        for stage in ("RETRIEVING", "SYNTHESIZING", "VERIFYING"):
            saved = db.get(ResearchJobStep, (job_id, stage))
            if saved is not None:
                saved.input = None
                saved.output = None
        db.execute(delete(ResearchDispatch).where(ResearchDispatch.job_id == job_id))
        db.commit()
        return True


@observability.job_span("research", "research_job")
def process_research_job(job_id: str, dispatch_id: str) -> None:
    job_started = perf_counter()
    job_outcome = "abandoned"
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
    stage = "PLANNING"
    try:
        for _ in range(5):
            if lost.is_set():
                return
            with SessionLocal() as db:
                job = db.get(ResearchJob, job_id)
                if job is None or job.status != "running" or job.lease_token != token:
                    return
                stage, query, workspace_id = job.current_stage, job.query, job.workspace_id
                method, plan, evidence, draft = job.retrieval_method, job.plan, job.evidence, job.draft
            if stage == "PLANNING":
                if not begin_step(job_id, token, stage, {"query": query}):
                    return
                with observability.research_stage(stage):
                    output = plan_questions(query)
                if not checkpoint(job_id, token, stage, "RETRIEVING", output):
                    return
            elif stage == "RETRIEVING":
                if not begin_step(job_id, token, stage, plan or {}):
                    return
                with observability.research_stage(stage):
                    output = retrieve_evidence(plan, workspace_id, method)
                if not checkpoint(job_id, token, stage, "SYNTHESIZING", output):
                    return
            elif stage == "SYNTHESIZING":
                if not begin_step(job_id, token, stage, {"plan": plan, "evidence": evidence or []}):
                    return
                with observability.research_stage(stage):
                    output = draft_report(query, plan, evidence or [])
                if not checkpoint(job_id, token, stage, "VERIFYING", output):
                    return
            elif stage == "VERIFYING":
                if not begin_step(job_id, token, stage, {"plan": plan, "evidence": evidence or [],
                                                         "draft": draft}):
                    return
                with SessionLocal() as db:
                    with observability.research_stage(stage):
                        verified = verify_report(plan, evidence or [], draft, db)
                if not checkpoint(job_id, token, stage, "SAVING", verified):
                    return
            elif stage == "SAVING":
                with observability.research_stage(stage):
                    with SessionLocal() as db:
                        verified_result = db.scalar(select(ResearchJob.verified_result).where(
                            ResearchJob.id == job_id))
                    if not begin_step(job_id, token, stage, {"verified_result": verified_result}):
                        return
                    complete_job(job_id, token)
                    job_outcome = "completed"
                return
            else:
                raise ResearchError("Research job has an invalid stage.")
    except Exception as exc:
        transient = isinstance(exc, (ResearchTransientError, OperationalError,
                                     DisconnectionError, DatabaseTimeoutError))
        retry = transient and attempt_count < min(max_attempts, 2 if isinstance(exc, ResearchInvalidJSON) else max_attempts)
        job_outcome = "retrying" if retry else "failed"
        if retry:
            observability.record_retry("research", "research_job")
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
                step = db.get(ResearchJobStep, (job_id, stage))
                if step is not None and step.status != "completed":
                    step.status = "failed"
                    step.error = "Temporary failure; retry scheduled." if retry else "Stage failed."
                if retry:
                    scheduled = db.execute(update(ResearchDispatch).where(
                        ResearchDispatch.job_id == job_id).values(
                        due_at=retry_at, published_at=None)).rowcount
                    if scheduled != 1:
                        db.rollback()
                        raise RuntimeError("Missing durable research dispatch for retry")
                else:
                    db.execute(update(ResearchJob).where(ResearchJob.id == job_id).values(
                        evidence=None, draft=None, verified_result=None))
                    db.execute(update(ResearchJobStep).where(ResearchJobStep.job_id == job_id,
                        ResearchJobStep.stage.in_(["RETRIEVING", "SYNTHESIZING", "VERIFYING", "SAVING"])
                    ).values(input=None, output=None))
                    db.execute(delete(ResearchDispatch).where(ResearchDispatch.job_id == job_id))
            db.commit()
    finally:
        stopped.set()
        thread.join(timeout=5)
        observability.record_job("research", "research_job", job_outcome,
                                 perf_counter() - job_started)
