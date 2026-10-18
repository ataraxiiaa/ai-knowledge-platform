"""Compare two stored experiment runs with explicit, optional semantic reviews."""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

METRICS = ("recall_at_5", "p95_latency_ms", "prompt_tokens", "completion_tokens", "total_tokens")


def compare(baseline, candidate, baseline_review=None, candidate_review=None) -> dict:
    for label, run in (("baseline", baseline), ("candidate", candidate)):
        if run.status != "completed":
            raise ValueError(f"{label} run is not completed")
    for field in ("dataset_id", "corpus_sha256", "split_sha256"):
        if getattr(baseline, field) != getattr(candidate, field):
            raise ValueError(f"Runs have different {field}; comparison is invalid")
    for label, run, review in (("baseline", baseline, baseline_review),
                               ("candidate", candidate, candidate_review)):
        if review is not None and review.run_id != run.id:
            raise ValueError(f"{label} review belongs to another run")

    def describe(run, review):
        metrics = {name: getattr(run, name) for name in METRICS}
        metrics.update({"citation_accuracy": review.citation_accuracy if review else None,
                        "answer_quality": review.answer_quality if review else None})
        return {"run_id": str(run.id), "code_version": run.code_version,
                "configuration": run.configuration,
                "review_id": str(review.id) if review else None,
                "reviewer": review.reviewer if review else None,
                "reviewer_type": review.reviewer_type if review else None,
                "rubric_version": review.rubric_version if review else None,
                "review_report_sha256": review.report_sha256 if review else None,
                "metrics": metrics}

    left, right = describe(baseline, baseline_review), describe(candidate, candidate_review)
    deltas = {}
    for name in (*METRICS, "citation_accuracy", "answer_quality"):
        a, b = left["metrics"][name], right["metrics"][name]
        deltas[name] = b - a if a is not None and b is not None else None
    warnings = []
    if baseline.configuration != candidate.configuration:
        warnings.append("Configurations differ; inspect the full configuration before attributing a delta.")
    if baseline.code_version != candidate.code_version:
        warnings.append("Code versions differ.")
    if (baseline_review is None) != (candidate_review is None):
        warnings.append("Only one run has a selected review; reviewed metrics are not paired.")
    if baseline_review and candidate_review:
        if baseline_review.rubric_version != candidate_review.rubric_version:
            warnings.append("Answer-quality rubric versions differ; quality scores are not comparable.")
            deltas["answer_quality"] = None
        if baseline_review.reviewer_type != candidate_review.reviewer_type:
            warnings.append("Reviewer types differ; reviewed scores may not be comparable.")
    return {"dataset_id": baseline.dataset_id, "corpus_sha256": baseline.corpus_sha256,
            "split_sha256": baseline.split_sha256, "baseline": left, "candidate": right,
            "candidate_minus_baseline": deltas, "warnings": warnings,
            "interpretation": "Descriptive differences from individual runs; no causal or statistical claim."}


def load_and_compare(database_url: str, baseline_id: uuid.UUID, candidate_id: uuid.UUID,
                     baseline_review_id: uuid.UUID | None = None,
                     candidate_review_id: uuid.UUID | None = None) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.experiments import ExperimentReview, ExperimentRun

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            baseline = session.get(ExperimentRun, baseline_id)
            candidate = session.get(ExperimentRun, candidate_id)
            if baseline is None or candidate is None:
                raise ValueError("Both run IDs must exist")
            baseline_review = session.get(ExperimentReview, baseline_review_id) if baseline_review_id else None
            candidate_review = session.get(ExperimentReview, candidate_review_id) if candidate_review_id else None
            if baseline_review_id and baseline_review is None:
                raise ValueError("Baseline review ID does not exist")
            if candidate_review_id and candidate_review is None:
                raise ValueError("Candidate review ID does not exist")
            return compare(baseline, candidate, baseline_review, candidate_review)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=uuid.UUID, required=True)
    parser.add_argument("--candidate", type=uuid.UUID, required=True)
    parser.add_argument("--baseline-review", type=uuid.UUID)
    parser.add_argument("--candidate-review", type=uuid.UUID)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("Set DATABASE_URL to the experiment database")
    try:
        result = load_and_compare(database_url, args.baseline, args.candidate,
                                  args.baseline_review, args.candidate_review)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
