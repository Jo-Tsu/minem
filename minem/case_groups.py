"""Case-group discovery backed by imported manifests and material records."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


CASE_LIBRARY_DIR = "20-case-control-library"
CASE_DATE_RE = re.compile(r"-(\d{8})-(?:\d+)$")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _manifest_paths(extracted_root: Path, source_roots: Iterable[Path]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    search_roots = [extracted_root, *source_roots]
    for root in search_roots:
        root = Path(root).expanduser().resolve()
        candidates: Iterable[Path]
        direct = root / CASE_LIBRARY_DIR
        if direct.is_dir():
            candidates = direct.glob("CASE-*/manifest.json")
        elif root.is_dir():
            candidates = root.glob(f"*/{CASE_LIBRARY_DIR}/CASE-*/manifest.json")
        else:
            continue
        for path in sorted(candidates):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(resolved)
    return paths


def _public_file_url(path: Path, extracted_root: Path) -> str:
    try:
        relative = path.resolve().relative_to(extracted_root.resolve())
    except ValueError:
        return ""
    return f"/extracted/{relative.as_posix()}" if path.is_file() else ""


def _resolve_manifest_path(manifest_path: Path, value: str, extracted_root: Path) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("/extracted/"):
        candidate = (extracted_root.parent / value.lstrip("/")).resolve()
        return value if candidate.is_file() else ""
    candidate = (manifest_path.parent / value).resolve()
    return _public_file_url(candidate, extracted_root)


def _date_from_code(code: str, fallback_ms: int) -> str:
    match = CASE_DATE_RE.search(code)
    if match:
        value = match.group(1)
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    from datetime import datetime

    return datetime.fromtimestamp(fallback_ms / 1000).strftime("%Y-%m-%d")


def _normalize_control(
    raw: dict[str, Any],
    manifest_path: Path,
    extracted_root: Path,
    asset_by_code: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    code = str(raw.get("code") or raw.get("control_code") or "").strip()
    asset = asset_by_code.get(code)
    if not code or not asset:
        return None
    control_url = str(asset.get("previewUrl") or "").strip()
    if not control_url:
        control_url = _resolve_manifest_path(
            manifest_path,
            str(raw.get("controlUrl") or raw.get("control_path") or raw.get("preview_path") or ""),
            extracted_root,
        )
    if not control_url:
        return None
    report_page_url = _resolve_manifest_path(
        manifest_path,
        str(raw.get("reportPageUrl") or raw.get("report_page") or raw.get("preview_path") or ""),
        extracted_root,
    ) or control_url
    ai = raw.get("ai") if isinstance(raw.get("ai"), dict) else None
    return {
        "id": str(raw.get("id") or raw.get("case_id") or code),
        "code": code,
        "award": str(raw.get("award") or raw.get("rank") or "案例页面"),
        "title": str(raw.get("title") or asset.get("title") or code),
        "scenario": str(raw.get("scenario") or "页面素材"),
        "sourceUrl": str(raw.get("sourceUrl") or raw.get("source_url") or ""),
        "controlUrl": control_url,
        "thumbnailUrl": str(asset.get("thumbnailUrl") or ""),
        "reportPageUrl": report_page_url,
        "summary": str(raw.get("summary") or "该案例页面已作为页面素材入库，可单独预览或插入汇报。"),
        "ai": ai,
    }


def _normalize_group(
    payload: dict[str, Any],
    manifest_path: Path,
    extracted_root: Path,
    asset_by_code: dict[str, dict[str, Any]],
    resource_paths: list[str],
) -> dict[str, Any] | None:
    code = str(payload.get("code") or payload.get("asset_code") or "").strip()
    if not code.startswith("CASE-"):
        return None
    raw_controls = payload.get("controls") or payload.get("cases") or []
    if not isinstance(raw_controls, list):
        return None
    controls = [
        control
        for raw in raw_controls
        if isinstance(raw, dict)
        for control in [_normalize_control(raw, manifest_path, extracted_root, asset_by_code)]
        if control
    ]
    if not controls:
        return None

    source_document = payload.get("source_document") if isinstance(payload.get("source_document"), dict) else {}
    report_material = payload.get("report_material") if isinstance(payload.get("report_material"), dict) else {}
    report_code = str(report_material.get("asset_code") or "").strip()
    report_asset = asset_by_code.get(report_code, {})
    entry_url = _public_file_url(manifest_path.parent / str(payload.get("entry") or "index.html"), extracted_root)
    report_url = str(payload.get("reportUrl") or report_asset.get("previewUrl") or entry_url)
    if report_url.startswith("/extracted/"):
        target = (extracted_root.parent / report_url.lstrip("/")).resolve()
        if not target.is_file():
            report_url = entry_url or controls[0]["controlUrl"]
    elif not report_url:
        report_url = entry_url or controls[0]["controlUrl"]

    resources = payload.get("resources") if isinstance(payload.get("resources"), list) else []
    related_resource_count = sum(1 for path in resource_paths if code in path)
    attachment_count = max(
        related_resource_count,
        len(resources),
        int(payload.get("attachmentCount") or 0),
    )
    modified_ms = int(manifest_path.stat().st_mtime * 1000)
    activity_ms = max(
        [modified_ms]
        + [int(asset_by_code.get(control["code"], {}).get("updatedAt") or 0) for control in controls]
    )
    brand = str(payload.get("brand") or "").strip()
    if not brand:
        title = str(payload.get("title") or code)
        brand = re.split(r"[「『\s]", title, maxsplit=1)[0] or "案例素材"
    return {
        "code": code,
        "title": str(payload.get("title") or code),
        "sourceDoc": str(payload.get("sourceDoc") or source_document.get("url") or ""),
        "detailUrl": str(payload.get("detailUrl") or entry_url or report_url),
        "reportUrl": report_url,
        "caseCount": len(controls),
        "controlCount": len(controls),
        "attachmentCount": attachment_count,
        "updatedAt": str(payload.get("updatedAt") or _date_from_code(code, modified_ms)),
        "updatedAtMs": activity_ms,
        "brand": brand,
        "controls": controls,
    }


def load_case_groups(
    extracted_root: Path,
    source_roots: Iterable[Path],
    asset_by_code: dict[str, dict[str, Any]],
    resource_paths: Iterable[str],
) -> list[dict[str, Any]]:
    """Return imported case groups whose page assets are actually available."""

    resources = [str(path or "") for path in resource_paths]
    by_code: dict[str, dict[str, Any]] = {}
    for manifest_path in _manifest_paths(extracted_root, source_roots):
        payload = _read_json(manifest_path)
        if not payload:
            continue
        group = _normalize_group(payload, manifest_path, extracted_root, asset_by_code, resources)
        if not group:
            continue
        current = by_code.get(group["code"])
        is_public = bool(_public_file_url(manifest_path, extracted_root))
        if current is None or (is_public and not current.get("_public", False)):
            group["_public"] = is_public
            by_code[group["code"]] = group

    groups = list(by_code.values())
    for group in groups:
        group.pop("_public", None)
    groups.sort(key=lambda item: (int(item.get("updatedAtMs") or 0), item["code"]), reverse=True)
    return groups
