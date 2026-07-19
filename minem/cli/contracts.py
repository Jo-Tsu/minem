"""Stable CLI result and error contracts."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from . import SCHEMA_VERSION


EXIT_FAILURE = 1
EXIT_ARGUMENT = 2
EXIT_CONNECTION = 3
EXIT_CONFIRMATION = 4


@dataclass
class CliError(Exception):
    code: str
    message: str
    details: Any = None
    exit_code: int = EXIT_FAILURE

    def __str__(self) -> str:
        return self.message


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:20]}"


def absolute_url(base_url: str, value: str | None) -> str:
    if not value:
        return ""
    return urljoin(f"{base_url.rstrip('/')}/", str(value).lstrip("/"))


def normalize_asset(asset: dict[str, Any] | None, base_url: str = "") -> dict[str, Any] | None:
    if not asset:
        return None
    asset_type = asset.get("asset_type") or asset.get("assetType") or asset.get("type") or ""
    if asset_type == "control":
        asset_type = "page"
    preview = asset.get("preview_url") or asset.get("previewUrl") or ""
    return {
        "id": asset.get("id") or asset.get("assetId") or "",
        "code": asset.get("asset_code") or asset.get("assetCode") or "",
        "type": asset_type,
        "title": asset.get("title") or asset.get("assetTitle") or "",
        "previewUrl": absolute_url(base_url, preview) if base_url else preview,
        "version": asset.get("version_no") or asset.get("versionNo") or 1,
        "updatedAt": asset.get("activity_at") or asset.get("updated_at") or asset.get("updatedAt") or 0,
    }


def success(
    command: str,
    request_id: str,
    server_url: str,
    started_at: float,
    *,
    resource: dict[str, Any] | None = None,
    data: Any = None,
    links: dict[str, str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "command": command,
        "requestId": request_id,
        "resource": resource,
        "data": {} if data is None else data,
        "links": links or {},
        "warnings": warnings or [],
        "meta": {
            "durationMs": round((time.monotonic() - started_at) * 1000),
            "serverUrl": server_url,
        },
        "error": None,
    }


def failure(
    command: str,
    request_id: str,
    server_url: str,
    started_at: float,
    error: CliError,
) -> dict[str, Any]:
    detail = {"code": error.code, "message": error.message}
    if error.details is not None:
        detail["details"] = error.details
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": False,
        "command": command,
        "requestId": request_id,
        "resource": None,
        "data": {},
        "links": {},
        "warnings": [],
        "meta": {
            "durationMs": round((time.monotonic() - started_at) * 1000),
            "serverUrl": server_url,
        },
        "error": detail,
    }
