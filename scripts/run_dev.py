#!/usr/bin/env python3
"""Development helper script for running TCMAgent locally.

This script is intentionally lightweight. It resolves the project root,
adds `src/` to `sys.path` for local development, and then delegates to the
runtime bootstrap entrypoint.

Recommended usage:
    uv run python scripts/run_dev.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def _project_root() -> Path:
    """Return the repository root based on this script location."""
    return Path(__file__).resolve().parent.parent


def _ensure_src_on_path(root: Path) -> None:
    """Add the local `src` directory to Python's import path if needed."""
    src_path = root / "src"
    src_str = str(src_path)

    if not src_path.exists():
        raise FileNotFoundError(f"Expected source directory does not exist: {src_path}")

    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def main() -> None:
    """Run the TCMAgent development server."""
    root = _project_root()
    _ensure_src_on_path(root)

    from tcm_agent.runtime.bootstrap import main as bootstrap_main

    bootstrap_main()


if __name__ == "__main__":
    main()
