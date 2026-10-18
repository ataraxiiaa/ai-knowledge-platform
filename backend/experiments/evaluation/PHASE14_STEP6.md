# Phase 14 step 6: automatic retrieval regression gate

The Delivery workflow runs the frozen `synthetic-regression-v1` development split on every pull request and push to `main`. It evaluates vector, BM25, and hybrid retrieval without generation or provider credentials. The gate requires complete reports with the pinned corpus/split hashes, 33 questions, chunk size 1024, overlap 64, and Recall@5 at least 0.98 for each strategy. This threshold is just below the recorded 0.9833 development result; it catches a loss of an evidence unit under the current fixture. All three JSON reports are uploaded as CI artifacts even when the gate fails.

The [baseline file](ci-baseline.json) is versioned and reviewable. If a deliberate model, chunking, or retrieval change makes the pinned settings obsolete, evaluate the effect, explain the tradeoff in the PR, and update the baseline in that same reviewed change. Do not silently lower the threshold to clear CI. The gate checks retrieval regressions on one synthetic corpus; it does not measure production Postgres latency, PDF extraction, reranker quality, answer quality, or citation support. Existing backend and integration jobs cover their respective behaviors.

Generation and semantic review remain opt-in because model calls can cost money, vary between runs, and require reviewer judgment. Use the runner with `--generate` and the [review protocol](PHASE14_STEP4.md) when changing prompts, LLM routes, or answer behavior. Compare persisted runs with [step 5's tool](PHASE14_STEP5.md). A single run is descriptive, not a causal estimate.

To reproduce the gate locally from `backend/` after `uv sync --locked`:

```sh
mkdir -p .test-tmp-ci-evaluation
for strategy in vector bm25 hybrid; do
  uv run --locked python scripts/evaluate_retrieval.py --strategy "$strategy" --split dev --output ".test-tmp-ci-evaluation/$strategy.json"
done
uv run --locked python scripts/check_evaluation_gate.py --baseline experiments/evaluation/ci-baseline.json --reports .test-tmp-ci-evaluation
```

Use fresh output paths for repeated local runs; the evaluator refuses to overwrite existing reports.
