"""Compare fixed character windows with real CPU embeddings, without writing a database."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from app.services.embeddings import DIMENSIONS, MODEL_NAME, embed_texts
from app.services.text import chunk_pages, clean_text, extract_pages


def similarities(queries, documents):
    q, d = np.asarray(queries), np.asarray(documents)
    return (q @ d.T) / (np.linalg.norm(q, axis=1)[:, None] * np.linalg.norm(d, axis=1)[None, :])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).resolve().parents[1] / "experiments/corpus.json")
    parser.add_argument("--pdf", type=Path, help="Optional PDF instead of the corpus pages; provide matching queries/evidence in --corpus")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "experiments/results.json")
    parser.add_argument("--overlap", type=int, default=64)
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    pages = extract_pages(args.pdf) if args.pdf else [(item["page"], clean_text(item["text"])) for item in corpus["pages"]]
    queries = corpus["queries"]
    for item in queries:
        if not any(item["evidence"] in text for _, text in pages):
            raise ValueError(f"Evidence is missing from corpus: {item['evidence']}")
    start = perf_counter()
    query_vectors = embed_texts([item["query"] for item in queries])
    warmup_seconds = perf_counter() - start
    word_vectors = embed_texts(["dog", "puppy", "screwdriver"])
    word_scores = similarities(word_vectors, word_vectors)
    runs = []
    for size in (256, 512, 1024):
        chunks = chunk_pages(pages, size, args.overlap)
        started = perf_counter()
        vectors = embed_texts([chunk.content for chunk in chunks])
        embed_seconds = perf_counter() - started
        started = perf_counter()
        scores = similarities(query_vectors, vectors)
        ranks = np.argsort(-scores, axis=1)
        search_ms = (perf_counter() - started) * 1000
        details = []
        reciprocal_ranks = []
        for item, order, row in zip(queries, ranks, scores, strict=True):
            relevant = [int(index) for index in order if item["evidence"] in chunks[int(index)].content]
            first_rank = next((rank for rank, index in enumerate(order, 1) if int(index) in relevant), None)
            reciprocal_ranks.append(1 / first_rank if first_rank else 0)
            details.append({
                "query": item["query"], "evidence": item["evidence"], "first_evidence_rank": first_rank,
                "top_3": [{"page": chunks[int(index)].page, "chunk_index": int(index), "score": float(row[index]), "content": chunks[int(index)].content} for index in order[:3]],
            })
        runs.append({
            "chunk_size": size, "chunk_unit": "characters", "overlap": args.overlap,
            "chunk_count": len(chunks), "embedded_characters": sum(len(c.content) for c in chunks),
            "vector_payload_bytes_float32": len(chunks) * DIMENSIONS * 4,
            "embedding_seconds_warm": embed_seconds, "exact_search_ms_all_queries": search_ms,
            "mean_reciprocal_rank": sum(reciprocal_ranks) / len(queries),
            **{f"hit_at_{k}": sum(item["first_evidence_rank"] is not None and item["first_evidence_rank"] <= k for item in details) / len(queries) for k in (1, 3, 5)},
            "queries": details,
        })
    result = {
        "recorded_at": datetime.now(timezone.utc).isoformat(), "model": MODEL_NAME,
        "execution_provider": "CPUExecutionProvider", "platform": platform.platform(),
        "python": platform.python_version(), "corpus_sha256": hashlib.sha256(json.dumps(pages).encode()).hexdigest(),
        "source_characters": sum(len(text) for _, text in pages), "query_count": len(queries),
        "initial_model_load_and_query_embedding_seconds": warmup_seconds,
        "word_cosines": {"dog_puppy": float(word_scores[0, 1]), "dog_screwdriver": float(word_scores[0, 2])},
        "limitations": "Small authored English corpus; one run; in-memory exact cosine, not database latency. Evidence must fit entirely inside one chunk. These are smoke measurements, not production quality estimates.",
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for run in runs:
        print(f"{run['chunk_size']} chars: {run['chunk_count']} chunks, {run['embedding_seconds_warm']:.3f}s embedding, hit@3={run['hit_at_3']:.3f}, MRR={run['mean_reciprocal_rank']:.3f}")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
