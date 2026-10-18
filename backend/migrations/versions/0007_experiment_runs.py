"""Store terminal evaluation runs with immutable provenance and nullable metrics."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("experiment_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("corpus_sha256", sa.String(64), nullable=False),
        sa.Column("split_sha256", sa.String(64), nullable=False),
        sa.Column("code_version", sa.String(128), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recall_at_5", sa.Float()),
        sa.Column("citation_accuracy", sa.Float()),
        sa.Column("answer_quality", sa.Float()),
        sa.Column("p95_latency_ms", sa.Float()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('completed', 'failed')", name="ck_experiment_runs_terminal_status"),
        sa.CheckConstraint("recall_at_5 IS NULL OR recall_at_5 BETWEEN 0 AND 1",
                           name="ck_experiment_runs_recall_range"),
        sa.CheckConstraint("citation_accuracy IS NULL OR citation_accuracy BETWEEN 0 AND 1",
                           name="ck_experiment_runs_citation_range"),
        sa.CheckConstraint("p95_latency_ms IS NULL OR p95_latency_ms >= 0",
                           name="ck_experiment_runs_latency_nonnegative"),
        sa.CheckConstraint("prompt_tokens IS NULL OR prompt_tokens >= 0",
                           name="ck_experiment_runs_prompt_tokens_nonnegative"),
        sa.CheckConstraint("completion_tokens IS NULL OR completion_tokens >= 0",
                           name="ck_experiment_runs_completion_tokens_nonnegative"),
        sa.CheckConstraint("total_tokens IS NULL OR total_tokens >= 0",
                           name="ck_experiment_runs_total_tokens_nonnegative"),
    )
    op.create_index("ix_experiment_runs_dataset_id", "experiment_runs", ["dataset_id"])
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("""CREATE FUNCTION reject_experiment_run_change() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              RAISE EXCEPTION 'Experiment runs are append-only';
            END; $$""")
        op.execute("""CREATE TRIGGER experiment_runs_immutable
            BEFORE UPDATE OR DELETE ON experiment_runs
            FOR EACH ROW EXECUTE FUNCTION reject_experiment_run_change()""")
    elif dialect == "sqlite":
        op.execute("""CREATE TRIGGER experiment_runs_no_update BEFORE UPDATE ON experiment_runs
            BEGIN SELECT RAISE(ABORT, 'Experiment runs are append-only'); END""")
        op.execute("""CREATE TRIGGER experiment_runs_no_delete BEFORE DELETE ON experiment_runs
            BEGIN SELECT RAISE(ABORT, 'Experiment runs are append-only'); END""")


def downgrade():
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER experiment_runs_immutable ON experiment_runs")
        op.execute("DROP FUNCTION reject_experiment_run_change()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER experiment_runs_no_update")
        op.execute("DROP TRIGGER experiment_runs_no_delete")
    op.drop_index("ix_experiment_runs_dataset_id", table_name="experiment_runs")
    op.drop_table("experiment_runs")
