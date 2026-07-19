"""Discover a MineM desktop runtime without coupling clients to a fixed port."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_BASE_URL = "http://127.0.0.1:8790"


def candidate_data_roots():
    override = os.environ.get("MINEM_DATA_DIR", "").strip()
    if override:
        yield Path(override).expanduser()
    home = Path.home()
    yield home / "Library" / "Application Support" / "MineM"
    yield home / "Library" / "Application Support" / "com.minem.materialos"


def read_service_manifest(data_root: Path):
    path = data_root / "runtime" / "service.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if payload.get("status") != "running" or payload.get("managedByClient") is not True:
        return None
    base_url = str(payload.get("baseUrl") or "").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
        return None
    return {**payload, "baseUrl": base_url, "manifestPath": str(path)}


def discover_service_manifest():
    seen = set()
    for root in candidate_data_roots():
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        manifest = read_service_manifest(root)
        if manifest:
            return manifest
    return None


def resolve_base_url(explicit=None, configured=None):
    if explicit:
        return str(explicit).rstrip("/")
    environment = os.environ.get("MINEM_BASE_URL", "").strip()
    if environment:
        return environment.rstrip("/")
    if configured:
        return str(configured).rstrip("/")
    manifest = discover_service_manifest()
    if manifest:
        return manifest["baseUrl"]
    return DEFAULT_BASE_URL
