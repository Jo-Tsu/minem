#!/usr/bin/env python3
"""Govern MineM material data without deleting displayable assets.

The script enforces the PRD data rules:
- RPT/CTRL/RES prefixes stay aligned with report/control/resource types.
- Directly imported HTML bundles keep parent shared assets needed for preview.
- Duplicated resources become versions instead of being physically deleted.
- Auto-scanned duplicate pages are folded under canonical page versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
ROOT = Path(__file__).resolve().parents[1]
EXTRACTED = ROOT / "extracted"


class RefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: list[tuple[str, str]] = []
        self.base_href = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag == "base" and attrs_dict.get("href"):
            self.base_href = attrs_dict["href"]
        for name in ("src", "poster"):
            value = attrs_dict.get(name)
            if value:
                self.refs.append((name, value))
        if tag == "link":
            value = attrs_dict.get("href")
            if value:
                self.refs.append(("href", value))
        srcset = attrs_dict.get("srcset")
        if srcset:
            for part in srcset.split(","):
                value = part.strip().split(" ")[0]
                if value:
                    self.refs.append(("srcset", value))


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_path_from_usage(usage: str) -> Path | None:
    match = re.search(r"自动导入：(.+)$", usage or "")
    if not match:
        return None
    path = Path(match.group(1).strip())
    return path if path.exists() and path.is_file() else None


def asset_path(row) -> Path | None:
    path = server.asset_library_path(row)
    if path and path.exists():
        return path
    preview_url = str(row["preview_url"] or "").split("?", 1)[0]
    if preview_url.startswith("/extracted/"):
        candidate = (ROOT / preview_url.lstrip("/")).resolve()
        if server.is_path_within(candidate, EXTRACTED):
            return candidate
    return None


def is_external_reference(value: str) -> bool:
    value = (value or "").strip()
    if not value or value in {".", "..", "...", "location.href"} or value.startswith(("#", "data:", "mailto:", "tel:", "javascript:", "var(")):
        return True
    parsed = urlparse(value)
    return bool(parsed.scheme or parsed.netloc)


def base_dir_for_html(html_path: Path, parser: RefParser) -> Path:
    href = (parser.base_href or "").strip()
    if not href or is_external_reference(href):
        return html_path.parent
    parsed = urlparse(href)
    path = unquote(parsed.path or href)
    if path.startswith("/"):
        return (ROOT / path.lstrip("/")).resolve()
    return (html_path.parent / path).resolve()


def local_ref_path(html_path: Path, base_dir: Path, value: str) -> Path | None:
    if is_external_reference(value):
        return None
    parsed = urlparse(value)
    path_text = unquote(parsed.path or value)
    if not path_text:
        return None
    if path_text.startswith("/"):
        candidate = (ROOT / path_text.lstrip("/")).resolve()
    else:
        candidate = (base_dir / path_text).resolve()
    if not server.is_path_within(candidate, ROOT):
        return None
    return candidate


def html_missing_refs(row) -> list[str]:
    path = asset_path(row)
    if not path or path.suffix.lower() not in {".html", ".htm"}:
        return []
    # Audit the selected page rather than the entire upload directory. A legacy
    # import can contain unrelated stale bundles; treating their missing files
    # as errors for every page created misleading data failures and duplicate
    # repairs.
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    parser = RefParser()
    parser.feed(text[:2_000_000])
    refs = list(parser.refs)
    css_text = re.sub(r"/\*.*?\*/", "", text[:2_000_000], flags=re.S)
    refs.extend(("css-url", match.group(1).strip("'\"")) for match in re.finditer(r"url\(([^)]+)\)", css_text, re.I))
    base_dir = base_dir_for_html(path, parser)
    missing = []
    for _, value in refs[:1000]:
        candidate = local_ref_path(path, base_dir, value)
        if candidate and not candidate.exists():
            missing.append(value)
    return missing


def repair_auto_html_bundles(conn) -> tuple[int, list[str]]:
    repaired = 0
    touched: list[str] = []
    rows = conn.execute(
        """
        select * from assets
        where media_kind = 'html'
          and source_type = 'auto'
          and upload_id <> ''
        order by created_at
        """
    ).fetchall()
    for row in rows:
        original = source_path_from_usage(row["usage"])
        if not original:
            continue
        before_missing = html_missing_refs(row)
        if not before_missing:
            continue
        target_root = server.EXTRACTED / row["upload_id"]
        digest = hashlib.sha1(str(original.resolve()).encode("utf-8")).hexdigest()[:10]
        _, rel = server.copy_html_dependency_bundle(original, target_root, digest)
        new_path = (target_root / rel).resolve()
        if not new_path.exists():
            continue
        conn.execute(
            """
            update assets
            set source_path = ?, preview_url = ?, snippet = ?, updated_at = ?
            where id = ?
            """,
            (
                rel,
                f"/extracted/{row['upload_id']}/{rel}",
                server.read_text_sample(new_path),
                server.now_ms(),
                row["id"],
            ),
        )
        repaired += 1
        touched.append(row["id"])
    return repaired, touched


def repair_superclub_report_entries(conn) -> tuple[int, list[str]]:
    repaired = 0
    touched: list[str] = []
    rows = conn.execute(
        """
        select * from assets
        where asset_type = 'report'
          and asset_code like 'RPT-%'
        """
    ).fetchall()
    timestamp = server.now_ms()
    for row in rows:
        if row["source_type"] != "auto":
            continue
        code = row["asset_code"]
        canonical_rel = f"30-report-material-library/{code}/index.html"
        canonical_path = server.EXTRACTED / "superclub" / canonical_rel
        if not canonical_path.exists():
            continue
        current = asset_path(row)
        current_ok = bool(current and current.exists() and current.resolve() == canonical_path.resolve())
        if current_ok and row["trusted_entry_ok"]:
            continue
        source_hash = f"sync-report:superclub:{file_sha1(canonical_path)}"
        conflict = conn.execute(
            "select id from assets where source_hash = ? and id <> ? limit 1",
            (source_hash, row["id"]),
        ).fetchone()
        if conflict:
            source_hash = f"{source_hash}:{row['id']}"
        tags = server.merge_tags(
            row["tags"],
            ["汇报素材", "完整汇报", "HTML 汇报", "案例素材"] if "HENGAN" in code else ["汇报素材", "完整汇报", "HTML 汇报"],
        )
        conn.execute(
            """
            update assets
            set category = 'report',
                source_type = ?,
                source_path = ?,
                preview_url = ?,
                upload_id = 'superclub',
                source_hash = ?,
                tags = ?,
                snippet = ?,
                updated_at = ?
            where id = ?
            """,
            (
                "case-material-generator" if "HENGAN" in code else "report-material-sync",
                canonical_rel,
                f"/extracted/superclub/{canonical_rel}",
                source_hash,
                ",".join(tags),
                server.read_text_sample(canonical_path),
                timestamp,
                row["id"],
            ),
        )
        try:
            server.validate_report_trusted_entry(conn, row["id"], refresh=True)
        except Exception:
            pass
        repaired += 1
        touched.append(row["id"])
    return repaired, touched


def source_priority(row) -> tuple[int, int, int, int, str]:
    source_type = row["source_type"] or ""
    code = row["asset_code"] or ""
    priority = {
        "case-material-generator": 0,
        "case-material-sync": 0,
        "report-material-sync": 1,
        "created-report-page": 2,
        "control-resource": 2,
        "upload": 3,
        "template": 3,
        "manual": 3,
        "report-material-candidate": 7,
        "auto": 9,
    }.get(source_type, 5)
    generic_ctrl_page = 1 if re.match(r"^CTRL-PAGE-\d+$", code) and source_type == "auto" else 0
    version_child = 1 if row["version_parent_id"] else 0
    return (priority, generic_ctrl_page, version_child, int(row["created_at"] or 0), code)


def next_group_version_no(conn, version_group: str) -> int:
    row = conn.execute(
        "select coalesce(max(version_no), 0) + 1 from assets where version_group = ?",
        (version_group,),
    ).fetchone()
    return int(row[0] or 1)


def merge_duplicate_versions(conn, asset_type: str, *, auto_controls_only: bool = False) -> tuple[int, int]:
    rows = conn.execute(
        "select * from assets where asset_type = ? and source_path <> ''",
        (asset_type,),
    ).fetchall()
    by_digest: dict[str, list] = {}
    for row in rows:
        path = asset_path(row)
        if not path or not path.exists() or not path.is_file():
            continue
        by_digest.setdefault(file_sha1(path), []).append(row)

    groups = 0
    merged = 0
    timestamp = server.now_ms()
    for digest, items in by_digest.items():
        if len(items) < 2:
            continue
        if auto_controls_only and not any(item["source_type"] == "auto" for item in items):
            continue
        primary = sorted(items, key=source_priority)[0]
        version_group = primary["version_group"] or primary["id"]
        group_changed = False
        primary_tags = ""
        primary_method = primary["similarity_method"] if str(primary["similarity_method"] or "").startswith("manual-") else "system-dedupe-primary"
        primary_updated_at = max(int(item["updated_at"] or 0) for item in items)
        if (
            primary["version_group"] != version_group
            or int(primary["version_no"] or 0) != 1
            or primary["version_parent_id"] != ""
            or primary["tags"] != primary_tags
            or primary["similarity_method"] != primary_method
        ):
            conn.execute(
                """
                update assets
                set version_group = ?,
                    version_no = 1,
                    version_parent_id = '',
                    similarity_score = 1.0,
                    similarity_method = ?,
                    tags = ?,
                    updated_at = ?
                where id = ?
                """,
                (version_group, primary_method, primary_tags, primary_updated_at, primary["id"]),
            )
            group_changed = True
        version_no = 2
        for item in sorted((item for item in items if item["id"] != primary["id"]), key=source_priority):
            child_tags = ""
            child_method = item["similarity_method"] if str(item["similarity_method"] or "").startswith("manual-") else "system-dedupe-version"
            if (
                item["version_group"] != version_group
                or int(item["version_no"] or 0) != version_no
                or item["version_parent_id"] != primary["id"]
                or item["tags"] != child_tags
                or item["similarity_method"] != child_method
            ):
                conn.execute(
                    """
                    update assets
                    set version_group = ?,
                        version_no = ?,
                        version_parent_id = ?,
                        similarity_score = 1.0,
                        similarity_method = ?,
                        tags = ?,
                        updated_at = ?
                    where id = ?
                    """,
                    (version_group, version_no, primary["id"], child_method, child_tags, timestamp, item["id"]),
                )
                group_changed = True
                merged += 1
            version_no += 1
        if group_changed:
            groups += 1
    return groups, merged


def audit(conn) -> dict:
    rows = conn.execute("select * from assets order by updated_at desc").fetchall()
    prefix_bad = []
    missing_files = []
    html_ref_issues = []
    for row in rows:
        code = row["asset_code"] or ""
        if code.startswith("RPT-") and row["asset_type"] != "report":
            prefix_bad.append([code, row["asset_type"]])
        if code.startswith("CTRL-") and row["asset_type"] != "control":
            prefix_bad.append([code, row["asset_type"]])
        if code.startswith("RES-") and row["asset_type"] != "resource":
            prefix_bad.append([code, row["asset_type"]])
        path = asset_path(row)
        if row["source_path"] and (not path or not path.exists()):
            missing_files.append([code, row["asset_type"], row["upload_id"], row["source_path"]])
        if row["media_kind"] == "html":
            missing = html_missing_refs(row)
            if missing:
                html_ref_issues.append([code, row["asset_type"], row["source_path"], missing[:12], len(missing)])
    return {
        "assetCount": len(rows),
        "prefixBad": prefix_bad,
        "missingFiles": missing_files,
        "htmlRefIssues": html_ref_issues,
    }


def refresh_touched_thumbnails(conn, asset_ids: list[str]) -> int:
    refreshed = 0
    for asset_id in sorted(set(asset_ids)):
        row = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not row or row["media_kind"] != "html":
            continue
        path = asset_path(row)
        if not path or not path.exists():
            continue
        fingerprint = server.thumbnail_source_fingerprint(dict(row))
        if server.generate_html_thumbnail(row["id"], path, fingerprint, allow_text_fallback=True):
            refreshed += 1
    return refreshed


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit MineM material data; pass --apply to perform repairs.")
    parser.add_argument("--apply", action="store_true", help="Apply repairs after reviewing the read-only audit output.")
    args = parser.parse_args()
    with server.db() as conn:
        before = audit(conn)
        if not args.apply:
            print(json.dumps({
                "apply": False,
                "assetCount": before["assetCount"],
                "prefixBad": len(before["prefixBad"]),
                "missingFiles": len(before["missingFiles"]),
                "htmlRefIssues": len(before["htmlRefIssues"]),
                "htmlRefSample": before["htmlRefIssues"][:12],
            }, ensure_ascii=False, indent=2))
            return
        bundle_count, bundle_touched = repair_auto_html_bundles(conn)
        report_count, report_touched = repair_superclub_report_entries(conn)
        resource_groups, resource_merged = merge_duplicate_versions(conn, "resource")
        control_groups, control_merged = merge_duplicate_versions(conn, "control")
        for row in conn.execute("select id from assets where asset_type = 'report'").fetchall():
            try:
                server.validate_report_trusted_entry(conn, row["id"], refresh=True)
            except Exception:
                pass
        touched = bundle_touched + report_touched
        refreshed = refresh_touched_thumbnails(conn, touched)
        conn.execute("update uploads set asset_count = (select count(*) from assets where assets.upload_id = uploads.id)")
        after = audit(conn)
    print(json.dumps({
        "apply": True,
        "before": {
            "assetCount": before["assetCount"],
            "prefixBad": len(before["prefixBad"]),
            "missingFiles": len(before["missingFiles"]),
            "htmlRefIssues": len(before["htmlRefIssues"]),
        },
        "repair": {
            "autoHtmlBundles": bundle_count,
            "superclubReports": report_count,
            "resourceDuplicateGroups": resource_groups,
            "resourceMergedVersions": resource_merged,
            "controlDuplicateGroups": control_groups,
            "controlMergedVersions": control_merged,
            "refreshedThumbnails": refreshed,
        },
        "after": {
            "assetCount": after["assetCount"],
            "prefixBad": len(after["prefixBad"]),
            "missingFiles": len(after["missingFiles"]),
            "htmlRefIssues": len(after["htmlRefIssues"]),
            "htmlRefSample": after["htmlRefIssues"][:12],
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
