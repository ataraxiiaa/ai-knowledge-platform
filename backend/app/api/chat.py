import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.api.documents import owned_workspace, require_vector_database
from app.core.config import settings
from app.db.session import get_db
from app.models.workspaces import Workspace
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.generation import GenerationError, generate_answer
from app.services.retrieval import retrieve_bm25, retrieve_hybrid, retrieve_passages, retrieve_reranked

router = APIRouter(prefix="/workspaces", tags=["Chat"])
logger = logging.getLogger(__name__)


@router.post("/{id}/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    workspace: Workspace = Depends(owned_workspace),
    db: Session = Depends(get_db),
    _vector_db: None = Depends(require_vector_database),
) -> ChatResponse:
    started = perf_counter()
    try:
        retriever = {"vector": retrieve_passages, "bm25": retrieve_bm25,
                     "hybrid": retrieve_hybrid, "hybrid_reranked": retrieve_reranked}[settings.RAG_RETRIEVAL_METHOD]
        passages = retriever(request.message, settings.RAG_TOP_K, workspace.id, db)
    except HTTPException as exc:
        raise HTTPException(exc.status_code, f"Retrieval failed: {exc.detail}") from exc
    except Exception as exc:
        logger.warning("RAG retrieval failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Retrieval failed. Please try again.") from exc
    logger.info("RAG retrieval: chunks=%d elapsed_ms=%.1f", len(passages), (perf_counter() - started) * 1000)
    started = perf_counter()
    try:
        revision = db.scalar(select(Workspace.corpus_revision).where(Workspace.id == workspace.id))
        result = generate_answer(request.message, passages, workspace.id, revision)
    except GenerationError as exc:
        logger.warning("RAG generation failed")
        raise HTTPException(502, str(exc)) from exc
    logger.info("RAG generation: status=%s elapsed_ms=%.1f", result.status, (perf_counter() - started) * 1000)
    return result
