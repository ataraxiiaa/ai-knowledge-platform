# Step 3: vector-only development baseline

Recorded 2026-10-16 (Asia/Karachi). See [RUNNER.md](RUNNER.md) for frozen metric
definitions and commands. Only the 33 development examples were scored; the
12 held-out examples remain unscored. No BM25, hybrid, or reranker was added.

## Results

| Measurement | Result | Denominator / interpretation |
|---|---|---|
| Evidence Recall@5 | 0.9833 | Macro average over 30 answerable questions |
| MRR | 0.9000 | First complete evidence match, full ranking, 30 questions |
| Complete evidence in top 5 | 29/30 (96.67%) | All evidence units present |
| Expected page in top 5 | 30/30 (100%) | Weaker than evidence coverage |
| Chunking evidence ceiling | 0.9833 | Same coverage over every chunk |
| Retrieval latency median / p95 | 8.96 / 11.62 ms | Query embedding + in-memory ranking; one local run |
| Generation status | 26 answered, 6 errors, 1 abstention | All 33 attempts |
| Unanswerable abstention | 1/3 (33.33%) | One abstention, one error, one unsupported answer |
| Citation support precision | 45/50 (90%) | Agent-reviewed claim-citation pairs; not independent human review |

The raw generation report deliberately leaves `citation_accuracy` null: automatic
quote validation is not semantic citation grading. The separate manual review
and score files record the 90% agent-reviewed estimate, with review coverage 100%.
Human review remains pending. Generation errors and abstentions emit no citations
and are excluded from citation precision; they remain visible in the counts above.

## What the failures tell us

**Chunk boundaries, not top-five ranking, limit this retrieval score.** For
`rag-037`, the HNSW explanation crosses a chunk boundary and is not wholly contained
in any chunk. The other required sentence is retrieved. Its evidence recall is
0.5 even though page 5 is present. The full-corpus evidence ceiling equals Recall@5,
so reranking alone cannot recover the missing exact evidence unit under this metric.
This is a diagnostic finding, not a reason to revise the annotations after seeing
the score. Matching jointly reconstructed evidence would require a separately
specified metric.

**Retrieval success does not guarantee successful generation.** The provider's
output failed evidence-format validation for `rag-002`, `rag-017`, and `rag-038`.
Quotes were absent from their cited passages for `rag-027`, `rag-037`, and
`rag-041`. The application rejected those responses. Five errors were on answerable
questions, one on an unanswerable question. No silent retries were used to improve
the recorded outcome.

**Valid quotes can still accompany unsupported claims.** The agent review marked
five claim-citation pairs unsupported: two dropped important qualifiers ("alone"
or "by itself"), one introduced a brightness comparison not in the source, one
attributed a battery-life benefit to monitoring/charge limits when the quote only
discussed heat, and one stated milliamp-hours despite the corpus giving no unit or
numeric capacity. The last answer responded to an unanswerable numeric question
with outside knowledge rather than abstaining.

Citation precision also misses other answer-quality problems. The aperture answer
added unrelated garden/database statements that were supported by their sources.
The sandy-soil answer omitted the requested compacted-soil comparison. These are
relevance/completeness problems even when individual citations are correct.

## Artifacts and reproducibility

- [Raw run](runs/vector-dev-v1.json): complete rankings, references, context, answers,
  errors, timings, configuration, corpus/split hashes, and source-code hashes.
- [Blank citation worksheet](runs/vector-dev-v1.citations.json): preserved for a
  fresh independent review.
- [Agent judgments](runs/vector-dev-v1.agent-review.json): all 50 claim-citation
  units with explicit reviewer identity and notes.
- [Citation score](runs/vector-dev-v1.citation-score.json): scored review summary.

Configuration: `BAAI/bge-small-en-v1.5`, 384 dimensions, cached CPU embeddings,
1024-character windows, 64-character overlap, exact cosine, top-k 5. Generation:
installed local Ollama `llama3.1:8b`, 120-second process-local timeout, JSON mode,
unchanged application prompt. Saved application environment was not modified.

Reproduce with a **new output filename**, from `backend/`, setting the corresponding
process environment (`HF_HUB_OFFLINE=1`, `CHUNK_SIZE=1024`, `CHUNK_OVERLAP=64`,
`LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=llama3.1:8b`, empty `LLM_API_KEY`,
and `LLM_TIMEOUT_SECONDS=120`):

```sh
uv run --locked python scripts/evaluate_retrieval.py --generate --output experiments/evaluation/runs/vector-dev-new.json
```

The synthetic corpus has only one document and ten chunks; top-five retrieval
returns half the chunk corpus. These high retrieval scores do not generalize to
larger collections. The evidence-unit metric differs from the older eight-question
Hit@5 smoke metric, so their values should not be treated as a controlled comparison.
LLM output is nondeterministic. This is one run, not an estimate of failure rates
with confidence intervals, and timings are not PostgreSQL or HTTP latency.

## Validation and approval boundary

The backend suite passed **93 tests** (one existing Starlette/httpx deprecation
warning). New tests cover evidence coverage versus rank, duplicate chunks,
document/page identity, split evidence, no-match and unanswerable behavior,
generation-error denominators, reused citations, partial reviews, altered reports,
and missing citations. CLI checks confirmed that accidental output overwrites and
held-out scoring without explicit opt-in are rejected. `git diff --check` passed.

Step 3 is complete. Pause for review before step 4, BM25 retrieval. No production
retrieval settings, generation prompts, or dataset annotations were tuned in this step.
