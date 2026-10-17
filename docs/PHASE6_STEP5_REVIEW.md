# Phase 6, step 5: bounded ingestion retries

New uploads save a configurable processing budget (`INGESTION_MAX_ATTEMPTS`,
default 3, allowed 1–5). A claimed attempt increments the durable count. The
worker retries transient SQLAlchemy availability errors and embedding transport,
timeout, or filesystem availability errors. Validation errors and unexpected
exceptions fail immediately. The two default retry waits are 30 and 120 seconds.

On retry, one database transaction sets `retrying`, stores `next_retry_at`, clears
the lease, and reschedules the existing dispatch record. The dispatcher only
returns a retrying document to `queued` when both its document retry time and
dispatch due time have elapsed. RQ automatic retries remain disabled. Early or
duplicate deliveries are no-ops; only a successful conditional claim increments
the attempt count. A terminal failure removes the dispatch record.

Chunk publication remains atomic with the `ready` transition. A database error
during publication rolls back the chunks and schedules another attempt when the
budget permits. User-visible transient errors are generic; exception classes
are logged without leaking exception text into document status.

Regression tests cover first and second retry delays, exhaustion, early and
duplicate delivery, transient database publish rollback, permanent errors, and
classification. Worker process death and expired-lease recovery are step 6;
this step handles exceptions that reach the worker's failure handler.

Review step 5 before authorizing step 6.
