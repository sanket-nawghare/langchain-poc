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
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    database_url: str = "sqlite:///./data/clinical_workflow.db"
    fhir_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8080/fhir")
    weaviate_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8081")

    llm_provider: str = "fake"
    llm_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""

    return Settings()
