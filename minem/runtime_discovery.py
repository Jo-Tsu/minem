"""Discover a MineM desktop runtime without coupling clients to a fixed port."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from minem.security import is_loopback_url, read_session_token


DEFAULT_BASE_URL = "http://127.0.0.1:8790"


def loopback_endpoint(value: str):
    try:
        parsed = urlparse(str(value or "").rstrip("/"))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    return parsed.scheme, port


def same_loopback_endpoint(left: str, right: str) -> bool:
    left_endpoint = loopback_endpoint(left)
    return bool(left_endpoint and left_endpoint == loopback_endpoint(right))


def candidate_data_roots():
    override = os.environ.get("MINEM_DATA_DIR", "").strip()
    if override:
        yield Path(override).expanduser()

    home = Path.home()
    yield home / "Library" / "Application Support" / "MineM"
    # Compatibility with early Tauri builds that used the bundle identifier.
    yield home / "Library" / "Application Support" / "com.minem.materialos"


def process_is_running(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def read_session_manifest(data_root: Path):
    path = data_root / "runtime" / "session.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    base_url = str(payload.get("baseUrl") or "").rstrip("/")
    if payload.get("status") != "running" or not loopback_endpoint(base_url):
        return None
    if not process_is_running(payload.get("pid")):
        return None
    return {**payload, "baseUrl": base_url, "manifestPath": str(path)}


def read_service_manifest(data_root: Path):
    path = data_root / "runtime" / "service.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if payload.get("status") != "running":
        return None
    if payload.get("managedByClient") is not True:
        return None
    base_url = str(payload.get("baseUrl") or "").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return None
    if not parsed.port:
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


def resolve_session_token(base_url: str) -> str:
    environment = os.environ.get("MINEM_SESSION_TOKEN", "").strip()
    if environment:
        return environment
    if not is_loopback_url(base_url):
        return ""

    for root in candidate_data_roots():
        manifest = read_session_manifest(root)
        if manifest and same_loopback_endpoint(manifest["baseUrl"], base_url):
            token = read_session_token(root / "runtime" / "session-token")
            if token:
                return token

    source_root = Path(__file__).resolve().parents[1]
    manifest = read_session_manifest(source_root)
    if manifest and same_loopback_endpoint(manifest["baseUrl"], base_url):
        return read_session_token(source_root / "runtime" / "session-token")
    return ""


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


def service_is_ready(base_url: str, timeout: float = 0.5) -> bool:
    try:
        with urlopen(base_url.rstrip("/") + "/api/version", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    release = payload.get("release") if isinstance(payload, dict) else None
    return response.status == 200 and isinstance(release, dict) and release.get("product") == "MineM"


def resolve_or_launch_base_url(explicit=None, timeout: float = 30.0, poll_interval: float = 0.2):
    if explicit or os.environ.get("MINEM_BASE_URL", "").strip():
        return resolve_base_url(explicit)

    manifest = discover_service_manifest()
    if manifest and service_is_ready(manifest["baseUrl"]):
        return manifest["baseUrl"]

    if sys.platform != "darwin":
        return DEFAULT_BASE_URL
    try:
        launched = subprocess.run(
            ["open", "-gj", "-a", "MineM"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return DEFAULT_BASE_URL
    if launched.returncode != 0:
        return DEFAULT_BASE_URL

    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        manifest = discover_service_manifest()
        if manifest and service_is_ready(manifest["baseUrl"]):
            return manifest["baseUrl"]
        time.sleep(max(0.02, poll_interval))
    return DEFAULT_BASE_URL
