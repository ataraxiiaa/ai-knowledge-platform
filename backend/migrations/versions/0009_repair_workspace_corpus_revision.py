"""Repair databases stamped at head without the workspace corpus revision column.

Revision 0006 normally adds this column. Some existing deployments report 0008
while the column is absent, so inspect the actual schema before repairing it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workspaces")}
    if "corpus_revision" not in columns:
        op.add_column("workspaces", sa.Column("corpus_revision", sa.Integer(),
                                              nullable=False, server_default="0"))


def downgrade():
    # The column belongs to revision 0006. Undoing this repair must not remove it.
    pass
