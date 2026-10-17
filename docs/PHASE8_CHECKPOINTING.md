# Phase 8: checkpoints and failure recovery

Research execution remains a deterministic state machine. PostgreSQL is the
source of truth; Redis/RQ only delivers work. `research_jobs.current_stage` and
its saved outputs govern resumption. `research_job_steps` records stage input,
output, status, attempt count, timestamps, and a safe error summary. Stage output
and the transition to the next stage commit together. Migration 0005 creates the
step table and backfills saved PLAN/RETRIEVE/SYNTHESIZE outputs from existing jobs.

`VERIFYING` checks live source chunks and exact quote matches, then commits the
verified report and advances to `SAVING`. `SAVING` rechecks source liveness and
atomically publishes the saved report, marks completion, and removes the dispatch
intent. It does not call the planner, retriever, writer, or full verifier. A
duplicate message cannot claim a completed job. Completed and terminal jobs
discard full evidence and draft snapshots, including large step payloads.

Provider timeouts, retrieval/embedding availability, and transient database
errors retry after 30 then 120 seconds by default, subject to the job attempt
limit. Invalid JSON gets at most one retry. Schema-invalid but parseable JSON,
fabricated citations, and deleted sources fail without automatic retry. The
dispatcher recovers expired leases, fences the old worker, and schedules the
current stage again. If a worker finished an external LLM call but died before
its checkpoint committed, that stage may run again; only completed checkpoints
are guaranteed not to rerun. This is at-least-once stage execution, not exactly
once external execution.

Fault-injection tests intentionally produce a provider timeout, embedding
availability error, malformed JSON, worker crash, and SAVE database error. They
assert the saved stage, step status, bounded attempts, and completion after
recovery. A separate test confirms repeated malformed JSON becomes terminal.
