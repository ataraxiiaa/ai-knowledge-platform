import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.experiments import ExperimentReview, ExperimentRun
from scripts.compare_experiment_runs import compare, load_and_compare


def run(**changes):
    values = {"id": uuid.uuid4(), "dataset_id": "synthetic-regression-v1",
              "corpus_sha256": "a" * 64, "split_sha256": "b" * 64,
              "code_version": "code-a", "configuration": {"strategy": "vector"},
              "status": "completed", "recall_at_5": .5, "p95_latency_ms": 10,
              "started_at": datetime.now(UTC), "completed_at": datetime.now(UTC)}
    values.update(changes)
    return ExperimentRun(**values)


def review(parent, **changes):
    values = {"id": uuid.uuid4(), "run_id": parent.id, "report_sha256": "c" * 64,
              "rubric_version": "answer_quality_v1", "reviewer": "Test reviewer",
              "reviewer_type": "human", "citation_accuracy": .5,
              "answer_quality": .75, "review_payload": {}}
    values.update(changes)
    return ExperimentReview(**values)


def test_comparison_preserves_missing_values_and_explicit_review_provenance():
    baseline = run()
    candidate = run(recall_at_5=.75, p95_latency_ms=8, code_version="code-b",
                    configuration={"strategy": "hybrid"})
    left, right = review(baseline), review(candidate, answer_quality=.5, citation_accuracy=None)
    result = compare(baseline, candidate, left, right)
    assert result["candidate_minus_baseline"]["recall_at_5"] == .25
    assert result["candidate_minus_baseline"]["p95_latency_ms"] == -2
    assert result["candidate_minus_baseline"]["answer_quality"] == -.25
    assert result["candidate_minus_baseline"]["citation_accuracy"] is None
    assert result["candidate_minus_baseline"]["prompt_tokens"] is None
    assert result["baseline"]["review_id"] == str(left.id)
    assert len(result["warnings"]) == 2


@pytest.mark.parametrize("difference", ["dataset_id", "corpus_sha256", "split_sha256", "status"])
def test_comparison_rejects_incompatible_runs(difference):
    baseline, candidate = run(), run()
    setattr(candidate, difference, "failed" if difference == "status" else "other")
    with pytest.raises(ValueError):
        compare(baseline, candidate)


def test_review_must_belong_to_selected_run_and_rubric_must_match():
    baseline, candidate = run(), run()
    with pytest.raises(ValueError, match="belongs to another run"):
        compare(baseline, candidate, review(candidate))
    result = compare(baseline, candidate, review(baseline),
                     review(candidate, rubric_version="future_v2"))
    assert result["candidate_minus_baseline"]["answer_quality"] is None


def test_database_comparison_reads_selected_rows(tmp_path):
    baseline, candidate = run(), run(recall_at_5=.9)
    selected = review(candidate)
    baseline_id, candidate_id, review_id = baseline.id, candidate.id, selected.id
    url = f"sqlite:///{(tmp_path / 'comparison.db').as_posix()}"
    engine = create_engine(url)
    ExperimentRun.__table__.create(engine)
    ExperimentReview.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([baseline, candidate, selected])
        session.commit()
    engine.dispose()
    result = load_and_compare(url, baseline_id, candidate_id, candidate_review_id=review_id)
    assert result["candidate"]["review_id"] == str(review_id)
    assert result["candidate_minus_baseline"]["recall_at_5"] == pytest.approx(.4)
    assert result["candidate_minus_baseline"]["answer_quality"] is None
    with pytest.raises(ValueError, match="does not exist"):
        load_and_compare(url, baseline_id, candidate_id, baseline_review_id=uuid.uuid4())
