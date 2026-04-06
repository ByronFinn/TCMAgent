"""In-memory case store wrapper module.

This module provides a thin repository-style wrapper around the shared MVP
in-memory case store defined in `tcm_agent.tools.case_tools`.

Why this exists
---------------
The current project is still in scaffolding mode. The actual storage logic lives
in the case tools module so that API routes, services, and future agent tools
can already operate on real state. This wrapper gives the rest of the codebase a
stable import location for state access, so later we can replace the backing
implementation with Redis, Postgres, or another persistent store without forcing
large refactors.

Current behavior
----------------
- Delegates all storage operations to the shared `CASE_STORE`
- Returns `CaseRecord` objects for mutable internal operations
- Returns detached `CaseState` snapshots for read-style access
- Supports stage locking metadata used by workflow control
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tcm_agent.schemas.case import CaseStage, CaseState
from tcm_agent.tools.case_tools import (
    CASE_STORE,
    CaseNotFoundError,
    CaseRecord,
    CaseStageLockedError,
    CaseToolError,
    InMemoryCaseStore,
)


@dataclass(slots=True)
class CaseStoreStats:
    """Lightweight statistics about the current in-memory store."""

    total_cases: int
    case_ids: list[str]


class CaseStoreRepository:
    """Repository wrapper around the shared in-memory case store.

    This class intentionally keeps the API small and explicit. Service and API
    layers should prefer using this wrapper instead of touching the raw shared
    store directly.
    """

    def __init__(self, store: InMemoryCaseStore | None = None) -> None:
        self._store = store or CASE_STORE

    @property
    def store(self) -> InMemoryCaseStore:
        """Expose the underlying store for advanced/internal usage."""
        return self._store

    def create(self, state: CaseState) -> None:
        """Create a new case record."""
        self._store.create(state)

    def get_record(self, case_id: str) -> CaseRecord:
        """Return the mutable internal record for a case."""
        return self._store.get(case_id)

    def get_state(self, case_id: str) -> CaseState:
        """Return the current case state snapshot."""
        return self.get_record(case_id).state

    def save_record(self, record: CaseRecord) -> None:
        """Persist a mutated record back into the store."""
        self._store.save(record)

    def exists(self, case_id: str) -> bool:
        """Return whether a case exists."""
        try:
            self._store.get(case_id)
        except CaseNotFoundError:
            return False
        return True

    def list_case_ids(self) -> list[str]:
        """Return all case IDs in sorted order."""
        return self._store.list_case_ids()

    def list_states(self) -> list[CaseState]:
        """Return all current case states."""
        return [self.get_state(case_id) for case_id in self.list_case_ids()]

    def reset(self) -> None:
        """Clear all in-memory case data."""
        self._store.reset()

    def lock_stage(self, case_id: str, stage: CaseStage) -> None:
        """Lock a stage for a given case."""
        record = self.get_record(case_id)
        record.locked_stages.add(stage)
        self.save_record(record)

    def unlock_stage(self, case_id: str, stage: CaseStage) -> None:
        """Unlock a stage for a given case."""
        record = self.get_record(case_id)
        record.locked_stages.discard(stage)
        self.save_record(record)

    def is_stage_locked(self, case_id: str, stage: CaseStage) -> bool:
        """Return whether a stage is locked for a given case."""
        record = self.get_record(case_id)
        return stage in record.locked_stages

    def get_locked_stages(self, case_id: str) -> set[CaseStage]:
        """Return the set of locked stages for a case."""
        record = self.get_record(case_id)
        return set(record.locked_stages)

    def delete(self, case_id: str) -> None:
        """Delete a case from the in-memory store.

        Since the shared store currently does not expose a dedicated delete
        method, this implementation performs the removal against the internal
        mapping. This is acceptable for the MVP wrapper and can be replaced once
        a proper repository backend is introduced.
        """
        if not self.exists(case_id):
            raise CaseNotFoundError(f"Case '{case_id}' was not found.")

        # Accessing internal state is acceptable here because this module is the
        # dedicated state wrapper for the current in-memory implementation.
        self._store._records.pop(case_id, None)  # type: ignore[attr-defined]

    def ensure_all_exist(self, case_ids: Iterable[str]) -> None:
        """Raise if any case in the iterable does not exist."""
        missing = [case_id for case_id in case_ids if not self.exists(case_id)]
        if missing:
            raise CaseNotFoundError(
                f"The following case(s) were not found: {', '.join(sorted(missing))}"
            )

    def stats(self) -> CaseStoreStats:
        """Return a simple store summary."""
        case_ids = self.list_case_ids()
        return CaseStoreStats(total_cases=len(case_ids), case_ids=case_ids)


DEFAULT_CASE_STORE = CaseStoreRepository()


def get_case_store() -> CaseStoreRepository:
    """Return the default shared case store repository."""
    return DEFAULT_CASE_STORE


__all__ = [
    "CASE_STORE",
    "DEFAULT_CASE_STORE",
    "CaseNotFoundError",
    "CaseRecord",
    "CaseStageLockedError",
    "CaseStoreRepository",
    "CaseStoreStats",
    "CaseToolError",
    "InMemoryCaseStore",
    "get_case_store",
]
