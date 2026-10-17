# Phase 6, step 1: background processing design

Status: proposed for user review, 2026-10-17. This step changes documentation only.
Steps 2–7 require separate approval. No dependencies, services or migrations have
been installed or applied for this design.

## Current implementation

- `backend/app/api/documents.py` validates ownership and chunk settings, saves the
  PDF, commits a `processing` document, then calls `ingest_document` synchronously.
  Its 201 response waits for parsing, chunking, embedding and database insertion.
- `backend/app/services/ingestion.py` commits chunks and `ready` together. Preserve
  that atomic publication. It currently catches every exception and stores
  `failed`; refactor this boundary so transient errors can be retried safely.
- `storage.py` already validates extension, header and upload size, uses generated
  paths, and removes files when saving fails. Full PDF parsing belongs in the worker.
- Chunk rows already have a unique `(document_id, chunk_index)` constraint.
  Retrieval already selects only `ready` documents in the owned workspace.
- Owned document list/detail endpoints already provide the polling surface.
  The Documents panel currently assumes upload waits for indexing; it has no
  processing polling. Document and workspace deletion also remove stored files.
- Compose already provides PostgreSQL and a backend sharing `/data` with a
  persistent volume. The backend image installs `requirements.txt`, while local
  development uses `pyproject.toml` and `uv.lock`; dependency updates must cover both.

## Queue decision: RQ + Redis

Use one `ingestion` queue and one job covering parse → chunk → embed → store.
RQ fits the current function-based pipeline without introducing task chains.
Dramatiq is a valid alternative with actors and automatic retry middleware;
Celery's richer workflow machinery is unnecessary for this phase.

Run the supported deployment path in Linux Docker containers, including on this
Windows workstation. RQ's worker documentation also describes SpawnWorker for
Windows; native Windows execution is optional, not a prerequisite for this phase.
Pin and verify dependency versions in step 2 rather than guessing compatible
versions now. Use JSON serialization on both producer and worker. Enqueue only
server-controlled document and dispatch IDs, never file bytes, ORM objects,
request sessions, credentials or client-selected function names.

Official references checked for this decision:
- [RQ workers and serializers](https://python-rq.org/docs/workers/)
- [RQ failures and retries](https://python-rq.org/docs/exceptions/)
- [Dramatiq guide](https://dramatiq.io/guide.html)
- [Celery platform FAQ](https://docs.celeryq.dev/en/stable/faq.html)

## Architecture and durable acceptance

```text
Browser -- PDF --> API -- save --> shared upload storage
                    |
                    +-- transaction: document + pending dispatch --> PostgreSQL
                    |
                    +-- 202 Accepted + document ID + status URL

Dispatcher -- read due dispatches --> Redis ingestion queue --> RQ worker
                                                              |
                                     read PDF; parse; chunk; embed
                                                              |
                           PostgreSQL: atomic chunks + ready status

Browser -- owned document GET/poll --> PostgreSQL document status
```

An outbox is a small database table recording work that still needs dispatching.
Create its record in the same transaction as the document. A lightweight
dispatcher service publishes due records to Redis and retries publication after
outages. The API does not depend on Redis being available at upload time.
202 means the file and work intent were durably accepted, not that a worker has
started or that Redis publication has already happened. This closes the crash
window between committing a document and enqueueing its job.

Publishing and marking a dispatch delivered cannot be one transaction across
Redis and PostgreSQL. A crash may publish twice: execution must be idempotent.
Redis persistence helps availability but is not the only recovery mechanism.
The recovery scan checks stale queued documents even if an outbox row says sent,
so a lost Redis job can be dispatched again. Do not promise exactly-once delivery.

Upload transfer and bounded file validation still take time. Processing does not
run inside the request or FastAPI BackgroundTasks. If file saving or the database
transaction fails, return an error and remove the file where possible. A crash
between file creation and DB commit can leave an orphan file; provide a guarded,
age-based reconciliation command that excludes recent uploads.

## States and API contract

| Stored status | UI label | Meaning |
|---|---|---|
| No record yet | Uploading | Browser transferring the file |
| `queued` | Queued | Durable work accepted; waiting for dispatch or a worker |
| `processing` | Processing | Worker claimed the document and is parsing |
| `chunking` | Chunking | Extracted pages are being split |
| `embedding` | Embedding | Vectors are being generated and prepared for storage |
| `ready` | Indexed | All chunks and vectors committed successfully |
| `retrying` | Retry scheduled | A retryable attempt failed; waiting until next attempt |
| `failed` | Failed | Permanent failure or retry budget exhausted |

Keep `ready` in the backend for retrieval compatibility; Indexed is a display
label. Stages are not percentages and fast stages may pass between polls.
Normal progression: queued → processing → chunking → embedding → ready.
An active stage may transition to retrying or failed. Retry starts at parsing;
there are no persisted intermediate chunks in this phase.

Keep `POST /workspaces/{id}/documents`, multipart PDF and chunk options. Change
success from 201 to 202, with the existing DocumentResponse fields plus
`updated_at`, `attempt_count`, `max_attempts`, and nullable `next_retry_at`.
Return a Location header pointing to the existing owned document-detail route.
Return a snapshot of the accepted queued state; a worker may already have moved
ahead by the next GET. No sensitive storage paths or raw exception details appear
in responses. Keep existing validation and ownership error codes.

Poll the owned list while any document is nonterminal, initially every two
seconds, with bounded backoff on network/server errors. Stop on ready/failed,
unmount or workspace change; avoid overlapping requests. Refresh when the tab
becomes visible. An HTTP polling error is not a document failure. Uploading is an
indeterminate indicator unless actual byte-progress reporting is implemented.

## Persistence and execution invariants

Add document fields for chunk size/overlap, pipeline version, embedding model,
attempt count, updated/start/finish timestamps, next retry time, and nullable
lease token/expiry. Store processing inputs at acceptance so worker defaults
cannot silently change an already accepted upload. Workers must reject unsupported
pipeline/model versions explicitly. Add an outbox table with document FK,
dispatch UUID, due time, publication state and publication-attempt metadata.

Each job opens its own DB session. Atomically claim an eligible document using a
short transaction; increment the attempt count and assign a unique lease token.
Duplicate jobs encountering a live claim or a terminal document exit harmlessly.
Do not hold a database row lock while parsing or embedding. Heartbeat the lease
through short independent transactions. Stage updates and final publication
must match the current lease token, fencing out an expired or superseded worker.

At publication, lock/recheck the document and lease, replace any stale chunks,
insert the complete validated set, and mark ready in one transaction. The existing
chunk uniqueness constraint is an additional guard, not the sole deduplication
mechanism. Roll back all chunk writes if publication fails. Never recreate a
deleted document with an ORM merge or add in an exception handler.

Deletion wins: removing a document/workspace cascades dispatch records and chunks.
Queued jobs for missing IDs become no-ops. Running jobs may finish computation,
but must fail the document/lease check before publishing. Queue cancellation is
best effort; correctness does not depend on stopping CPU work immediately.

## Retries, recovery and operations

Use one retry authority: PostgreSQL attempt state plus the outbox dispatcher.
Do not simultaneously enable RQ automatic retries for these jobs. Proposed
defaults: three processing attempts total, delays of 30 and 120 seconds, 15-minute
job timeout, 30-second heartbeat, two-minute lease, recovery scan every 30 seconds.
Verify these on actual embedding workloads before treating them as production
defaults. Duplicate delivery does not consume an attempt unless it claims work.
Queue-publication retries do not consume processing attempts.

Retry classified transient model-download/network/database failures. Reject
malformed, encrypted, scanned/empty PDFs and configured size/token limits without
automatic retry. Unknown failures are terminal unless explicitly classified;
persist safe error codes/messages and log diagnostics server-side. Worker kill,
timeout or host loss may bypass exception handlers: recovery reclaims expired
leases and either schedules the next attempt or marks failed at the budget limit.
Do not infer failure simply from a slow stage or from missing short-lived RQ results.

Start with one worker processing one job at a time and two embedding threads.
Scale by adding worker processes after measuring memory/CPU, since each execution
may load a model. Pre-download model files to the shared cache before accepting
jobs; standard forked RQ jobs may reload the model per job. Keep model-cache and
upload storage available at identical paths in API and worker containers.
This shared-volume design is single-host; multiple hosts require shared/object
storage before scaling out.

Add Redis with persistence, a worker service and a dispatcher service. Use the
same backend image/config; run migrations once before consumers start. Override
the inherited HTTP healthcheck for worker/dispatcher containers. Monitor queue
age, outbox backlog, worker heartbeat, attempt count, job duration and terminal
failures. Keep document status authoritative in PostgreSQL even when Redis/RQ
results expire. Redis outages delay work; they do not prevent existing indexed
documents from serving search/chat. Durable acceptance should be identified
separately from processing health in readiness/operations documentation.

Migration must preserve existing ready/failed rows. Legacy processing/pending
rows have no persisted job inputs; mark them failed with a safe interrupted-work
message rather than guessing settings and replaying them. Do not automatically
ingest placeholder documents lacking a stored PDF.

## Implementation gates and acceptance checks

1. This design: inspect current behavior, select RQ, agree on lifecycle and
   persistence. Documentation review only; no runtime changes to test.
2. Infrastructure: pin dependencies in both installation paths, add isolated
   Redis/worker smoke job, verify separate-process execution and shared storage.
3. Async ingestion: migration, durable outbox/dispatcher, worker pipeline and 202
   contract. Verify the response finishes while an intentionally blocked worker
   has not processed the PDF; recover dispatch after Redis outage. Final publication
   and duplicate-claim protection must exist before this path is enabled.
4. UI: stages and polling, terminal stop, failed states, workspace switches and
   ready-only retrieval. Update existing synchronous API tests and smoke scripts.
5. Retry policy: permanent vs transient failures, exact bounded attempts,
   retry schedule, duplicate delivery and rollback with no partial index.
6. Recovery: multiple workers/documents, kill/restart, expired-lease fencing,
   deletion during processing, missing Redis jobs and orphan-file cleanup.
7. End-to-end: real PDF → queue → worker → pgvector → cited chat, plus failure
   injection. Record upload acceptance latency separately from time-to-index;
   update README/LEARNING and operational commands. Use disposable test services.

Every gate ends with a review summary and waits for user approval before the next.
