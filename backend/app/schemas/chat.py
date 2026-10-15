import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.documents import SearchResult


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1024)

    @field_validator("message")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value.strip()


class ChatSource(BaseModel):
    id: int
    document: str
    document_id: uuid.UUID
    page: int
    chunk_id: uuid.UUID
    quote: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    # The actual context sent to generation, for retrieval/generation debugging.
    retrieved_chunks: list[SearchResult]
    status: Literal["answered", "insufficient_evidence"]
