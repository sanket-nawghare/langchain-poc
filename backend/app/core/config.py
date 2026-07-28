"""Validated application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and backend `.env`."""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_prefix="CLINICAL_",
        extra="ignore",
        validate_default=True,
    )

    app_name: str = "AI Clinical Workflow Engine"
    app_version: str = "0.1.0"
    environment: Literal["local", "test", "staging", "production"] = "local"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    database_url: str = "sqlite:///./data/clinical_workflow.db"
    fhir_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8080/fhir")
    fhir_request_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    fhir_max_retries: int = Field(default=2, ge=0, le=3)
    fhir_retry_backoff_seconds: float = Field(default=0.1, ge=0, le=5)
    fhir_max_pages_per_search: int = Field(default=5, ge=1, le=20)
    fhir_max_records_per_type: int = Field(default=500, ge=1, le=500)
    weaviate_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8081")
    workflow_node_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    workflow_node_max_retries: int = Field(default=1, ge=0, le=3)

    llm_provider: str = "fake"
    llm_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""

    return Settings()
