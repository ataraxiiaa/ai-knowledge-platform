"""Check frozen retrieval regression reports against the reviewed CI baseline."""
import argparse
import json
import math
from pathlib import Path


def check_report(report: dict, baseline: dict, strategy: str) -> dict:
    expected_strategy = {"vector": "vector_only", "bm25": "bm25_only",
                         "hybrid": "hybrid"}[strategy]
    expected = {"status": "complete", "strategy": expected_strategy,
                "split": baseline["split"], "dataset_id": baseline["dataset_id"],
                "corpus_sha256": baseline["corpus_sha256"],
                "split_sha256": baseline["split_sha256"],
                "expected_questions": baseline["expected_questions"]}
    failures = [f"{key}: expected {value!r}, got {report.get(key)!r}"
                for key, value in expected.items() if report.get(key) != value]
    if len(report.get("results", [])) != baseline["expected_questions"]:
        failures.append("Question results are incomplete")
    config = report.get("config", {})
    for key in ("chunk_size", "chunk_overlap"):
        if config.get(key) != baseline[key]:
            failures.append(f"{key}: expected {baseline[key]}, got {config.get(key)}")
    if any(row.get("generation") is not None for row in report.get("results", [])):
        failures.append("CI retrieval gate must not run generation")
    recall = report.get("summary", {}).get("recall_at_5")
    threshold = baseline["minimum_recall_at_5"][strategy]
    if (not isinstance(recall, (int, float)) or isinstance(recall, bool)
            or not math.isfinite(recall) or recall < threshold):
        failures.append(f"Recall@5 {recall!r} is below {threshold}")
    return {"strategy": strategy, "recall_at_5": recall, "minimum": threshold,
            "passed": not failures, "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True,
                        help="Directory containing vector.json, bm25.json, hybrid.json")
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    results = []
    for strategy in ("vector", "bm25", "hybrid"):
        path = args.reports / f"{strategy}.json"
        if not path.is_file():
            results.append({"strategy": strategy, "passed": False,
                            "failures": [f"Missing report: {path}"]})
            continue
        results.append(check_report(json.loads(path.read_text(encoding="utf-8")), baseline, strategy))
    print(json.dumps(results, indent=2))
    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
