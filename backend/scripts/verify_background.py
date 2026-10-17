"""Disposable Compose test: --accept with no Redis/worker, then --wait after startup."""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.environ.get("PHASE6_TEST_MODE") != "1":
    raise SystemExit("Use only the disposable docker-compose.ingestion-test.yml project")

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select, func
from app.main import app
from app.models.documents import IngestionDispatch
from app.db.session import SessionLocal
from app.services.ingestion import process_document
from app.dispatcher import dispatch_once

STATE = Path("/data/background-probe.json")


def pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
        DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td (A puppy is a young dog. Puppies learn with positive rewards.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["accept", "wait"])
    args = parser.parse_args()
    with TestClient(app) as client:
        if args.mode == "accept":
            credentials = {"email": f"probe-{uuid.uuid4()}@example.com", "password": "test-password-123"}
            assert client.post("/auth/register", json=credentials).status_code == 201
            token = client.post("/auth/login", json=credentials).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            workspace = client.post("/workspaces", headers=headers, json={"name": "Disposable background test"}).json()["id"]
            started = time.monotonic()
            response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                                   files={"file": ("puppy.pdf", pdf())})
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "queued" and response.json()["chunk_count"] == 0
            print(f"PASS: upload accepted in {time.monotonic()-started:.3f}s without Redis or a worker", flush=True)
            with SessionLocal() as db:
                dispatch_id = str(db.scalar(select(IngestionDispatch.id)))
            assert dispatch_once() == 0, "Run acceptance before Redis starts"
            with SessionLocal() as db:
                assert db.scalar(select(func.count()).select_from(IngestionDispatch)) == 1
            STATE.write_text(json.dumps({"headers": headers, "workspace": workspace,
                "location": response.headers["location"], "document": response.json()["id"],
                "dispatch": dispatch_id}))
            print("PASS: queue failure retained durable dispatch intent", flush=True)
            return
        state = json.loads(STATE.read_text())
        deadline = time.monotonic() + 120
        statuses = set()
        while time.monotonic() < deadline:
            response = client.get(state["location"], headers=state["headers"])
            assert response.status_code == 200, response.text
            document = response.json()
            statuses.add(document["status"])
            if document["status"] == "failed":
                raise AssertionError(document)
            if document["status"] == "ready":
                break
            time.sleep(.5)
        else:
            raise TimeoutError(f"Not indexed in 120s: {statuses}")
        assert document["chunk_count"] > 0 and document["attempt_count"] == 1
        process_document(state["document"], state["dispatch"])
        duplicate = client.get(state["location"], headers=state["headers"]).json()
        assert duplicate["chunk_count"] == document["chunk_count"] and duplicate["attempt_count"] == 1
        result = client.post(f"/workspaces/{state['workspace']}/search", headers=state["headers"],
            json={"query": "puppy", "method": "bm25"})
        assert result.status_code == 200 and result.json()[0]["page"] == 1
        assert client.delete(f"/workspaces/{state['workspace']}", headers=state["headers"]).status_code == 204
        process_document(state["document"], state["dispatch"])
        STATE.unlink()
        print("PASS: real Redis -> worker -> PDF -> embeddings -> PostgreSQL; duplicate no-op; retrieval; deletion", flush=True)


if __name__ == "__main__":
    main()
