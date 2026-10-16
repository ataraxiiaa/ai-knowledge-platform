# Phase 5, step 1: post-RAG verification and baseline

Reviewed on 2026-10-16 (Asia/Karachi), against commit
`98752994302373a74ff14ed63b8ccf590a23624d`.
Raw experiment timestamps use UTC (2026-10-15).

## Decision

**The basic RAG smoke-test gate passed.** The real API path now verifies PDF upload,
page extraction, local embeddings, PostgreSQL vector storage and retrieval, context
construction, local LLM generation, and document/page quotation validation.
Step 1 is complete. Stop for user review before step 2; no evaluation dataset,
BM25, hybrid retrieval, or reranking was added.

This supersedes the unmet gate in `PHASE5_BASELINE.md` and the pending integration
verification in `PHASE4_REVIEW.md`. Those documents preserve the earlier findings.

## Checks performed

| Check | Result |
|---|---|
| Isolated backend regression suite | 79 passed, 22.55s |
| Migrations and Alembic schema comparison on empty PostgreSQL | Passed |
| Real PDF -> CPU embeddings -> vector(384) -> cosine search | Passed; top cosine 0.7755 |
| Real retrieval -> local LLM -> validated document/page quotes | Passed |
| Search/chat workspace isolation | Passed |
| Empty-workspace chat abstention | Passed |
| Workspace deletion, chunk cascade, PDF cleanup | Passed |
| Fresh vector-only corpus experiment | Passed; quality scores unchanged |

The test suite reports one upstream Starlette/httpx deprecation warning.
The full integration command was `scripts/verify_pgvector.py --chat`, using
`backend/.venv/Scripts/python.exe`. It tested `What is a puppy?` against an authored
`dogs.pdf`, checked each cited quote against the actual retrieved chunk, and checked
document identity, page 1, citation markers, and unauthorized workspace access.

Docker Desktop was started for the verification. A new auto-removing container
named `knowledge-phase5-step1-check` used `pgvector/pgvector:pg16`, a disposable
database `phase5_check`, and a localhost-only port mapping `127.0.0.1:55435`.
No existing database or volume was used. The test container was stopped after the
run. Docker Desktop remains running. No saved application configuration changed.

Generation used installed local Ollama `llama3.1:8b` at
`http://localhost:11434/v1`, with a process-local timeout of 120 seconds and no API
key. Only synthetic text was used. Embeddings used cached weights with
`HF_HUB_OFFLINE=1`. The application default timeout remains 60 seconds, and its
model remains explicitly configurable; this does not configure deployed chat.

## Retrieval configuration frozen for comparison

- Model: `BAAI/bge-small-en-v1.5`, 384 dimensions, CPU, 512-token input limit.
- Default chunking: 1024 Unicode characters, 64-character overlap, page-local.
- Ranking: exact cosine distance, then chunk ID for ties; ready documents only,
  filtered by the authenticated workspace before limiting results.
- Search default top-k: 5; chat `RAG_TOP_K`: 5; configurable range: 1–20.
- No similarity threshold, approximate vector index, lexical retrieval, or reranker.
- The integration smoke deliberately uses 64-character chunks with overlap 8 to
  exercise multiple chunks in a tiny PDF; it is not the default-size benchmark.

## Fresh vector baseline

Command from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts/chunk_experiment.py --output experiments/phase5-post-rag-vector-baseline.json
```

The run used isolated test configuration, offline model access, and no database.
Raw provenance, timings, ranks, and retrieved passages are recorded in
`phase5-post-rag-vector-baseline.json`. Earlier baseline files were preserved.

| Chunk size | Overlap | Chunks | Evidence Hit@1 | Evidence Hit@5 | MRR |
|---|---|---|---|---|---|
| 256 | 64 | 37 | 0.500 | 1.000 | 0.7292 |
| 512 | 64 | 17 | 0.625 | 1.000 | 0.8125 |
| 1024 (default) | 64 | 10 | 0.750 | 1.000 | 0.8750 |

Corpus: five authored pages, 7,122 cleaned characters, eight questions.
Corpus SHA-256:
`3c688318befa76a04593d24129d665c23fda2140fbeb640fb174a116fc045393`.

Hit@5 means at least one top-five chunk contains the complete annotated evidence
string; it is not general multi-evidence Recall@5. MRR measures the first such
match over the full ranking. The complete-evidence criterion favors larger chunks.
These are in-memory retrieval scores, not PostgreSQL latency measurements.

## Limits and next approval boundary

A successful smoke test demonstrates the pipeline works on a small synthetic
example. It does not establish general answer quality, semantic citation accuracy,
production performance, or deployment readiness. Exact quote matching establishes
provenance, not whether each claim follows logically from the quote. The existing
eight-query corpus is not the planned 30–50-example evaluation dataset.

The next approved unit of work would be step 2: create and review the evaluation
dataset with question, expected document, expected page, and expected answer.
No step 2 work was started during this review.
