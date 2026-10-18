# Phase 14 step 5: stored-run comparison

`scripts/compare_experiment_runs.py` reads two completed `experiment_runs` records and produces a JSON comparison. It rejects comparisons across different dataset IDs, corpus hashes, or split hashes. These are regression comparisons; the synthetic v1 split is not an unseen benchmark.

Use explicit review IDs for answer quality and citation accuracy. The tool does not select the latest or highest-scoring review, and never substitutes the raw run's unreviewed semantic fields. If either score is unknown, its delta is `null`. Deltas are candidate minus baseline: a positive Recall@5 delta means higher recall, while a negative P95 latency delta means lower latency. Token counts also remain `null` when provider usage was unavailable.

```sh
uv run --locked python scripts/compare_experiment_runs.py \
  --baseline BASELINE_RUN_UUID --candidate CANDIDATE_RUN_UUID \
  --baseline-review BASELINE_REVIEW_UUID --candidate-review CANDIDATE_REVIEW_UUID
```

Set `DATABASE_URL` to the migrated experiment database. Review arguments are optional, but both should be selected to compare reviewed metrics. The output includes each run's full configuration, code version, reviewer provenance, metric values, deltas, and warnings for differing configurations or reviewer types. If rubric versions differ, the answer-quality delta is suppressed. Differences from single runs are descriptive, not statistical or causal evidence. Run multiple trials and add representative reviewed PDFs before drawing broader conclusions.
