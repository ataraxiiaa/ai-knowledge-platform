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
    total_latencies = sorted(row.get("total_ms", row["retrieval_ms"]) for row in rows)
    usages = [row.get("token_usage") for row in generated]
    complete_usage = bool(usages) and all(
        usage is not None and usage.get("prompt_tokens") is not None
        and usage.get("completion_tokens") is not None for usage in usages
    )
    def mean(values):
        return statistics.mean(values) if values else None
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
        "p95_latency_ms": total_latencies[max(0, math.ceil(len(total_latencies) * .95) - 1)] if total_latencies else None,
        "prompt_tokens": sum(usage["prompt_tokens"] for usage in usages) if complete_usage else None,
        "completion_tokens": sum(usage["completion_tokens"] for usage in usages) if complete_usage else None,
        "total_tokens": sum(usage["prompt_tokens"] + usage["completion_tokens"]
                            for usage in usages) if complete_usage else None,
        "token_usage_coverage": sum(usage is not None and usage.get("prompt_tokens") is not None
                                    and usage.get("completion_tokens") is not None for usage in usages),
        "generation_attempts": len(generated),
        "generation_status_counts": dict(Counter(row["generation"]["status"] for row in generated)),
        "actual_model_counts": dict(Counter(
            f"{row['generation_provider']}:{row['generation_model']}" for row in generated
            if row.get("generation_provider") and row.get("generation_model"))),
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


def persist_report(report: dict, database_url: str) -> None:
    """Insert one terminal row; never revise a prior experiment."""
    if report["status"] != "complete":
        raise ValueError("Only completed evaluation reports can be persisted")
    if len(report["results"]) != report["expected_questions"]:
        raise ValueError("Incomplete evaluation reports cannot be persisted")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.experiments import ExperimentRun

    summary = report["summary"]
    config = {**report["config"], "split": report["split"],
              "git_commit": report["git_commit"], "source_sha256": report["source_sha256"],
              "python": report["python"], "platform": report["platform"],
              "actual_model_counts": summary.get("actual_model_counts", {})}
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            session.add(ExperimentRun(
                id=uuid.UUID(report["run_id"]), dataset_id=report["dataset_id"],
                corpus_sha256=report["corpus_sha256"], split_sha256=report["split_sha256"],
                code_version=report["code_version"], configuration=config, status="completed",
                recall_at_5=summary["recall_at_5"], citation_accuracy=summary["citation_accuracy"],
                answer_quality=None, p95_latency_ms=summary["p95_latency_ms"],
                prompt_tokens=summary["prompt_tokens"], completion_tokens=summary["completion_tokens"],
                total_tokens=summary["total_tokens"],
                started_at=datetime.fromisoformat(report["recorded_at"]),
                completed_at=datetime.fromisoformat(report["completed_at"])))
            session.commit()
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "experiments/evaluation")
    parser.add_argument("--split", choices=["dev", "held_out"], default="dev")
    parser.add_argument("--strategy", choices=["vector", "bm25", "hybrid", "hybrid_reranked"], default="vector")
    parser.add_argument("--allow-held-out", action="store_true", help="Explicitly select the historical held-out split")
    parser.add_argument("--generate", action="store_true", help="Send questions and retrieved text to the configured LLM")
    parser.add_argument("--persist", action="store_true", help="Insert the completed run into the configured database")
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; existing files are never overwritten")
    args = parser.parse_args()
    if args.split == "held_out" and not args.allow_held_out:
        parser.error("Historical held-out scoring requires --allow-held-out")
    if args.persist and not os.environ.get("DATABASE_URL"):
        parser.error("--persist requires an explicit DATABASE_URL environment variable and applied migrations")
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

    if args.generate and not (settings.CHAT_MODEL or settings.LLM_MODEL).strip():
        parser.error("--generate requires CHAT_MODEL or LLM_MODEL and a reachable provider")
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
                    ROOT / "app/services/reranking.py", ROOT / "app/services/hybrid.py",
                    ROOT / "app/services/model_gateway.py", ROOT / "app/core/config.py",
                    ROOT / "scripts/validate_evaluation_dataset.py", ROOT / "uv.lock"]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    source_sha256 = {str(p.relative_to(ROOT)): fingerprint(p.read_bytes()) for p in source_files}
    report = {
        "run_id": str(uuid.uuid4()), "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "strategy": args.strategy if args.strategy in ("hybrid", "hybrid_reranked") else f"{args.strategy}_only", "split": args.split,
        "dataset_id": manifest["dataset_id"], "expected_questions": len(examples),
        "corpus_sha256": fingerprint(corpus_bytes), "split_sha256": fingerprint(split_bytes),
        "git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "source_sha256": source_sha256,
        "code_version": fingerprint(json.dumps(source_sha256, sort_keys=True).encode()),
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
                   "chat_provider": (settings.CHAT_PROVIDER or "openai_compatible") if args.generate else None,
                   "chat_model": (settings.CHAT_MODEL or settings.LLM_MODEL) if args.generate else None,
                   "fallback_provider": settings.MODEL_FALLBACK_PROVIDER if args.generate else None,
                   "fallback_model": settings.MODEL_FALLBACK_MODEL if args.generate else None,
                   "token_limit_field": settings.OPENAI_TOKEN_LIMIT_FIELD if args.generate else None,
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
        question_started = started = perf_counter()
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
            row["token_usage"] = None
            row["generation_provider"] = None
            row["generation_model"] = None
            def record_completion(completion):
                row["generation_provider"] = completion.provider
                row["generation_model"] = completion.model
                if completion.usage is not None:
                    row["token_usage"] = {"prompt_tokens": completion.usage.input_tokens,
                                          "completion_tokens": completion.usage.output_tokens}
            try:
                answer = generate_answer(example["question"], ranking[:5], on_completion=record_completion)
                row["generation"] = answer.model_dump(mode="json")
            except GenerationError as exc:
                row["generation"] = {"status": "error", "error": str(exc)}
            row["generation_ms"] = (perf_counter() - started) * 1000
            if not ranking and row["generation"]["status"] == "insufficient_evidence":
                row["token_usage"] = {"prompt_tokens": 0, "completion_tokens": 0}
        row["total_ms"] = (perf_counter() - question_started) * 1000
        report["results"].append(row)
        report["summary"] = summarize(report["results"])
        write_report(args.output, report)
        print(f"{example['id']}: recall@5={row['retrieval']['recall_at_5'] if row['retrieval'] else 'n/a'}"
              + (f", generation={row['generation']['status']}" if args.generate else ""), flush=True)
    report["status"] = "complete"
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_report(args.output, report)
    if args.generate:
        review = {"run_id": report["run_id"], "report_sha256": fingerprint(args.output.read_bytes()),
                  "reviewer": "", "items": [item for row in report["results"]
                    for item in citation_items(row["id"], row["generation"])]}
        write_report(review_path, review)
    if args.persist:
        persist_report(report, settings.DATABASE_URL)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
