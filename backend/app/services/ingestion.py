import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunks import Chunk
from app.models.documents import Document
from app.services.embeddings import MODEL_NAME, embed_texts, validate_vectors
from app.services.text import IngestionError, chunk_pages, extract_pages

logger = logging.getLogger(__name__)


def ingest_document(db: Session, document: Document, path: Path, size: int, overlap: int) -> None:
    """A small, synchronous pipeline. Chunk inserts and ready status commit together."""
    try:
        pages = extract_pages(path)
        chunks = chunk_pages(pages, size, overlap, settings.MAX_DOCUMENT_CHUNKS)
        vectors = embed_texts([chunk.content for chunk in chunks])
        validate_vectors(vectors, len(chunks))
        db.add_all([
            Chunk(
                document_id=document.id, content=chunk.content, page=chunk.page,
                chunk_index=chunk.chunk_index, embedding=vector,
                chunk_metadata={
                    "embedding_model": MODEL_NAME, "embedding_dimensions": 384,
                    "chunk_unit": "characters", "chunk_size": size, "chunk_overlap": overlap,
                    "start_char": chunk.start, "end_char": chunk.end,
                    "cleaning_version": 1, "parser": "pypdf",
                },
            ) for chunk, vector in zip(chunks, vectors, strict=True)
        ])
        document.status = "ready"
        document.error = None
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Document ingestion failed for %s", document.id)
        document.status = "failed"
        document.error = str(exc) if isinstance(exc, IngestionError) else "Ingestion failed. Please retry or contact the administrator."
        db.add(document)
        db.commit()
    db.refresh(document)
