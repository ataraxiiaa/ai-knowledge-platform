"""Score a completed manual review without mistaking quote provenance for support."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_retrieval import citation_items, fingerprint


def score(report: dict, review: dict, report_bytes: bytes) -> dict:
    if json.loads(report_bytes) != report:
        raise ValueError("Report content differs from fingerprinted bytes")
    if report["status"] != "complete":
        raise ValueError("Only completed runs can be reviewed")
    if review["run_id"] != report["run_id"] or review["report_sha256"] != fingerprint(report_bytes):
        raise ValueError("Review does not match this exact report")
    expected = [item for row in report["results"] if row.get("generation")
                for item in citation_items(row["id"], row["generation"])]
    if len(review["items"]) != len(expected):
        raise ValueError("Missing or extra review units")
    counts = {"supported": 0, "unsupported": 0, "uncertain": 0, "pending": 0}
    for actual, original in zip(review["items"], expected, strict=True):
        if {k: v for k, v in actual.items() if k not in ("judgment", "notes")} != {
                k: v for k, v in original.items() if k not in ("judgment", "notes")}:
            raise ValueError("Review claim/source was altered, duplicated, or reordered")
        judgment = actual.get("judgment")
        if judgment not in (None, "supported", "unsupported", "uncertain"):
            raise ValueError("Judgment must be supported, unsupported, uncertain, or null")
        if judgment == "supported" and actual["source"] is None:
            raise ValueError("An uncited claim cannot be marked supported")
        counts[judgment or "pending"] += 1
    total = len(expected)
    definitive = counts["supported"] + counts["unsupported"]
    if definitive and not review.get("reviewer", "").strip():
        raise ValueError("Identify the reviewer when recording judgments")
    return {"reviewer": review.get("reviewer", ""), "units": total, "counts": counts,
            "definitive_review_coverage": definitive / total if total else None,
            "citation_accuracy": counts["supported"] / total if total and definitive == total else None,
            "partial_supported_fraction": counts["supported"] / definitive if definitive else None,
            "note": "Claim-citation support precision; incomplete/uncertain reviews have no final accuracy. "
                    "Abstentions and generation errors are reported separately, not treated as correct citations."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    print(json.dumps(score(json.loads(raw), json.loads(args.review.read_text(encoding="utf-8")), raw), indent=2))
