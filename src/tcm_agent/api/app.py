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
            "TCMAgent provides the