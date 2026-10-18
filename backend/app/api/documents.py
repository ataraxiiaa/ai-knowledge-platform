import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.chunks import Chunk
from app.models.documents import Document, IngestionDispatch
from app.models.research import ResearchDispatch, ResearchJob, ResearchJobSource, ResearchJobStep
from app.services.ingestion import now
from app.models.users import User
from app.models.workspaces import Workspace
from app.schemas.documents import DocumentResponse, SearchRequest, SearchResult
from app.services.retrieval import retrieve_bm25, retrieve_hybrid, retrieve_passages, retrieve_reranked
from app.services.embeddings import MODEL_NAME
from app.services.storage import delete_document_file, store_pdf

router = APIRouter(prefix="/workspaces", tags=["Documents"])
logger = logging.getLogger(__name__)


def owned_workspace(id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.id == id, Workspace.user_id == user.id))
    if workspace is None:
        raise HTTPException(404, "Workspace not found")
    db.expunge(workspace)
    db.rollback()
    return workspace


def require_vector_database(db: Session = Depends(get_db)) -> None:
    if db.get_bind().dialect.name != "postgresql":
        raise HTTPException(503, "Document ingestion and semantic search require PostgreSQL with pgvector. Run migrations first.")


def document_response(document: Document, db: Session) -> DocumentResponse:
    count = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id))
    return DocumentResponse(
        id=document.id, workspace_id=document.workspace_id, filename=document.filename,
        status=document.status, error=document.error, created_at=document.created_at, chunk_count=count or 0,
        updated_at=document.updated_at, attempt_count=document.attempt_count,
        max_attempts=document.max_attempts, next_retry_at=document.next_retry_at,
    )


@router.post("/{id}/documents", response_model=DocumentResponse, status_code=202)
def upload_document(
    response: Response,
    workspace: Workspace = Depends(owned_workspace),
    file: UploadFile = File(...),
    chunk_size: int | None = Form(default=None, ge=64, le=1024),
    chunk_overlap: int | None = Form(default=None, ge=0),
    db: Session = Depends(get_db),
    _vector_db: None = Depends(require_vector_database),
):
    size = chunk_size if chunk_size is not None else settings.CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP
    if overlap >= size:
        raise HTTPException(422, "chunk_overlap must be smaller than chunk_size")
    document_id = uuid.uuid4()
    storage_key = store_pdf(file, workspace.id, document_id)
    filename = (file.filename or "document.pdf").replace("\\", "/").rsplit("/", 1)[-1][:255]
    document = Document(
        id=document_id, workspace_id=workspace.id, filename=filename,
        storage_path=storage_key, status="queued",
        chunk_size=size, chunk_overlap=overlap, pipeline_version=1, embedding_model=MODEL_NAME,
        max_attempts=settings.INGESTION_MAX_ATTEMPTS,
    )
    try:
        db.add(document)
        db.flush()
        db.add(IngestionDispatch(document_id=document_id))
        accepted = document_response(document, db)
        db.commit()
    except Exception:
        db.rollback()
        try:
            delete_document_file(workspace.id, document_id)
        except Exception:
            logger.exception("Could not remove PDF after failed database transaction: %s", document_id)
        raise
    response.headers["Location"] = f"/workspaces/{workspace.id}/documents/{document_id}"
    return accepted


@router.get("/{id}/documents", response_model=list[DocumentResponse])
def list_documents(workspace: Workspace = Depends(owned_workspace), db: Session = Depends(get_db)):
    documents = db.scalars(select(Document).where(Document.workspace_id == workspace.id).order_by(Document.created_at.desc())).all()
    return [document_response(document, db) for document in documents]


@router.get("/{id}/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: uuid.UUID, workspace: Workspace = Depends(owned_workspace), db: Session = Depends(get_db)):
    document = db.scalar(select(Document).where(Document.id == document_id, Document.workspace_id == workspace.id))
    if document is None:
        raise HTTPException(404, "Document not found")
    return document_response(document, db)


@router.delete("/{id}/documents/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, workspace: Workspace = Depends(owned_workspace), db: Session = Depends(get_db)):
    document = db.scalar(select(Document).where(Document.id == document_id, Document.workspace_id == workspace.id))
    if document is None:
        raise HTTPException(404, "Document not found")
    affected = db.scalars(select(ResearchJobSource.job_id).join(
        ResearchJob, ResearchJob.id == ResearchJobSource.job_id).where(
        ResearchJobSource.document_id == document_id,
        ResearchJob.workspace_id == workspace.id,
        ResearchJob.status.in_(["queued", "running", "retrying"]))).all()
    if affected:
        db.execute(update(ResearchJob).where(ResearchJob.id.in_(affected)).values(
            status="failed", error="A source document was deleted during research.",
            lease_token=None, lease_expires_at=None, next_retry_at=None,
            evidence=None, draft=None, verified_result=None,
            completed_at=now(), updated_at=now()))
        db.execute(update(ResearchJobStep).where(ResearchJobStep.job_id.in_(affected)).values(
            input=None, output=None))
        db.execute(update(ResearchJobStep).where(
            ResearchJobStep.job_id.in_(affected), ResearchJobStep.status == "running"
        ).values(status="failed", error="Source document deleted."))
        db.execute(delete(ResearchDispatch).where(ResearchDispatch.job_id.in_(affected)))
    db.delete(document)
    db.flush()
    db.execute(update(Workspace).where(Workspace.id == workspace.id).values(
        corpus_revision=Workspace.corpus_revision + 1))
    db.commit()
    try:
        delete_document_file(workspace.id, document_id)
    except Exception:
        logger.exception("Could not remove stored PDF %s", document_id)
    return Response(status_code=204)


@router.post("/{id}/search", response_model=list[SearchResult])
def search_documents(
    request: SearchRequest,
    workspace: Workspace = Depends(owned_workspace),
    db: Session = Depends(get_db),
    _vector_db: None = Depends(require_vector_database),
):
    if request.method == "bm25":
        return retrieve_bm25(request.query, request.top_k, workspace.id, db)
    if request.method == "hybrid_reranked":
        return retrieve_reranked(request.query, request.top_k, workspace.id, db)
    if request.method == "hybrid":
        return retrieve_hybrid(request.query, request.top_k, workspace.id, db)
    return retrieve_passages(request.query, request.top_k, workspace.id, db)
