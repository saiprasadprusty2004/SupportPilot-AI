from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    demo_mode: bool = False
    app_url: str = "http://localhost:5173"
    database_url: str = "sqlite:///./data/supportpilot.db"
    worker_database_url: str = ""
    migration_database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "development-only-change-before-production"
    encryption_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    composio_api_key: str = ""
    composio_gmail_auth_config: str = ""
    composio_slack_auth_config: str = ""
    composio_googledrive_auth_config: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    storage_backend: str = "local"
    storage_path: str = "./data/uploads"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_revision: str = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
    workspace_concurrency: int = 2
    global_concurrency: int = 20
    groq_requests_per_minute: int = 20
    groq_tokens_per_minute: int = 7000

    def validate_runtime(self):
        if self.app_env == "production":
            if self.demo_mode or len(self.secret_key) < 32 or self.secret_key.startswith("development"):
                raise RuntimeError("Production requires DEMO_MODE=false and a random SECRET_KEY (32+ chars)")
            if not self.app_url.startswith("https://"):
                raise RuntimeError("Production APP_URL must use HTTPS")
        if not self.demo_mode:
            if self.database_url.startswith("sqlite"):
                raise RuntimeError("Live mode requires PostgreSQL; SQLite is demo/test only")
            if not self.encryption_key:
                raise RuntimeError("Live mode requires a Fernet ENCRYPTION_KEY")
        Path(self.storage_path).mkdir(parents=True, exist_ok=True)


@lru_cache
def settings() -> Settings:
    return Settings()
