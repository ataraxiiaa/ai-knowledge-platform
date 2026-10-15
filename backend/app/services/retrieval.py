"""Shared exact dense retrieval for search and RAG."""
import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunks import Chunk
from app.models.documents import Document
from app.schemas.documents import SearchResult
from app.services.embeddings import embed_texts
from app.services.text import IngestionError

logger = logging.getLogger(__name__)


def retrieve_passages(query: str, top_k: int, workspace_id: uuid.UUID, db: Session) -> list[SearchResult]:
    query = query.strip()
    if not query:
        raise HTTPException(422, "Query cannot be blank")
    try:
        vector = embed_texts([query])[0]
    except IngestionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("Query embedding failed")
        raise HTTPException(503, "Embedding model unavailable. Please try again.") from exc
    distance = Chunk.embedding.cosine_distance(vector)
    rows = db.execute(
        select(Chunk, Document.filename, distance.label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.workspace_id == workspace_id, Document.status == "ready")
        .order_by(distance, Chunk.id).limit(top_k)
    ).all()
    return [SearchResult(
        chunk_id=chunk.id, document_id=chunk.document_id, filename=filename,
        content=chunk.content, page=chunk.page, chunk_index=chunk.chunk_index,
        similarity=max(-1.0, min(1.0, 1.0 - float(dist))), metadata=chunk.chunk_metadata,
    ) for chunk, filename, dist in rows]
