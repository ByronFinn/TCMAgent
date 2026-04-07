"""Skills loader for TCMAgent agent factory.

## Design rationale

deepagents' SkillsMiddleware is created automatically by ``create_deep_agent``
when a ``SubAgent`` spec carries a ``skills`` key::

    subagent_skills = spec.get("skills")
    if subagent_skills:
        subagent_middleware.append(
            SkillsMiddleware(backend=backend, sources=subagent_skills)
        )

Critically, it uses the **same backend** that was passed to ``create_deep_agent``.
This module's job is therefore to:

1. Build the right **backend** - a ``CompositeBackend`` that routes the
   ``/skills/`` prefix to a ``FilesystemBackend`` (pointing at the project's
   ``skills/`` directory) while leaving all other paths on the default
   ``StateBackend`` (safe, ephemeral, appropriate for a web API).

2. Export the per-role **source path lists** used in SubAgent specs.

## Skill file format (Agent Skills spec)

Each skill lives in its own sub-directory inside one of the source directories.
The sub-directory name IS the skill name.  The directory must contain exactly
one ``SKILL.md`` file with YAML front-matter::

    skills/
    ├── shared/
    │   ├── tcm-clinical-basics/
    │   │   └── SKILL.md          ← ---\\nname: tcm-clinical-basics\\n...\\n---
    │   └── case-state-protocol/
    │       └── SKILL.md
    └── triage/
        ├── red-flags-protocol/
        │   └── SKILL.md
        └── ...

## Path conventions

All source paths are absolute from the **CompositeBackend root** (``/``).
The CompositeBackend routes the ``/skills/`` prefix to
``FilesystemBackend(root_dir=SKILLS_ROOT, virtual_mode=True)``, which strips
the ``/skills/`` prefix before forwarding to the filesystem.  So:

    CompositeBackend path   →   FilesystemBackend path   →   Disk path
    /skills/triage/         →   /triage/                 →   SKILLS_ROOT/triage/
    /skills/shared/         →   /shared/                 →   SKILLS_ROOT/shared/

## Security note

``FilesystemBackend(virtual_mode=True)`` is scoped strictly to ``SKILLS_ROOT``.
Path traversal (``..``, ``~``, absolute escapes) is blocked.  The backend is
only ever used by ``SkillsMiddleware`` for READ operations (it never writes
skill files).  The agent's own file tools (``read_file``, ``write_file``, etc.)
go through the ``StateBackend`` default, so the agent cannot access the
filesystem at large.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# factory.py → agents/ → tcm_agent/ → src/ → project-root/
# parents: [0]=agents  [1]=tcm_agent  [2]=src  [3]=project-root
_PROJECT_ROOT: Path = Path(__file__).parents[3]

#: Absolute path to the project-level skills directory on disk.
SKILLS_ROOT: Path = _PROJECT_ROOT / "skills"

# ---------------------------------------------------------------------------
# CompositeBackend route prefix
# ---------------------------------------------------------------------------

#: The path prefix that CompositeBackend routes to the skills FilesystemBackend.
#: All skill source paths seen by SubAgent specs must start with this prefix.
SKILLS_PREFIX: str = "/skills/"

# ---------------------------------------------------------------------------
# Per-role skill source paths
# (absolute from the CompositeBackend root, i.e. prefixed with SKILLS_PREFIX)
# ---------------------------------------------------------------------------

#: Skill sources loaded by every sub-agent.
SHARED_SOURCE: str = f"{SKILLS_PREFIX}shared/"

#: Skill sources specific to ``triage-agent``.
TRIAGE_SOURCE: str = f"{SKILLS_PREFIX}triage/"

#: Skill sources specific to ``intake-agent``.
INTAKE_SOURCE: str = f"{SKILLS_PREFIX}intake/"

#: Skill sources specific to ``safety-agent``.
SAFETY_SOURCE: str = f"{SKILLS_PREFIX}safety/"


def triage_skill_sources() -> list[str]:
    """Return skill source paths for ``triage-agent``.

    Shared skills are loaded first; triage-specific skills override when
    skill names collide (last-wins semantics from deepagents).
    """
    return [SHARED_SOURCE, TRIAGE_SOURCE]


def intake_skill_sources() -> list[str]:
    """Return skill source paths for ``intake-agent``."""
    return [SHARED_SOURCE, INTAKE_SOURCE]


def safety_skill_sources() -> list[str]:
    """Return skill source paths for ``safety-agent``."""
    return [SHARED_SOURCE, SAFETY_SOURCE]


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------


def skills_available() -> bool:
    """Return ``True`` when the skills directory exists and contains SKILL.md files."""
    if not SKILLS_ROOT.is_dir():
        return False
    return any(SKILLS_ROOT.rglob("SKILL.md"))


def build_composite_backend() -> Any | None:
    """Build a ``CompositeBackend`` suitable for use as ``create_deep_agent``'s backend.

    The returned backend routes ``/skills/`` paths to a read-scoped
    ``FilesystemBackend`` (virtual_mode=True) so that ``SkillsMiddleware``
    can load skill files from disk.  All other paths fall through to a
    ``StateBackend`` (ephemeral, web-API-safe).

    Returns ``None`` when:

    - The ``skills/`` directory does not exist or contains no ``SKILL.md``
      files (so callers can fall back to the plain ``StateBackend`` default).
    - deepagents backends are not importable (incomplete install).

    Usage::

        backend = build_composite_backend()
        graph = create_deep_agent(..., backend=backend)
    """
    if not skills_available():
        logger.info(
            "Skills directory not found or contains no SKILL.md files at %s; "
            "returning None – create_deep_agent will use its default StateBackend.",
            SKILLS_ROOT,
        )
        return None

    try:
        from deepagents.backends import (  # type: ignore[import-untyped]
            FilesystemBackend,
            StateBackend,
        )
        from deepagents.backends.composite import CompositeBackend  # type: ignore[import-untyped]
    except ImportError as exc:
        logger.warning("deepagents backends not available: %s", exc)
        return None

    skills_backend = FilesystemBackend(
        root_dir=str(SKILLS_ROOT),
        virtual_mode=True,  # Block path traversal; scope reads to SKILLS_ROOT
    )

    composite = CompositeBackend(
        default=StateBackend(),
        routes={SKILLS_PREFIX: skills_backend},
    )

    logger.info(
        "CompositeBackend built: /skills/ → FilesystemBackend(%s), default → StateBackend()",
        SKILLS_ROOT,
    )
    return composite


# ---------------------------------------------------------------------------
# Diagnostic helper
# ---------------------------------------------------------------------------


def describe_skills_layout() -> dict[str, Any]:
    """Return a diagnostic summary of the current skills layout on disk.

    Useful for the ``/health`` endpoint and startup logging.  Reports which
    source directories and skill sub-directories (i.e. directories with a
    ``SKILL.md``) are present.
    """
    if not SKILLS_ROOT.is_dir():
        return {
            "skills_root": str(SKILLS_ROOT),
            "available": False,
            "reason": "skills root directory does not exist",
        }

    source_dirs = {
        "shared": SKILLS_ROOT / "shared",
        "triage": SKILLS_ROOT / "triage",
        "intake": SKILLS_ROOT / "intake",
        "safety": SKILLS_ROOT / "safety",
    }

    skill_dirs: dict[str, list[str]] = {}
    for src_name, src_path in source_dirs.items():
        if not src_path.is_dir():
            continue
        found = sorted(
            d.name for d in src_path.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
        )
        if found:
            skill_dirs[src_name] = found

    total = sum(len(v) for v in skill_dirs.values())

    return {
        "skills_root": str(SKILLS_ROOT),
        "available": total > 0,
        "source_dirs": {k: v.is_dir() for k, v in source_dirs.items()},
        "skills": skill_dirs,
        "total_skills": total,
    }


__all__ = [
    "INTAKE_SOURCE",
    "SAFETY_SOURCE",
    "SHARED_SOURCE",
    "SKILLS_PREFIX",
    "SKILLS_ROOT",
    "TRIAGE_SOURCE",
    "build_composite_backend",
    "describe_skills_layout",
    "intake_skill_sources",
    "safety_skill_sources",
    "skills_available",
    "triage_skill_sources",
]
