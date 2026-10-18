import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.documents import owned_workspace, require_vector_database
from app.core.config import settings
from app.services.model_gateway import configured
from app.db.session import get_db
from app.models.documents import Document
from app.models.research import ResearchDispatch, ResearchJob
from app.models.workspaces import Workspace
from app.schemas.research import ResearchJobCreate, ResearchJobDetail, ResearchJobSummary

router = APIRouter(prefix="/workspaces", tags=["Research"])


@router.post("/{id}/research-jobs", response_model=ResearchJobDetail, status_code=202)
def create_research_job(request: ResearchJobCreate, response: Response,
                        workspace: Workspace = Depends(owned_workspace),
                        db: Session = Depends(get_db),
                        _vector_db: None = Depends(require_vector_database)):
    if not configured("research_plan") or not configured("research_draft"):
        raise HTTPException(503, "Research generation is not configured.")
    ready = db.scalar(select(func.count()).select_from(Document).where(
        Document.workspace_id == workspace.id, Document.status == "ready"))
    if not ready:
        raise HTTPException(422, "Index at least one document before starting research.")
    job = ResearchJob(workspace_id=workspace.id, query=request.query,
                      status="queued", current_stage="PLANNING",
                      retrieval_method=settings.RAG_RETRIEVAL_METHOD,
                      max_attempts=settings.RESEARCH_MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    db.add(ResearchDispatch(job_id=job.id))
    accepted = ResearchJobDetail.model_validate(job)
    db.commit()
    response.headers["Location"] = f"/workspaces/{workspace.id}/research-jobs/{job.id}"
    return accepted


@router.get("/{id}/research-jobs", response_model=list[ResearchJobSummary])
def list_research_jobs(workspace: Workspace = Depends(owned_workspace),
                       db: Session = Depends(get_db)):
    jobs = db.scalars(select(ResearchJob).where(
        ResearchJob.workspace_id == workspace.id).order_by(
        ResearchJob.created_at.desc(), ResearchJob.id.desc()).limit(50)).all()
    result = [ResearchJobSummary.model_validate(job) for job in jobs]
    db.rollback()
    return result


@router.get("/{id}/research-jobs/{job_id}", response_model=ResearchJobDetail)
def get_research_job(job_id: uuid.UUID, workspace: Workspace = Depends(owned_workspace),
                     db: Session = Depends(get_db)):
    job = db.scalar(select(ResearchJob).where(
        ResearchJob.id == job_id, ResearchJob.workspace_id == workspace.id))
    if job is None:
        raise HTTPException(404, "Research job not found")
    result = ResearchJobDetail.model_validate(job)
    db.rollback()
    return result
