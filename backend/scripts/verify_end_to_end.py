"""Disposable real-embedding queue-to-cited-chat probe with failure injection."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.environ.get("PHASE6_TEST_MODE") != "1":
    raise SystemExit("Use only the disposable docker-compose.ingestion-test.yml project")

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models.chunks import Chunk
from app.models.documents import Document
from scripts.verify_background import pdf

QUOTE = "A puppy is a young dog."


class CitationProvider(BaseHTTPRequestHandler):
    invalid_evidence = False

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        size = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(size))
        context = json.loads(request["messages"][1]["content"])
        assert context["question"] == "What is a puppy?"
        assert QUOTE in context["passages"][0]["text"]
        quote = "Fabricated quotation" if self.invalid_evidence else QUOTE
        claims = {"claims": [{"text": QUOTE, "evidence": [{"source_id": 1, "quote": quote}]}]}
        response = json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(claims)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


def wait_for_document(client, location, headers, terminal, seconds=180):
    deadline = time.monotonic() + seconds
    seen = []
    while time.monotonic() < deadline:
        response = client.get(location, headers=headers)
        assert response.status_code == 200, response.text
        document = response.json()
        seen.append(document["status"])
        if document["status"] in ("ready", "failed"):
            assert document["status"] == terminal, (document, seen)
            return document, seen
        time.sleep(.25)
    raise TimeoutError(f"Document did not reach {terminal}: {seen}")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), CitationProvider)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.LLM_BASE_URL = f"http://127.0.0.1:{server.server_port}/v1"
    settings.LLM_MODEL = "disposable-citation-provider"
    settings.RAG_RETRIEVAL_METHOD = "vector"
    try:
        with TestClient(app) as client:
            credentials = {"email": f"e2e-{uuid.uuid4()}@example.com", "password": "test-password-123"}
            assert client.post("/auth/register", json=credentials).status_code == 201
            token = client.post("/auth/login", json=credentials).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            workspace = client.post("/workspaces", headers=headers,
                                    json={"name": "Disposable end-to-end test"}).json()["id"]

            started = time.monotonic()
            response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                                   files={"file": ("puppy.pdf", pdf())})
            accepted = time.monotonic()
            assert response.status_code == 202 and response.json()["status"] == "queued", response.text
            document, stages = wait_for_document(client, response.headers["location"], headers, "ready")
            indexed = time.monotonic()
            assert document["attempt_count"] == 1 and document["chunk_count"] > 0
            with SessionLocal() as db:
                dimensions = db.scalar(select(func.vector_dims(Chunk.embedding)).where(
                    Chunk.document_id == uuid.UUID(document["id"])).limit(1))
                assert dimensions == 384
            search = client.post(f"/workspaces/{workspace}/search", headers=headers,
                                 json={"query": "What is a puppy?", "method": "vector"})
            assert search.status_code == 200, search.text
            assert search.json()[0]["document_id"] == document["id"]
            assert search.json()[0]["page"] == 1 and QUOTE in search.json()[0]["content"]
            answer = client.post(f"/workspaces/{workspace}/chat", headers=headers,
                                 json={"message": "What is a puppy?"})
            assert answer.status_code == 200, answer.text
            chat = answer.json()
            assert chat["status"] == "answered" and chat["answer"].endswith("[1]"), chat
            assert len(chat["sources"]) == 1
            source = chat["sources"][0]
            assert source["document"] == "puppy.pdf" and source["page"] == 1
            assert source["document_id"] == document["id"] and source["quote"] == QUOTE
            assert any(hit["chunk_id"] == source["chunk_id"] and QUOTE in hit["content"]
                       for hit in chat["retrieved_chunks"])
            print("METRICS_JSON: " + json.dumps({
                "upload_acceptance_seconds": round(accepted - started, 3),
                "time_to_index_seconds": round(indexed - started, 3),
                "observed_stages": sorted(set(stages)),
            }), flush=True)
            print("PASS: real PDF -> RQ worker -> real embedding -> pgvector -> vector search -> cited chat", flush=True)

            CitationProvider.invalid_evidence = True
            invalid = client.post(f"/workspaces/{workspace}/chat", headers=headers,
                                  json={"message": "What is a puppy?"})
            assert invalid.status_code == 502 and "evidence" in invalid.json()["detail"].lower()
            CitationProvider.invalid_evidence = False
            print("PASS: fabricated provider evidence rejected by chat endpoint", flush=True)

            bad = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                              files={"file": ("broken.pdf", b"%PDF-1.7\nnot a valid PDF")})
            assert bad.status_code == 202, bad.text
            failed, _ = wait_for_document(client, bad.headers["location"], headers, "failed")
            assert failed["attempt_count"] == 1 and failed["chunk_count"] == 0
            print("PASS: malformed PDF fails without retries or partial chunks", flush=True)

            assert client.delete(f"/workspaces/{workspace}", headers=headers).status_code == 204
            with SessionLocal() as db:
                assert db.scalar(select(func.count()).select_from(Document).where(
                    Document.workspace_id == uuid.UUID(workspace))) == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
