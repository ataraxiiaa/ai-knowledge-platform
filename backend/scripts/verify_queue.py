"""Enqueue a unique probe and verify separate-worker execution and shared storage."""
import hashlib
import os
from pathlib import Path
import socket
import sys
import time
import uuid
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.services.queue import ingestion_queue
from app.services.queue_smoke import inspect_shared_file


def main() -> None:
    token = str(uuid.uuid4())
    path = settings.UPLOAD_DIR / ".queue-smoke" / f"{token}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"queue infrastructure probe {token}".encode()
    path.write_bytes(payload)
    job = None
    try:
        job = ingestion_queue().enqueue(inspect_shared_file, token, job_timeout=30,
                                        result_ttl=300, failure_ttl=300)
        print(f"Enqueued {job.id}; producer={socket.gethostname()}:{os.getpid()}", flush=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                status = job.get_status()
            except (RedisConnectionError, RedisTimeoutError):
                time.sleep(.25)
                continue
            if status == "failed":
                raise RuntimeError("Probe failed; inspect worker logs")
            if status == "finished":
                result = job.return_value(refresh=True)
                assert result["token"] == token
                assert result["sha256"] == hashlib.sha256(payload).hexdigest()
                assert (result["hostname"], result["pid"]) != (socket.gethostname(), os.getpid())
                print(f"PASS: JSON job, separate worker {result['hostname']}:{result['pid']}, shared file verified")
                return
            time.sleep(.25)
        raise TimeoutError("No completed probe within 60 seconds; check Redis and worker health")
    finally:
        path.unlink(missing_ok=True)
        if job is not None:
            try:
                if job.get_status() in ("finished", "failed", "queued"):
                    job.delete()
            except (RedisConnectionError, RedisTimeoutError):
                print("Redis unavailable during probe cleanup; inspect the reported job ID.", file=sys.stderr)


if __name__ == "__main__":
    main()
