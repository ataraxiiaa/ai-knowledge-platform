from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select

from app.api.documents import require_vector_database
from app.core.config import settings
from app.main import app
from app.models.chunks import Chunk
from app.models.documents import Document, IngestionDispatch
from app.services import ingestion
from app.services.text import IngestionError, chunk_pages, clean_text
from app.services.embeddings import validate_vectors


def pdf_bytes(text="A puppy is a young dog. Dogs learn through positive reinforcement.", encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def owner(client, email="owner@example.com"):
    payload = {"email": email, "password": "password123"}
    assert client.post("/auth/register", json=payload).status_code == 201
    token = client.post("/auth/login", json=payload).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    workspace = client.post("/workspaces", headers=headers, json={"name": "PDF research"}).json()["id"]
    return headers, workspace


@pytest.fixture
def ingestion_client(client, monkeypatch):
    app.dependency_overrides[require_vector_database] = lambda: None
    monkeypatch.setattr(ingestion, "embed_texts", lambda texts: [[1.0] + [0.0] * 383 for _ in texts])
    from conftest import TestingSessionLocal
    monkeypatch.setattr(ingestion, "SessionLocal", TestingSessionLocal)
    yield client
    app.dependency_overrides.pop(require_vector_database, None)


def test_cleaning_and_chunk_boundaries():
    assert clean_text("  A\x00\n\t puppy\u00a0 ") == "A puppy"
    chunks = chunk_pages([(2, "abcdefghijkl"), (4, "uvwxyz")], size=6, overlap=2)
    assert [(c.page, c.content) for c in chunks] == [(2, "abcdef"), (2, "efghij"), (2, "ijkl"), (4, "uvwxyz")]
    assert [c.chunk_index for c in chunks] == [0, 1, 2, 3]
    assert [(c.start, c.end) for c in chunks] == [(0, 6), (4, 10), (8, 12), (0, 6)]
    with pytest.raises(ValueError):
        chunk_pages([(1, "text")], 64, 64)
    with pytest.raises(IngestionError):
        chunk_pages([(1, "a" * 100)], 10, 9, max_chunks=2)


def test_upload_extract_embed_list_and_delete(ingestion_client, db_session):
    headers, workspace = owner(ingestion_client)
    response = ingestion_client.post(f"/workspaces/{workspace}/documents", headers=headers,
        files={"file": ("../../lesson.pdf", pdf_bytes(), "application/pdf")},
        data={"chunk_size": "64", "chunk_overlap": "8"})
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["chunk_count"] == 0
    result = finish_job(ingestion_client, headers, response, db_session)
    assert result["status"] == "ready" and result["chunk_count"] >= 1
    assert result["filename"] == "lesson.pdf"
    assert "storage_path" not in result
    document = db_session.scalar(select(Document))
    stored = settings.UPLOAD_DIR / document.storage_path
    assert stored.exists() and stored.is_relative_to(settings.UPLOAD_DIR)
    chunk = db_session.scalar(select(Chunk))
    assert "puppy" in chunk.content and chunk.page == 1
    assert len(chunk.embedding) == 384
    assert chunk.chunk_metadata["chunk_size"] == 64
    assert ingestion_client.get(f"/workspaces/{workspace}/documents", headers=headers).json()[0]["id"] == result["id"]
    assert ingestion_client.delete(f"/workspaces/{workspace}/documents/{result['id']}", headers=headers).status_code == 204
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert not stored.exists()


@pytest.mark.parametrize("data, expected", [(pdf_bytes(""), "No extractable text"), (pdf_bytes(encrypted=True), "Encrypted"), (b"%PDF-1.7\nbroken", "Could not read")])
def test_unreadable_pdf_records_failure(ingestion_client, db_session, data, expected):
    headers, workspace = owner(ingestion_client)
    response = ingestion_client.post(f"/workspaces/{workspace}/documents", headers=headers, files={"file": ("input.pdf", data)})
    assert response.status_code == 202
    result = finish_job(ingestion_client, headers, response, db_session)
    assert result["status"] == "failed"
    assert expected in result["error"]
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0


def test_embedding_failure_does_not_leave_chunks(ingestion_client, monkeypatch, db_session):
    headers, workspace = owner(ingestion_client)
    def fail(texts):
        raise RuntimeError("private internal path or provider details")
    monkeypatch.setattr(ingestion, "embed_texts", fail)
    response = ingestion_client.post(f"/workspaces/{workspace}/documents", headers=headers, files={"file": ("input.pdf", pdf_bytes())})
    result = finish_job(ingestion_client, headers, response, db_session)
    assert result["status"] == "failed"
    assert "private" not in result["error"]
    assert result["chunk_count"] == 0


def test_chunk_commit_failure_rolls_back_all_chunks(ingestion_client, monkeypatch, db_session):
    headers, workspace = owner(ingestion_client)
    from sqlalchemy.orm import Session
    commit = Session.commit
    def fail_once_ready(self):
        if any(isinstance(item, Chunk) for item in self.new):
            self.flush()
            raise RuntimeError("simulated commit failure")
        commit(self)
    monkeypatch.setattr(Session, "commit", fail_once_ready)
    response = ingestion_client.post(f"/workspaces/{workspace}/documents", headers=headers, files={"file": ("input.pdf", pdf_bytes())})
    result = finish_job(ingestion_client, headers, response, db_session)
    assert result["status"] == "failed"
    assert result["chunk_count"] == 0


def test_upload_size_type_and_overlap_validation(ingestion_client, monkeypatch, db_session):
    headers, workspace = owner(ingestion_client)
    url = f"/workspaces/{workspace}/documents"
    assert ingestion_client.post(url, headers=headers, files={"file": ("bad.pdf", b"not a PDF")}).status_code == 415
    assert ingestion_client.post(url, headers=headers, files={"file": ("empty.pdf", b"")}).status_code == 400
    assert ingestion_client.post(url, headers=headers, files={"file": ("file.txt", pdf_bytes())}).status_code == 415
    assert ingestion_client.post(url, headers=headers, files={"file": ("input.pdf", pdf_bytes())}, data={"chunk_size": 64, "chunk_overlap": 64}).status_code == 422
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 10)
    assert ingestion_client.post(url, headers=headers, files={"file": ("big.pdf", pdf_bytes())}).status_code == 413
    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert not list(settings.UPLOAD_DIR.rglob("*.pdf"))


def test_document_ownership_and_workspace_cleanup(ingestion_client, db_session):
    headers, workspace = owner(ingestion_client)
    other_headers, _ = owner(ingestion_client, "other@example.com")
    url = f"/workspaces/{workspace}/documents"
    assert ingestion_client.post(url, headers=other_headers, files={"file": ("input.pdf", pdf_bytes())}).status_code == 404
    assert ingestion_client.post(url, files={"file": ("input.pdf", pdf_bytes())}).status_code == 401
    document_id = ingestion_client.post(url, headers=headers, files={"file": ("input.pdf", pdf_bytes())}).json()["id"]
    assert ingestion_client.get(url, headers=other_headers).status_code == 404
    assert ingestion_client.get(f"{url}/{document_id}", headers=other_headers).status_code == 404
    assert ingestion_client.delete(f"{url}/{document_id}", headers=other_headers).status_code == 404
    assert ingestion_client.post(f"/workspaces/{workspace}/search", headers=other_headers, json={"query": "puppy"}).status_code == 404
    assert ingestion_client.delete(f"/workspaces/{workspace}", headers=headers).status_code == 204
    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert not list(settings.UPLOAD_DIR.rglob("*.pdf"))


def test_sqlite_ingestion_is_explicitly_unavailable(client):
    headers, workspace = owner(client)
    response = client.post(f"/workspaces/{workspace}/documents", headers=headers, files={"file": ("input.pdf", pdf_bytes())})
    assert response.status_code == 503
    assert "PostgreSQL" in response.json()["detail"]


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[0.0] * 384], [[float("nan")] * 384], [[float("inf")] * 384]])
def test_invalid_embedding_output_is_rejected(vectors):
    with pytest.raises(IngestionError):
        validate_vectors(vectors, expected=1)


def finish_job(client, headers, response, db):
    import uuid
    document_id = uuid.UUID(response.json()["id"])
    dispatch = db.scalar(select(IngestionDispatch).where(IngestionDispatch.document_id == document_id))
    dispatch_id = str(dispatch.id)
    db.commit()
    ingestion.process_document(str(document_id), dispatch_id)
    db.expire_all()
    return client.get(response.headers["location"], headers=headers).json()
