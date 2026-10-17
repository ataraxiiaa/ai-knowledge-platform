"""Durable workspace corpus version for cache invalidation."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("workspaces", sa.Column("corpus_revision", sa.Integer(),
                                          nullable=False, server_default="0"))


def downgrade():
    op.drop_column("workspaces", "corpus_revision")
