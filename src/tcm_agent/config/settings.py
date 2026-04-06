"""Application settings for TCMAgent."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables.

    Values are primarily sourced from a local `.env` file during development
    and from real environment variables in deployed environments.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    debug: bool = False

    # API server
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Model provider
    model_provider: Literal["openai", "anthropic", "openrouter", "custom"] = "openai"
    model_name: str = "gpt-4o-mini"
    model_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # Provider credentials
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"

    # LangSmith / tracing
    langsmith_api_key: str | None = None
    langsmith_tracing: bool = False
    langsmith_project: str = "TCMAgent"

    # UI / frontend integration
    deep_agents_ui_url: str = "http://localhost:3000"
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Safety / workflow thresholds
    triage_high_risk_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    convergence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    intake_completeness_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    # Runtime behavior
    enable_audit_log: bool = True
    enable_reasoning_trace: bool = True
    enable_human_review: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_development(self) -> bool:
        """Whether the app is running in a development-like mode."""
        return self.app_env in {"development", "test"}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_allow_origins_list(self) -> list[str]:
        """Parsed CORS origins."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tracing_enabled(self) -> bool:
        """Whether external tracing is enabled."""
        return self.langsmith_tracing and bool(self.langsmith_api_key)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def model_api_key(self) -> str | None:
        """Resolve the active model provider API key."""
        provider_to_key = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "openrouter": self.openrouter_api_key,
            "custom": None,
        }
        return provider_to_key[self.model_provider]

    def require_neo4j_credentials(self) -> None:
        """Raise if Neo4j credentials are incomplete."""
        if not self.neo4j_uri:
            raise ValueError("NEO4J_URI is required.")
        if not self.neo4j_username:
            raise ValueError("NEO4J_USERNAME is required.")
        if not self.neo4j_password:
            raise ValueError("NEO4J_PASSWORD is required.")

    def require_model_credentials(self) -> None:
        """Raise if the selected model provider is missing its API key."""
        if self.model_provider == "custom":
            return
        if not self.model_api_key:
            raise ValueError(
                f"Missing API key for model provider '{self.model_provider}'. "
                "Set the corresponding provider credential in the environment."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
