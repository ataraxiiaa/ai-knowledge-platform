"""Disposable PostgreSQL/Redis probe for killed workers and duplicate delivery."""
from datetime import timedelta
import multiprocessing
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.environ.get("PHASE6_TEST_MODE") != "1":
    raise SystemExit("Use only the disposable docker-compose.ingestion-test.yml project")

from fastapi.testclient import TestClient
from rq import Worker
from rq.serializers import JSONSerializer
from sqlalchemy import func, select

from app.dispatcher import dispatch_once, recover_expired_leases
from app.db.session import SessionLocal
from app.main import app
from app.models.chunks import Chunk
from app.models.documents import Document, IngestionDispatch
from app.services import ingestion
from app.services.queue import ingestion_queue, redis_connection
from scripts.verify_background import pdf


def vectors(texts):
    return [[1.0] + [0.0] * 383 for _ in texts]


def processing_child(document_id, dispatch_id, entered, release):
    def hold(texts):
        entered.set()
        release.wait(180)
        return vectors(texts)
    ingestion.embed_texts = hold
    ingestion.process_document(document_id, dispatch_id)


def rq_child():
    ingestion.embed_texts = vectors
    connection = redis_connection()
    worker = Worker([ingestion_queue(connection)], connection=connection,
                    serializer=JSONSerializer, name=f"recovery-probe-{os.getpid()}")
    worker.work(burst=True)


def wait_for(event, label):
    if not event.wait(60):
        raise AssertionError(f"Timed out waiting for {label}")


def main():
    connection = redis_connection()
    connection.ping()
    context = multiprocessing.get_context("spawn")
    with TestClient(app) as client:
        credentials = {"email": f"recovery-{uuid.uuid4()}@example.com", "password": "test-password-123"}
        assert client.post("/auth/register", json=credentials).status_code == 201
        token = client.post("/auth/login", json=credentials).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        workspace = client.post("/workspaces", headers=headers, json={"name": "Recovery probe"}).json()["id"]
        response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                               files={"file": ("probe.pdf", pdf())})
        assert response.status_code == 202, response.text
        document_id = response.json()["id"]
        with SessionLocal() as db:
            dispatch_id = str(db.scalar(select(IngestionDispatch.id).where(
                IngestionDispatch.document_id == uuid.UUID(document_id))))

        entered, release = context.Event(), context.Event()
        killed = context.Process(target=processing_child, args=(document_id, dispatch_id, entered, release))
        killed.start()
        try:
            wait_for(entered, "embedding stage")
            with SessionLocal() as db:
                record = db.get(Document, uuid.UUID(document_id))
                assert record.status == "embedding" and record.attempt_count == 1
                old_token = record.lease_token
            killed.terminate()
            killed.join(15)
            assert not killed.is_alive()
        finally:
            if killed.is_alive():
                killed.kill()
                killed.join()

        with SessionLocal() as db:
            record = db.get(Document, uuid.UUID(document_id))
            record.lease_expires_at = ingestion.now() - timedelta(seconds=1)
            db.commit()
        assert recover_expired_leases() == 1
        assert not ingestion.touch(uuid.UUID(document_id), old_token)
        with SessionLocal() as db:
            record = db.get(Document, uuid.UUID(document_id))
            dispatch = db.scalar(select(IngestionDispatch).where(IngestionDispatch.document_id == record.id))
            assert record.status == "retrying" and record.attempt_count == 1
            assert dispatch is not None
            record.next_retry_at = ingestion.now() - timedelta(seconds=1)
            dispatch.due_at = record.next_retry_at
            db.commit()
        assert dispatch_once() == 1
        # Duplicate delivery may run in either worker; only one can claim.
        ingestion_queue().enqueue("app.services.ingestion.process_document", document_id, dispatch_id,
                                  result_ttl=300, failure_ttl=86400, ttl=120)
        workers = [context.Process(target=rq_child) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(90)
            assert worker.exitcode == 0, f"RQ worker exited {worker.exitcode}"
        with SessionLocal() as db:
            record = db.get(Document, uuid.UUID(document_id))
            count = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == record.id))
            assert record.status == "ready" and record.attempt_count == 2 and count > 0
            assert db.scalar(select(IngestionDispatch.id).where(IngestionDispatch.document_id == record.id)) is None
        print("PASS: killed worker fenced; expired lease recovered; two RQ workers handled duplicate delivery once", flush=True)

        # Deleting while a second worker computes must not resurrect the document.
        response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                               files={"file": ("delete.pdf", pdf())})
        assert response.status_code == 202
        deleted_id = response.json()["id"]
        with SessionLocal() as db:
            deleted_dispatch = str(db.scalar(select(IngestionDispatch.id).where(
                IngestionDispatch.document_id == uuid.UUID(deleted_id))))
        entered, release = context.Event(), context.Event()
        deleting = context.Process(target=processing_child,
                                   args=(deleted_id, deleted_dispatch, entered, release))
        deleting.start()
        try:
            wait_for(entered, "deletion-stage embedding")
            assert client.delete(response.headers["location"], headers=headers).status_code == 204
            release.set()
            deleting.join(30)
            assert deleting.exitcode == 0
        finally:
            if deleting.is_alive():
                deleting.kill()
                deleting.join()
        with SessionLocal() as db:
            assert db.get(Document, uuid.UUID(deleted_id)) is None
            assert db.scalar(select(func.count()).select_from(Chunk).where(
                Chunk.document_id == uuid.UUID(deleted_id))) == 0
        print("PASS: deletion during embedding did not recreate document or chunks", flush=True)

        response = client.post(f"/workspaces/{workspace}/documents", headers=headers,
                               files={"file": ("lost-job.pdf", pdf())})
        assert response.status_code == 202
        lost_id = uuid.UUID(response.json()["id"])
        assert dispatch_once() == 1
        assert ingestion_queue().count == 1
        ingestion_queue().empty()
        with SessionLocal() as db:
            dispatch = db.scalar(select(IngestionDispatch).where(IngestionDispatch.document_id == lost_id))
            dispatch.due_at = ingestion.now() - timedelta(seconds=1)
            db.commit()
        assert dispatch_once() == 1
        replacement = context.Process(target=rq_child)
        replacement.start()
        replacement.join(90)
        assert replacement.exitcode == 0
        with SessionLocal() as db:
            record = db.get(Document, lost_id)
            assert record.status == "ready" and record.attempt_count == 1
        print("PASS: lost Redis job republished from PostgreSQL dispatch intent", flush=True)


if __name__ == "__main__":
    main()
