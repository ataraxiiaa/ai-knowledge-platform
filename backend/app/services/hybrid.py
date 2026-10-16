"""Equal-weight reciprocal rank fusion; raw retrieval scores are not added."""
from app.schemas.documents import SearchResult


def reciprocal_rank_fusion(dense: list[SearchResult], lexical: list[SearchResult],
                           rank_constant: int = 60) -> list[SearchResult]:
    if rank_constant < 1:
        raise ValueError("RRF rank constant must be positive")
    results = {}
    for method, hits in (("vector", dense), ("bm25", lexical)):
        seen = set()
        for hit in hits:
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            rank = len(seen)
            if hit.chunk_id not in results:
                results[hit.chunk_id] = hit.model_copy(update={
                    "retrieval_method": "hybrid", "similarity": None, "bm25_score": None,
                    "fusion_score": 0.0, "vector_rank": None, "bm25_rank": None})
            result = results[hit.chunk_id]
            result.fusion_score += 1 / (rank_constant + rank)
            if method == "vector":
                result.vector_rank = rank
                result.similarity = hit.similarity
            else:
                result.bm25_rank = rank
                result.bm25_score = hit.bm25_score
    return sorted(results.values(), key=lambda hit: (-hit.fusion_score, hit.chunk_id.int))
