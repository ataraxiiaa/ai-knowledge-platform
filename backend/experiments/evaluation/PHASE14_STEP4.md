# Phase 14 step 4: answer-quality review

Answer quality and citation support are independent measurements. A review is bound to the exact completed report bytes by SHA-256 and run ID. The `experiment_reviews` table stores append-only judgments; it never revises the raw `experiment_runs` row. Each review identifies its reviewer and whether the reviewer is human or an agent. Agent judgments are labeled as such and are not independent human annotation.

For an answered, answerable question, assign one integer score:

| Score | Meaning |
| --- | --- |
| 0 | Wrong, irrelevant, or claims the evidence does not support. |
| 1 | Some relevant content, but the central answer is wrong or mostly missing. |
| 2 | Partly correct; material omissions or errors remain. |
| 3 | Correct central answer with a minor omission or imprecision. |
| 4 | Correct, complete for the question, and faithful to the available evidence. |

Judge semantic content against the expected answer and evidence, not exact wording. Citation support is assessed separately for every claim/source pair. An answer can have high quality and poor citations, or the reverse.

Status outcomes are scored deterministically: correct abstention on an unanswerable question gets 4; false abstention, an answer to an unanswerable question, and a generation error get 0. These units remain in the denominator. A run without generation has undefined quality. A pending answer judgment leaves final `answer_quality` null; `quality_review_coverage` shows progress. Final quality is the sum of all question scores divided by `4 × question count`. Citation accuracy remains null until every emitted claim/source unit has a definitive support judgment. No emitted claims means undefined citation accuracy.

Create a template from the completed JSON report, fill `reviewer`, `reviewer_type`, answer `score` values and citation `judgment` values, and save a new reviewed copy:

```sh
uv run --locked python scripts/score_evaluation_review.py --report experiments/evaluation/runs/example.json --create-template experiments/evaluation/runs/example.review-template.json
uv run --locked python scripts/score_evaluation_review.py --report experiments/evaluation/runs/example.json --review experiments/evaluation/runs/example.reviewed.json
```

Use `--persist` on the second command with an explicit `DATABASE_URL` after the corresponding run has been persisted. Each persist inserts a new immutable review record, including partial reviews. Preserve the report and original template. The older `score_citation_review.py` and citation-only review files remain valid for citation scoring; they do not acquire an answer-quality score.
