from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import urlparse


TOKEN_BYTES = 32
API_TOKEN_HEADER = "X-MineM-Session-Token"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def atomic_write_private(path: str | Path, value: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def rotate_session_token(path: str | Path) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    atomic_write_private(path, token)
    return token


def read_session_token(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def token_matches(provided: str, expected: str) -> bool:
    provided = str(provided or "").strip()
    expected = str(expected or "").strip()
    return bool(provided and expected and secrets.compare_digest(provided, expected))


def request_token(headers) -> str:
    direct = str(headers.get(API_TOKEN_HEADER) or "").strip()
    if direct:
        return direct
    authorization = str(headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def is_loopback_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in LOOPBACK_HOSTS


def same_origin(value: str, expected_origin: str) -> bool:
    if not value:
        return False
    try:
        left = urlparse(value)
        right = urlparse(expected_origin)
    except ValueError:
        return False
    return (
        left.scheme == right.scheme
        and left.hostname == right.hostname
        and (left.port or (443 if left.scheme == "https" else 80))
        == (right.port or (443 if right.scheme == "https" else 80))
    )


def browser_write_origin_allowed(headers, expected_origin: str) -> bool:
    origin = str(headers.get("Origin") or "").strip()
    fetch_site = str(headers.get("Sec-Fetch-Site") or "").strip().lower()
    if origin:
        return same_origin(origin, expected_origin) and fetch_site in {"", "same-origin", "none"}
    # Non-browser clients normally omit both Origin and Sec-Fetch-Site and must
    # still provide the session token. A browser explicitly reporting a cross
    # site context is rejected even when an Origin header is missing.
    return fetch_site not in {"cross-site", "same-site"}


def session_bootstrap_allowed(headers, expected_origin: str) -> bool:
    fetch_mode = str(headers.get("Sec-Fetch-Mode") or "").strip().lower()
    fetch_dest = str(headers.get("Sec-Fetch-Dest") or "").strip().lower()
    fetch_site = str(headers.get("Sec-Fetch-Site") or "").strip().lower()
    referer = str(headers.get("Referer") or "").strip()
    return (
        fetch_mode == "navigate"
        and fetch_dest in {"document", "iframe"}
        and fetch_site in {"same-origin", "none"}
        and (not referer or same_origin(referer, expected_origin))
    )
