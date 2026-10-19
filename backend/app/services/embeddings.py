"""Provider-specific 384-dimensional embeddings; local CPU or Cloudflare."""
import math
from functools import lru_cache
from threading import Lock

import httpx

from app.core.config import settings
from app.services.text import IngestionError

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CLOUDFLARE_MODEL = "@cf/baai/bge-small-en-v1.5"
DIMENSIONS = 384
MAX_TOKENS = 512
_lock = Lock()


class EmbeddingServiceError(IngestionError):
    """Remote provider refused or returned an unusable embedding result."""


def embedding_model_id() -> str:
    return (f"cloudflare:{CLOUDFLARE_MODEL}:mean"
            if settings.EMBEDDING_PROVIDER == "cloudflare" else MODEL_NAME)


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


def _embed_local(texts: list[str]) -> list[list[float]]:
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


def _embed_cloudflare(texts: list[str]) -> list[list[float]]:
    endpoint = (f"https://api.cloudflare.com/client/v4/accounts/"
                f"{settings.CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_MODEL}")
    vectors: list[list[float]] = []
    try:
        with httpx.Client(timeout=settings.CLOUDFLARE_EMBEDDING_TIMEOUT_SECONDS) as client:
            for start in range(0, len(texts), settings.EMBEDDING_BATCH_SIZE):
                batch = texts[start:start + settings.EMBEDDING_BATCH_SIZE]
                response = client.post(endpoint,
                    headers={"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}"},
                    json={"text": batch, "pooling": "mean"})
                if response.status_code == 429:
                    raise EmbeddingServiceError("Cloudflare embedding limit reached. Try again later.")
                if response.status_code in (401, 403):
                    raise EmbeddingServiceError("Cloudflare embedding credentials were rejected.")
                if response.status_code == 400:
                    raise IngestionError("Cloudflare rejected the text. Try a smaller chunk size.")
                if response.status_code >= 500:
                    raise ConnectionError("Cloudflare embedding service is temporarily unavailable.")
                if response.status_code != 200:
                    raise EmbeddingServiceError("Cloudflare embedding request failed.")
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise EmbeddingServiceError("Cloudflare returned an invalid embedding response.") from exc
                result = payload.get("result") if isinstance(payload, dict) else None
                data = result.get("data") if isinstance(result, dict) else None
                if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(data, list) or len(data) != len(batch):
                    raise EmbeddingServiceError("Cloudflare returned an invalid embedding response.")
                if any(not isinstance(vector, list) or len(vector) != DIMENSIONS or
                       any(not isinstance(value, (int, float)) for value in vector)
                       for vector in data):
                    raise EmbeddingServiceError("Cloudflare returned invalid embedding vectors.")
                vectors.extend(data)
    except httpx.TransportError as exc:
        raise ConnectionError("Could not reach Cloudflare embeddings.") from exc
    try:
        validate_vectors(vectors, len(texts))
    except IngestionError as exc:
        raise EmbeddingServiceError("Cloudflare returned invalid embedding vectors.") from exc
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if settings.EMBEDDING_PROVIDER == "cloudflare":
        return _embed_cloudflare(texts)
    return _embed_local(texts)


if __name__ == "__main__":
    vector = embed_texts(["Model download and CPU inference verification."])[0]
    print(f"Ready: {embedding_model_id()}, {len(vector)} dimensions")
