import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(f".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    app_env: str = "local"
    database_url: str = "sqlite:///./fisaai6-research-agent.db"
    
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


@lru_cache() # Least Recently Used (가장 최근에 덜 쓰인 항목을 제거하는 캐시 전략): 함수의 반환값 캐싱 - 한번만 올려서 계속 사용
def get_settings() -> Settings:
    return Settings()
