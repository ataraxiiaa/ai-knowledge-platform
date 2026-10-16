import copy
import json

import pytest

from scripts.evaluate_retrieval import citation_items, fingerprint, retrieval_metrics, summarize
from scripts.score_citation_review import score


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
