"""One lazy-loaded CPU model per process; no remote embedding API."""
import math
from functools import lru_cache
from threading import Lock

from app.core.config import settings
from app.services.text import IngestionError

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
MAX_TOKENS = 512
_lock = Lock()


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    from tokenizers import Tokenizer

    model = TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(settings.EMBEDDING_CACHE_DIR),
        threads=settings.EMBEDDING_THREADS,
        providers=["CPUExecutionProvider"],
    )
    # Clone so validation cannot alter the inference tokenizer's padding/truncation.
    tokenizer = Tokenizer.from_str(model.model.tokenizer.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return model, tokenizer


def validate_vectors(vectors: list[list[float]], expected: int) -> None:
    if len(vectors) != expected or any(
        len(vector) != DIMENSIONS
        or not all(math.isfinite(value) for value in vector)
        or sum(value * value for value in vector) == 0
        for vector in vectors
    ):
        raise IngestionError("Embedding model returned invalid vectors. Please retry the upload.")


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    with _lock:
        model, tokenizer = _model()
        if any(len(tokenizer.encode(text).ids) > MAX_TOKENS for text in texts):
            raise IngestionError("Text exceeds the embedding model's 512-token limit. Use smaller chunks or a shorter query.")
        vectors = [vector.tolist() for vector in model.embed(
            texts, batch_size=settings.EMBEDDING_BATCH_SIZE)]
    validate_vectors(vectors, len(texts))
    return vectors


if __name__ == "__main__":
    vector = embed_texts(["Model download and CPU inference verification."])[0]
    print(f"Ready: {MODEL_NAME}, {len(vector)} dimensions, CPUExecutionProvider")
