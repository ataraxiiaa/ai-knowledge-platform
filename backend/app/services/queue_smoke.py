"""Infrastructure probe, callable only through internal tooling (no API route)."""
import hashlib
import os
import socket
import uuid

from app.core.config import settings


def inspect_shared_file(token: str) -> dict:
    token = str(uuid.UUID(token))
    path = settings.UPLOAD_DIR / ".queue-smoke" / f"{token}.txt"
    return {"token": token, "pid": os.getpid(), "hostname": socket.gethostname(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
