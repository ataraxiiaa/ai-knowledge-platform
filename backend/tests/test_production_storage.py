import os
import uuid
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.services import storage


def test_custom_s3_endpoint_uses_path_style_for_supabase(monkeypatch):
    import boto3

    captured = {}
    monkeypatch.setattr(storage.settings, "S3_REGION", "ap-southeast-1")
    monkeypatch.setattr(storage.settings, "S3_ENDPOINT_URL",
                        "https://project.storage.supabase.co/storage/v1/s3")
    monkeypatch.setattr(boto3, "client", lambda service, **options: captured.update(
        service=service, **options))

    storage.s3_client()

    assert captured["service"] == "s3"
    assert captured["region_name"] == "ap-southeast-1"
    assert captured["endpoint_url"].endswith("/storage/v1/s3")
    assert captured["config"].s3["addressing_style"] == "path"


def test_s3_upload_download_delete_and_workspace_cleanup(monkeypatch, tmp_path):
    workspace_id, document_id = uuid.uuid4(), uuid.uuid4()
    key = storage.document_key(workspace_id, document_id)
    objects = {}

    class Client:
        def upload_fileobj(self, source, bucket, name, ExtraArgs):
            assert bucket == "pdfs"
            assert ExtraArgs["ContentType"] == "application/pdf"
            objects[name] = source.read()

        def download_file(self, bucket, name, path):
            with open(path, "wb") as destination:
                destination.write(objects[name])

        def delete_object(self, Bucket, Key):
            objects.pop(Key, None)

        def get_paginator(self, operation):
            assert operation == "list_objects_v2"
            return self

        def paginate(self, Bucket, Prefix):
            return [{"Contents": [{"Key": name} for name in objects if name.startswith(Prefix)]}]

    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage.settings, "S3_BUCKET", "pdfs")
    monkeypatch.setattr(storage, "s3_client", Client)
    upload = UploadFile(filename="paper.pdf", file=BytesIO(b"%PDF-1.7\ncontent"))
    assert storage.store_pdf(upload, workspace_id, document_id) == key
    assert objects[key] == b"%PDF-1.7\ncontent"
    with storage.open_document(workspace_id, document_id) as path:
        assert path.read_bytes() == objects[key]
        assert path.exists()
    assert not path.exists()
    storage.delete_document_file(workspace_id, document_id)
    assert not objects
    objects[key] = b"first"
    objects[f"{workspace_id}/{uuid.uuid4()}.pdf"] = b"second"
    other = f"{uuid.uuid4()}/other.pdf"
    objects[other] = b"other"
    storage.delete_workspace_files(workspace_id)
    assert objects == {other: b"other"}


def test_s3_upload_rejects_invalid_pdf_before_network(monkeypatch):
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage, "s3_client", lambda: pytest.fail("S3 should not be called"))
    upload = UploadFile(filename="paper.pdf", file=BytesIO(b"not a PDF"))
    with pytest.raises(HTTPException) as error:
        storage.store_pdf(upload, uuid.uuid4(), uuid.uuid4())
    assert error.value.status_code == 415


def test_s3_download_failure_is_retryable(monkeypatch):
    from app.services.ingestion import retryable_failure

    class Client:
        def download_file(self, *args):
            raise OSError("temporary outage")

    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage, "s3_client", Client)
    with pytest.raises(storage.StorageUnavailable) as error, storage.open_document(
            uuid.uuid4(), uuid.uuid4()):
        pass
    assert retryable_failure(error.value, "parsing")


def test_production_entrypoint_loads_secrets_and_quotes_passwords(monkeypatch, tmp_path):
    from app.production_entrypoint import configure

    for name, value in (("SECRET_KEY", "s" * 40), ("DB_PASSWORD", "db:@/word"),
                        ("REDIS_PASSWORD", "redis:@/word")):
        filename = tmp_path / name
        filename.write_text(value, encoding="utf-8")
        monkeypatch.setenv(f"{name}_FILE", str(filename))
    configure()
    from sqlalchemy.engine import make_url

    database = make_url(os.environ["DATABASE_URL"])
    assert database.password == "db:@/word"
    assert "redis%3A%40%2Fword" in os.environ["REDIS_URL"]
