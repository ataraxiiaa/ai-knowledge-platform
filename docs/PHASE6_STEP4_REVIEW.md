# Phase 6, step 4: document processing status UI

The Documents panel now shows the current stage for each document: Queued,
Processing, Chunking, Embedding and Indexed. During the request it shows an
Uploading message with the filename; upload byte percentages are not available
from the current API helper. Failed documents show their error and stop the
progress timeline. Retry status has a readable label for the upcoming retry work.

When any document is active, the panel refreshes the workspace document list
every two seconds. A failed status request shows a separate retry notice and
uses exponential backoff up to 30 seconds. It does not mark a document failed.
When the tab is hidden, network polling pauses and checks less often; when the
tab becomes visible, it refreshes immediately. Polling stops when all documents
are ready/failed, the panel unmounts or the workspace changes. Responses from an
old workspace are ignored. Manual refresh remains available.

Search controls are disabled while no document is indexed, and the UI explains
when search will become available. This matches the server's existing ready-only
retrieval filter. Existing backend APIs and response fields are unchanged in
this step.

## Verification

Frontend ESLint, standalone TypeScript checking and production build passed. The
first build could not reach existing Google Fonts; retrying with network access
passed. Next.js reported its existing multiple-lockfile workspace-root warning.
`git diff --check` passed. No backend code or frontend test suite was changed.
No visual browser review was performed.

Step 4 ends at review. Approve step 5 before implementing bounded retries and
failure classification.
