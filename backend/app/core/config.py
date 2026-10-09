from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = (BACKEND_DIR / "app.db").as_posix()


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Knowledge Platform"
    DATABASE_URL: str = f"sqlite:///{DEFAULT_SQLITE_PATH}"
    SECRET_KEY: str = "development-secret-key-change-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,*"

    @property
    def cors_origins_list(self) -> list[str]:
        val = self.CORS_ORIGINS.strip()
        if not val or val == "*":
            return ["*"]
        if val.startswith("[") and val.endswith("]"):
            import json
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        return [i.strip() for i in val.split(",") if i.strip()]

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_database_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
