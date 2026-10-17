"""Load Docker secrets before importing application settings."""
import os
from pathlib import Path
import sys
from urllib.parse import quote


def configure() -> None:
    for name in ("SECRET_KEY", "DB_PASSWORD", "REDIS_PASSWORD", "AWS_ACCESS_KEY_ID",
                 "AWS_SECRET_ACCESS_KEY", "LLM_API_KEY", "GEMINI_API_KEY"):
        filename = os.environ.get(f"{name}_FILE")
        if filename:
            value = Path(filename).read_text(encoding="utf-8").strip()
            if not value and name not in ("LLM_API_KEY", "GEMINI_API_KEY"):
                raise ValueError(f"{name}_FILE is empty")
            os.environ[name] = value
    password = os.environ.pop("DB_PASSWORD", None)
    if password is not None:
        from sqlalchemy.engine import URL

        os.environ["DATABASE_URL"] = URL.create(
            "postgresql+psycopg", username=os.environ.get("DB_USER", "knowledge"),
            password=password, host=os.environ.get("DB_HOST", "db"),
            port=5432, database=os.environ.get("DB_NAME", "knowledge_platform"),
        ).render_as_string(hide_password=False)
    redis_password = os.environ.pop("REDIS_PASSWORD", None)
    if redis_password is not None:
        os.environ["REDIS_URL"] = f"redis://:{quote(redis_password, safe='')}@redis:6379/0"


if __name__ == "__main__":
    configure()
    if len(sys.argv) < 2:
        raise SystemExit("A service command is required")
    os.execvp(sys.argv[1], sys.argv[1:])
