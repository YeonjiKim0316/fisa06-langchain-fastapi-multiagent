import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(f".env.{os.environ.get('APP_ENV', 'local')}", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    app_env: str = "local"
    database_url: str = "sqlite:///./deepresearch.db"
    
    # 스토리지 설정
    local_storage_dir: str = "saved_reports"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str | None = None
    s3_bucket_name: str | None = None

    # 인증 및 API 키
    secret_key: str = "change-me-in-production"
    openai_api_key: str = ""
    tavily_api_key: str = ""
    google_api_key: str = ""


@lru_cache()
def get_settings() -> Settings:
    return Settings()
