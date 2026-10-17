# Phase 10: Redis caching and cost optimization

The cache is optional and fail-open. The API, ingestion worker, and research
worker use Redis with short connection timeouts; a failed connection pauses cache
attempts in that process for five seconds. Core ingestion, retrieval, chat, and
research remain authoritative in PostgreSQL and the model gateway.

`workspaces.corpus_revision` starts at zero. It increments in the same database
transaction that publishes indexed chunks or deletes a document. Retrieval keys
include this revision, workspace UUID, exact trimmed query, retrieval method,
top K, embedding and reranker models, and retrieval settings. Chat keys include
the revision, workspace UUID, question, exact retrieved passage IDs and text,
system prompt, and configured model route. Old Redis entries may remain until
their TTL, but are never addressed after the revision changes. A future route
that edits document content or metadata must increment the same revision.
Deleting a workspace leaves only expiring, inaccessible cache entries.

Embedding keys use the workspace UUID, pinned local model name/dimension, and
exact text. HMAC-SHA256 hides raw queries and content in Redis key names. Cache
values still contain vectors, retrieved passages, or generated JSON, so Redis
must be access-controlled like the queue and must not be publicly exposed.
Embedding TTL defaults to one day; retrieval and chat TTLs default to five
minutes. Values over 512 KiB are not cached. Cached vectors are checked for
shape and finite values; cached retrieval data is parsed back into the response
schema. Chat output is stored only after the application validates its citation
format and exact quotes. Every chat hit is validated again against the current
retrieved passages. Invalid cached output is discarded and regenerated.
Research drafts, errors, and incomplete streams are not cached.

`GET /workspaces/{id}/cache-metrics` requires ownership and reports current
UTC-day hits, misses, hit rate, embedding calls avoided, observed provider tokens
avoided, and estimated milliseconds saved. Latency saved is an estimate based on
the original miss duration minus cache read time, not a controlled measurement.
Set `CACHE_MODEL_PRICES_JSON` to a JSON map such as
`{"openai_compatible:model-name":{"input":0.15,"output":0.60}}`, where prices
are USD per million tokens. Cost saved is estimated from the actual model and
reported usage stored with each cache entry. If prices or usage are absent, the
cost remains unknown rather than being reported as zero. Metrics are ephemeral
Redis counters, grouped by UTC day, and disappear when Redis is cleared.

For a running API, repeat the same chat request and inspect counter deltas:

```powershell
cd backend
$env:CACHE_BENCHMARK_TOKEN = 'your-auth-token'
uv run --locked python scripts/benchmark_cache.py --url http://localhost:8000 --workspace YOUR_WORKSPACE_UUID --query 'What are the limitations?'
```

The first benchmark request may already be warm. The script reports its timing
and the average of later requests, and checks that answered results retain
sources. Unit tests cover workspace isolation, document-publish/delete revision
changes, cache reuse, invalid cached claims, owner-only metrics, and Redis outage
fallback.

The disposable PostgreSQL/Redis probe additionally repeats real search and
chat requests, checks Redis hit and token counters, confirms citations on a
cached answer, and verifies that document deletion removes it from later search
results.
