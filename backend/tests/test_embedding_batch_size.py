from app.core.config import settings
from app.services import embeddings


def test_embedding_batch_size_can_limit_web_service_memory(monkeypatch):
    observed = []

    class Vector:
        def tolist(self):
            return [1.0] + [0.0] * 383

    class Model:
        def embed(self, texts, batch_size):
            observed.append((list(texts), batch_size))
            return [Vector() for _ in texts]

    class Tokenizer:
        def encode(self, text):
            return type("Encoding", (), {"ids": text.split()})()

    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 1)
    monkeypatch.setattr(embeddings, "_model", lambda: (Model(), Tokenizer()))

    vectors = embeddings.embed_texts(["first passage", "second passage"])

    assert len(vectors) == 2
    assert observed == [(["first passage", "second passage"], 1)]
