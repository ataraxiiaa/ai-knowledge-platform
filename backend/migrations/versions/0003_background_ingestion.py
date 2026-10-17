"""Durable ingestion inputs, claims and dispatch intent."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite cannot add CURRENT_TIMESTAMP defaults to populated tables.
    with op.batch_alter_table("documents", recreate="always" if op.get_context().dialect.name == "sqlite" else "auto") as batch:
        for name in ("chunk_size", "chunk_overlap", "pipeline_version"):
            batch.add_column(sa.Column(name, sa.Integer(), nullable=True))
        batch.add_column(sa.Column("embedding_model", sa.String(255), nullable=True))
        for name, default in (("attempt_count", "0"), ("max_attempts", "1")):
            batch.add_column(sa.Column(name, sa.Integer(), server_default=default, nullable=False))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
        for name in ("started_at", "finished_at", "next_retry_at", "lease_expires_at"):
            batch.add_column(sa.Column(name, sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.execute("UPDATE documents SET status='failed', error='Processing interrupted before background jobs were enabled. Please upload again.' WHERE status NOT IN ('ready', 'failed')")
    op.create_table("ingestion_dispatches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("due_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False))
    op.create_index("ix_ingestion_dispatches_due_at", "ingestion_dispatches", ["due_at"])


def downgrade():
    op.drop_table("ingestion_dispatches")
    for name in ("chunk_size", "chunk_overlap", "pipeline_version", "embedding_model",
                 "attempt_count", "max_attempts", "updated_at", "started_at", "finished_at",
                 "next_retry_at", "lease_expires_at", "lease_token"):
        op.drop_column("documents", name)
