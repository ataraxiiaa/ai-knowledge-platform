# Phase 5, subphase 1: readiness review and vector baseline

Reviewed on 2026-10-16 against commit
`9e67da9f7ef7c6352ac41ff0b83f11f34f61af2e`.

Follow-up: Phase 4 implementation subsequently added chat generation and validated
source quotations. See `PHASE4_REVIEW.md` for current validation and remaining
integration prerequisites. This document preserves the original baseline findings.

## Gate decision

**Basic RAG is not implemented end to end in this checkout.** PDF ingestion and
dense retrieval exist, but there is no answer-generation service/API, context-to-LLM
flow, or generated-answer citation validation. The frontend chat returns a preview
message. Complete the basic RAG prerequisite before improving retrieval; subphase 2
has not started. This review does not add or change application behavior.

## Verified implementation

- `app/services/ingestion.py`: PDF extraction, page-local chunking, embeddings,
  atomic chunk persistence, and safe failure status without partial chunks.
- `app/services/embeddings.py`: local FastEmbed CPU model
  `BAAI/bge-small-en-v1.5`, 384 dimensions, 512-token input validation.
- `app/api/documents.py`: exact pgvector cosine search, filtered to ready documents
  in the authenticated user's workspace. Ties use chunk ID. Ownership is checked
  before retrieval; no ownership behavior was changed.
- `app/schemas/documents.py`: default top-k 5, allowed range 1–20. Results include
  document/chunk IDs, filename, page, text, similarity, and ingestion metadata.
  These are source references, not citations attached to generated claims.
- `app/core/config.py`: default chunk size 1024 Unicode characters, overlap 64;
  these are code defaults, not a claim about deployment environment overrides.
- `app/api/__init__.py` registers authentication, health, workspace, and document
  routes only. `frontend/app/workspaces/[id]/page.tsx` implements preview chat.

## Validation performed

From `backend/`, using its existing virtual environment:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.cache/phase5-subphase1-tests
```

Result: **52 passed**, one upstream Starlette/httpx deprecation warning, 18.47s.
The tests use isolated SQLite and temporary upload storage. Ingestion tests mock
embeddings; passing them does not establish live pgvector retrieval correctness.
Coverage includes ingestion errors, rollback, metadata, ownership, and cleanup.

The existing real-model experiment was rerun offline with cached weights:

```powershell
$env:DATABASE_URL='sqlite:///:memory:'
$env:SECRET_KEY='phase5-baseline-test-only-0123456789abcdef'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:HF_HUB_OFFLINE='1'
.\.venv\Scripts\python.exe scripts/chunk_experiment.py --output experiments/phase5-vector-baseline.json
```

The key above is only a test configuration value. This experiment does not access
a database. Raw outputs, timestamps, environment, corpus hash, and per-query
retrieval evidence are in `phase5-vector-baseline.json`. Historical `results.json`
was preserved.

| Chunk size | Overlap | Chunks | Evidence Hit@1 | Evidence Hit@5 | MRR |
|---|---|---|---|---|---|
| 256 | 64 | 37 | 0.500 | 1.000 | 0.7292 |
| 512 | 64 | 17 | 0.625 | 1.000 | 0.8125 |
| 1024 (default) | 64 | 10 | 0.750 | 1.000 | 0.8750 |

These reproduce the historical quality scores on five authored pages and eight
questions. Hit@5 means at least one of the first five chunks contains the entire
expected evidence string. It is not general multi-evidence Recall@5. MRR uses the
first complete-evidence match over the full ranking. Larger chunks benefit from
this criterion. Timings are single-run in-memory cosine measurements, not API or
PostgreSQL latency. This small synthetic corpus is not the planned 30–50-example
evaluation dataset or a held-out quality benchmark.

## Outstanding prerequisites

1. Implement and verify basic RAG: retrieved passages to an LLM, a grounded answer,
   document/page citations tied to supporting passages, and insufficient-evidence
   behavior. Choose the provider/model and its configuration as part of that work.
2. Run `scripts/verify_pgvector.py` with `PHASE3_TEST_DATABASE_URL` pointing to an
   empty disposable PostgreSQL database. That variable was not set during this
   review, so the script was not run. Historical documentation reports a previous
   successful smoke test; it is not fresh verification of this checkout.
3. Verify the complete upload → retrieval → generated answer → citations path.
   Generated-answer citation accuracy cannot yet be measured.

Subphase 1 review and baseline capture are complete; its end-to-end RAG readiness
checkpoint remains unmet. Pause here for user review before further implementation.
