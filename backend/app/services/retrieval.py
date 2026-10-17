"""Shared exact dense retrieval for search and RAG."""
import logging
import uuid
from functools import wraps
from time import perf_counter

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunks import Chunk
from app.models.documents import Document
from app.models.workspaces import Workspace
from app.core.config import settings
from app.services.bm25 import BM25Index, tokenize
from app.services.hybrid import reciprocal_rank_fusion
from app.schemas.documents import SearchResult
from app.services.model_gateway import embed as embed_texts
from app.services import cache
from app.services.embeddings import MODEL_NAME as EMBEDDING_MODEL_NAME
from app.services.reranking import MODEL_NAME as RERANK_MODEL_NAME
from app.services.text import IngestionError
from app.services import observability

logger = logging.getLogger(__name__)


def cached(method: str):
    """Cache complete retrieval output under a durable corpus revision."""
    def decorate(function):
        @wraps(function)
        def wrapped(query: str, top_k: int, workspace_id: uuid.UUID, db: Session) -> list[SearchResult]:
            started = perf_counter()
            with observability.span("rag.retrieval", {"rag.retrieval.method": method, "rag.top_k": top_k}) as current:
                try:
                    results = _retrieve_cached(function, query, top_k, workspace_id, db, method)
                    if current is not None:
                        current.set_attribute("rag.retrieval.chunks", len(results))
                    observability.record_retrieval(method, perf_counter() - started, len(results))
                    return results
                except Exception:
                    if current is not None:
                        current.set_attribute("error", True)
                    observability.record_retrieval(method, perf_counter() - started, 0)
                    raise
        return wrapped
    return decorate


def _retrieve_cached(function, query, top_k, workspace_id, db, method):
    if not query.strip() or db is None:
        return function(query, top_k, workspace_id, db)
    revision = db.scalar(select(Workspace.corpus_revision).where(Workspace.id == workspace_id))
    if revision is None:
        return function(query, top_k, workspace_id, db)
    configuration = {"embedding_model": EMBEDDING_MODEL_NAME,
        "rerank_model": RERANK_MODEL_NAME,
        "bm25_max": settings.BM25_MAX_CHUNKS,
        "hybrid_candidates": settings.HYBRID_CANDIDATES,
        "hybrid_rrf_k": settings.HYBRID_RRF_K,
        "rerank_candidates": settings.RERANK_CANDIDATES}
    cache_key = cache.key("retrieval", workspace_id, revision, method,
                          query.strip(), top_k, configuration)
    hit = cache.get("retrieval", workspace_id, cache_key)
    if hit and isinstance(hit.get("data"), list):
        try:
            return [SearchResult.model_validate(item) for item in hit["data"]]
        except (ValueError, TypeError):
            pass
    started = perf_counter()
    results = function(query, top_k, workspace_id, db)
    cache.put("retrieval", workspace_id, cache_key,
              [item.model_dump(mode="json") for item in results],
              settings.RETRIEVAL_CACHE_TTL_SECONDS,
              (perf_counter() - started) * 1000)
    return results


@cached("hybrid")
def retrieve_hybrid(query: str, top_k: int, workspace_id: uuid.UUID, db: Session) -> list[SearchResult]:
    dense = retrieve_passages(query, settings.HYBRID_CANDIDATES, workspace_id, db)
    lexical = retrieve_bm25(query, settings.HYBRID_CANDIDATES, workspace_id, db)
    return reciprocal_rank_fusion(dense, lexical, settings.HYBRID_RRF_K)[:top_k]


@cached("bm25")
def retrieve_bm25(query: str, top_k: int, workspace_id: uuid.UUID, db: Session) -> list[SearchResult]:
    if not query.strip():
        raise HTTPException(422, "Query cannot be blank")
    if not tokenize(query):
        return []
    # Scope the corpus before computing DF/average length; never load embeddings.
    rows = db.execute(
        select(Chunk.id, Chunk.document_id, Chunk.content, Chunk.page, Chunk.chunk_index,
               Chunk.chunk_metadata, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.workspace_id == workspace_id, Document.status == "ready")
        .order_by(Chunk.id).limit(settings.BM25_MAX_CHUNKS + 1)
    ).all()
    if len(rows) > settings.BM25_MAX_CHUNKS:
        raise HTTPException(503, "Workspace exceeds the configured in-memory BM25 chunk limit.")
    scores = BM25Index([row.content for row in rows]).scores(query)
    order = sorted((i for i, score in enumerate(scores) if score > 0),
                   key=lambda i: (-scores[i], rows[i].id.int))[:top_k]
    return [SearchResult(chunk_id=rows[i].id, document_id=rows[i].document_id,
                         filename=rows[i].filename, content=rows[i].content,
                         page=rows[i].page, chunk_index=rows[i].chunk_index,
                         metadata=rows[i].chunk_metadata, similarity=None,
                         bm25_score=scores[i], retrieval_method="bm25") for i in order]


@cached("vector")
def retrieve_passages(query: str, top_k: int, workspace_id: uuid.UUID, db: Session) -> list[SearchResult]:
    query = query.strip()
    if not query:
        raise HTTPException(422, "Query cannot be blank")
    try:
        vector = embed_texts([query], workspace_id)[0]
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


@cached("hybrid_reranked")
def retrieve_reranked(query: str, top_k: int, workspace_id: uuid.UUID, db: Session) -> list[SearchResult]:
    from app.services.reranking import rerank_passages

    candidates = retrieve_hybrid(query, settings.RERANK_CANDIDATES, workspace_id, db)
    return rerank_passages(query, candidates)[:top_k]
