import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceBase(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="Workspace name")
    description: Optional[str] = Field(
        default=None,
        description="Workspace description",
    )


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Workspace name",
    )
    description: Optional[str] = Field(
        default=None,
        description="Workspace description",
    )


class WorkspaceResponse(WorkspaceBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
