import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.services.storage import document_path
from conftest import TestingSessionLocal
from scripts import cleanup_orphan_pdfs
from scripts.cleanup_orphan_pdfs import orphan_pdfs
from test_background_ingestion import accept, ingestion_client


def test_orphan_scan_keeps_tracked_and_recent_files(ingestion_client, monkeypatch):
    monkeypatch.setattr(cleanup_orphan_pdfs, "SessionLocal", TestingSessionLocal)
    _, response = accept(ingestion_client)
    tracked = document_path(uuid.UUID(response.json()["workspace_id"]), uuid.UUID(response.json()["id"]))
    old_orphan = tracked.with_name(f"{uuid.uuid4()}.pdf")
    recent_orphan = tracked.with_name(f"{uuid.uuid4()}.pdf")
    old_orphan.write_bytes(b"%PDF-orphan")
    recent_orphan.write_bytes(b"%PDF-recent")
    old_time = time.time() - 7200
    os.utime(tracked, (old_time, old_time))
    os.utime(old_orphan, (old_time, old_time))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    assert list(orphan_pdfs(settings.UPLOAD_DIR, cutoff)) == [old_orphan]
    assert tracked.exists() and recent_orphan.exists() and old_orphan.exists()


def test_orphan_scan_ignores_unmanaged_names_and_missing_root(tmp_path):
    assert list(orphan_pdfs(tmp_path / "missing", datetime.now(timezone.utc))) == []
    foreign = tmp_path / "uploads" / str(uuid.uuid4())
    foreign.mkdir(parents=True)
    (foreign / "not-a-uuid.pdf").write_bytes(b"data")
    (foreign / f"{uuid.uuid4().hex}.pdf").write_bytes(b"data")
    assert list(orphan_pdfs(foreign.parent, datetime.now(timezone.utc))) == []


def test_cleanup_command_dry_run_then_apply(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cleanup_orphan_pdfs, "SessionLocal", TestingSessionLocal)
    root = tmp_path / "uploads"
    workspace_dir = root / str(uuid.uuid4())
    workspace_dir.mkdir(parents=True)
    orphan = workspace_dir / f"{uuid.uuid4()}.pdf"
    orphan.write_bytes(b"%PDF-orphan")
    old_time = time.time() - 7200
    os.utime(orphan, (old_time, old_time))
    monkeypatch.setattr(settings, "UPLOAD_DIR", root)
    monkeypatch.setattr(sys, "argv", ["cleanup_orphan_pdfs.py"])
    cleanup_orphan_pdfs.main()
    assert "dry run only" in capsys.readouterr().out and orphan.exists()
    monkeypatch.setattr(sys, "argv", ["cleanup_orphan_pdfs.py", "--apply"])
    cleanup_orphan_pdfs.main()
    assert "1 orphan PDF(s) removed" in capsys.readouterr().out
    assert not orphan.exists()
