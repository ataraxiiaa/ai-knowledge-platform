import json
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = (BACKEND_DIR / "app.db").as_posix()


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Knowledge Platform"
    DATABASE_URL: str = f"sqlite:///{DEFAULT_SQLITE_PATH}"
    SECRET_KEY: str = Field(min_length=32, repr=False)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24, gt=0)
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    UPLOAD_DIR: Path = BACKEND_DIR / "storage"
    EMBEDDING_CACHE_DIR: Path = BACKEND_DIR / ".cache" / "embeddings"
    EMBEDDING_THREADS: int = Field(default=2, ge=1, le=16)
    MAX_UPLOAD_BYTES: int = Field(default=10 * 1024 * 1024, ge=1024)
    MAX_PDF_PAGES: int = Field(default=100, ge=1)
    MAX_DOCUMENT_CHARS: int = Field(default=1_000_000, ge=1)
    MAX_DOCUMENT_CHUNKS: int = Field(default=5000, ge=1)
    CHUNK_SIZE: int = Field(default=1024, ge=64, le=1024)
    CHUNK_OVERLAP: int = Field(default=64, ge=0)

    @model_validator(mode="after")
    def validate_chunking(self):
        if self.CHUNK_OVERLAP >= self.CHUNK_SIZE:
            raise ValueError("CHUNK_OVERLAP must be less than CHUNK_SIZE")
        return self

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        if len(value.strip()) < 32 or any(
            marker in value.lower()
            for marker in ("change-this", "change-in-production", "development-secret", "replace-me")
        ):
            raise ValueError("SECRET_KEY must be a generated secret of at least 32 characters")
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_origins(cls, value: str) -> str:
        origins = json.loads(value) if value.strip().startswith("[") else value.split(",")
        if not isinstance(origins, list) or not origins or any(
            not isinstance(origin, str)
            or not origin.strip().startswith(("http://", "https://"))
            or "*" in origin
            for origin in origins
        ):
            raise ValueError("CORS_ORIGINS must contain explicit HTTP(S) origins without wildcards")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        val = self.CORS_ORIGINS.strip()
        if val.startswith("["):
            return [origin.strip() for origin in json.loads(val)]
        return [i.strip() for i in val.split(",") if i.strip()]

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_database_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


settings = Settings()
