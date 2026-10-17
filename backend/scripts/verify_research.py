"""Disposable PDF-to-verified-report probe with real workers and embeddings."""
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.environ.get("PHASE7_TEST_MODE") != "1":
    raise SystemExit("Only run in the disposable research test project")

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from app.db.session import SessionLocal
from app.main import app
from app.models.research import ResearchDispatch, ResearchJob


def pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
        DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def wait(client, location, headers, expected, timeout=180):
    deadline = time.monotonic() + timeout
    stages = set()
    while time.monotonic() < deadline:
        response = client.get(location, headers=headers)
        assert response.status_code == 200, response.text
        value = response.json()
        stages.add(value.get("current_stage", value["status"]))
        if value["status"] in ("ready", "completed", "failed"):
            assert value["status"] == expected, value
            return value, stages
        time.sleep(.25)
    raise TimeoutError(f"Expected {expected}, observed {stages}")


def main():
    with TestClient(app) as client:
        credentials = {"email": f"research-{uuid.uuid4()}@example.com", "password": "test-password-123"}
        assert client.post("/auth/register", json=credentials).status_code == 201
        token = client.post("/auth/login", json=credentials).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        workspace = client.post("/workspaces", headers=headers,
                                json={"name": "Disposable research test"}).json()["id"]
        papers = (
            ("cache.pdf", "KV cache compression reduces memory used by attention state."),
            ("weights.pdf", "Weight quantization reduces memory used by model parameters."),
        )
        document_ids = []
        for filename, content in papers:
            response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                                   files={"file": (filename, pdf(content))})
            assert response.status_code == 202, response.text
            document, _ = wait(client, response.headers["location"], headers, "ready")
            document_ids.append(document["id"])
        started = time.monotonic()
        response = client.post(f"/workspaces/{workspace}/research-jobs", headers=headers,
            json={"query": "Compare how these papers reduce LLM inference memory usage."})
        accepted = time.monotonic()
        assert response.status_code == 202 and response.json()["status"] == "queued", response.text
        report, stages = wait(client, response.headers["location"], headers, "completed")
        finished = time.monotonic()
        assert report["current_stage"] == "COMPLETED" and report["attempt_count"] == 1
        assert report["evidence"] is None and report["result"]["gaps"] == []
        assert len(report["plan"]["questions"]) == 3
        assert len(report["result"]["sections"]) == 3
        sources = report["result"]["sources"]
        assert {source["document"] for source in sources} == {"cache.pdf", "weights.pdf"}
        assert {source["document_id"] for source in sources} == set(document_ids)
        assert all(source["page"] == 1 for source in sources)
        assert all(section["claims"][0]["citation_ids"] for section in report["result"]["sections"])
        print("METRICS_JSON: " + json.dumps({
            "research_acceptance_seconds": round(accepted - started, 3),
            "research_completion_seconds": round(finished - started, 3),
            "observed_stages": sorted(stages),
        }), flush=True)
        print("PASS: two real PDFs -> ingestion queue -> research queue -> real retrieval -> verified two-source report", flush=True)

        other = {"email": f"other-{uuid.uuid4()}@example.com", "password": "test-password-123"}
        assert client.post("/auth/register", json=other).status_code == 201
        other_token = client.post("/auth/login", json=other).json()["access_token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}
        assert client.get(response.headers["location"], headers=other_headers).status_code == 404

        invalid = client.post(f"/workspaces/{workspace}/research-jobs", headers=headers,
            json={"query": "invalid evidence test: compare memory approaches"})
        assert invalid.status_code == 202
        failed, _ = wait(client, invalid.headers["location"], headers, "failed")
        assert failed["attempt_count"] == 1 and failed["result"] is None
        assert failed["evidence"] is None
        print("PASS: fabricated research citation rejected without a report", flush=True)

        assert client.delete(f"/workspaces/{workspace}/documents/{document_ids[0]}",
                             headers=headers).status_code == 204
        retained = client.get(response.headers["location"], headers=headers).json()
        assert retained["status"] == "completed" and retained["result"] == report["result"]
        with SessionLocal() as db:
            assert db.scalar(select(ResearchDispatch.id).where(
                ResearchDispatch.job_id == uuid.UUID(report["id"]))) is None
        assert client.delete(f"/workspaces/{workspace}", headers=headers).status_code == 204
        with SessionLocal() as db:
            assert db.get(ResearchJob, uuid.UUID(report["id"])) is None
        print("PASS: tenant isolation, completed-report retention, workspace cascade", flush=True)


if __name__ == "__main__":
    main()
