"""Checkpoint research stages and separate verification from publication."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("research_jobs", sa.Column("verified_result", sa.JSON()))
    op.create_table("research_job_steps",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("research_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("stage", sa.String(32), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input", sa.JSON()),
        sa.Column("output", sa.JSON()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()))
    # Preserve checkpoints for jobs created before step history existed.
    jobs = sa.table("research_jobs", sa.column("id", sa.Uuid()),
        sa.column("plan", sa.JSON()), sa.column("evidence", sa.JSON()),
        sa.column("draft", sa.JSON()), sa.column("attempt_count", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)))
    steps = sa.table("research_job_steps", sa.column("job_id", sa.Uuid()),
        sa.column("stage", sa.String()), sa.column("status", sa.String()),
        sa.column("output", sa.JSON()), sa.column("attempt_count", sa.Integer()),
        sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("completed_at", sa.DateTime(timezone=True)))
    connection = op.get_bind()
    for job in connection.execute(sa.select(jobs)).mappings():
        for stage, value in (("PLANNING", job["plan"]),
                             ("RETRIEVING", job["evidence"]),
                             ("SYNTHESIZING", job["draft"])):
            if value is not None:
                connection.execute(sa.insert(steps).values(job_id=job["id"], stage=stage,
                    status="completed", output=value, attempt_count=job["attempt_count"],
                    started_at=job["created_at"], completed_at=job["updated_at"]))


def downgrade():
    op.drop_table("research_job_steps")
    op.drop_column("research_jobs", "verified_result")
