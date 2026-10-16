# Phase 5, step 6: cross-encoder reranking

Hybrid retrieval now supports an optional local CPU cross-encoder,
`Xenova/ms-marco-MiniLM-L-6-v2`, through the existing FastEmbed dependency.
Each branch retrieves up to 20 chunks, RRF merges them, the best 20 fused chunks
are reranked, and five are sent to generation by default. Original document IDs,
page numbers, text and citation metadata survive reordering.

## Use and behavior

From `backend/`, warm the model with the application's configured environment:

```sh
uv run --locked python -m app.services.reranking
uv run --locked python scripts/evaluate_retrieval.py --strategy hybrid_reranked --output experiments/evaluation/runs/reranked-dev-new.json
```

The first warmup downloads model files; later runs use the cache. Set
`HF_HUB_OFFLINE=1` to require cached Hugging Face files. The default cache is
`backend/.cache/rerankers`; keep it persistent in deployments. Download/model
initialization can delay a cold request, so warm before serving traffic.
The implementation uses two CPU threads and batches of eight pairs. These can
serialize concurrent requests behind the inference lock; no throughput claim is made.

Search accepts `{"query":"What are the limitations?","method":"hybrid_reranked","top_k":5}`.
The Documents panel includes this method. Chat opts in through
`RAG_RETRIEVAL_METHOD=hybrid_reranked`. Vector remains the default.
`RERANK_CANDIDATES=20` bounds the fused shortlist (range 20–200);
`RERANK_THREADS=2` controls model threads (range 1–16). The shortlist cannot exceed
the available hybrid union. No migrations or dependency changes are required.

Successful results include `rerank_status: "applied"` and `rerank_score`.
Scores are raw relevance logits, not probabilities, and may be negative. Ties
use ascending chunk UUID. Cosine, BM25 and RRF scores remain separately available.
Model failures, nonfinite/missing scores and query/passage pairs exceeding 512
tokens preserve hybrid order with `rerank_status: "fallback"`, null reranker
scores and `retrieval_method: "hybrid"`. Both search and chat show a fallback
notice. No partial ranking or silently truncated pair is accepted. Retrieval
branch failures still fail the request; empty workspaces skip reranking.

## Development results

The unchanged 33-question development split has 30 answerable questions and
three abstention checks. The corpus has only ten chunks, so all ten reached the
reranker; this does not test candidate loss on a large corpus. Chunk size 1024,
overlap 64, RRF constant 60 and top-k 5 match earlier runs.

| Metric | Vector | BM25 | Hybrid | Hybrid + reranker |
|---|---:|---:|---:|---:|
| Evidence Recall@5 | 0.9833 | 0.9833 | 0.9833 | 0.9833 |
| MRR | 0.9000 | 0.9833 | 0.9500 | 0.9833 |
| Complete evidence at 5 | 29/30 | 29/30 | 29/30 | 29/30 |

Compared with hybrid, first evidence moved from rank two to one for `rag-002`,
`rag-013` and `rag-037`; `rag-014` regressed from one to two. The chunk-boundary
evidence limitation remains. Reranking matches BM25's MRR on this small synthetic
dataset, so these results do not justify choosing it as the default.

[Raw development run](runs/reranked-dev-v1.json) records all candidate lists,
pre-rerank order, scores, source/data hashes and timings. All 33 requests applied
reranking with zero fallbacks. Median reranking time was **656.58 ms**, median
total query retrieval **670.82 ms**, and p95 **859.67 ms**. Cached model warmup
took 0.19 seconds and is excluded from query timings. Earlier hybrid median was
6.81 ms; a step-6 regression run measured 6.29 ms with identical per-question
retrieval metrics. These single local runs are not controlled API benchmarks;
the offline runner excludes database work and per-request BM25 rebuilding.

Generation was not run across this split. Citation accuracy and abstention
quality for reranked retrieval remain unmeasured; the earlier vector citation
result must not be reused for this method. Model name and implementation hashes
are recorded, but upstream model weights are not revision-pinned.

## Verification and review boundary

All **124 backend tests** passed, including ordering, ties, source preservation,
candidate and final limits, empty inputs, invalid scores, model failures, pair
length validation, ownership and configured reranked chat context. Frontend
lint, TypeScript and production build passed. Existing Starlette/httpx and
multiple-lockfile warnings remain. No browser visual QA was performed.

The disposable PostgreSQL check passed real PDF ingestion, dense + lexical
retrieval, fusion, real cross-encoder scoring without fallback, source metadata
and tenant isolation. Its local `llama3.1:8b` chat call returned invalid evidence
format and was correctly rejected with HTTP 502. This is a generation failure,
not a retrieval failure; a successful end-to-end cited answer is not claimed
for this run. The generation prompt and evidence validation remain unchanged.
A separate retrieval-only smoke test completed successfully, including cascade
and file cleanup. Both checks used fresh databases in a dedicated disposable
container, which was removed afterward; existing application databases were untouched.

Step 6 ends at review. The 12 held-out questions remain unscored. Step 7's final
four-strategy comparison and citation review require the user's next approval.
