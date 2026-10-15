from pathlib import Path
import shutil
import uuid

from fastapi import HTTPException, UploadFile

from app.core.config import settings


def document_path(workspace_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    return settings.UPLOAD_DIR.resolve() / str(workspace_id) / f"{document_id}.pdf"


def store_pdf(upload: UploadFile, workspace_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    if not (upload.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Only PDF files are supported.")
    path = document_path(workspace_id, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as destination:
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
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def delete_document_file(workspace_id: uuid.UUID, document_id: uuid.UUID) -> None:
    document_path(workspace_id, document_id).unlink(missing_ok=True)


def delete_workspace_files(workspace_id: uuid.UUID) -> None:
    # Both path components are controlled by the server; filenames never select paths.
    root = settings.UPLOAD_DIR.resolve()
    target = root / str(workspace_id)
    if target.exists() and target.parent == root:
        shutil.rmtree(target)
