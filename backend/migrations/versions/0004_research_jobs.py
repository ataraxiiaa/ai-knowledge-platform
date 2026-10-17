"""Durable staged research jobs and source provenance."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("research_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_stage", sa.String(32), nullable=False),
        sa.Column("retrieval_method", sa.String(32), nullable=False),
        sa.Column("plan", sa.JSON()), sa.Column("evidence", sa.JSON()),
        sa.Column("draft", sa.JSON()), sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_research_jobs_workspace_id", "research_jobs", ["workspace_id"])
    op.create_table("research_dispatches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_research_dispatches_due_at", "research_dispatches", ["due_at"])
    op.create_table("research_job_sources",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("research_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_id", sa.Uuid(), primary_key=True))
    op.create_index("ix_research_job_sources_document_id", "research_job_sources", ["document_id"])


def downgrade():
    op.drop_table("research_job_sources")
    op.drop_table("research_dispatches")
    op.drop_table("research_jobs")
