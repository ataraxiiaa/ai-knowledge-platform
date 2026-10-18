"""Rebuild schema skipped by an incorrectly stamped legacy database.

One deployed database reports revision 0009 but has only the revision 0001
tables plus workspaces.corpus_revision. Accept that exact state or a complete
schema; reject any other partial state instead of guessing what to change.
"""

import sqlalchemy as sa
from alembic import context, op
from alembic.script import ScriptDirectory

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

MISSING_TABLES = {
    "chunks", "ingestion_dispatches", "research_jobs", "research_dispatches",
    "research_job_sources", "research_job_steps", "experiment_runs", "experiment_reviews",
}
MISSING_DOCUMENT_COLUMNS = {
    "storage_path", "error", "chunk_size", "chunk_overlap", "pipeline_version",
    "embedding_model", "attempt_count", "max_attempts", "updated_at",
    "started_at", "finished_at", "next_retry_at", "lease_token", "lease_expires_at",
}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    missing_tables = MISSING_TABLES - tables
    if not {"users", "workspaces", "documents"} <= tables:
        raise RuntimeError("Core tables are missing; manual schema review is required")
    document_columns = {column["name"] for column in inspector.get_columns("documents")}
    workspace_columns = {column["name"] for column in inspector.get_columns("workspaces")}
    missing_document_columns = MISSING_DOCUMENT_COLUMNS - document_columns

    if not missing_tables and not missing_document_columns:
        return
    if (missing_tables != MISSING_TABLES
            or missing_document_columns != MISSING_DOCUMENT_COLUMNS
            or "corpus_revision" not in workspace_columns):
        raise RuntimeError("Unexpected partial schema; manual schema review is required")

    # Reuse the reviewed migrations in their original order. 0006 already ran
    # through the guarded 0009 repair, so adding that column again would fail.
    scripts = ScriptDirectory.from_config(context.config)
    for prior in ("0002", "0003", "0004", "0005", "0007", "0008"):
        scripts.get_revision(prior).module.upgrade()


def downgrade():
    # Repairing a stamped schema is forward-only; do not discard restored data.
    pass
