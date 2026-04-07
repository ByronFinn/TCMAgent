"""API application entrypoint for TCMAgent."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tcm_agent.api.routes.cases import router as cases_router
from tcm_agent.api.routes.chat import router as chat_router
from tcm_agent.config import get_settings
from tcm_agent.graph.neo4j_client import Neo4jClientError, Neo4jConfig, create_neo4j_client

logger = logging.getLogger(__name__)

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
            "TCMAgent provides the backend API for a TCM consultation system. "
            "It integrates with a Neo4j graph database to manage and query "
            "TCM knowledge and case data. The API is designed to support a "
            "variety of frontend clients, including web and mobile applications."
        ),
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def global_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.get("/health", tags=["system"], summary="Health check")
    async def health_check() -> dict[str, Any]:
        neo4j_status = getattr(app.state, "neo4j_status", {})
        return {
            "ok": neo4j_status.get("ok", False),
            "service": APP_TITLE,
            "version": APP_VERSION,
            "graph": neo4j_status,
        }

    app.include_router(cases_router)
    app.include_router(chat_router)
    return app
