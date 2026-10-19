from conftest import TestingSessionLocal
from sqlalchemy import select

from app.core.config import settings
from app.models.documents import Document, IngestionDispatch
from app.models.users import User
from app.models.workspaces import Workspace
from app.services import web_local_jobs


def _queued_document(db_session):
    user = User(email="local@example.com", password_hash="test")
    workspace = Workspace(user=user, name="Local test")
    document = Document(workspace=workspace, filename="paper.pdf", status="queued")
    dispatch = IngestionDispatch(document_id=document.id)
    db_session.add_all([user, workspace, document])
    db_session.flush()
    dispatch.document_id = document.id
    db_session.add(dispatch)
    db_session.commit()
    return document.id


def test_missing_pdf_fails_queued_job_with_reupload_message(db_session, monkeypatch):
    monkeypatch.setattr(web_local_jobs, "SessionLocal", TestingSessionLocal)
    document_id = _queued_document(db_session)

    assert web_local_jobs._next_document() is None

    db_session.expire_all()
    document = db_session.get(Document, document_id)
    assert document.status == "failed"
    assert "upload it again" in document.error
    assert db_session.scalar(select(IngestionDispatch)) is None


def test_local_runner_claims_existing_pdf(db_session, monkeypatch):
    monkeypatch.setattr(web_local_jobs, "SessionLocal", TestingSessionLocal)
    document_id = _queued_document(db_session)
    document = db_session.get(Document, document_id)
    path = settings.UPLOAD_DIR / str(document.workspace_id) / f"{document_id}.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-test")

    claimed = web_local_jobs._next_document()

    assert claimed is not None and claimed[0] == str(document_id)
    db_session.expire_all()
    assert db_session.get(Document, document_id).status == "queued"
    assert db_session.scalar(select(IngestionDispatch)).publish_attempts == 1
