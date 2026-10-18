import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import uuid

import pytest
from sqlalchemy import create_engine, select

from app.models.experiments import ExperimentRun
from scripts.evaluate_retrieval import citation_items, fingerprint, persist_report, retrieval_metrics, summarize
from scripts.validate_evaluation_dataset import validate
from scripts.score_citation_review import score


def test_dataset_fingerprint_rejects_changed_annotations(tmp_path):
    source = Path(__file__).resolve().parents[1] / "experiments" / "evaluation"
    for name in ("manifest.json", "corpus.json", "dev.json", "held-out.json"):
        shutil.copyfile(source / name, tmp_path / name)
    shutil.copyfile(source.parent / "corpus.json", tmp_path / "source.json")
    (tmp_path / "manifest.json").write_text(
        (tmp_path / "manifest.json").read_text(encoding="utf-8").replace('"source": "../corpus.json"',
                                                                    '"source": "source.json"'), encoding="utf-8")
    assert validate(tmp_path)["examples"] == 45
    questions = json.loads((tmp_path / "dev.json").read_text(encoding="utf-8"))
    questions[0]["question"] = "Changed but structurally valid question?"
    (tmp_path / "dev.json").write_text(json.dumps(questions), encoding="utf-8")
    with pytest.raises(ValueError, match="split fingerprint changed"):
        validate(tmp_path)


def example():
    return {"answerable": True, "expected_document": "a", "expected_page": 2,
            "required_evidence": ["First fact.", "Second fact."]}


def hit(text, document="a", page=2):
    return {"filename": document, "page": page, "content": text}


def test_evidence_recall_and_full_rank_mrr_are_distinct():
    ranking = [hit("irrelevant"), hit("First fact."), hit("First fact."),
               hit("irrelevant"), hit("irrelevant"), hit("Second fact.")]
    result = retrieval_metrics(example(), ranking)
    assert result["recall_at_5"] == .5  # Duplicate chunks do not count twice.
    assert result["reciprocal_rank"] == .5
    assert result["chunking_evidence_ceiling"] == 1
    assert not result["complete_evidence_at_5"]


def test_wrong_document_and_page_do_not_match_identical_evidence():
    result = retrieval_metrics(example(), [hit("First fact.", document="b"), hit("Second fact.", page=3)])
    assert result["recall_at_5"] == 0 and result["reciprocal_rank"] == 0
    assert not result["page_hit_at_5"]


def test_split_evidence_has_no_complete_match():
    result = retrieval_metrics(example(), [hit("First "), hit("fact."), hit("Second fact.")])
    assert result["recall_at_5"] == .5
    assert result["chunking_evidence_ceiling"] == .5
    assert result["first_evidence_rank"] == 3


def test_empty_and_unanswerable_retrieval():
    result = retrieval_metrics(example(), [])
    assert result["recall_at_5"] == 0 and result["reciprocal_rank"] == 0
    assert retrieval_metrics({"answerable": False}, []) is None


def test_lexical_no_match_does_not_lower_chunking_ceiling():
    result = retrieval_metrics(example(), [], corpus=[hit("First fact. Second fact.")])
    assert result["recall_at_5"] == 0 and result["reciprocal_rank"] == 0
    assert result["chunking_evidence_ceiling"] == 1


def test_mrr_beyond_top_five():
    result = retrieval_metrics(example(), [hit("no")] * 5 + [hit("First fact. Second fact.")])
    assert result["recall_at_5"] == 0
    assert result["reciprocal_rank"] == pytest.approx(1 / 6)


def test_summary_excludes_unanswerable_from_recall_but_counts_provider_errors():
    rows = [{"answerable": True, "retrieval": retrieval_metrics(example(), [hit("First fact.")]),
             "retrieval_ms": 2, "generation": {"status": "answered"}},
            {"answerable": False, "retrieval": None, "retrieval_ms": 4, "generation": {"status": "error"}},
            {"answerable": False, "retrieval": None, "retrieval_ms": 6,
             "generation": {"status": "insufficient_evidence"}}]
    result = summarize(rows)
    assert result["recall_at_5"] == .5 and result["mrr"] == 1
    assert result["unanswerable_abstention_rate"] == .5
    assert result["retrieval_ms_median"] == 4 and result["retrieval_ms_p95"] == 6
    assert result["citation_accuracy"] is None


def test_summary_uses_total_latency_and_never_invents_token_usage():
    rows = [
        {"answerable": True, "retrieval": retrieval_metrics(example(), [hit("First fact.")]),
         "retrieval_ms": 5, "total_ms": 25, "generation": {"status": "answered"},
         "generation_provider": "gemini", "generation_model": "model-a",
         "token_usage": {"prompt_tokens": 10, "completion_tokens": 4}},
        {"answerable": True, "retrieval": retrieval_metrics(example(), [hit("Second fact.")]),
         "retrieval_ms": 8, "total_ms": 40, "generation": {"status": "error"},
         "token_usage": None},
    ]
    summary = summarize(rows)
    assert summary["p95_latency_ms"] == 40
    assert summary["token_usage_coverage"] == 1
    assert summary["actual_model_counts"] == {"gemini:model-a": 1}
    assert summary["prompt_tokens"] is None and summary["total_tokens"] is None
    rows[1]["token_usage"] = {"prompt_tokens": 3, "completion_tokens": 0}
    summary = summarize(rows)
    assert summary["prompt_tokens"] == 13
    assert summary["completion_tokens"] == 4
    assert summary["total_tokens"] == 17


def test_persist_report_inserts_terminal_run_without_rewriting(tmp_path):
    from sqlalchemy.exc import IntegrityError

    url = f"sqlite:///{(tmp_path / 'runs.db').as_posix()}"
    engine = create_engine(url)
    ExperimentRun.__table__.create(engine)
    engine.dispose()
    timestamp = datetime.now(timezone.utc).isoformat()
    report = {"run_id": str(uuid.uuid4()), "status": "complete", "dataset_id": "synthetic-regression-v1",
              "expected_questions": 0, "results": [],
              "corpus_sha256": "a" * 64, "split_sha256": "b" * 64, "code_version": "c" * 64,
              "recorded_at": timestamp, "completed_at": timestamp, "split": "dev",
              "git_commit": None, "source_sha256": {"runner.py": "d" * 64},
              "python": "3.12", "platform": "test", "config": {"chunk_size": 512},
              "summary": {"recall_at_5": 0.0, "citation_accuracy": None, "p95_latency_ms": 42.0,
                          "prompt_tokens": None, "completion_tokens": None, "total_tokens": None}}
    persist_report(report, url)
    engine = create_engine(url)
    with engine.connect() as connection:
        stored = connection.execute(select(ExperimentRun.__table__)).one()
    engine.dispose()
    assert stored.recall_at_5 == 0.0 and stored.citation_accuracy is None
    assert stored.p95_latency_ms == 42.0 and stored.configuration["chunk_size"] == 512
    assert stored.configuration["source_sha256"]["runner.py"] == "d" * 64
    with pytest.raises(IntegrityError):
        persist_report(report, url)
    report["status"] = "running"
    with pytest.raises(ValueError, match="Only completed"):
        persist_report(report, url)


def review_fixture():
    generation = {"status": "answered", "answer": "First claim. [1]\n\nSecond claim. [1]",
                  "sources": [{"id": 1, "quote": "First fact."}]}
    report = {"run_id": "run-1", "status": "complete",
              "results": [{"id": "q1", "generation": generation}]}
    raw = json.dumps(report).encode()
    review = {"run_id": "run-1", "report_sha256": fingerprint(raw), "reviewer": "Test reviewer",
              "items": citation_items("q1", generation)}
    return report, review, raw


def test_same_source_is_reviewed_for_each_claim():
    report, review, raw = review_fixture()
    assert len(review["items"]) == 2
    review["items"][0]["judgment"] = "supported"
    result = score(report, review, raw)
    assert result["citation_accuracy"] is None and result["definitive_review_coverage"] == .5
    review["items"][1]["judgment"] = "unsupported"
    assert score(report, review, raw)["citation_accuracy"] == .5


@pytest.mark.parametrize("corruption", ["hash", "duplicate", "missing", "invalid_label", "source"])
def test_review_integrity(corruption):
    report, review, raw = review_fixture()
    if corruption == "hash": review["report_sha256"] = "wrong"
    if corruption == "duplicate": review["items"][1] = copy.deepcopy(review["items"][0])
    if corruption == "missing": review["items"].pop()
    if corruption == "invalid_label": review["items"][0]["judgment"] = "yes"
    if corruption == "source": review["items"][0]["source"]["quote"] = "Changed quote"
    with pytest.raises(ValueError):
        score(report, review, raw)


def test_uncited_claim_is_preserved_for_review():
    items = citation_items("q1", {"status": "answered", "answer": "No citation.", "sources": []})
    assert len(items) == 1 and items[0]["source"] is None


def test_no_generation_or_citations_is_not_perfect_accuracy():
    assert summarize([])["citation_accuracy"] is None
    report = {"run_id": "r", "status": "complete", "results": []}
    raw = json.dumps(report).encode()
    result = score(report, {"run_id": "r", "report_sha256": fingerprint(raw), "items": []}, raw)
    assert result["citation_accuracy"] is None
