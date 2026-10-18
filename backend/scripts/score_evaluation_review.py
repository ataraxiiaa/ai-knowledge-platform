"""Create and score append-only answer-quality and citation reviews."""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_retrieval import citation_items, fingerprint
from scripts.score_citation_review import score as score_citations

RUBRIC_VERSION = "answer_quality_v1"


def quality_items(report: dict) -> list[dict]:
    items = []
    for row in report["results"]:
        generation = row.get("generation")
        if generation is None:
            continue
        status = generation["status"]
        if status == "answered" and row["answerable"]:
            score, basis = None, "review"
        elif status == "insufficient_evidence" and not row["answerable"]:
            score, basis = 4, "deterministic_status"
        else:
            score, basis = 0, "deterministic_status"
        items.append({"question_id": row["id"], "question": row["question"],
                      "answerable": row["answerable"],
                      "expected_answer": row.get("expected_answer"),
                      "generation": generation, "basis": basis,
                      "score": score, "notes": ""})
    return items


def template(report: dict, report_bytes: bytes) -> dict:
    if json.loads(report_bytes) != report or report["status"] != "complete":
        raise ValueError("Only exact completed reports can be reviewed")
    return {"run_id": report["run_id"], "report_sha256": fingerprint(report_bytes),
            "reviewer": "", "reviewer_type": "human", "rubric_version": RUBRIC_VERSION,
            "items": [item for row in report["results"] if row.get("generation")
                      for item in citation_items(row["id"], row["generation"])],
            "quality_items": quality_items(report)}


def score_review(report: dict, review: dict, report_bytes: bytes) -> dict:
    citation = score_citations(report, review, report_bytes)
    if review.get("rubric_version") != RUBRIC_VERSION:
        raise ValueError("Unknown answer-quality rubric")
    if review.get("reviewer_type") not in ("human", "agent"):
        raise ValueError("Reviewer type must be human or agent")
    expected = quality_items(report)
    actual = review.get("quality_items")
    if not isinstance(actual, list) or len(actual) != len(expected):
        raise ValueError("Missing or extra answer-quality review units")
    scored = 0
    total_score = 0
    for item, original in zip(actual, expected, strict=True):
        if not isinstance(item, dict) or {k: v for k, v in item.items() if k not in ("score", "notes")} != {
                k: v for k, v in original.items() if k not in ("score", "notes")}:
            raise ValueError("Answer-quality identity was altered, duplicated, or reordered")
        value = item.get("score")
        if value is not None and (type(value) is not int or value < 0 or value > 4):
            raise ValueError("Answer-quality score must be an integer from 0 to 4 or null")
        if original["basis"] == "deterministic_status" and value != original["score"]:
            raise ValueError("Deterministic status score cannot be changed")
        if value is not None:
            scored += 1
            total_score += value
    if scored and not str(review.get("reviewer", "")).strip():
        raise ValueError("Identify the reviewer when recording judgments")
    return {"run_id": report["run_id"], "report_sha256": fingerprint(report_bytes),
            "reviewer": review.get("reviewer", ""), "reviewer_type": review["reviewer_type"],
            "rubric_version": RUBRIC_VERSION,
            "citation_accuracy": citation["citation_accuracy"],
            "citation_review_coverage": citation["definitive_review_coverage"],
            "answer_quality": total_score / (4 * len(expected)) if expected and scored == len(expected) else None,
            "quality_review_coverage": scored / len(expected) if expected else None,
            "quality_units": len(expected), "quality_scored": scored}


def persist_review(result: dict, review: dict, database_url: str) -> str:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.experiments import ExperimentReview, ExperimentRun

    run_id = uuid.UUID(result["run_id"])
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            if session.get(ExperimentRun, run_id) is None:
                raise ValueError("Persist the matching experiment run before its review")
            record = ExperimentReview(
                run_id=run_id, report_sha256=result["report_sha256"],
                rubric_version=result["rubric_version"], reviewer=result["reviewer"],
                reviewer_type=result["reviewer_type"],
                citation_accuracy=result["citation_accuracy"], answer_quality=result["answer_quality"],
                citation_review_coverage=result["citation_review_coverage"],
                quality_review_coverage=result["quality_review_coverage"], review_payload=review)
            session.add(record)
            session.commit()
            return str(record.id)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create-template", type=Path)
    action.add_argument("--review", type=Path)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()
    if args.persist and not args.review:
        parser.error("--persist requires --review")
    raw = args.report.read_bytes()
    report = json.loads(raw)
    if args.create_template:
        with args.create_template.open("x", encoding="utf-8") as handle:
            json.dump(template(report, raw), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return
    review = json.loads(args.review.read_text(encoding="utf-8"))
    result = score_review(report, review, raw)
    if args.persist:
        if not os.environ.get("DATABASE_URL"):
            parser.error("--persist requires an explicit DATABASE_URL")
        result["review_id"] = persist_review(result, review, os.environ["DATABASE_URL"])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
