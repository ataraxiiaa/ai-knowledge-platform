# Phase 7: durable research jobs

The accepted architecture is one deterministic workflow with structured LLM
operations, not separate planner/writer/reviewer agents. `POST
/workspaces/{id}/research-jobs` returns 202 after committing a job and its
dispatch intent together. List and detail endpoints enforce workspace ownership.
Only indexed documents in that workspace are eligible. A job saves its retrieval
method at acceptance.

| Stage | Operation and saved output |
|---|---|
| PLANNING | LLM returns 2–4 distinct subquestions; save the validated plan. |
| RETRIEVING | Search up to five passages per question, deduplicate chunks, save bounded evidence and source links. |
| SYNTHESIZING | LLM drafts up to four cited claims per question; save the structured draft. |
| VERIFYING | Recheck live source chunks and exact quotes; publish sections, citation numbers, and evidence gaps atomically. |
| COMPLETED | Retain the report and exact cited quotes; discard full chunk snapshots and draft. |

For requests asking to compare approaches, the plan always includes a direct
comparison subquestion even if the planner omitted one.

`research_jobs` stores the query, status, current stage, saved stage outputs,
result, error, attempts, lease, and timestamps. `research_dispatches` holds the
durable publication intent; `research_job_sources` indexes document IDs used by
active jobs. A separate RQ queue and worker use the existing Redis and dispatcher.
Only a conditional PostgreSQL claim increments attempts. Heartbeats renew a
two-minute lease; expired work is retried or failed within the saved budget.
Transient provider and retrieval availability errors get 30/120-second waits.
Permanent validation and citation errors fail immediately. RQ automatic retries
are disabled.

Document deletion marks active jobs using that source failed and fences their
workers. A source disappearing during retrieval or verification is also detected
before a stage commits. Completed reports retain only the exact cited quotes;
workspace deletion cascades jobs and reports. This retention rule was approved
before implementation.

Quote verification rejects source IDs outside the saved evidence and quotes
absent from the corresponding chunk. It cannot prove semantic entailment, so
human review remains necessary for consequential claims. The provider receives
the research question and retrieved text, as it does for chat.

Disposable verification used two generated PDFs, a real ingestion worker, a
separate research worker, real FastEmbed/pgvector retrieval, and a deterministic
local OpenAI-compatible provider. A two-source comparative report completed in **5.199 s**
after **0.018 s** acceptance on one local run. A fabricated quote failed without
a report; owner isolation, source-deletion retention, and workspace cascade also
passed. PostgreSQL `alembic check` found no drift. The deterministic provider
tests orchestration and citation mechanics, not open-ended LLM report quality.

To repeat with an already cached embedding model and generated root `.env`
`SECRET_KEY`:

```sh
docker build -t knowledge-phase7-check backend
docker compose -p phase7-research-check -f docker-compose.research-test.yml up -d db redis migrate provider worker research_worker dispatcher
docker compose -p phase7-research-check -f docker-compose.research-test.yml run --rm --no-deps probe
docker compose -p phase7-research-check -f docker-compose.research-test.yml down -v
```

The test project has no host ports or production volumes. Its test-mode guard
prevents the provider and probe scripts from running accidentally elsewhere.
