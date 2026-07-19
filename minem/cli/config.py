"""User configuration for MineM CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

from minem.runtime_discovery import discover_service_manifest, resolve_base_url

from .contracts import CliError


ALLOWED_KEYS = {"server", "output"}


def config_path() -> Path:
    override = os.environ.get("MINEM_CONFIG_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "minem" / "config.json"


def load_config() -> dict:
    path = config_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise CliError("CONFIG_INVALID", f"Cannot read MineM config at {path}: {error}") from error
    return payload if isinstance(payload, dict) else {}


def save_config(payload: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def set_value(key: str, value: str) -> dict:
    if key not in ALLOWED_KEYS:
        raise CliError("INVALID_ARGUMENT", f"Unsupported config key: {key}", details={"allowed": sorted(ALLOWED_KEYS)}, exit_code=2)
    if key == "output" and value not in {"table", "json", "jsonl", "yaml"}:
        raise CliError("INVALID_ARGUMENT", "output must be table, json, jsonl, or yaml", exit_code=2)
    payload = load_config()
    payload[key] = value
    path = save_config(payload)
    return {"key": key, "value": value, "path": str(path)}


def unset_value(key: str) -> dict:
    payload = load_config()
    payload.pop(key, None)
    path = save_config(payload)
    return {"key": key, "path": str(path)}


def effective_server(explicit: str | None = None) -> str:
    config = load_config()
    return resolve_base_url(explicit, configured=config.get("server"))


def runtime_details() -> dict:
    return discover_service_manifest() or {}
