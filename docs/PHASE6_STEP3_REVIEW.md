# Phase 6, step 3: durable asynchronous ingestion

`POST /workspaces/{id}/documents` now validates and stores the PDF, creates the
document plus dispatch intent in one PostgreSQL transaction, and returns `202`
with the existing document fields, initial `queued` status, and a `Location`
header for the owned detail endpoint. The HTTP request does not connect to Redis,
parse the PDF, or embed chunks. PostgreSQL is authoritative for job/document
state; retrieval remains restricted to `ready` documents.

## Architecture

The new `ingestion_dispatches` outbox table closes the lost-job window between
document creation and queue publication. A dispatcher polls due rows and sends
only server-selected function path, document UUID and dispatch UUID through the
JSON-serialized RQ queue. It holds the row lock while publishing. On Redis errors
it leaves intent due for another attempt. After publication, it keeps the row and
republishes queued work after 60 seconds until a worker claims or finishes it.
This is at-least-once delivery; duplicate jobs are expected and safe. A Redis job
expires after 120 seconds in queue, while PostgreSQL remains the recovery source.

The worker atomically claims only `queued` documents with a matching dispatch,
records its attempt and assigns a unique, expiring lease. Each worker has its own
database sessions. It reads saved chunk settings/model, parses, changes the
status to `chunking`, chunks, then sets `embedding` while embedding. A small
heartbeat thread renews the lease using independent sessions. Before publish,
the worker conditionally updates the document using its token/lease. One DB
transaction replaces any partial chunks, inserts all validated vectors, marks
`ready`, and removes the dispatch. If the conditional update fails because the
document was deleted or the lease changed, it rolls back and publishes nothing.
Duplicate delivery after completion or deletion is a no-op.

This step records retry fields but deliberately gives new jobs one processing
attempt (`max_attempts=1`). Failures become `failed`; bounded processing retries
and stale-lease recovery are later phase steps. Outbox publication itself retries
every 60 seconds. Unknown worker failures expose a safe generic message while
logs contain the exception class, not document contents or paths.

The migration preserves `ready` and existing `failed` records. Legacy `pending`
or `processing` records are marked failed with an interrupted-work message;
their original chunk settings were not recorded, so silently reprocessing them
would be unsafe. New records persist chunk size, overlap, pipeline version and
embedding model. Migration was exercised against disposable PostgreSQL and
populated SQLite. `alembic check` found no model/schema drift.

Compose runs a one-shot migration service first, then API, Redis, worker and
dispatcher. A worker and API share the upload/model volume. The dispatcher checks
outbox state in PostgreSQL if Redis is unavailable. Redis is not a dependency of
API readiness; uploads can be accepted durably while it is down. UI automatic
polling/stage presentation is step 4. The text now explains that processing
continues after upload and offers manual Refresh list.

## Verification (2026-10-17)

- All **136 backend tests passed**, including acceptance without Redis, outbox
  retry, duplicate delivery, worker lease fencing, deletion during embedding,
  source retrieval, legacy migration preservation and queue configuration.
- Frontend lint and TypeScript checks passed.
- Both production and disposable Compose configurations validated. The Linux
  backend image built successfully and the disposable PostgreSQL migration passed.
- End-to-end test used fresh Redis and pgvector/PostgreSQL containers with no
  host ports or production volumes. Upload returned 202 in **20 ms** while Redis
  and worker were stopped. The dispatcher retained intent through a Redis
  connection failure. After starting Redis/worker/dispatcher, the real PDF was
  parsed, chunked, embedded and committed; duplicate delivery did not add chunks,
  BM25 search found the indexed page, and deletion followed by a stale delivery
  did not recreate the document. The script also passed worker readiness.
- The first Redis outage harness run revealed a cleanup/polling error; the probe
  was fixed to tolerate transient disconnects, then the repeat verified queue
  persistence and execution after restart. Only the isolated step-3 Compose
  resources were removed. Existing app services, databases and saved `.env`
  were not modified.

Upload time still includes file transfer and local disk writing. The 20 ms figure
is one small synthetic local test, not a general latency guarantee. The poll UI,
automatic retries, recovery after killed/stuck workers, multi-worker stress and
full operational testing remain for steps 4–7.

Step 3 ends at review. Approve step 4 before implementing frontend polling and
status-stage presentation.
