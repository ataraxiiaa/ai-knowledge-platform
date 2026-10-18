# Phase 14, step 1: evaluation contract

The 45-question `synthetic-regression-v1` suite is the **first frozen permanent regression fixture**. The approved scope is synthetic v1 first; representative real-PDF cases belong in a later dataset version. The manifest pins corpus, development, and held-out file bytes by SHA-256. Any change to a question, answer, evidence quote, split, or source text requires a new dataset ID and new fingerprints; never silently rewrite v1. Run `uv run --locked python scripts/validate_evaluation_dataset.py` from `backend/` before scoring. The validator checks structure and exact evidence provenance, not whether the expected answer is semantically complete or whether a citation supports a generated claim.

The corpus is one authored English text document across five pages, not uploaded PDFs. It contains 33 development and 12 historical held-out questions (40 answerable, five unanswerable), 54 required evidence units, and eight answerable questions per page. The held-out split was used for the Phase 5 final comparison on 2026-10-16. **It is no longer unseen.** Use both splits for repeatable regression checks and add new, independently reviewed material before claiming an unbiased final comparison. Independent review of the agent-authored reference answers and evidence is still pending. No production performance or general RAG-quality claim follows from this fixture alone.

## Frozen metric meanings

| Metric | Definition | Denominator / exclusions |
|---|---|---|
| Recall@5 | For each answerable question, count required evidence strings wholly inside a top-five chunk with the annotated document and page; divide by required evidence count, then macro-average. | 40 answerable questions; unanswerable questions excluded. |
| MRR | Reciprocal rank of the first chunk containing any complete required evidence string on the correct document/page. | Answerable questions; zero for no hit. Candidate windows may limit the ranking. |
| Complete evidence@5 | All required evidence strings covered in the top five. | Answerable questions. |
| Page hit@5 | At least one top-five chunk from the expected page. | Answerable questions; weaker than evidence recall. |
| Unanswerable abstention rate | Correct `insufficient_evidence` responses. | All unanswerable generation attempts; errors count as failures. |
| Citation accuracy | Supported claim-citation pairs divided by all reviewed claim-citation pairs. | Undefined until every pair has a definitive support judgment; uncited claims remain review units. Excludes generation failures and abstentions from this precision, which must be reported separately. |
| Retrieval P95 | Nearest-rank 95th percentile of per-question local retrieval duration. | All questions in a completed run. Excludes corpus embedding/warmup; it is not API end-to-end latency. |

Answer quality has **no validated numeric metric yet**. Expected answers are semantic references, not exact-string targets. Phase 14 step 4 must define a rubric and review protocol before storing a number. Total question latency and provider-reported token usage are defined in the [runner specification](RUNNER.md), not by the dataset itself. Report null/unknown rather than zero for metrics not measured.

## Comparison rules

Compare runs only when dataset ID and corpus/split hashes match. Record chunk size/overlap, embedding model, retrieval strategy, candidate counts, reranker/model versions, prompt hash, LLM provider/model, and code version. Mark incomplete runs and generation failures separately. A split evidence string across chunk boundaries lowers the strict chunking ceiling even if the model receives the information in adjacent chunks; the known `rag-031` case makes held-out Recall@5 ceiling 0.95 for the Phase 5 chunk settings. Existing held-out model outputs were sampled without a fixed seed, so one-run differences are not causal evidence.

Before treating this as a permanent product benchmark, add representative permission-cleared PDFs with stable source identity and page annotations, and have another reviewer check references and evidence. Version those additions separately; keep v1 available for regression history.
