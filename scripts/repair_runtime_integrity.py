#!/usr/bin/env python3
"""Repair broken runtime records without creating a database backup.

Dry-run is the default. ``--apply`` requires the MineM server to be stopped.
The repair preserves a usable sibling version whenever one exists, rewrites
report relationships, and removes only records whose local content is gone or
whose HTML dependency closure is incomplete.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minem.html_dependencies import audit_dependency_closure  # noqa: E402


TAG_TABLES = ("asset_tag_evidence", "asset_tag_suggestions", "asset_tags")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path.home() / "Library" / "Application Support" / "MineM",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


@contextmanager
def runtime_lock(runtime_root: Path):
    lock_path = runtime_root / "data" / "minem.server.lock"
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.seek(0)
        owner = handle.read().strip() or "unknown"
        raise RuntimeError(f"MineM 服务仍在运行：{owner}") from error
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def asset_path(runtime_root: Path, row) -> Path | None:
    preview = str(row["preview_url"] or "")
    if preview.startswith("/extracted/"):
        path = runtime_root / unquote(urlparse(preview).path.lstrip("/"))
    elif row["upload_id"] and row["source_path"]:
        path = runtime_root / "extracted" / row["upload_id"] / row["source_path"]
    else:
        return None
    path = path.resolve()
    extracted = (runtime_root / "extracted").resolve()
    return path if path.is_relative_to(extracted) else None


def recover_known_files(runtime_root: Path, rows, *, apply: bool):
    source_root = Path.home() / "Documents" / "pitch_html" / "brand-dashboard-video-page" / "assets"
    known = {
        "brand-dashboard.mp4": source_root / "brand-dashboard.mp4",
        "page-background.png": source_root / "page-background.png",
    }
    recovered = []
    for row in rows:
        target = asset_path(runtime_root, row)
        if not target or target.exists():
            continue
        source = known.get(Path(str(row["source_path"] or "")).name)
        if not source or not source.is_file():
            continue
        recovered.append({"assetId": row["id"], "source": str(source), "target": str(target)})
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return recovered


def broken_assets(conn, runtime_root: Path):
    rows = conn.execute(
        "select * from assets where asset_type in ('control', 'resource') order by asset_type, id"
    ).fetchall()
    missing = []
    dependency_broken = []
    for row in rows:
        path = asset_path(runtime_root, row)
        if path is not None and not path.is_file():
            missing.append(row)
            continue
        if row["asset_type"] != "control" or not path or path.suffix.lower() not in {".html", ".htm"}:
            continue
        audit = audit_dependency_closure(path.parent)
        entry = path.name
        blockers = [item for item in audit["blockingMissing"] if item["entry"] == entry]
        if blockers:
            dependency_broken.append((row, blockers))
    invalid = {row["id"]: row for row in missing}
    invalid.update({row["id"]: row for row, _ in dependency_broken})
    return missing, dependency_broken, invalid


def table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "select 1 from sqlite_master where type='table' and name=?", (name,)
    ).fetchone())


def replace_json_ids(value, replacements, removed):
    try:
        items = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        items = []
    result = []
    for item in items:
        if item in removed:
            item = replacements.get(item, "")
        if item and item not in result:
            result.append(item)
    return json.dumps(result, ensure_ascii=False)


def choose_replacements(conn, invalid):
    replacements = {}
    invalid_ids = set(invalid)
    for asset_id, row in invalid.items():
        group = str(row["version_group"] or row["id"])
        candidates = conn.execute(
            """
            select * from assets
            where asset_type = ? and (version_group = ? or id = ?)
            order by updated_at desc, created_at desc, id desc
            """,
            (row["asset_type"], group, group),
        ).fetchall()
        replacement = next((item for item in candidates if item["id"] not in invalid_ids), None)
        if replacement:
            replacements[asset_id] = replacement["id"]
    return replacements


def apply_integrity_repair(conn, runtime_root: Path, invalid, replacements, zero_uploads):
    removed = set(invalid)
    timestamp = int(time.time() * 1000)
    for old_id, new_id in replacements.items():
        conn.execute(
            "update report_page_slots set control_id=?, updated_at=? where control_id=?",
            (new_id, timestamp, old_id),
        )
        conn.execute(
            "update report_page_candidates set control_id=?, updated_at=? where control_id=?",
            (new_id, timestamp, old_id),
        )
    placeholders = ",".join("?" for _ in removed)
    if removed:
        conn.execute(f"delete from report_page_slots where control_id in ({placeholders})", list(removed))
        conn.execute(f"delete from report_page_candidates where control_id in ({placeholders})", list(removed))
        conn.execute(
            f"delete from report_page_normalizations where source_control_id in ({placeholders}) or normalized_control_id in ({placeholders})",
            [*removed, *removed],
        )
        for table in TAG_TABLES:
            if table_exists(conn, table):
                conn.execute(f"delete from {table} where asset_id in ({placeholders})", list(removed))
        if table_exists(conn, "asset_history"):
            columns = {row[1] for row in conn.execute("pragma table_info(asset_history)")}
            for column in {"asset_id", "version_asset_id"} & columns:
                conn.execute(f"delete from asset_history where {column} in ({placeholders})", list(removed))
        conn.execute(f"delete from assets where id in ({placeholders})", list(removed))

    for report in conn.execute("select report_id from report_page_arrangements").fetchall():
        report_id = report["report_id"]
        arrangement = conn.execute(
            "select * from report_page_arrangements where report_id=?", (report_id,)
        ).fetchone()
        conn.execute(
            """update report_page_arrangements
               set page_order=?, hidden_page_ids=?, updated_at=? where report_id=?""",
            (
                replace_json_ids(arrangement["page_order"], replacements, removed),
                replace_json_ids(arrangement["hidden_page_ids"], replacements, removed),
                timestamp,
                report_id,
            ),
        )
    report_ids = [row["report_id"] for row in conn.execute(
        "select distinct report_id from report_page_slots order by report_id"
    )]
    for report_id in report_ids:
        rows = conn.execute(
            "select rowid from report_page_slots where report_id=? order by page_number, rowid",
            (report_id,),
        ).fetchall()
        for page_number, row in enumerate(rows, 1):
            conn.execute(
                "update report_page_slots set page_number=?, updated_at=? where rowid=?",
                (-page_number, timestamp, row["rowid"]),
            )
        conn.execute(
            "update report_page_slots set page_number=-page_number where report_id=? and page_number < 0",
            (report_id,),
        )

    for upload_id in zero_uploads:
        if table_exists(conn, "import_tasks"):
            conn.execute("delete from import_tasks where upload_id=?", (upload_id,))
        conn.execute("delete from uploads where id=?", (upload_id,))
    conn.execute(
        """update uploads set asset_count=(select count(*) from assets where upload_id=uploads.id),
           file_count=(select count(*) from assets where upload_id=uploads.id)"""
    )

    for asset_id in removed:
        (runtime_root / "thumbnails" / f"{asset_id}.png").unlink(missing_ok=True)
        (runtime_root / "thumbnails" / f"{asset_id}.json").unlink(missing_ok=True)
    for upload_id in zero_uploads:
        shutil.rmtree(runtime_root / "extracted" / upload_id, ignore_errors=True)
        for path in (runtime_root / "uploads").glob(f"{upload_id}.*"):
            path.unlink(missing_ok=True)


def main():
    args = parse_args()
    runtime_root = args.runtime_root.expanduser().resolve()
    db_path = runtime_root / "data" / "materials.db"
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("select * from assets").fetchall()
        recovered = recover_known_files(runtime_root, rows, apply=args.apply)
        missing, dependency_broken, invalid = broken_assets(conn, runtime_root)
        replacements = choose_replacements(conn, invalid)
        zero_uploads = [row["id"] for row in conn.execute(
            """select upload.id from uploads upload left join assets asset on asset.upload_id=upload.id
               group by upload.id having count(asset.id)=0 order by upload.created_at"""
        )]
        payload = {
            "apply": args.apply,
            "recoveredFiles": recovered,
            "missingRecords": len(missing),
            "dependencyBrokenRecords": len(dependency_broken),
            "invalidRecords": len(invalid),
            "replacementRecords": len(replacements),
            "zeroAssetUploads": zero_uploads,
            "samples": {
                "invalid": [
                    {"id": row["id"], "code": row["asset_code"], "type": row["asset_type"]}
                    for row in list(invalid.values())[:50]
                ],
                "dependencyBroken": [
                    {"id": row["id"], "code": row["asset_code"], "missing": len(items)}
                    for row, items in dependency_broken[:50]
                ],
            },
        }
        if args.apply:
            with runtime_lock(runtime_root):
                conn.execute("begin immediate")
                try:
                    apply_integrity_repair(conn, runtime_root, invalid, replacements, zero_uploads)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            payload["applied"] = True
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
