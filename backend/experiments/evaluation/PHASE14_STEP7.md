# Phase 14 step 7: reproducible regression snapshot

The [compact snapshot](phase14-snapshot-v1.json) records eight completed retrieval-only runs over the frozen synthetic v1 dataset: four strategies on the development split and four on the historically used held-out split. It includes run IDs, SHA-256 hashes of the full local JSON reports, code/configuration fingerprints, summaries, and per-question retrieval scores. The full reports were kept locally during measurement; the snapshot is the versioned comparison artifact. Re-running the evaluator creates new run IDs, timings, and report hashes. The pinned dataset hashes and deterministic retrieval scores are the useful reproducibility checks.

| Strategy | Dev Recall@5 | Dev MRR | Historical held-out Recall@5 | Historical held-out MRR |
| --- | ---: | ---: | ---: | ---: |
| Vector | 0.9833 | 0.9000 | 0.9500 | 1.0000 |
| BM25 | 0.9833 | 0.9833 | 0.9500 | 0.9000 |
| Hybrid | 0.9833 | 0.9500 | 0.9500 | 1.0000 |
| Hybrid + reranker | 0.9833 | 0.9833 | 0.9500 | 1.0000 |

All four methods have the same evidence Recall@5 on this tiny corpus. The held-out 0.95 score includes the known chunk-boundary case `rag-031`, which limits strict single-chunk evidence coverage at the recorded chunk settings. MRR changes because the first relevant evidence chunk moves within the ranking. Reranking applied to every question in these runs, but the corpus has only ten chunks, so these results say little about large candidate pools. The reranked development retrieval P95 was about 787 ms on the measurement machine versus about 8 ms for vector; these local timings are not production latency or a cross-machine benchmark.

No LLM generation ran for this snapshot. Citation accuracy, answer quality, and token usage are therefore unknown, not zero. The [earlier Phase 5 report](FINAL_RESULTS.md) includes generation and agent citation reviews for separate, older runs; do not join those judgments to these run IDs. The held-out split was already used in Phase 5 and is a regression split now, not unseen final validation. The dataset is one authored English document rather than representative PDFs, and its annotations have no independent human review. This snapshot cannot support a general claim that one retrieval method is best.

The [CI gate](PHASE14_STEP6.md) checks the three non-reranked development strategies automatically. Run the reranker and historical held-out split deliberately with fresh output paths. When changing embeddings, chunking, retrieval, reranking, prompts, or the LLM, record the configuration and compare new runs against compatible baselines; generation changes also require [semantic review](PHASE14_STEP4.md). A new independently reviewed PDF dataset is the next prerequisite for credible product-quality claims.
