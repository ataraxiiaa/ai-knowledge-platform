import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    current_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="PLANNING")
    retrieval_method: Mapped[str] = mapped_column(String(32), nullable=False)
    plan: Mapped[dict | None] = mapped_column(JSON)
    evidence: Mapped[list | None] = mapped_column(JSON)
    draft: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatches: Mapped[list["ResearchDispatch"]] = relationship(cascade="all, delete-orphan")
    sources: Mapped[list["ResearchJobSource"]] = relationship(cascade="all, delete-orphan")


class ResearchDispatch(Base):
    __tablename__ = "research_dispatches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ResearchJobSource(Base):
    __tablename__ = "research_job_sources"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_jobs.id", ondelete="CASCADE"), primary_key=True)
    # Kept after a document is deleted so completed reports retain provenance.
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, index=True)
