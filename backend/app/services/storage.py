import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings


class StorageUnavailable(Exception):
    """Object storage is temporarily inaccessible."""


def document_key(workspace_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"{workspace_id}/{document_id}.pdf"


def s3_client():
    import boto3
    from botocore.config import Config

    options = {"region_name": settings.S3_REGION}
    if settings.S3_ENDPOINT_URL:
        options["endpoint_url"] = settings.S3_ENDPOINT_URL
        # Supabase Storage (and other custom S3 endpoints) require the bucket
        # in the URL path rather than as a subdomain of the endpoint host.
        options["config"] = Config(s3={"addressing_style": "path"})
    return boto3.client("s3", **options)


def document_path(workspace_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    return settings.UPLOAD_DIR.resolve() / str(workspace_id) / f"{document_id}.pdf"


def store_pdf(upload: UploadFile, workspace_id: uuid.UUID, document_id: uuid.UUID) -> str:
    if not (upload.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Only PDF files are supported.")
    key = document_key(workspace_id, document_id)
    path = document_path(workspace_id, document_id)
    if settings.STORAGE_BACKEND == "local":
        path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
              if settings.STORAGE_BACKEND == "s3" else path.open("xb")) as destination:
            total = 0
            while data := upload.file.read(64 * 1024):
                if total == 0 and not data.startswith(b"%PDF-"):
                    raise HTTPException(415, "The file does not have a valid PDF header.")
                total += len(data)
                if total > settings.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"PDF exceeds the {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.")
                destination.write(data)
            if total == 0:
                raise HTTPException(400, "The uploaded file is empty.")
            if settings.STORAGE_BACKEND == "s3":
                destination.seek(0)
                s3_client().upload_fileobj(destination, settings.S3_BUCKET, key,
                                           ExtraArgs={"ContentType": "application/pdf"})
    except Exception:
        if settings.STORAGE_BACKEND == "local":
            path.unlink(missing_ok=True)
        raise
    return key


@contextmanager
def open_document(workspace_id: uuid.UUID, document_id: uuid.UUID):
    if settings.STORAGE_BACKEND == "local":
        yield document_path(workspace_id, document_id)
        return
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "document.pdf"
        try:
            s3_client().download_file(settings.S3_BUCKET, document_key(workspace_id, document_id), str(path))
        except Exception as exc:
            raise StorageUnavailable("Could not download PDF from object storage") from exc
        yield path


def delete_document_file(workspace_id: uuid.UUID, document_id: uuid.UUID) -> None:
    if settings.STORAGE_BACKEND == "s3":
        s3_client().delete_object(Bucket=settings.S3_BUCKET, Key=document_key(workspace_id, document_id))
    else:
        document_path(workspace_id, document_id).unlink(missing_ok=True)


def delete_workspace_files(workspace_id: uuid.UUID) -> None:
    if settings.STORAGE_BACKEND == "s3":
        client = s3_client()
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=settings.S3_BUCKET, Prefix=f"{workspace_id}/"
        ):
            for item in page.get("Contents", []):
                client.delete_object(Bucket=settings.S3_BUCKET, Key=item["Key"])
        return
    # Both path components are controlled by the server; filenames never select paths.
    root = settings.UPLOAD_DIR.resolve()
    target = root / str(workspace_id)
    if target.exists() and target.parent == root:
        shutil.rmtree(target)
