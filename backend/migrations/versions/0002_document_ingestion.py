"""Document storage and page-aware vector chunks."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("documents", sa.Column("storage_path", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("error", sa.Text(), nullable=True))
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(384) if dialect == "postgresql" else sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # Start with exact nearest-neighbor search. Add HNSW only after measurement.


def downgrade():
    op.drop_table("chunks")
    op.drop_column("documents", "error")
    op.drop_column("documents", "storage_path")
    # The vector extension may be shared with other applications; leave it installed.
