import copy
import json
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.experiments import ExperimentReview, ExperimentRun
from scripts.evaluate_retrieval import persist_report
from scripts.score_evaluation_review import persist_review, score_review, template


def fixture():
    report = {"run_id": str(uuid.uuid4()), "status": "complete", "results": [
        {"id": "q1", "question": "What?", "answerable": True, "expected_answer": "A fact",
         "generation": {"status": "answered", "answer": "A fact [1]", "sources": [
             {"id": 1, "quote": "A fact"}]}},
        {"id": "q2", "question": "Unknown?", "answerable": False, "expected_answer": None,
         "generation": {"status": "insufficient_evidence"}},
        {"id": "q3", "question": "Broken?", "answerable": True, "expected_answer": "A fact",
         "generation": {"status": "error", "error": "timeout"}},
    ]}
    raw = json.dumps(report).encode()
    review = template(report, raw)
    review["reviewer"] = "Agent test"
    review["reviewer_type"] = "agent"
    return report, raw, review


def test_quality_and_citations_are_independent_with_partial_review():
    report, raw, review = fixture()
    assert [item["score"] for item in review["quality_items"]] == [None, 4, 0]
    first = score_review(report, review, raw)
    assert first["answer_quality"] is None and first["quality_review_coverage"] == pytest.approx(2 / 3)
    assert first["citation_accuracy"] is None
    review["quality_items"][0]["score"] = 2
    second = score_review(report, review, raw)
    assert second["answer_quality"] == .5 and second["citation_accuracy"] is None
    review["items"][0]["judgment"] = "supported"
    assert score_review(report, review, raw)["citation_accuracy"] == 1


@pytest.mark.parametrize("change", ["hash", "reorder", "identity", "status_score", "fraction", "type"])
def test_quality_review_rejects_tampering(change):
    report, raw, review = fixture()
    if change == "hash":
        review["report_sha256"] = "wrong"
    elif change == "reorder":
        review["quality_items"].reverse()
    elif change == "identity":
        review["quality_items"][0]["expected_answer"] = "changed"
    elif change == "status_score":
        review["quality_items"][1]["score"] = 0
    elif change == "fraction":
        review["quality_items"][0]["score"] = 2.5
    elif change == "type":
        review["reviewer_type"] = "unknown"
    with pytest.raises(ValueError):
        score_review(report, review, raw)


def test_review_persists_without_changing_run(tmp_path):
    report, raw, review = fixture()
    report.update({"dataset_id": "synthetic-regression-v1", "expected_questions": 3,
                   "corpus_sha256": "a" * 64, "split_sha256": "b" * 64,
                   "code_version": "c" * 64, "recorded_at": "2026-10-18T00:00:00+00:00",
                   "completed_at": "2026-10-18T00:01:00+00:00", "split": "dev",
                   "git_commit": None, "source_sha256": {}, "python": "3.12", "platform": "test",
                   "config": {}, "summary": {"recall_at_5": .5, "citation_accuracy": None,
                   "p95_latency_ms": 10, "prompt_tokens": None,
                   "completion_tokens": None, "total_tokens": None}})
    raw = json.dumps(report).encode()
    review = template(report, raw)
    review["reviewer"] = "Human test"
    review["quality_items"][0]["score"] = 3
    result = score_review(report, review, raw)
    url = f"sqlite:///{(tmp_path / 'review.db').as_posix()}"
    engine = create_engine(url)
    ExperimentRun.__table__.create(engine)
    ExperimentReview.__table__.create(engine)
    engine.dispose()
    persist_report(report, url)
    persist_review(result, copy.deepcopy(review), url)
    engine = create_engine(url)
    with Session(engine) as session:
        run = session.get(ExperimentRun, uuid.UUID(report["run_id"]))
        stored = session.scalar(select(ExperimentReview))
        assert run.answer_quality is None and run.citation_accuracy is None
        assert stored.answer_quality == pytest.approx(7 / 12)
        assert stored.citation_accuracy is None and stored.reviewer_type == "human"
        stored.reviewer = "altered"
        with pytest.raises(ValueError, match="append-only"):
            session.commit()
    engine.dispose()
