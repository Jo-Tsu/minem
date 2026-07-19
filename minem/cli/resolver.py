"""Resolve MineM assets by internal ID, public code, or URL."""

from __future__ import annotations

import urllib.parse
from typing import Any

from .contracts import CliError


TYPE_TO_API = {"page": "control", "control": "control", "report": "report", "resource": "resource"}


def _url_id(reference: str) -> str:
    parsed = urllib.parse.urlsplit(reference)
    path = parsed.path if parsed.scheme or parsed.netloc else reference
    parts = [urllib.parse.unquote(item) for item in path.split("/") if item]
    if len(parts) >= 2 and parts[0] in {"pages", "reports"}:
        return parts[1]
    return ""


def _asset_type(asset: dict[str, Any]) -> str:
    return str(asset.get("asset_type") or asset.get("assetType") or "")


def resolve_asset(client, reference: str, expected_type: str | None = None) -> dict[str, Any]:
    reference = str(reference or "").strip()
    if not reference:
        raise CliError("INVALID_ARGUMENT", "Asset reference is required", exit_code=2)
    api_type = TYPE_TO_API.get(expected_type or "", expected_type or "")
    direct_id = _url_id(reference) or reference
    if "/" not in direct_id and not direct_id.upper().startswith(("RPT-", "CTRL-", "RES-")):
        try:
            payload = client.request("GET", f"/api/assets/{urllib.parse.quote(direct_id)}")
            asset = payload.get("asset") or {}
            if asset and (not api_type or _asset_type(asset) == api_type):
                return asset
        except CliError as error:
            if error.code != "NOT_FOUND":
                raise

    query = urllib.parse.urlencode({
        "type": api_type or "all",
        "q": reference,
        "include_versions": "1",
        "page": "1",
        "page_size": "200",
        "view": "list",
    })
    payload = client.request("GET", f"/api/assets?{query}")
    candidates = payload.get("assets") or []
    normalized_reference = reference.rstrip("/").lower()
    parsed_path = urllib.parse.urlsplit(reference).path.rstrip("/").lower()

    def is_exact(asset):
        values = {
            str(asset.get("id") or "").rstrip("/").lower(),
            str(asset.get("asset_code") or asset.get("assetCode") or "").rstrip("/").lower(),
            str(asset.get("preview_url") or asset.get("previewUrl") or "").rstrip("/").lower(),
            str(asset.get("source_path") or asset.get("sourcePath") or "").rstrip("/").lower(),
        }
        return normalized_reference in values or (parsed_path and parsed_path in values)

    exact = [asset for asset in candidates if is_exact(asset)]
    matches = exact or candidates
    if len(matches) == 1:
        asset = matches[0]
        if api_type and _asset_type(asset) != api_type:
            raise CliError("TYPE_MISMATCH", f"{reference} is not a {expected_type} asset")
        return asset
    if not matches:
        raise CliError("NOT_FOUND", f"Asset not found: {reference}")
    raise CliError(
        "AMBIGUOUS_REFERENCE",
        f"Asset reference matches {len(matches)} records: {reference}",
        details={
            "candidates": [
                {"id": item.get("id"), "code": item.get("asset_code") or item.get("assetCode"), "title": item.get("title")}
                for item in matches[:20]
            ]
        },
    )


def resolve_assets(client, references: list[str], expected_type: str | None = None) -> list[dict[str, Any]]:
    resolved = []
    seen = set()
    for reference in references:
        asset = resolve_asset(client, reference, expected_type)
        if asset.get("id") not in seen:
            resolved.append(asset)
            seen.add(asset.get("id"))
    return resolved
