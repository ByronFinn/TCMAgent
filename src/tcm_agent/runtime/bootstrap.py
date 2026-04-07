"""Application bootstrap module for TCMAgent.

This module provides a lightweight runtime entrypoint for local development and
early-stage deployment. It is intentionally conservative:

- Centralizes startup configuration
- Verifies critical runtime dependencies and configuration
- Builds a minimal shared runtime context
- Starts the API server when available
- Falls back to a placeholder app during early scaffolding

As the project grows, this module can evolve into the canonical place for:
- dependency container initialization
- database and graph client wiring
- agent registry setup
- lifecycle hooks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI

from tcm_agent.config import Settings, get_settings
from tcm_agent.graph.neo4j_client import (
    Neo4jClient,
    Neo4jClientError,
    Neo4jConfig,
    create_neo4j_client,
)

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    """Configure process-wide logging.

    This keeps logging setup minimal but consistent for development. It can later
    be replaced by a richer structlog / JSON logging configuration if needed.
    """
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )

    logger.debug("Logging configured", extra={"level": level_name})


@dataclass(slots=True)
class RuntimeContext:
    """Shared runtime dependencies for the application process."""

    settings: Settings
    neo4j_client: Neo4jClient | None = None

    def health_summary(self) -> dict[str, Any]:
        """Return a lightweight runtime health summary."""
        graph_health: dict[str, Any]
        if self.neo4j_client is None:
            graph_health = {
                "ok": False,
                "backend": "neo4j",
                "error": "Neo4j client not initialized",
            }
        else:
            graph_health = self.neo4j_client.healthcheck()

        return {
            "app_env": self.settings.app_env,
            "debug": self.settings.debug,
            "tracing_enabled": self.settings.tracing_enabled,
            "graph": graph_health,
        }


def build_neo4j_client(settings: Settings) -> Neo4jClient | None:
    """Create and verify the Neo4j client if credentials are present.

    During early scaffolding, the project may be started before Neo4j is fully
    available. In that case we log a warning and continue, because API and schema
    work can still proceed with a partially wired runtime.
    """
    if not settings.neo4j_password:
        logger.warning("Neo4j password is not configured; graph client will be disabled.")
        return None

    config = Neo4jConfig(
        uri=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )

    client = create_neo4j_client(config)

    try:
        client.verify_connectivity()
    except (Neo4jClientError, Exception) as exc:
        logger.warning("Neo4j connectivity check failed: %s", exc)
        client.close()
        return None

    logger.info("Neo4j client initialized successfully.")
    return client


def build_runtime_context(settings: Settings | None = None) -> RuntimeContext:
    """Build the shared runtime context for the process."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)

    neo4j_client = build_neo4j_client(resolved_settings)

    context = RuntimeContext(
        settings=resolved_settings,
        neo4j_client=neo4j_client,
    )
    logger.info("Runtime context initialized.")
    return context


def create_placeholder_app(context: RuntimeContext) -> FastAPI:
    """Create a minimal FastAPI app while the full API module is still evolving."""
    app = FastAPI(
        title="TCMAgent API",
        version="0.1.0",
        description=(
            "Neo4j-driven convergent TCM consultation backend. "
            "This placeholder app is used until the full API router layer is wired."
        ),
    )

    app.state.runtime_context = context

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "TCMAgent",
            "runtime": context.health_summary(),
        }

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "message": "TCMAgent bootstrap app is running.",
        }

    return app


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the application object.

    If a richer API factory exists, use it. Otherwise fall back to the placeholder
    bootstrap app so local development can still start successfully.
    """
    context = build_runtime_context(settings)

    try:
        from tcm_agent.api.app import create_app as create_api_app  # type: ignore
    except Exception as exc:
        logger.info("Falling back to placeholder app: %s", exc)
        return create_placeholder_app(context)

    app = create_api_app(context=context)
    logger.info("Application created from api.app factory.")
    return app


def shutdown_runtime(context: RuntimeContext) -> None:
    """Gracefully close runtime dependencies."""
    if context.neo4j_client is not None:
        try:
            context.neo4j_client.close()
            logger.info("Neo4j client closed.")
        except Exception as exc:
            logger.warning("Failed to close Neo4j client cleanly: %s", exc)


def main() -> None:
    """CLI entrypoint for local development startup."""
    settings = get_settings()

    logger.info(
        "Starting TCMAgent server on %s:%s",
        settings.api_host,
        settings.api_port,
    )

    if settings.is_development:
        uvicorn.run(
            "tcm_agent.runtime.bootstrap:create_app",
            host=settings.api_host,
            port=settings.api_port,
            reload=True,
            log_level=settings.log_level.lower(),
            factory=True,
        )
    else:
        app = create_app(settings)
        uvicorn.run(
            app,
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
        )


if __name__ == "__main__":
    main()
