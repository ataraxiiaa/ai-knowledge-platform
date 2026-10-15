"""End-to-end smoke test. PHASE3_TEST_DATABASE_URL must target an EMPTY disposable database."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
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
