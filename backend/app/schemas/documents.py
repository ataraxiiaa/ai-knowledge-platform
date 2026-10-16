import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    filename: str
    status: str
    error: str | None
    created_at: datetime
    chunk_count: int

    model_config = ConfigDict(from_attributes=True)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1024)
    top_k: int = Field(default=5, ge=1, le=20)
    method: Literal["vector", "bm25", "hybrid", "hybrid_reranked"] = "vector"


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    content: str
    page: int
    chunk_index: int
    similarity: float | None = None
    bm25_score: float | None = None
    retrieval_method: Literal["vector", "bm25", "hybrid", "hybrid_reranked"] = "vector"
    rerank_score: float | None = None
    rerank_status: Literal["applied", "fallback"] | None = None
    fusion_score: float | None = None
    vector_rank: int | None = None
    bm25_rank: int | None = None
    metadata: dict[str, Any]
