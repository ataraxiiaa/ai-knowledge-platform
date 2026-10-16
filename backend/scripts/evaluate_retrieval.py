"""Offline vector or BM25 evaluation; generation and held-out scoring are opt-in."""
import argparse
import copy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
from time import perf_counter
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def retrieval_metrics(example: dict, ranking: list[dict], k: int = 5,
                      corpus: list[dict] | None = None) -> dict | None:
    if not example["answerable"]:
        return None
    evidence = example["required_evidence"]

    def covered(hit):
        if hit["filename"] != example["expected_document"] or hit["page"] != example["expected_page"]:
            return set()
        return {i for i, quote in enumerate(evidence) if quote in hit["content"]}

    sets = [covered(hit) for hit in ranking]
    found = set().union(*sets[:k])
    available = set().union(*(covered(hit) for hit in corpus)) if corpus is not None else set().union(*sets)
    first = next((rank for rank, matches in enumerate(sets, 1) if matches), None)
    return {
        "recall_at_5": len(found) / len(evidence),
        "reciprocal_rank": 1 / first if first else 0.0,
        "first_evidence_rank": first,
        "complete_evidence_at_5": len(found) == len(evidence),
        "page_hit_at_5": any(hit["filename"] == example["expected_document"]
                              and hit["page"] == example["expected_page"] for hit in ranking[:k]),
        "covered_evidence_indices": sorted(found),
        "chunking_evidence_ceiling": len(available) / len(evidence),
    }


def citation_items(question_id: str, generation: dict) -> list[dict]:
    if generation.get("status") != "answered":
        return []
    sources = {source["id"]: source for source in generation["sources"]}
    items = []
    for index, paragraph in enumerate(generation["answer"].split("\n\n"), 1):
        ids = list(dict.fromkeys(int(value) for value in re.findall(r"\[(\d+)\]", paragraph)))
        # An uncited claim is a failed review unit, not silently discarded.
        for source_id in ids or [None]:
            items.append({"question_id": question_id, "claim_index": index,
                          "source_id": source_id, "claim": paragraph,
                          "source": copy.deepcopy(sources.get(source_id)), "judgment": None, "notes": ""})
    return items


def summarize(rows: list[dict]) -> dict:
    positive = [row["retrieval"] for row in rows if row["retrieval"] is not None]
    generated = [row for row in rows if row.get("generation") is not None]
    negative = [row for row in generated if not row["answerable"]]
    positive_generated = [row for row in generated if row["answerable"]]
    latencies = sorted(row["retrieval_ms"] for row in rows)
    mean = lambda values: statistics.mean(values) if values else None
    return {
        "rerank_status_counts": dict(Counter(row["rerank_status"] for row in rows if "rerank_status" in row)),
        "reranking_ms_median": statistics.median([row["reranking_ms"] for row in rows if "reranking_ms" in row]) if any("reranking_ms" in row for row in rows) else None,
        "questions": len(rows), "answerable_questions": len(positive),
        "unanswerable_questions": len(rows) - len(positive),
        "recall_at_5": mean([row["recall_at_5"] for row in positive]),
        "mrr": mean([row["reciprocal_rank"] for row in positive]),
        "complete_evidence_at_5": mean([int(row["complete_evidence_at_5"]) for row in positive]),
        "page_hit_at_5": mean([int(row["page_hit_at_5"]) for row in positive]),
        "chunking_evidence_ceiling": mean([row["chunking_evidence_ceiling"] for row in positive]),
        "retrieval_ms_median": statistics.median(latencies) if latencies else None,
        "retrieval_ms_p95": latencies[max(0, math.ceil(len(latencies) * .95) - 1)] if latencies else None,
        "generation_attempts": len(generated),
        "generation_status_counts": dict(Counter(row["generation"]["status"] for row in generated)),
        # Errors remain in denominators; they are never counted as abstentions.
        "unanswerable_abstention_rate": mean([int(row["generation"]["status"] == "insufficient_evidence") for row in negative]),
        "answerable_abstention_rate": mean([int(row["generation"]["status"] == "insufficient_evidence") for row in positive_generated]),
        "citation_accuracy": None,
        "citation_accuracy_status": "requires manual claim-support review" if generated else "generation not run",
    }


def write_report(output: Path, report: dict) -> None:
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "experiments/evaluation")
    parser.add_argument("--split", choices=["dev", "held_out"], default="dev")
    parser.add_argument("--strategy", choices=["vector", "bm25", "hybrid", "hybrid_reranked"], default="vector")
    parser.add_argument("--allow-held-out", action="store_true", help="Explicitly unlock the final comparison split")
    parser.add_argument("--generate", action="store_true", help="Send questions and retrieved text to the configured LLM")
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; existing files are never overwritten")
    args = parser.parse_args()
    if args.split == "held_out" and not args.allow_held_out:
        parser.error("Held-out scoring requires --allow-held-out; reserve it for the final fixed comparison")
    review_path = args.output.with_suffix(".citations.json")
    if args.output.exists() or (args.generate and review_path.exists()):
        parser.error("Output already exists; choose a new output path")

    from scripts.validate_evaluation_dataset import validate
    validate(args.dataset)  # Structural checks only; no held-out scoring.
    manifest = json.loads((args.dataset / "manifest.json").read_text(encoding="utf-8"))
    corpus_bytes = (args.dataset / manifest["corpus_file"]).read_bytes()
    split_bytes = (args.dataset / manifest["splits"][args.split]["file"]).read_bytes()
    corpus, examples = json.loads(corpus_bytes), json.loads(split_bytes)

    # No database is imported or used. A test-only key lets the offline tool run
    # without a deployed application's authentication configuration.
    os.environ.setdefault("SECRET_KEY", "offline-evaluation-only-0123456789abcdef")
    import numpy as np
    from app.core.config import settings
    from app.schemas.documents import SearchResult
    from app.services.embeddings import DIMENSIONS, MODEL_NAME, embed_texts
    from app.services.generation import GenerationError, SYSTEM_PROMPT, generate_answer
    from app.services.text import chunk_pages, clean_text
    from app.services.bm25 import BM25Index, K1, B, TOKENIZER_VERSION
    from app.services.hybrid import reciprocal_rank_fusion

    if args.generate and not settings.LLM_MODEL.strip():
        parser.error("--generate requires LLM_MODEL and a reachable configured LLM_BASE_URL")
    chunk_size, overlap = settings.CHUNK_SIZE, settings.CHUNK_OVERLAP
    passages = []
    for document in corpus["documents"]:
        document_id = uuid.uuid5(uuid.NAMESPACE_URL, document["document"])
        chunks = chunk_pages([(p["page"], clean_text(p["text"])) for p in document["pages"]], chunk_size, overlap)
        for chunk in chunks:
            chunk_id = uuid.uuid5(document_id, f"{chunk_size}:{overlap}:{chunk.page}:{chunk.start}")
            passages.append(SearchResult(chunk_id=chunk_id, document_id=document_id,
                filename=document["document"], page=chunk.page, chunk_index=chunk.chunk_index,
                content=chunk.content, similarity=0.0,
                metadata={"start_char": chunk.start, "end_char": chunk.end}))
    started = perf_counter()
    if args.strategy in ("vector", "hybrid", "hybrid_reranked"):
        vectors = np.asarray(embed_texts([p.content for p in passages]), dtype=np.float64)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    if args.strategy in ("bm25", "hybrid", "hybrid_reranked"):
        bm25 = BM25Index([p.content for p in passages])
    from app.services.reranking import MODEL_NAME as RERANK_MODEL, score_passages, rerank_passages
    warm_started = perf_counter()
    if args.strategy == "hybrid_reranked":
        score_passages("warmup", ["A short passage."])
    reranker_warmup_seconds = perf_counter() - warm_started
    index_seconds = perf_counter() - started
    source_files = [Path(__file__), ROOT / "app/services/embeddings.py", ROOT / "app/services/text.py",
                    ROOT / "app/services/generation.py", ROOT / "app/services/bm25.py",
                    ROOT / "app/services/reranking.py", ROOT / "app/services/hybrid.py", ROOT / "uv.lock"]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    report = {
        "run_id": str(uuid.uuid4()), "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "strategy": args.strategy if args.strategy in ("hybrid", "hybrid_reranked") else f"{args.strategy}_only", "split": args.split,
        "corpus_sha256": fingerprint(corpus_bytes), "split_sha256": fingerprint(split_bytes),
        "git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "source_sha256": {str(p.relative_to(ROOT)): fingerprint(p.read_bytes()) for p in source_files},
        "python": platform.python_version(), "platform": platform.platform(),
        "reranker_warmup_seconds": reranker_warmup_seconds,
        "config": {"reranker": {"model": RERANK_MODEL, "candidates": settings.RERANK_CANDIDATES, "threads": settings.RERANK_THREADS, "batch_size": 8, "max_pair_tokens": 512} if args.strategy == "hybrid_reranked" else None,
                   "embedding_model": MODEL_NAME if args.strategy != "bm25" else None,
                   "dimensions": DIMENSIONS if args.strategy != "bm25" else None,
                   "bm25": {"k1": K1, "b": B, "tokenizer": TOKENIZER_VERSION,
                            "zero_score_policy": "exclude"} if args.strategy != "vector" else None,
                   "hybrid": {"candidates_per_branch": settings.HYBRID_CANDIDATES,
                              "rrf_k": settings.HYBRID_RRF_K, "weights": "equal"} if args.strategy in ("hybrid", "hybrid_reranked") else None,
                   "chunk_size": chunk_size, "chunk_overlap": overlap, "top_k": 5,
                   "chunk_count": len(passages), "tie_break": "deterministic fixture chunk UUID",
                   "llm_model": settings.LLM_MODEL if args.generate else None,
                   "llm_timeout_seconds": settings.LLM_TIMEOUT_SECONDS if args.generate else None,
                   "prompt_sha256": fingerprint(SYSTEM_PROMPT.encode()) if args.generate else None},
        "index_build_seconds_including_model_load": index_seconds,
        "limitations": ["Synthetic single-document corpus; question-level split.",
                        "In-memory ranking; not PostgreSQL/API latency. UUIDs are fixture IDs.",
                        "Recall uses complete evidence strings within individual chunks.",
                        "MRR uses the returned ranking; hybrid is limited to the fused candidate union.",
                        "LLM results are nondeterministic; source hashes identify this implementation."],
        "results": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, report)
    all_passages = [p.model_dump(mode="json") for p in passages]
    for example in examples:
        started = perf_counter()
        dense, lexical = [], []
        if args.strategy in ("vector", "hybrid", "hybrid_reranked"):
            query = np.asarray(embed_texts([example["question"]])[0], dtype=np.float64)
            query /= np.linalg.norm(query)
            scores = vectors @ query
            order = sorted(range(len(passages)), key=lambda i: (-float(scores[i]), passages[i].chunk_id.int))
            dense = [passages[i].model_copy(update={"similarity": float(scores[i])}) for i in order]
        if args.strategy in ("bm25", "hybrid", "hybrid_reranked"):
            scores = bm25.scores(example["question"])
            candidates = [i for i, score in enumerate(scores) if score > 0]
            order = sorted(candidates, key=lambda i: (-float(scores[i]), passages[i].chunk_id.int))
            lexical = [passages[i].model_copy(update={"similarity": None, "bm25_score": float(scores[i]),
                                                    "retrieval_method": "bm25"}) for i in order]
        if args.strategy in ("hybrid", "hybrid_reranked"):
            dense, lexical = dense[:settings.HYBRID_CANDIDATES], lexical[:settings.HYBRID_CANDIDATES]
            ranking = reciprocal_rank_fusion(dense, lexical, settings.HYBRID_RRF_K)
        else:
            ranking = dense if args.strategy == "vector" else lexical
        pre_rerank = ranking
        rerank_started = perf_counter()
        if args.strategy == "hybrid_reranked":
            ranking = rerank_passages(example["question"], ranking)
        reranking_ms = (perf_counter() - rerank_started) * 1000
        elapsed = (perf_counter() - started) * 1000
        serialized = [p.model_dump(mode="json") for p in ranking]
        row = {"id": example["id"], "question": example["question"], "answerable": example["answerable"],
               "expected_document": example["expected_document"], "expected_page": example["expected_page"],
               "expected_answer": example["expected_answer"], "required_evidence": example["required_evidence"],
               "retrieval_ms": elapsed, "retrieval": retrieval_metrics(example, serialized, corpus=all_passages),
               "ranking": serialized, "generation": None}
        if args.strategy in ("hybrid", "hybrid_reranked"):
            row["candidate_rankings"] = {"vector": [p.model_dump(mode="json") for p in dense],
                                         "bm25": [p.model_dump(mode="json") for p in lexical]}
        if args.strategy == "hybrid_reranked":
            row["pre_rerank_ranking"] = [p.model_dump(mode="json") for p in pre_rerank[:settings.RERANK_CANDIDATES]]
            row["reranking_ms"] = reranking_ms
            row["rerank_status"] = ranking[0].rerank_status if ranking else "empty"
        if args.generate:
            started = perf_counter()
            try:
                answer = generate_answer(example["question"], ranking[:5])
                row["generation"] = answer.model_dump(mode="json")
            except GenerationError as exc:
                row["generation"] = {"status": "error", "error": str(exc)}
            row["generation_ms"] = (perf_counter() - started) * 1000
        report["results"].append(row)
        report["summary"] = summarize(report["results"])
        write_report(args.output, report)
        print(f"{example['id']}: recall@5={row['retrieval']['recall_at_5'] if row['retrieval'] else 'n/a'}"
              + (f", generation={row['generation']['status']}" if args.generate else ""), flush=True)
    report["status"] = "complete"
    write_report(args.output, report)
    if args.generate:
        review = {"run_id": report["run_id"], "report_sha256": fingerprint(args.output.read_bytes()),
                  "reviewer": "", "items": [item for row in report["results"]
                    for item in citation_items(row["id"], row["generation"])]}
        write_report(review_path, review)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
