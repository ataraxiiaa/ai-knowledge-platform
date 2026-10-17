# Phase 6, step 7: end-to-end validation

The disposable `docker-compose.ingestion-test.yml` project ran PostgreSQL with
pgvector, Redis, the dispatcher, and an RQ worker. The probe submitted a generated
text PDF through `POST /workspaces/{id}/documents`, observed a 202 queued response,
waited for `ready`, queried real 384-dimensional FastEmbed vectors through the
vector search endpoint, and called `/chat`. The returned citation pointed to the
uploaded filename, page 1, and an exact quote in the retrieved chunk.

| Measurement | This run |
|---|---:|
| Upload acceptance | 0.021 s |
| Upload to indexed | 2.072 s |

These are one local sample with a prewarmed model cache, not performance targets.
Polling observed queued, embedding, and ready; intermediate stages can finish
between polls. The chat probe used a local deterministic OpenAI-compatible
provider, not a real language model. It validates request plumbing and the
server's citation checks, not answer quality or citation accuracy on open-ended
questions. Earlier Phase 4/5 evaluation covers those separately.

Failure injection confirmed that a fabricated quotation from the provider is
rejected with HTTP 502. A malformed PDF passed upload-header validation, then
failed in the worker after one attempt with no chunks. Step 6 separately verified
worker death, duplicate delivery, deletion during embedding, and lost Redis jobs.

To reproduce, use the isolated commands in [README.md](../README.md). The probe
requires `PHASE6_TEST_MODE=1` from the test Compose file and a prewarmed embedding
cache mounted read-only. The disposable Compose project and its volume were
removed after verification. The backend pytest suite also passes.
