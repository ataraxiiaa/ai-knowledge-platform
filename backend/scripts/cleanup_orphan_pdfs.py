"""List orphan uploads; pass --apply to remove files at least one hour old."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import uuid

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.documents import Document  # noqa: E402


def orphan_pdfs(root: Path, cutoff: datetime):
    """Yield only old server-named PDFs without a matching document row."""
    if not root.exists():
        return
    root = root.resolve()
    with SessionLocal() as db:
        for workspace_dir in root.iterdir():
            if workspace_dir.is_symlink() or not workspace_dir.is_dir():
                continue
            try:
                workspace_id = uuid.UUID(workspace_dir.name)
            except ValueError:
                continue
            if str(workspace_id) != workspace_dir.name:
                continue
            for path in workspace_dir.iterdir():
                if path.is_symlink() or not path.is_file() or path.suffix != ".pdf":
                    continue
                try:
                    document_id = uuid.UUID(path.stem)
                    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                except (ValueError, OSError):
                    continue
                if str(document_id) != path.stem:
                    continue
                if modified > cutoff:
                    continue
                if db.scalar(select(Document.id).where(
                    Document.id == document_id, Document.workspace_id == workspace_id,
                )) is None:
                    yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Remove listed files")
    parser.add_argument("--min-age-hours", type=float, default=1.0)
    args = parser.parse_args()
    if args.min_age_hours < 1:
        parser.error("--min-age-hours must be at least 1")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.min_age_hours)
    count = 0
    for path in orphan_pdfs(settings.UPLOAD_DIR, cutoff):
        if args.apply:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
        print(f"{'removed' if args.apply else 'would remove'}: {path}")
        count += 1
    print(f"{count} orphan PDF(s) {'removed' if args.apply else 'found; dry run only'}")


if __name__ == "__main__":
    main()
