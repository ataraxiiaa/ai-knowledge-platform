"""Validate annotations and provenance only; does not run retrieval or an LLM."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    raw = (root / manifest["corpus_file"]).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == manifest["corpus_sha256"], "Corpus fingerprint changed")
    corpus = json.loads(raw)
    pages = {}
    for document in corpus["documents"]:
        for page in document["pages"]:
            key = (document["document"], page["page"])
            require(key not in pages, f"Duplicate document/page: {key}")
            require(type(page["page"]) is int and page["page"] > 0, "Invalid page number")
            require(isinstance(page["text"], str) and bool(page["text"].strip()), "Empty page")
            pages[key] = page["text"]
    source = json.loads((root / manifest["source"]).read_text(encoding="utf-8"))
    require(corpus["documents"][0]["pages"] == source["pages"], "Snapshot differs from source corpus")
    ids, questions, evidence_splits = set(), set(), {}
    totals, by_page, by_category = Counter(), Counter(), Counter()
    for split, spec in manifest["splits"].items():
        examples = json.loads((root / spec["file"]).read_text(encoding="utf-8"))
        require(len(examples) == spec["count"], f"Wrong {split} example count")
        for item in examples:
            label = item["id"]
            require(label not in ids, f"Duplicate ID: {label}")
            ids.add(label)
            require(item["split"] == split, f"{label}: split mismatch")
            require(isinstance(item["question"], str) and 0 < len(item["question"].strip()) <= 1024,
                    f"{label}: invalid question")
            normalized = " ".join(item["question"].lower().split())
            require(normalized not in questions, f"{label}: duplicate question")
            questions.add(normalized)
            require(isinstance(item["expected_answer"], str) and bool(item["expected_answer"].strip()),
                    f"{label}: missing expected answer")
            require(type(item["answerable"]) is bool, f"{label}: answerable must be boolean")
            require(isinstance(item["required_evidence"], list), f"{label}: evidence must be a list")
            by_category[item["category"]] += 1
            totals[split] += 1
            if item["answerable"]:
                totals["answerable"] += 1
                key = (item["expected_document"], item["expected_page"])
                require(type(item["expected_page"]) is int and key in pages, f"{label}: unknown source")
                require(bool(item["required_evidence"]), f"{label}: missing evidence")
                require(len(set(item["required_evidence"])) == len(item["required_evidence"]),
                        f"{label}: duplicate evidence")
                by_page[str(key[1])] += 1
                for quote in item["required_evidence"]:
                    require(isinstance(quote, str) and bool(quote.strip()) and quote in pages[key],
                            f"{label}: evidence missing from expected page")
                    evidence_key = (*key, quote)
                    require(evidence_splits.get(evidence_key, split) == split,
                            f"{label}: identical evidence shared across splits")
                    evidence_splits[evidence_key] = split
            else:
                totals["unanswerable"] += 1
                require(item["expected_document"] is None and item["expected_page"] is None
                        and item["required_evidence"] == [], f"{label}: unanswerable has a positive target")
                require(bool(item.get("unanswerable_reason", "").strip()), f"{label}: missing rationale")
    require(30 <= len(ids) <= 50, "Starter dataset must have 30–50 examples")
    require(totals["answerable"] == manifest["answerable_count"], "Answerable count mismatch")
    require(totals["unanswerable"] == manifest["unanswerable_count"], "Unanswerable count mismatch")
    return {"status": "passed", "examples": len(ids), "counts": dict(totals),
            "answerable_by_page": dict(by_page), "categories": dict(by_category),
            "corpus_sha256": manifest["corpus_sha256"],
            "note": "Structural and exact-source validation only; no retrieval scores or semantic grading."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path,
                        default=Path(__file__).resolve().parents[1] / "experiments/evaluation")
    args = parser.parse_args()
    print(json.dumps(validate(args.dataset), indent=2))
