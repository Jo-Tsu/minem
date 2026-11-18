"""Paths shared by runtime maintenance and verification commands."""

import os
from pathlib import Path


def maintenance_root(runtime_root: Path) -> Path:
    return runtime_root / "maintenance"


def maintenance_runtime_root(project_root: Path) -> Path:
    configured = os.environ.get("MINEM_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    project_runtime = project_root / "runtime"
    return project_runtime if (project_runtime / "data/materials.db").is_file() else project_root


def validation_root(runtime_root: Path) -> Path:
    return maintenance_root(runtime_root) / "validation"


def history_root(runtime_root: Path) -> Path:
    return maintenance_root(runtime_root) / "history"
