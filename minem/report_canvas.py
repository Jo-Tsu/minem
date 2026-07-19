"""Derived page versions for report-specific canvas normalization."""

from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
from urllib.parse import quote


def _declared_path(extracted_root: Path, asset) -> Path | None:
    upload_id = str(asset["upload_id"] or "").strip()
    rel = str(asset["source_path"] or "").strip().lstrip("/")
    if not upload_id or not rel:
        return None
    path = (extracted_root / upload_id / rel).resolve()
    upload_root = (extracted_root / upload_id).resolve()
    return path if path.is_relative_to(upload_root) else None


def _source_path(extracted_root: Path, asset) -> Path | None:
    path = _declared_path(extracted_root, asset)
    return path if path and path.is_file() else None


def _relative_source_url(target: Path, source: Path) -> str:
    """Use one URL that works in both HTTP previews and file-based screenshots."""
    relative = Path(os.path.relpath(source, target.parent)).as_posix()
    return f"{quote(relative, safe='/.:-_')}?embed=1"


def _derived_html(source_url: str, title: str, target_width: int, target_height: int, source_width: int, source_height: int) -> str:
    scale_x = target_width / max(source_width, 1)
    scale_y = target_height / max(source_height, 1)
    return f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>{html.escape(title, quote=True)}</title>
<style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#030712}}
.material-control-stage{{position:relative;width:{target_width}px;height:{target_height}px;overflow:hidden;background:#030712}}
.minem-normalized-source{{position:absolute;inset:0;width:{source_width}px;height:{source_height}px;border:0;transform:scale({scale_x:.10f},{scale_y:.10f});transform-origin:top left}}
</style></head><body>
<main class=\"material-control-stage\" data-minem-normalized-canvas=\"true\"><iframe class=\"minem-normalized-source\" src=\"{html.escape(source_url, quote=True)}\" title=\"{html.escape(title, quote=True)}\"></iframe></main>
<script>const DESIGN_W={target_width};const DESIGN_H={target_height};</script>
</body></html>"""


def normalize_report_page_canvases(
    conn,
    report_id: str,
    *,
    extracted_root: Path,
    detect_dimensions,
    now_ms,
    next_candidate_asset_code,
    next_asset_version_no,
    merge_tags,
    read_text_sample,
):
    """Create/reuse report-targeted control versions and repoint only this report's slots."""
    report = conn.execute("select * from assets where id = ? and asset_type = 'report'", (report_id,)).fetchone()
    if not report:
        return {"normalized": 0, "reused": 0, "created": [], "replacements": {}}
    report_path = _source_path(extracted_root, report)
    target_width, target_height = detect_dimensions(report_path) if report_path else (1920, 1080)
    if not target_width or not target_height:
        target_width, target_height = 1920, 1080
    timestamp = now_ms()
    replacements = {}
    created = []
    refreshed = []
    reused = 0
    slots = conn.execute(
        """
        select slot.page_number, slot.control_id, asset.*
        from report_page_slots slot
        join assets asset on asset.id = slot.control_id and asset.asset_type = 'control'
        where slot.report_id = ? and slot.control_id <> ''
        order by slot.page_number
        """,
        (report_id,),
    ).fetchall()
    for slot in slots:
        control = slot
        origin = conn.execute(
            """
            select source_control_id from report_page_normalizations
            where normalized_control_id = ?
            order by updated_at desc limit 1
            """,
            (control["id"],),
        ).fetchone()
        source_control_id = origin["source_control_id"] if origin else control["id"]
        source = conn.execute("select * from assets where id = ? and asset_type = 'control'", (source_control_id,)).fetchone() or control
        source_path = _source_path(extracted_root, source)
        if not source_path:
            continue
        source_width, source_height = detect_dimensions(source_path)
        if not source_width or not source_height:
            source_width, source_height = 1920, 1080
        if source_width == target_width and source_height == target_height:
            continue
        try:
            source_digest = hashlib.sha1(source_path.read_bytes()).hexdigest()
        except OSError:
            continue
        fingerprint = f"report-canvas-v1:{source_control_id}:{source_digest}:{target_width}x{target_height}"
        mapping = conn.execute(
            """
            select normalized_control_id, source_fingerprint from report_page_normalizations
            where report_id = ? and source_control_id = ? and target_width = ? and target_height = ?
            """,
            (report_id, source_control_id, target_width, target_height),
        ).fetchone()
        normalized = None
        if mapping and mapping["source_fingerprint"] == fingerprint:
            normalized = conn.execute("select * from assets where id = ? and asset_type = 'control'", (mapping["normalized_control_id"],)).fetchone()
        # A previous interrupted startup can leave the derived asset written
        # before its mapping row is committed. Source hashes are unique, so
        # recover that asset and backfill the mapping instead of failing or
        # creating another version.
        if not normalized:
            normalized = conn.execute(
                "select * from assets where asset_type = 'control' and source_hash = ? limit 1",
                (fingerprint,),
            ).fetchone()
        if normalized:
            normalized_id = normalized["id"]
            reused += 1
            target = _declared_path(extracted_root, normalized)
        else:
            digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
            upload_id = str(report["upload_id"] or source["upload_id"] or "").strip()
            rel = f"_minem_normalized/{report_id}/{source_control_id}-{target_width}x{target_height}-{digest}/index.html"
            target = (extracted_root / upload_id / rel).resolve()
            upload_root = (extracted_root / upload_id).resolve()
            if not target.is_relative_to(upload_root):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            normalized_id = f"canvas-{report_id}-{source_control_id}-{digest}"
        if not target:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source_url = _relative_source_url(target, source_path)
        derived_html = _derived_html(source_url, source["title"], target_width, target_height, source_width, source_height)
        try:
            wrapper_changed = not target.is_file() or target.read_text(encoding="utf-8") != derived_html
        except OSError:
            wrapper_changed = True
        if wrapper_changed:
            target.write_text(derived_html, encoding="utf-8")
        if not normalized:
            code = next_candidate_asset_code(conn, source["asset_code"])
            version_group = source["version_group"] or source["id"]
            tags = merge_tags(source["tags"], ["汇报尺寸适配", f"目标画布:{target_width}x{target_height}"])
            conn.execute(
                """
                insert into assets
                (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, source_path, preview_url, upload_id, source_hash, version_group, version_no, version_parent_id, similarity_score, similarity_method, tag_seeded, created_at, updated_at)
                values (?, ?, 'page', ?, ?, ?, 'control', ?, 'html', '', 'report-canvas-normalized', ?, ?, ?, ?, ?, ?, ?, 1.0, 'report-canvas-normalized', 1, ?, ?)
                """,
                (
                    normalized_id,
                    source["title"],
                    f"为汇报 {report['asset_code']} 适配 {target_width}×{target_height} 画布的页面版本。",
                    ",".join(tags),
                    read_text_sample(target),
                    code,
                    rel,
                    f"/extracted/{upload_id}/{rel}",
                    upload_id,
                    fingerprint,
                    version_group,
                    next_asset_version_no(conn, version_group),
                    source_control_id,
                    timestamp,
                    timestamp,
                ),
            )
            created.append({"id": normalized_id, "path": target, "fingerprint": fingerprint})
        elif wrapper_changed:
            refreshed.append({"id": normalized_id, "path": target, "fingerprint": fingerprint})
        conn.execute(
            """
            insert into report_page_normalizations
            (report_id, source_control_id, normalized_control_id, target_width, target_height, source_width, source_height, source_fingerprint, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(report_id, source_control_id, target_width, target_height) do update set
              normalized_control_id=excluded.normalized_control_id,
              source_width=excluded.source_width,
              source_height=excluded.source_height,
              source_fingerprint=excluded.source_fingerprint,
              updated_at=excluded.updated_at
            """,
            (report_id, source_control_id, normalized_id, target_width, target_height, source_width, source_height, fingerprint, timestamp, timestamp),
        )
        if control["id"] != normalized_id:
            replacements[control["id"]] = normalized_id
            conn.execute(
                "update report_page_slots set control_id = ?, note = ?, updated_at = ? where report_id = ? and page_number = ?",
                (normalized_id, f"汇报尺寸适配 {target_width}x{target_height}", timestamp, report_id, slot["page_number"]),
            )
    refreshed_ids = {item["id"] for item in refreshed}
    historical_mappings = conn.execute(
        """
        select source_control_id, normalized_control_id, target_width, target_height, source_width, source_height, source_fingerprint
        from report_page_normalizations where report_id = ?
        """,
        (report_id,),
    ).fetchall()
    for mapping in historical_mappings:
        normalized_id = mapping["normalized_control_id"]
        if normalized_id in refreshed_ids or any(item["id"] == normalized_id for item in created):
            continue
        source = conn.execute("select * from assets where id = ? and asset_type = 'control'", (mapping["source_control_id"],)).fetchone()
        normalized = conn.execute("select * from assets where id = ? and asset_type = 'control'", (normalized_id,)).fetchone()
        if not source or not normalized:
            continue
        source_path = _source_path(extracted_root, source)
        target = _declared_path(extracted_root, normalized)
        if not source_path or not target:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        derived_html = _derived_html(
            _relative_source_url(target, source_path),
            source["title"],
            int(mapping["target_width"] or 1920),
            int(mapping["target_height"] or 1080),
            int(mapping["source_width"] or 1920),
            int(mapping["source_height"] or 1080),
        )
        try:
            wrapper_changed = not target.is_file() or target.read_text(encoding="utf-8") != derived_html
        except OSError:
            wrapper_changed = True
        if wrapper_changed:
            target.write_text(derived_html, encoding="utf-8")
            refreshed.append({"id": normalized_id, "path": target, "fingerprint": mapping["source_fingerprint"]})
            refreshed_ids.add(normalized_id)
    if replacements:
        row = conn.execute("select * from report_page_arrangements where report_id = ?", (report_id,)).fetchone()
        if row:
            try:
                page_order = [replacements.get(item, item) for item in json.loads(row["page_order"])]
                hidden = [replacements.get(item, item) for item in json.loads(row["hidden_page_ids"])]
            except (TypeError, ValueError, json.JSONDecodeError):
                page_order, hidden = [], []
            conn.execute(
                "update report_page_arrangements set page_order = ?, hidden_page_ids = ?, updated_at = ? where report_id = ?",
                (json.dumps(list(dict.fromkeys(page_order))), json.dumps(list(dict.fromkeys(hidden))), timestamp, report_id),
            )
        conn.execute("update assets set updated_at = ? where id = ?", (timestamp, report_id))
    return {
        "normalized": len(replacements),
        "reused": reused,
        "created": created,
        "refreshed": refreshed,
        "replacements": replacements,
        "target": [target_width, target_height],
    }
