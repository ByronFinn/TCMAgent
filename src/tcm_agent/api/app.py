"""API application entrypoint for TCMAgent."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tcm_agent.api.routes.cases import router as cases_router
from tcm_agent.api.routes.chat_runtime import router as chat_router
from tcm_agent.config import get_settings
from tcm_agent.graph.neo4j_client import Neo4jClientError, Neo4jConfig, create_neo4j_client

APP_TITLE = "TCMAgent API"
APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared application resources."""
    settings = get_settings()

    neo4j_status: dict[str, Any]
    neo4j_client = None

    try:
        if settings.neo4j_password:
            neo4j_client = create_neo4j_client(
                Neo4jConfig(
                    uri=settings.neo4j_uri,
                    username=settings.neo4j_username,
                    password=settings.neo4j_password,
                    database=settings.neo4j_database,
                )
            )
            neo4j_status = neo4j_client.healthcheck()
        else:
            neo4j_status = {
                "ok": False,
                "backend": "neo4j",
                "uri": settings.neo4j_uri,
                "database": settings.neo4j_database,
                "error": "NEO4J_PASSWORD is not configured.",
            }
    except Neo4jClientError as exc:
        neo4j_status = {
            "ok": False,
            "backend": "neo4j",
            "uri": settings.neo4j_uri,
            "database": settings.neo4j_database,
            "error": str(exc),
        }

    app.state.settings = settings
    app.state.neo4j_client = neo4j_client
    app.state.neo4j_status = neo4j_status

    yield

    client = getattr(app.state, "neo4j_client", None)
    if client is not None:
        client.close()


def create_app(context: Any | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = getattr(context, "settings", None) or get_settings()

    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        debug=settings.debug,
        lifespan=lifespan,
        summary="Neo4j-driven convergent TCM consultation backend.",
        description=(
            "TCMAgent provides the backend services for a convergent TCM consultation "
            "system built on top of knowledge-graph-guided reasoning, structured case "
            "state management, and agent orchestration."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if context is not None:
        app.state.runtime_context = context

    @app.get("/", tags=["system"])
    async def root() -> dict[str, Any]:
        """Basic application metadata."""
        return {
            "name": APP_TITLE,
            "version": APP_VERSION,
            "environment": settings.app_env,
            "debug": settings.debug,
        }

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        """Application health summary."""
        neo4j_status = getattr(app.state, "neo4j_status", {"ok": False, "backend": "neo4j"})
        return {
            "ok": bool(neo4j_status.get("ok")),
            "service": "tcm-agent-api",
            "version": APP_VERSION,
            "environment": settings.app_env,
            "dependencies": {
                "neo4j": neo4j_status,
            },
        }

    @app.get("/health/live", tags=["system"])
    async def live() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "alive"}

    @app.get("/health/ready", tags=["system"])
    async def ready() -> dict[str, Any]:
        """Readiness probe."""
        neo4j_status = getattr(app.state, "neo4j_status", {"ok": False})
        return {
            "status": "ready" if neo4j_status.get("ok") else "degraded",
            "neo4j_ok": bool(neo4j_status.get("ok")),
        }

    @app.get("/config", tags=["system"])
    async def config_summary() -> dict[str, Any]:
        """Non-sensitive runtime configuration summary."""
        return {
            "app_env": settings.app_env,
            "model_provider": settings.model_provider,
            "model_name": settings.model_name,
            "model_temperature": settings.model_temperature,
            "neo4j_uri": settings.neo4j_uri,
            "neo4j_database": settings.neo4j_database,
            "deep_agents_ui_url": settings.deep_agents_ui_url,
            "enable_audit_log": settings.enable_audit_log,
            "enable_reasoning_trace": settings.enable_reasoning_trace,
            "enable_human_review": settings.enable_human_review,
        }

    app.include_router(cases_router)
    app.include_router(chat_router)

    return app


app = create_app()


def main() -> None:
    """Run the API server in local development mode."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "tcm_agent.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.is_development,
        factory=False,
    )


if __name__ == "__main__":
    main()
