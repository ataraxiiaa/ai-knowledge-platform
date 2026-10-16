# Phase 5, step 7: final retrieval comparison

## Protocol

On 2026-10-16, the previously unused 12-question held-out split was scored once
per strategy, with generation, after user approval. Ten questions are answerable
and two require abstention. This is a question-level split sharing one synthetic
five-page document (ten chunks), not a document-disjoint benchmark.

The settings were fixed from step 6: chunk size 1024, overlap 64, top-k 5,
BGE-small-en-v1.5 dense embeddings, BM25 k1=1.2/b=0.75, 20 candidates per branch,
equal-weight RRF k=60, and MiniLM-L6 cross-encoder on the best 20 fused candidates.
The cross-encoder uses two CPU threads, batches of eight and a 512-token pair
limit. No parameters, annotations, prompts or model choices were tuned after
seeing held-out scores. Vector remains the application default.

All four strategies used local Ollama `llama3.1:8b`, the unchanged generation
prompt, JSON mode, 2000 maximum output tokens and a 120-second timeout. The
[installed model digest](runs/step7-model.json) is recorded. Generation is sampled
with provider defaults and no fixed seed; differences from one run are not causal
proof that a retrieval strategy produces better answers. Calls ran sequentially;
there were no retries to replace failures. Raw reports preserve errors.

Citation judgments are **agent review, not independent human review**. Every
accepted claim?citation pair is checked for semantic support by its quoted
source. Exact quote matching alone does not establish support. Review coverage,
errors and abstentions are reported separately. Citation support precision does
not measure answer completeness, relevance or usefulness.

## Held-out results

| Strategy | Recall@5 | MRR | Median / p95 retrieval (ms) | Answered / errors / abstentions | Citation support (agent) |
|---|---:|---:|---:|---:|---:|
| vector | 0.95 | 1.00 | 15.71 / 21.08 | 7 / 4 / 1 | 20/20 (100.0%) |
| bm25 | 0.95 | 0.90 | 0.15 / 0.19 | 8 / 4 / 0 | 10/12 (83.3%) |
| hybrid | 0.95 | 1.00 | 19.72 / 27.39 | 6 / 6 / 0 | 20/21 (95.2%) |
| hybrid_reranked | 0.95 | 1.00 | 753.06 / 942.62 | 6 / 5 / 1 | 8/10 (80.0%) |

Recall and MRR average only the ten answerable questions; all methods had full
evidence in the top five on 9/10 and the expected page on 10/10. MRR finds the
first matching evidence, so 1.00 does not imply all required evidence was found.
The two unanswerable questions remain in generation/error denominators, not
retrieval-recall denominators. Vector and reranked hybrid abstained on 1/2;
BM25 and hybrid on 0/2. Errors are never counted as correct abstentions.

Citation review covered all 63 accepted claim?citation pairs: 58 supported and
five unsupported. The denominators differ because failed generation produces no
accepted claims and some answers are verbose. A 100% support result for vector
therefore does not mean 100% answer success: four requests failed, and several
accepted claims were tangential. All 12 reranked requests applied the model with
zero fallbacks; median cross-encoder scoring alone was 732.80 ms.

Raw reports: [vector](runs/vector-held-out-v1.json),
[BM25](runs/bm25-held-out-v1.json), [hybrid](runs/hybrid-held-out-v1.json),
[reranked hybrid](runs/hybrid_reranked-held-out-v1.json).
The [machine-readable comparison](runs/step7-comparison.json) joins each exact
report fingerprint to its validated citation review. Raw reports retain null
citation accuracy because review is a separate immutable artifact.

## Decision

Keep **vector** as the application default. Hybrid and reranking do not improve
held-out retrieval over vector here; reranking adds substantial CPU latency.
BM25 is fastest but ranks first evidence second on `rag-015` and `rag-024`,
reducing MRR to 0.90. Its strong development result did not transfer to these
held-out questions. All four modes remain available for experiments.

This is a conservative decision for this application, not a general claim that
vector search beats hybrid retrieval. No default, prompt, chunking or schema was
changed in step 7. Next improvements should address generation format reliability,
semantic support, relevance/completeness and chunk boundaries, using fresh
validation data before revisiting retrieval choices.

## Failure analysis

The `rag-031` mulch placement sentence crosses a chunk boundary. Only one of its
two required evidence strings is wholly contained in an individual chunk. This
sets a macro evidence-recall ceiling of 0.95 on this split, even if all chunks
are retrieved. The information exists across chunks; this is a chunking and
metric limitation, not proof that the source lacks the answer.

The vector answer to `rag-015` contains several supported but irrelevant extra
claims, and `rag-032` repeats a claim. BM25's answers to `rag-015`, `rag-023` and
`rag-024` omit requested details even though their citations can support the
claims they do make. These examples show why citation accuracy is insufficient
as an overall answer-quality measure.

BM25 also produces a primary-key claim whose cited quote concerns table
relationships, and a placeholder claim for the unanswerable watering question.
Both were marked unsupported. Quote provenance checks accepted their source
text, but semantic review rejected the claim?source relationship.

The reranked answer to `rag-023` discusses plants and astronomy despite retrieved
battery evidence. Its `rag-032` answer changes what the trial compares and cites
an explanation-versus-coincidence quote for a different claim about comparing
observations. These are generation failures even when retrieval succeeds.

## Validation

All four reports completed with matching corpus, split and implementation hashes.
All review fingerprints and immutable claim/source fields validated, with 100%
review coverage. Dataset validation passed for all 45 examples, and all 15
metric/citation evaluation tests passed. No application-code changes were needed;
the prior step's 124-test suite and frontend checks were not rerun for these
report-only changes. No database or saved application environment was modified.

## Reproduction and limits

From `backend/`, configure the model and settings above, then run each of
`vector`, `bm25`, `hybrid`, and `hybrid_reranked` with a fresh output filename:

```sh
uv run --locked python scripts/evaluate_retrieval.py --strategy vector --split held_out --allow-held-out --generate --output experiments/evaluation/runs/vector-held-out-new.json
uv run --locked python scripts/score_citation_review.py --report experiments/evaluation/runs/vector-held-out-v1.json --review experiments/evaluation/runs/vector-held-out-v1.agent-review.json
```

Raw `.citations.json` worksheets remain blank; separate `.agent-review.json`
files preserve the recorded judgments, and `.citation-score.json` files contain
fingerprint-validated scores. Corpus/split fingerprints, implementation hashes,
rankings and timing accompany each raw run. Latencies exclude model warmup,
index creation, PostgreSQL and per-request live BM25 rebuilding. A single local
run is not a controlled production latency benchmark.

This held-out split is now consumed: do not tune on it and still call it unseen.
Future iteration needs newly held-out questions, representative PDFs and a
larger document-disjoint corpus. Independent human review remains pending.
