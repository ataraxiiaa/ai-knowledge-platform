# Phase 5, step 4: BM25 retrieval

Step 4 is complete and awaits review before hybrid retrieval. Held-out questions
remain unscored. Generation prompts, vector defaults, and dataset annotations were
not changed.

## Behavior

`POST /workspaces/{id}/search` accepts `method: "bm25"`; omitted method still means
`"vector"`. The Documents panel has a method selector. The chat endpoint continues
to use vector retrieval. Example request:

```json
{"query": "HNSW", "top_k": 5, "method": "bm25"}
```

BM25 searches the same stored chunk text and preserves chunk/document IDs, filename,
page, chunk index, and ingestion metadata. Its response has `retrieval_method:
"bm25"`, a positive `bm25_score`, and `similarity: null`. Vector responses retain
their numeric cosine `similarity` and have `bm25_score: null`. Scores are not
probabilities or comparable across methods. Consumers using BM25 must handle null
cosine similarity. Existing vector requests retain their behavior.

The API checks ownership before retrieval. Only ready documents in that workspace
contribute to document frequencies, average length, candidates, and ranking.
Failed/processing documents and other workspaces cannot influence the score.
Queries with no matching tokens return an empty list, including punctuation-only
queries. Blank queries return 422. Zero-score chunks are never used to fill top-k.
Ties use ascending chunk UUID. Search retains the existing PostgreSQL prerequisite.

## Fixed algorithm

The shared `app/services/bm25.py` module is used by both the API and evaluator.
It has no new package dependency. Each chunk is one BM25 document.

```text
idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
score(q,d) = sum over distinct query terms t:
  idf(t) * tf(t,d) * (k1 + 1)
  / (tf(t,d) + k1 * (1 - b + b * length(d) / average_length))
k1 = 1.2; b = 0.75
```

The positive-IDF form follows the [Lucene BM25 reference](https://lucene.apache.org/core/7_7_0/core/org/apache/lucene/search/similarities/BM25Similarity.html).
Parameter meanings/defaults are described in [Elastic's similarity documentation](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity).
The explicit formula above includes the conventional `(k1 + 1)` numerator factor;
this is a standalone implementation, not a claim of byte-identical Lucene scoring.

Tokenization uses Unicode NFKC normalization, case-folding, and letter/number runs.
Hyphens, underscores, decimal punctuation, and other punctuation separate tokens:
`GPU-42` -> `gpu`, `42`; `ef_search` -> `ef`, `search`. No stemming, synonym expansion,
stopword removal, or query-term repetition weighting is used. Identifiers are
searchable by their component tokens, not treated as indivisible exact phrases.
Common-word overlap may still yield unrelated hits; positive BM25 is not an
answerability guarantee. Parameters were fixed before this evaluation, not tuned.

The API rebuilds a workspace-local in-memory index on each request. It loads text
and metadata, not embeddings, and does not call the embedding model. There is no
persistent cache to invalidate after upload, deletion, or status changes. For a
bounded first implementation, `BM25_MAX_CHUNKS` defaults to 20,000 ready chunks.
The service reads at most cap+1 rows and returns 503 above the cap; it never scores
a silently truncated corpus. Larger collections need an indexed lexical backend.
No migration or existing-document reingestion is required.

## Development comparison

Same corpus/split hashes, 1024-character chunks, overlap 64, top-k 5, 30 answerable
questions plus three unanswerable diagnostics. Generation was not run in this
step; no BM25 citation or abstention accuracy is claimed.

| Metric | Vector | BM25 |
|---|---|---|
| Evidence Recall@5 | 0.9833 | 0.9833 |
| MRR | 0.9000 | 0.9833 |
| Complete evidence at 5 | 29/30 | 29/30 |
| Expected page at 5 | 30/30 | 30/30 |
| Full-corpus evidence ceiling | 0.9833 | 0.9833 |
| Local query latency median / p95 | 6.24 / 7.72 ms | 0.075 / 0.104 ms |

BM25 moved the first complete evidence match from rank 2 to rank 1 for `rag-002`,
`rag-014`, `rag-035`, `rag-036`, and `rag-037`. Other first-evidence ranks were
unchanged. The split HNSW evidence in `rag-037` still prevents complete evidence
coverage; rank improvements do not repair that chunk boundary.

The evaluator excludes zero-score BM25 candidates. Its chunking ceiling is now
explicitly computed over all corpus chunks rather than only returned candidates;
this preserves the original metric meaning when lexical search returns fewer hits.
Every vector per-question metric matches the preserved step 3 run.

This is a synthetic one-document, ten-chunk collection; top-five retrieval covers
half the corpus. Shared vocabulary favors lexical matching. These results do not
establish that BM25 is generally better than dense retrieval. Timings are from one
local run, exclude index construction, and are not API/PostgreSQL latency. In
particular, the API rebuilds its BM25 index per request while the benchmark builds
it once; the table must not be used to claim the same API speedup.

Raw runs: [BM25](runs/bm25-dev-v1.json) and
[vector regression comparison](runs/vector-dev-step4.json). Prior runs were preserved.

Reproduce from `backend/`, using a fresh output filename:

```sh
uv run --locked python scripts/evaluate_retrieval.py --strategy bm25 --output experiments/evaluation/runs/bm25-dev-new.json
```

## Validation

- 108 backend tests passed, including hand-calculated BM25, length normalization,
  saturation, Unicode/identifier handling, no overlap, stable ties, ready/ownership
  filtering before statistics, deleted chunks, limits, and score metadata.
- Frontend ESLint, TypeScript, and production build passed. Browser visual QA was
  not performed. The build retains the existing multiple-lockfile warning.
- The real disposable PostgreSQL smoke test passed: PDF -> embeddings -> storage,
  vector search, BM25 chunk loading/ranking, no-match behavior, source identity,
  tenant isolation, cascade and file cleanup. The dedicated container was removed
  afterward; no existing database or volume was used.
- `git diff --check` passed. The existing Starlette/httpx deprecation warning remains.

Approval boundary: stop before step 5 (merge dense and BM25 results). There is no
hybrid ranking, reranker, automatic strategy change, or held-out evaluation yet.
