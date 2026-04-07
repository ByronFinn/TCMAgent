"""Neo4j client utilities for TCMAgent.

This module provides a small, typed wrapper around the official Neo4j Python
driver so the rest of the application does not need to manage sessions,
connectivity checks, or low-level query execution details directly.

Design goals:
- Keep connection management centralized
- Return plain Python data structures for service/tool layers
- Make it easy to swap in app settings later
- Be safe to use in short-lived scripts and long-lived API processes
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, LiteralString

from neo4j import Driver, GraphDatabase, Query, Record
from neo4j.exceptions import Neo4jError

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Neo4jConfig:
    """Connection configuration for Neo4j."""

    uri: str
    username: str
    password: str
    database: str = "neo4j"
    max_connection_lifetime: int = 3600
    max_connection_pool_size: int = 50
    connection_timeout: float = 15.0

    @classmethod
    def from_env(cls) -> Neo4jConfig:
        """Build config from environment variables."""
        return cls(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            username=os.getenv("NEO4J_USERNAME", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", ""),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )


class Neo4jClientError(RuntimeError):
    """Raised when Neo4j operations fail in an application-facing way."""


class Neo4jClient:
    """Thin wrapper around the Neo4j driver.

    This class is intentionally small. Repository and service layers should hold
    domain logic; this client should focus only on connectivity and query
    execution.
    """

    def __init__(self, config: Neo4jConfig) -> None:
        self.config = config
        self._driver: Driver = GraphDatabase.driver(
            config.uri,
            auth=(config.username, config.password),
            max_connection_lifetime=config.max_connection_lifetime,
            max_connection_pool_size=config.max_connection_pool_size,
            connection_timeout=config.connection_timeout,
        )

    @property
    def driver(self) -> Driver:
        """Expose the underlying driver for advanced use cases."""
        return self._driver

    def verify_connectivity(self) -> None:
        """Verify the driver can connect to Neo4j."""
        try:
            self._driver.verify_connectivity()
            logger.debug("Neo4j connectivity verified for %s", self.config.uri)
        except Neo4jError as exc:
            logger.exception("Neo4j connectivity verification failed")
            raise Neo4jClientError("Failed to verify Neo4j connectivity") from exc

    def close(self) -> None:
        """Close the underlying driver."""
        self._driver.close()

    def run_query(
        self,
        query: LiteralString | Query,
        parameters: Mapping[str, Any] | None = None,
        *,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a read/write query and return records as dictionaries."""
        db_name = database or self.config.database
        params = dict(parameters or {})

        try:
            with self._driver.session(database=db_name) as session:
                result = session.run(query, params)
                records = [self._record_to_dict(record) for record in result]
                summary = result.consume()
        except Neo4jError as exc:
            logger.exception("Neo4j query failed")
            raise Neo4jClientError("Neo4j query execution failed") from exc

        logger.debug(
            "Neo4j query executed: database=%s records=%s query_type=%s",
            db_name,
            len(records),
            summary.query_type,
        )
        return records

    def run_write(
        self,
        query: LiteralString | Query,
        parameters: Mapping[str, Any] | None = None,
        *,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a write query inside an explicit transaction."""
        db_name = database or self.config.database
        params = dict(parameters or {})

        def _tx_func(tx: Any) -> list[dict[str, Any]]:
            result = tx.run(query, params)
            return [self._record_to_dict(record) for record in result]

        try:
            with self._driver.session(database=db_name) as session:
                records = session.execute_write(_tx_func)
        except Neo4jError as exc:
            logger.exception("Neo4j write transaction failed")
            raise Neo4jClientError("Neo4j write transaction failed") from exc

        logger.debug("Neo4j write completed: database=%s records=%s", db_name, len(records))
        return records

    def run_read(
        self,
        query: LiteralString | Query,
        parameters: Mapping[str, Any] | None = None,
        *,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a read query inside an explicit transaction."""
        db_name = database or self.config.database
        params = dict(parameters or {})

        def _tx_func(tx: Any) -> list[dict[str, Any]]:
            result = tx.run(query, params)
            return [self._record_to_dict(record) for record in result]

        try:
            with self._driver.session(database=db_name) as session:
                records = session.execute_read(_tx_func)
        except Neo4jError as exc:
            logger.exception("Neo4j read transaction failed")
            raise Neo4jClientError("Neo4j read transaction failed") from exc

        logger.debug("Neo4j read completed: database=%s records=%s", db_name, len(records))
        return records

    def healthcheck(self) -> dict[str, Any]:
        """Return a small health summary for API/status endpoints."""
        try:
            self.verify_connectivity()
            records = self.run_read("RETURN 1 AS ok")
        except Neo4jClientError as exc:
            return {
                "ok": False,
                "backend": "neo4j",
                "uri": self.config.uri,
                "database": self.config.database,
                "error": str(exc),
            }

        return {
            "ok": bool(records and records[0].get("ok") == 1),
            "backend": "neo4j",
            "uri": self.config.uri,
            "database": self.config.database,
        }

    def __enter__(self) -> Neo4jClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    @staticmethod
    def _record_to_dict(record: Record) -> dict[str, Any]:
        """Convert a Neo4j record into a plain dictionary."""
        return {key: record[key] for key in record}


def create_neo4j_client(config: Neo4jConfig | None = None) -> Neo4jClient:
    """Factory helper for app bootstrap and tests."""
    return Neo4jClient(config or Neo4jConfig.from_env())


__all__ = [
    "Neo4jClient",
    "Neo4jClientError",
    "Neo4jConfig",
    "create_neo4j_client",
]
