"""Append-only semantic reviews for immutable experiment runs."""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("experiment_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("experiment_runs.id"), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("rubric_version", sa.String(32), nullable=False),
        sa.Column("reviewer", sa.String(255), nullable=False),
        sa.Column("reviewer_type", sa.String(16), nullable=False),
        sa.Column("citation_accuracy", sa.Float()),
        sa.Column("answer_quality", sa.Float()),
        sa.Column("citation_review_coverage", sa.Float()),
        sa.Column("quality_review_coverage", sa.Float()),
        sa.Column("review_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("reviewer_type IN ('human', 'agent')", name="ck_experiment_reviews_reviewer_type"),
        sa.CheckConstraint("citation_accuracy IS NULL OR citation_accuracy BETWEEN 0 AND 1",
                           name="ck_experiment_reviews_citation_range"),
        sa.CheckConstraint("answer_quality IS NULL OR answer_quality BETWEEN 0 AND 1",
                           name="ck_experiment_reviews_quality_range"),
    )
    op.create_index("ix_experiment_reviews_run_id", "experiment_reviews", ["run_id"])
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("""CREATE FUNCTION reject_experiment_review_change() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              RAISE EXCEPTION 'Experiment reviews are append-only';
            END; $$""")
        op.execute("""CREATE TRIGGER experiment_reviews_immutable
            BEFORE UPDATE OR DELETE ON experiment_reviews
            FOR EACH ROW EXECUTE FUNCTION reject_experiment_review_change()""")
    elif dialect == "sqlite":
        op.execute("""CREATE TRIGGER experiment_reviews_no_update BEFORE UPDATE ON experiment_reviews
            BEGIN SELECT RAISE(ABORT, 'Experiment reviews are append-only'); END""")
        op.execute("""CREATE TRIGGER experiment_reviews_no_delete BEFORE DELETE ON experiment_reviews
            BEGIN SELECT RAISE(ABORT, 'Experiment reviews are append-only'); END""")


def downgrade():
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER experiment_reviews_immutable ON experiment_reviews")
        op.execute("DROP FUNCTION reject_experiment_review_change()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER experiment_reviews_no_update")
        op.execute("DROP TRIGGER experiment_reviews_no_delete")
    op.drop_index("ix_experiment_reviews_run_id", table_name="experiment_reviews")
    op.drop_table("experiment_reviews")
