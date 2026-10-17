import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResearchJobCreate(BaseModel):
    query: str = Field(min_length=1, max_length=1024)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Research request cannot be blank")
        return value.strip()


class ResearchJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    query: str
    status: Literal["queued", "running", "retrying", "completed", "failed"]
    current_stage: Literal["PLANNING", "RETRIEVING", "SYNTHESIZING", "VERIFYING", "SAVING", "COMPLETED"]
    retrieval_method: str
    error: str | None
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ResearchJobDetail(ResearchJobSummary):
    plan: dict[str, Any] | None
    evidence: list[dict[str, Any]] | None
    result: dict[str, Any] | None
    steps: list["ResearchStepSummary"]


class ResearchStepSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: Literal["PLANNING", "RETRIEVING", "SYNTHESIZING", "VERIFYING", "SAVING"]
    status: Literal["running", "completed", "failed"]
    attempt_count: int
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None

