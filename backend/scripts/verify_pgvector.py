"""End-to-end smoke test. PHASE3_TEST_DATABASE_URL must target an EMPTY disposable database."""
import os
import argparse
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--rerank", action="store_true", help="Verify the installed cross-encoder without fallback")
parser.add_argument("--chat", action="store_true", help="Also call the configured LLM with synthetic PDF text and validate citations")
args = parser.parse_args()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

url = os.environ["PHASE3_TEST_DATABASE_URL"]
os.environ["DATABASE_URL"] = url
os.environ["SECRET_KEY"] = "pgvector-integration-test-only-0123456789abcdef"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

from sqlalchemy import create_engine, inspect, text

engine = create_engine(url)
if engine.dialect.name != "postgresql" or inspect(engine).get_table_names():
    raise SystemExit("Refusing verification: use an empty, disposable PostgreSQL database.")

# This intentionally runs both migration upgrades on actual PostgreSQL.
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=ROOT, check=True)

from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app
from test_ingestion import pdf_bytes, owner
from app.services.embeddings import embed_texts
from app.services.text import IngestionError

try:
    embed_texts(["dog " * 600])
except IngestionError:
    pass
else:
    raise AssertionError("Oversized inputs must be rejected, not silently truncated")

(ROOT / ".cache").mkdir(exist_ok=True)

with TemporaryDirectory(prefix="pgvector-upload-", dir=ROOT / ".cache") as storage:
    settings.UPLOAD_DIR = Path(storage)
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        headers, workspace = owner(client)
        other_headers, other_workspace = owner(client, "other@example.com")
        payload = pdf_bytes("A puppy is a young dog. Puppies learn with positive rewards. A canine companion needs patient training.")
        response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
            files={"file": ("dogs.pdf", payload)}, data={"chunk_size": 64, "chunk_overlap": 8})
        assert response.status_code == 201, response.text
        document = response.json()
        assert document["status"] == "ready", document
        assert document["chunk_count"] > 1
        result = client.post(f"/workspaces/{workspace}/search", headers=headers, json={"query": "young canine", "top_k": 1})
        assert result.status_code == 200, result.text
        hits = result.json()
        assert len(hits) == 1 and "puppy" in hits[0]["content"].lower(), hits
        assert hits[0]["page"] == 1 and -1 <= hits[0]["similarity"] <= 1
        assert client.post(f"/workspaces/{workspace}/search", headers=other_headers, json={"query": "dog"}).status_code == 404
        assert client.post(f"/workspaces/{other_workspace}/search", headers=other_headers, json={"query": "dog"}).json() == []
        lexical = client.post(f"/workspaces/{workspace}/search", headers=headers,
                              json={"query": "puppy", "top_k": 1, "method": "bm25"})
        assert lexical.status_code == 200, lexical.text
        lexical_hits = lexical.json()
        assert len(lexical_hits) == 1 and "puppy" in lexical_hits[0]["content"].lower()
        assert lexical_hits[0]["document_id"] == document["id"] and lexical_hits[0]["page"] == 1
        assert lexical_hits[0]["bm25_score"] > 0 and lexical_hits[0]["similarity"] is None
        assert lexical_hits[0]["retrieval_method"] == "bm25"
        assert client.post(f"/workspaces/{workspace}/search", headers=headers,
                           json={"query": "zzznomatch987", "method": "bm25"}).json() == []
        assert client.post(f"/workspaces/{workspace}/search", headers=other_headers,
                           json={"query": "puppy", "method": "bm25"}).status_code == 404
        assert client.post(f"/workspaces/{other_workspace}/search", headers=other_headers,
                           json={"query": "puppy", "method": "bm25"}).json() == []
        print("PASS: BM25 PostgreSQL chunk loading, keyword ranking, source metadata, no-match and tenant isolation")
        fused = client.post(f"/workspaces/{workspace}/search", headers=headers,
                            json={"query": "puppy", "method": "hybrid", "top_k": 5})
        assert fused.status_code == 200, fused.text
        fused_hits = fused.json()
        assert fused_hits and len({hit["chunk_id"] for hit in fused_hits}) == len(fused_hits)
        for hit in fused_hits:
            assert hit["document_id"] == document["id"] and hit["page"] == 1
            assert hit["retrieval_method"] == "hybrid" and hit["fusion_score"] > 0
            expected = sum(1 / (settings.HYBRID_RRF_K + hit[field])
                           for field in ("vector_rank", "bm25_rank") if hit[field] is not None)
            assert abs(hit["fusion_score"] - expected) < 1e-12
        assert client.post(f"/workspaces/{workspace}/search", headers=other_headers,
                           json={"query": "puppy", "method": "hybrid"}).status_code == 404
        assert client.post(f"/workspaces/{other_workspace}/search", headers=other_headers,
                           json={"query": "puppy", "method": "hybrid"}).json() == []
        print("PASS: hybrid rank fusion, deduplication, source identity and tenant isolation")
        if args.rerank:
            reranked = client.post(f"/workspaces/{workspace}/search", headers=headers,
                                   json={"query": "puppy", "method": "hybrid_reranked", "top_k": 5})
            assert reranked.status_code == 200, reranked.text
            reranked_hits = reranked.json()
            assert reranked_hits and all(hit["rerank_status"] == "applied" for hit in reranked_hits)
            assert all(hit["document_id"] == document["id"] and hit["page"] == 1 for hit in reranked_hits)
            assert [hit["rerank_score"] for hit in reranked_hits] == sorted(
                [hit["rerank_score"] for hit in reranked_hits], reverse=True)
            assert client.post(f"/workspaces/{workspace}/search", headers=other_headers,
                               json={"query": "puppy", "method": "hybrid_reranked"}).status_code == 404
            assert client.post(f"/workspaces/{other_workspace}/search", headers=other_headers,
                               json={"query": "puppy", "method": "hybrid_reranked"}).json() == []
            print("PASS: real cross-encoder ranking, source preservation and tenant isolation; no fallback")
        if args.chat:
            answer = client.post(f"/workspaces/{workspace}/chat", headers=headers,
                                json={"message": "What is a puppy?"})
            assert answer.status_code == 200, answer.text
            data = answer.json()
            assert data["status"] == "answered" and data["sources"], data
            context = {hit["chunk_id"]: hit for hit in data["retrieved_chunks"]}
            assert all(hit["retrieval_method"] == settings.RAG_RETRIEVAL_METHOD for hit in context.values())
            for source in data["sources"]:
                assert source["document_id"] == document["id"] and source["page"] == 1
                assert source["document"] == "dogs.pdf"
                assert source["quote"] in context[source["chunk_id"]]["content"]
                assert f"[{source['id']}]" in data["answer"]
            assert client.post(f"/workspaces/{workspace}/chat", headers=other_headers,
                               json={"message": "What is a puppy?"}).status_code == 404
            empty = client.post(f"/workspaces/{other_workspace}/chat", headers=other_headers,
                                json={"message": "What is a puppy?"}).json()
            assert empty["status"] == "insufficient_evidence" and empty["sources"] == []
            print("PASS: real retrieval -> configured LLM -> validated document/page evidence; chat tenant isolation")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT vector_dims(embedding) FROM chunks LIMIT 1")) == 384
            rows = connection.execute(text("SELECT embedding <=> embedding FROM chunks")).scalars().all()
            assert all(abs(value) < 1e-6 for value in rows)
        assert client.delete(f"/workspaces/{workspace}", headers=headers).status_code == 204
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM chunks")) == 0
        assert not list(Path(storage).rglob("*.pdf"))
        client.delete(f"/workspaces/{other_workspace}", headers=other_headers)
        print(f"PASS: real PDF -> CPU embeddings -> vector(384) -> cosine retrieval; tenant isolation; cascade/file cleanup. Top cosine: {hits[0]['similarity']:.4f}")
engine.dispose()
