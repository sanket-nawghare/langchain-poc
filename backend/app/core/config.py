"""Validated application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
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
    max_request_body_bytes: int = Field(default=16_384, ge=1024, le=1_048_576)
    workflow_rate_limit_per_minute: int = Field(default=120, ge=1, le=10_000)
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
    weaviate_grpc_port: int = Field(default=50051, ge=1, le=65535)
    weaviate_request_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    guideline_corpus_lock_path: Path = Path("data/guidelines/corpus-lock.json")
    workflow_node_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    workflow_node_max_retries: int = Field(default=1, ge=0, le=3)
    langsmith_tracing_enabled: bool = False

    llm_provider: Literal["fake", "openai", "anthropic", "ollama"] = "fake"
    llm_api_key: SecretStr | None = None
    llm_model: str = Field(
        default="gpt-5.6-sol",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    llm_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    llm_anthropic_model: str = Field(
        default="claude-sonnet-4-6",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    llm_anthropic_base_url: AnyHttpUrl = AnyHttpUrl("https://api.anthropic.com")
    llm_ollama_model: str = Field(
        default="qwen3:4b",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:/-]+$",
    )
    llm_ollama_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:11434")
    llm_ollama_context_window: int = Field(default=8192, ge=4096, le=32768)
    llm_request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=3)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    llm_reasoning_effort: Literal[
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ] = "medium"

    @model_validator(mode="after")
    def validate_llm_provider(self) -> "Settings":
        """Require credentials and TLS only when the real provider is selected."""

        if self.llm_provider in {"openai", "anthropic"}:
            if self.llm_api_key is None:
                raise ValueError(
                    "llm_api_key is required when a real llm_provider is selected"
                )
            provider_url = (
                self.llm_base_url
                if self.llm_provider == "openai"
                else self.llm_anthropic_base_url
            )
            if provider_url.scheme != "https":
                raise ValueError("the selected LLM provider URL must use HTTPS")
        if self.llm_provider == "ollama" and self.llm_ollama_base_url.host not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("the Ollama provider URL must use a loopback host")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""

    return Settings()
