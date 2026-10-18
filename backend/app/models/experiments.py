"""Terminal, append-only evaluation results independent of user workspaces."""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    __table_args__ = (
        CheckConstraint("status IN ('completed', 'failed')", name="ck_experiment_runs_terminal_status"),
        CheckConstraint("recall_at_5 IS NULL OR recall_at_5 BETWEEN 0 AND 1",
                        name="ck_experiment_runs_recall_range"),
        CheckConstraint("citation_accuracy IS NULL OR citation_accuracy BETWEEN 0 AND 1",
                        name="ck_experiment_runs_citation_range"),
        CheckConstraint("p95_latency_ms IS NULL OR p95_latency_ms >= 0",
                        name="ck_experiment_runs_latency_nonnegative"),
        CheckConstraint("prompt_tokens IS NULL OR prompt_tokens >= 0",
                        name="ck_experiment_runs_prompt_tokens_nonnegative"),
        CheckConstraint("completion_tokens IS NULL OR completion_tokens >= 0",
                        name="ck_experiment_runs_completion_tokens_nonnegative"),
        CheckConstraint("total_tokens IS NULL OR total_tokens >= 0",
                        name="ck_experiment_runs_total_tokens_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    corpus_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    split_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    code_version: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    recall_at_5: Mapped[float | None] = mapped_column(Float)
    citation_accuracy: Mapped[float | None] = mapped_column(Float)
    answer_quality: Mapped[float | None] = mapped_column(Float)
    p95_latency_ms: Mapped[float | None] = mapped_column(Float)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                   server_default=func.now())


@event.listens_for(ExperimentRun, "before_update")
@event.listens_for(ExperimentRun, "before_delete")
def reject_terminal_change(*_args) -> None:
    raise ValueError("Experiment runs are append-only")


class ExperimentReview(Base):
    __tablename__ = "experiment_reviews"
    __table_args__ = (
        CheckConstraint("reviewer_type IN ('human', 'agent')", name="ck_experiment_reviews_reviewer_type"),
        CheckConstraint("citation_accuracy IS NULL OR citation_accuracy BETWEEN 0 AND 1",
                        name="ck_experiment_reviews_citation_range"),
        CheckConstraint("answer_quality IS NULL OR answer_quality BETWEEN 0 AND 1",
                        name="ck_experiment_reviews_quality_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("experiment_runs.id"), nullable=False, index=True)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewer_type: Mapped[str] = mapped_column(String(16), nullable=False)
    citation_accuracy: Mapped[float | None] = mapped_column(Float)
    answer_quality: Mapped[float | None] = mapped_column(Float)
    citation_review_coverage: Mapped[float | None] = mapped_column(Float)
    quality_review_coverage: Mapped[float | None] = mapped_column(Float)
    review_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                   server_default=func.now())


@event.listens_for(ExperimentReview, "before_update")
@event.listens_for(ExperimentReview, "before_delete")
def reject_review_change(*_args) -> None:
    raise ValueError("Experiment reviews are append-only")
