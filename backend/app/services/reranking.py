"""CPU cross-encoder scoring with explicit, source-preserving hybrid fallback."""
from functools import lru_cache
import logging
import math
from threading import Lock
from time import perf_counter

from app.core.config import settings
from app.schemas.documents import SearchResult
from app.services import observability

MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"
MAX_TOKENS = 512
_lock = Lock()
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model():
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    from tokenizers import Tokenizer

    model = TextCrossEncoder(model_name=MODEL_NAME, cache_dir=str(settings.RERANK_CACHE_DIR),
                            threads=settings.RERANK_THREADS, providers=["CPUExecutionProvider"])
    tokenizer = Tokenizer.from_str(model.model.tokenizer.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return model, tokenizer


def score_passages(query: str, documents: list[str]) -> list[float]:
    if not documents:
        return []
    with _lock:
        model, tokenizer = _model()
        if any(len(tokenizer.encode(query, text).ids) > MAX_TOKENS for text in documents):
            raise ValueError("Query and passage exceed the 512-token pair limit")
        return [float(score) for score in model.rerank(query, documents, batch_size=8)]


def rerank_passages(query: str, candidates: list[SearchResult]) -> list[SearchResult]:
    """Rerank a bounded hybrid shortlist; never silently return partial scores."""
    candidates = candidates[:settings.RERANK_CANDIDATES]
    if not candidates:
        return []
    started = perf_counter()
    with observability.span("rag.reranking", {"rag.reranking.candidates": len(candidates)}) as span:
        return _rerank_observed(query, candidates, started, span)


def _rerank_observed(query, candidates, started, span):
    try:
        scores = score_passages(query, [hit.content for hit in candidates])
        if len(scores) != len(candidates) or not all(math.isfinite(score) for score in scores):
            raise ValueError("Invalid reranker scores")
    except Exception as exc:
        # Do not log query, source text, or exception messages containing credentials.
        logger.warning("Reranking unavailable (%s); using hybrid order", type(exc).__name__)
        observability.record_reranking(perf_counter() - started, len(candidates), outcome="fallback")
        if span is not None:
            span.set_attribute("outcome", "fallback")
        return [hit.model_copy(update={"retrieval_method": "hybrid", "rerank_score": None,
                                       "rerank_status": "fallback"}) for hit in candidates]
    ranked = [hit.model_copy(update={"retrieval_method": "hybrid_reranked",
                                    "rerank_score": score, "rerank_status": "applied"})
              for hit, score in zip(candidates, scores)]
    observability.record_reranking(perf_counter() - started, len(candidates), outcome="success")
    if span is not None:
        span.set_attribute("outcome", "success")
    return sorted(ranked, key=lambda hit: (-hit.rerank_score, hit.chunk_id.int))


if __name__ == "__main__":
    scores = score_passages("What is a puppy?", ["A puppy is a young dog."])
    if len(scores) != 1 or not math.isfinite(scores[0]):
        raise RuntimeError("Invalid warmup result")
    print(f"Ready: {MODEL_NAME}, CPUExecutionProvider")
