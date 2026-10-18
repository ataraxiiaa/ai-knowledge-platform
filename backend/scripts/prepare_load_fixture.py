"""Seed a disposable API with two indexed papers for the Phase 15 load test."""
import argparse
import json
import os
import time
import uuid
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


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


def seed(base_url: str, timeout: float = 240) -> dict:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        credentials = {"email": f"load-{uuid.uuid4()}@example.com", "password": f"Load-{uuid.uuid4()}"}
        response = client.post("/auth/register", json=credentials)
        response.raise_for_status()
        response = client.post("/auth/login", json=credentials)
        response.raise_for_status()
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post("/workspaces", headers=headers, json={"name": "Phase 15 disposable load fixture"})
        response.raise_for_status()
        workspace_id = response.json()["id"]
        documents = []
        for name, content in (("cache.pdf", "KV cache compression reduces memory used by attention state."),
                              ("weights.pdf", "Weight quantization reduces memory used by model parameters.")):
            response = client.post(f"/workspaces/{workspace_id}/documents", headers=headers,
                                   files={"file": (name, pdf(content), "application/pdf")})
            response.raise_for_status()
            location = response.headers["location"]
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                result = client.get(location, headers=headers)
                result.raise_for_status()
                document = result.json()
                if document["status"] == "ready":
                    documents.append(document["id"])
                    break
                if document["status"] == "failed":
                    raise RuntimeError(f"Fixture indexing failed: {document['error']}")
                time.sleep(.5)
            else:
                raise TimeoutError(f"Fixture indexing timed out for {name}")
        return {"base_url": base_url, "token": token, "workspace_id": workspace_id,
                "document_ids": documents}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Fixture file already exists; use a new output path")
    fixture = seed(args.base_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(fixture, handle)
    print(f"Indexed {len(fixture['document_ids'])} disposable documents in workspace {fixture['workspace_id']}")


if __name__ == "__main__":
    main()
