# Phase 5, step 5: hybrid retrieval

Hybrid combines dense and BM25 candidates using equal-weight reciprocal rank
fusion (RRF). The search API and Documents panel accept `method: "hybrid"`.
Vector remains the default. No reranker or held-out scoring is included.

## Algorithm and configuration

For each distinct chunk in either candidate list:

```text
fusion_score = sum(1 / (HYBRID_RRF_K + branch_rank))
```

Ranks start at one. A missing chunk contributes zero from that branch. Duplicate
chunk IDs within a branch contribute once; repeated IDs across branches merge.
Different chunks with identical text remain distinct because their provenance
can differ. Final ties use ascending chunk UUID. Raw cosine and BM25 values are
preserved for inspection but are never added together. The formula and the default
rank constant are described in [Elastic's RRF documentation](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion).

| Setting | Default | Meaning |
|---|---|---|
| `HYBRID_CANDIDATES` | 20 | Candidates from each branch, before merging; range 20–200 |
| `HYBRID_RRF_K` | 60 | Rank smoothing constant; range 1–1000 |
| `RAG_RETRIEVAL_METHOD` | `vector` | Chat retriever: vector, bm25, or hybrid |
| Search `top_k` / chat `RAG_TOP_K` | 5 | Final context/result limit; range 1–20 |

The minimum candidate limit supports the API's maximum top-k. Each branch is
filtered to ready documents in the owned workspace before ranking and limiting.
At defaults, at most 40 distinct candidates can be fused and then trimmed to top-k.
The existing in-memory BM25 corpus cap still applies. Both branches run sequentially
on the request's database session; no unsafe concurrent session sharing is added.

Search example:

```json
{"query": "How does HNSW search work?", "method": "hybrid", "top_k": 5}
```

Hybrid results retain document/page/content metadata and include `fusion_score`,
`vector_rank`, `bm25_rank`, `similarity` (cosine if present in the dense candidates),
and `bm25_score` (if present in lexical candidates). Absent branch scores/ranks are
null. The UI labels the ordering score RRF. It is not a probability or confidence.

Set `RAG_RETRIEVAL_METHOD=hybrid` on the backend to use this path for chat. No saved
environment was changed during implementation. An empty lexical list is a valid
outcome and allows dense candidates to rank alone. A branch failure, such as an
embedding error or BM25 corpus-cap error, fails the request instead of silently
labeling a degraded result as a successful two-branch search. An empty workspace
returns no passages and chat abstains. No database migration is required.

## Development comparison

Corpus and split fingerprints match the prior runs. Chunk size 1024, overlap 64,
top-k 5, 20 candidates per branch, RRF constant 60. Parameters were fixed before
scoring; there was no grid search or held-out evaluation.

| Metric | Vector | BM25 | Hybrid |
|---|---|---|---|
| Evidence Recall@5 | 0.9833 | 0.9833 | 0.9833 |
| MRR | 0.9000 | 0.9833 | 0.9500 |
| Complete evidence at 5 | 29/30 | 29/30 | 29/30 |
| Expected page at 5 | 30/30 | 30/30 | 30/30 |

Hybrid improves first-evidence rank from 2 to 1 over vector on `rag-014`, `rag-035`,
and `rag-036`. BM25 also ranks evidence first on `rag-002` and `rag-037`, while
hybrid leaves it second. Fusion is therefore better than vector on this small
development set, but worse than BM25. Do not assume combining retrievers always
beats the stronger individual branch or change the default on this evidence alone.

The same HNSW evidence crosses a chunk boundary and limits evidence recall. Fusion
cannot reconstruct missing complete-string evidence. The dataset has only ten
chunks, so the default candidate limit does not truncate the dense list. Larger
collections may lose evidence before fusion; the evaluator measures MRR over the
fused candidate union, not hypothetical ranks outside that window.

[Raw hybrid run](runs/hybrid-dev-v1.json) contains both candidate lists, the fused
ranking, constituent ranks/scores, config, timings, and code/data hashes. Median
local query time was 6.81 ms and p95 9.48 ms in one run. Corpus indexing is excluded;
this is not API latency, especially because the live BM25 index is rebuilt per
request. Generation was not run for the 33 development questions in this step;
no hybrid citation or abstention accuracy is claimed. The separate live smoke
test exercises generation on one synthetic question.

Reproduce from `backend/`, selecting a new output filename:

```sh
uv run --locked python scripts/evaluate_retrieval.py --strategy hybrid --output experiments/evaluation/runs/hybrid-dev-new.json
```

Use fixed `CHUNK_SIZE=1024`, `CHUNK_OVERLAP=64`, `HYBRID_CANDIDATES=20`, and
`HYBRID_RRF_K=60` for this comparison. The offline evaluator uses the same fusion
function as the API. Independent per-branch raw scores do not affect fusion order
once branch ranks are fixed.

## Validation and review boundary

The backend regression suite passed **116 tests**, including fusion arithmetic,
duplicate handling, same-text distinct chunks, stable ties, empty branches,
candidate limits, source preservation, raw-score scale independence, ownership,
failure behavior, and configured hybrid context selection for chat. Frontend lint,
TypeScript, and production build passed. Existing Starlette/httpx and multiple-lockfile
warnings remain; no browser visual QA was performed.

The live PostgreSQL + local Ollama smoke test passed with
`RAG_RETRIEVAL_METHOD=hybrid`: real PDF ingestion, both retrieval branches, RRF
arithmetic, deduplication, source identity, tenant isolation, hybrid context passed
to generation, validated citations, empty-workspace abstention, and cascade/file
cleanup. It used a new disposable pgvector container on localhost port 55437 and
installed `llama3.1:8b`; only synthetic text was used. The container was removed
afterward. Existing data and saved application settings were not changed.

Regression reruns verified every vector and BM25 per-question retrieval metric
matches the preserved step 4 files after the evaluator refactor. `git diff --check`
passed. No full development-set generation evaluation was performed for hybrid.

Step 5 ends at review. Step 6 (cross-encoder reranking) has not started; the 12
held-out questions remain unscored.
