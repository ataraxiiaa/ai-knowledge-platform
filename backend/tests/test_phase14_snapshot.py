import json
from pathlib import Path
from statistics import mean

DATASET = Path(__file__).resolve().parents[1] / "experiments/evaluation"


def test_phase14_snapshot_matches_frozen_dataset_and_question_scores():
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    snapshot = json.loads((DATASET / "phase14-snapshot-v1.json").read_text(encoding="utf-8"))
    assert snapshot["dataset_id"] == manifest["dataset_id"]
    assert {(run["split"], run["strategy"]) for run in snapshot["runs"]} == {
        (split, strategy) for split in ("dev", "held_out")
        for strategy in ("vector", "bm25", "hybrid", "hybrid_reranked")}
    for run in snapshot["runs"]:
        assert run["corpus_sha256"] == manifest["corpus_sha256"]
        assert run["split_sha256"] == manifest["splits"][run["split"]]["sha256"]
        questions = run["question_metrics"]
        summary = run["summary"]
        assert len(questions) == summary["questions"] == manifest["splits"][run["split"]]["count"]
        assert len({row["id"] for row in questions}) == len(questions)
        answerable = [row for row in questions if row["answerable"]]
        assert len(answerable) == summary["answerable_questions"]
        assert mean(row["recall_at_5"] for row in answerable) == summary["recall_at_5"]
        assert mean(row["reciprocal_rank"] for row in answerable) == summary["mrr"]
        assert run["config"]["chunk_size"] == 1024
        assert run["config"]["chunk_overlap"] == 64
        assert summary["generation_attempts"] == 0
        assert summary["citation_accuracy"] is None
        assert summary["total_tokens"] is None
