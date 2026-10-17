# Phase 6, step 6: recovery after interrupted work

The dispatcher now scans for active documents with expired PostgreSQL leases every
30 seconds. It processes up to 20 per scan, using row locks that skip documents
another dispatcher has locked. An abandoned attempt keeps its existing count.
If another attempt remains, the scan sets `retrying` and schedules the existing
durable dispatch after the normal 30/120-second delay. At the attempt limit, it
marks the document `failed` and removes the dispatch. The lease token is cleared
in either case. Recovery does not depend on an RQ failure callback or result key.

The worker's existing conditional token-and-expiry checks fence a resumed old
worker from renewing status or committing chunks. The queued outbox retains its
60-second republish interval for lost Redis messages. Duplicate deliveries do
not increment the attempt count unless one claims the document.

`backend/scripts/cleanup_orphan_pdfs.py` scans only canonical UUID workspace
directories and UUID-named PDFs under the configured upload root. It skips
symlinks and files newer than one hour, and checks for a matching document row.
It prints candidates by default; `--apply` removes them. Run it separately from
the dispatcher and review the dry run first. It does not remove directories or
unknown file names.

Verification:

- Isolated pytest covers retry recovery, exhaustion, live/deleted documents,
  stale-worker fencing, and orphan cleanup dry-run/apply behavior.
- The disposable PostgreSQL/Redis probe killed a child during embedding,
  expired and recovered its lease, then sent duplicate work to two RQ workers.
  One attempt produced the index. It also deleted a document during embedding
  without resurrection and erased a Redis job before outbox republishing.
- No production database or upload volume was used. The disposable Compose
  project and its volume were removed after the probe.

Step 7 remains the end-to-end real-model and cited-chat validation. Review this
step before authorizing step 7.
