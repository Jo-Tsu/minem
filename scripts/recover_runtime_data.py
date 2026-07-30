#!/usr/bin/env python3
"""Merge a secondary MineM runtime into the primary runtime without duplicates."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sqlite3
from pathlib import Path


ASSET_COLUMNS = (
    "id",
    "title",
    "category",
    "usage",
    "tags",
    "snippet",
    "asset_type",
    "asset_code",
    "media_kind",
    "source_type",
    "source_path",
    "preview_url",
    "upload_id",
    "created_at",
    "updated_at",
    "source_hash",
    "version_group",
    "version_no",
    "version_parent_id",
    "similarity_score",
    "similarity_method",
    "resource_kind",
    "tag_seeded",
    "trusted_entry_ok",
    "trusted_entry_url",
    "trusted_page_count",
    "trusted_viewer_page_count",
    "trusted_hash",
    "trusted_size",
    "trusted_checked_at",
)
UPLOAD_COLUMNS = (
    "id",
    "filename",
    "stored_path",
    "extract_path",
    "file_count",
    "asset_count",
    "content_hash",
    "created_at",
)
CONTROL_CODE_PARTS = {
    "page": "PAGE",
    "storytelling": "PAGE",
    "proof": "PROOF",
    "workflow": "FLOW",
    "mock": "PAGE",
    "story": "STORY",
    "visual": "VIS",
    "code": "CODE",
}
RESOURCE_CODE_PARTS = {
    "image": "IMG",
    "video": "VID",
    "gif": "GIF",
    "svg": "SVG",
}


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma busy_timeout = 10000")
    if not read_only:
        connection.execute("pragma foreign_keys = on")
    return connection


def date_key(milliseconds: int) -> str:
    timestamp = max(int(milliseconds or 0), 0) / 1000
    try:
        return dt.datetime.fromtimestamp(timestamp).strftime("%Y%m%d")
    except (OverflowError, OSError, ValueError):
        return dt.datetime.now().strftime("%Y%m%d")


def code_prefix(row: dict) -> str:
    asset_type = row["asset_type"]
    if asset_type == "report":
        return f"RPT-{date_key(row['created_at'])}"
    if asset_type == "resource":
        kind = RESOURCE_CODE_PARTS.get(row["media_kind"], "FILE")
        return f"RES-{kind}-{date_key(row['created_at'])}"
    return f"CTRL-{CONTROL_CODE_PARTS.get(row['category'], 'GEN')}"


def allocate_code(row: dict, used_codes: set[str]) -> str:
    desired = str(row.get("asset_code") or "").strip()
    if desired and desired not in used_codes:
        used_codes.add(desired)
        return desired
    prefix = code_prefix(row)
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    current = 0
    for code in used_codes:
        match = pattern.match(code)
        if match:
            current = max(current, int(match.group(1)))
    while True:
        current += 1
        candidate = f"{prefix}-{current:03d}"
        if candidate not in used_codes:
            used_codes.add(candidate)
            return candidate


def safe_runtime_path(root: Path, recorded_path: str) -> Path:
    relative = Path(str(recorded_path or "").strip())
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid runtime path: {recorded_path!r}")
    resolved = (root / relative).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def copy_runtime_item(source_root: Path, target_root: Path, recorded_path: str) -> bool:
    source = safe_runtime_path(source_root, recorded_path)
    target = safe_runtime_path(target_root, recorded_path)
    if not source.exists():
        raise FileNotFoundError(f"missing runtime file: {source}")
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return True


def mapped_json_list(value: str, asset_map: dict[str, str]) -> str:
    try:
        items = json.loads(value or "[]")
    except (TypeError, ValueError):
        items = []
    if not isinstance(items, list):
        items = []
    return json.dumps([asset_map.get(str(item), str(item)) for item in items], ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="perform the merge; default is a dry run")
    args = parser.parse_args()

    source_root = args.source_root.expanduser().resolve()
    target_root = args.target_root.expanduser().resolve()
    source_db_path = source_root / "data" / "materials.db"
    target_db_path = target_root / "data" / "materials.db"
    if source_db_path == target_db_path:
        raise SystemExit("source and target runtimes must be different")
    if not source_db_path.is_file() or not target_db_path.is_file():
        raise SystemExit("both runtimes must contain data/materials.db")

    source = connect(source_db_path, read_only=True)
    target = connect(target_db_path)
    source_uploads = {
        row["id"]: dict(row)
        for row in source.execute("select * from uploads").fetchall()
    }
    target_uploads = {
        row["id"]: dict(row)
        for row in target.execute("select * from uploads").fetchall()
    }
    source_assets = [dict(row) for row in source.execute(
        "select * from assets order by created_at, id"
    ).fetchall()]
    target_assets = [dict(row) for row in target.execute("select * from assets").fetchall()]
    target_by_id = {row["id"]: row for row in target_assets}
    target_by_hash = {
        row["source_hash"]: row for row in target_assets if row.get("source_hash")
    }
    target_reports_by_package = {}
    for row in target_assets:
        upload = target_uploads.get(row.get("upload_id") or "")
        content_hash = str((upload or {}).get("content_hash") or "")
        if row["asset_type"] == "report" and content_hash:
            target_reports_by_package[
                (content_hash, row["source_path"], row["title"])
            ] = row
    used_codes = {row["asset_code"] for row in target_assets if row.get("asset_code")}

    asset_map: dict[str, str] = {}
    insert_rows: list[dict] = []
    duplicate_rows: list[dict] = []
    renamed_codes: list[dict] = []
    for row in source_assets:
        if row["id"] in target_by_id:
            asset_map[row["id"]] = row["id"]
            continue
        source_upload = source_uploads.get(row.get("upload_id") or "")
        content_hash = str((source_upload or {}).get("content_hash") or "")
        package_report = (
            target_reports_by_package.get((content_hash, row["source_path"], row["title"]))
            if row["asset_type"] == "report" and content_hash
            else None
        )
        if package_report:
            asset_map[row["id"]] = package_report["id"]
            duplicate_rows.append(
                {
                    "sourceId": row["id"],
                    "targetId": package_report["id"],
                    "sourceCode": row["asset_code"],
                    "targetCode": package_report["asset_code"],
                }
            )
            continue
        existing = target_by_hash.get(row.get("source_hash") or "")
        if existing and row.get("source_hash"):
            asset_map[row["id"]] = existing["id"]
            duplicate_rows.append(
                {
                    "sourceId": row["id"],
                    "targetId": existing["id"],
                    "sourceCode": row["asset_code"],
                    "targetCode": existing["asset_code"],
                }
            )
            continue
        asset_map[row["id"]] = row["id"]
        incoming = {column: row[column] for column in ASSET_COLUMNS}
        assigned_code = allocate_code(incoming, used_codes)
        if assigned_code != incoming["asset_code"]:
            renamed_codes.append(
                {
                    "id": incoming["id"],
                    "from": incoming["asset_code"],
                    "to": assigned_code,
                }
            )
        incoming["asset_code"] = assigned_code
        insert_rows.append(incoming)

    for row in insert_rows:
        row["version_group"] = asset_map.get(row["version_group"], row["version_group"]) or row["id"]
        row["version_parent_id"] = asset_map.get(
            row["version_parent_id"], row["version_parent_id"]
        )

    inserted_asset_ids = {row["id"] for row in insert_rows}
    inserted_report_ids = {
        row["id"] for row in insert_rows if row["asset_type"] == "report"
    }
    needed_upload_ids = {row["upload_id"] for row in insert_rows if row.get("upload_id")}
    missing_uploads = sorted(needed_upload_ids - source_uploads.keys())
    if missing_uploads:
        raise SystemExit(f"missing upload records: {', '.join(missing_uploads)}")

    slot_rows = [
        dict(row)
        for row in source.execute(
            "select * from report_page_slots order by report_id, page_number"
        ).fetchall()
        if row["report_id"] in inserted_report_ids
    ]
    missing_controls = sorted(
        {
            row["control_id"]
            for row in slot_rows
            if row["control_id"] and row["control_id"] not in asset_map
        }
    )
    if missing_controls:
        raise SystemExit(f"unmapped report controls: {', '.join(missing_controls)}")

    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "sourceAssets": len(source_assets),
        "targetAssetsBefore": len(target_assets),
        "assetsToInsert": len(insert_rows),
        "duplicatesReused": len(duplicate_rows),
        "codesReassigned": len(renamed_codes),
        "uploadsToCopy": len(needed_upload_ids),
        "reportsToInsert": len(inserted_report_ids),
        "reportSlotsToInsert": len(slot_rows),
        "insertByType": {
            asset_type: sum(row["asset_type"] == asset_type for row in insert_rows)
            for asset_type in ("report", "control", "resource")
        },
        "sampleCodeChanges": renamed_codes[:10],
    }
    if not args.apply:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    copied_paths = 0
    for upload_id in sorted(needed_upload_ids):
        upload = source_uploads[upload_id]
        for field in ("stored_path", "extract_path"):
            recorded = upload.get(field) or ""
            if recorded and copy_runtime_item(source_root, target_root, recorded):
                copied_paths += 1
    asset_placeholders = ", ".join("?" for _ in ASSET_COLUMNS)
    upload_placeholders = ", ".join("?" for _ in UPLOAD_COLUMNS)
    with target:
        for upload_id in sorted(needed_upload_ids):
            upload = source_uploads[upload_id]
            target.execute(
                f"insert or ignore into uploads ({', '.join(UPLOAD_COLUMNS)}) "
                f"values ({upload_placeholders})",
                tuple(upload[column] for column in UPLOAD_COLUMNS),
            )
        for row in insert_rows:
            target.execute(
                f"insert into assets ({', '.join(ASSET_COLUMNS)}) "
                f"values ({asset_placeholders})",
                tuple(row[column] for column in ASSET_COLUMNS),
            )
        for row in slot_rows:
            target.execute(
                """
                insert into report_page_slots
                  (report_id, page_number, title, status, control_id, task_key, note, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_map[row["report_id"]],
                    row["page_number"],
                    row["title"],
                    row["status"],
                    asset_map.get(row["control_id"], row["control_id"]),
                    row["task_key"],
                    row["note"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        for row in source.execute("select * from report_page_arrangements").fetchall():
            if row["report_id"] not in inserted_report_ids:
                continue
            target.execute(
                """
                insert into report_page_arrangements
                  (report_id, page_order, hidden_page_ids, updated_by, updated_at)
                values (?, ?, ?, ?, ?)
                """,
                (
                    asset_map[row["report_id"]],
                    mapped_json_list(row["page_order"], asset_map),
                    mapped_json_list(row["hidden_page_ids"], asset_map),
                    row["updated_by"],
                    row["updated_at"],
                ),
            )
        for row in source.execute("select * from report_page_normalizations").fetchall():
            if row["report_id"] not in inserted_report_ids:
                continue
            target.execute(
                """
                insert or ignore into report_page_normalizations
                  (report_id, source_control_id, normalized_control_id, target_width, target_height,
                   source_width, source_height, source_fingerprint, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_map[row["report_id"]],
                    asset_map.get(row["source_control_id"], row["source_control_id"]),
                    asset_map.get(row["normalized_control_id"], row["normalized_control_id"]),
                    row["target_width"],
                    row["target_height"],
                    row["source_width"],
                    row["source_height"],
                    row["source_fingerprint"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        target.execute("pragma optimize")

    summary["copiedRuntimeItems"] = copied_paths
    summary["targetAssetsAfter"] = target.execute("select count(*) from assets").fetchone()[0]
    summary["targetReportSlotsAfter"] = target.execute(
        "select count(*) from report_page_slots"
    ).fetchone()[0]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
