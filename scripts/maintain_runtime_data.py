#!/usr/bin/env python3
"""Audit and clean MineM runtime metadata without touching referenced assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "materials.db"
UPLOADS = ROOT / "uploads"
EXTRACTED = ROOT / "extracted"


def relative_runtime_path(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def upload_files(upload_id: str) -> list[Path]:
    if "/" in upload_id or "\\" in upload_id:
        return []
    return sorted(path for path in UPLOADS.glob(f"{upload_id}.*") if path.is_file())


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_paths(row: sqlite3.Row) -> tuple[str, str]:
    upload_id = row["id"]
    files = upload_files(upload_id)
    extract_dir = EXTRACTED / upload_id
    stored = row["stored_path"] or ""
    extracted = row["extract_path"] or ""
    if files:
        stored = relative_runtime_path(files[0])
    elif extract_dir.is_dir() and (
        "material-library" in stored
        or stored.rstrip("/").endswith(f"/extracted/{upload_id}")
    ):
        stored = relative_runtime_path(extract_dir)
    if extract_dir.is_dir():
        extracted = relative_runtime_path(extract_dir)
    elif "material-library" in extracted:
        extracted = relative_runtime_path(extract_dir)
    return stored, extracted


def zero_asset_uploads(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        select u.*, count(a.id) referenced_assets
        from uploads u
        left join assets a on a.upload_id = u.id
        group by u.id
        having count(a.id) = 0 and coalesce(u.asset_count, 0) = 0
        order by u.created_at
        """
    ).fetchall()
    return [dict(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and clean MineM runtime metadata")
    parser.add_argument("--apply", action="store_true", help="Apply path migration and remove confirmed unreferenced runtime data")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    upload_columns = {row[1] for row in conn.execute("pragma table_info(uploads)").fetchall()}
    has_content_hash = "content_hash" in upload_columns
    path_updates = []
    for row in conn.execute("select * from uploads order by created_at").fetchall():
        stored, extracted = normalized_paths(row)
        if stored != row["stored_path"] or extracted != row["extract_path"]:
            path_updates.append({
                "id": row["id"],
                "storedPath": stored,
                "extractPath": extracted,
            })

    zero_uploads = zero_asset_uploads(conn)
    backup_files = sorted((ROOT / "data").glob("materials.db.before-*"))
    legacy_tag_counts = {
        "assets": conn.execute("select count(*) from assets where trim(coalesce(tags, '')) <> ''").fetchone()[0],
        "assetHistory": conn.execute("select count(*) from asset_history where trim(coalesce(tags, '')) <> ''").fetchone()[0],
        "storylines": conn.execute("select count(*) from report_storyline_collections where trim(coalesce(tags, '')) <> ''").fetchone()[0],
    }
    hash_updates = []
    for row in conn.execute("select id from uploads order by created_at").fetchall():
        files = upload_files(row["id"])
        current = ""
        if has_content_hash:
            current = conn.execute("select content_hash from uploads where id = ?", (row["id"],)).fetchone()[0] or ""
        if files and not current:
            hash_updates.append({"id": row["id"], "contentHash": file_sha1(files[0])})
    removable_files = []
    removable_dirs = []
    for upload in zero_uploads:
        removable_files.extend(upload_files(upload["id"]))
        extract_dir = EXTRACTED / upload["id"]
        if extract_dir.is_dir() and extract_dir.resolve().is_relative_to(EXTRACTED.resolve()):
            removable_dirs.append(extract_dir)

    payload = {
        "apply": args.apply,
        "pathUpdates": path_updates,
        "zeroAssetUploads": [item["id"] for item in zero_uploads],
        "backupFiles": [path.name for path in backup_files],
        "contentHashUpdates": hash_updates,
        "legacyTagCounts": legacy_tag_counts,
        "removableFiles": [relative_runtime_path(path) for path in removable_files],
        "removableDirectories": [relative_runtime_path(path) for path in removable_dirs],
    }

    if args.apply:
        try:
            with conn:
                if not has_content_hash:
                    conn.execute("alter table uploads add column content_hash text not null default ''")
                    conn.execute("create index if not exists idx_uploads_content_hash on uploads(content_hash) where content_hash <> ''")
                for update in path_updates:
                    conn.execute(
                        "update uploads set stored_path = ?, extract_path = ? where id = ?",
                        (update["storedPath"], update["extractPath"], update["id"]),
                    )
                for update in hash_updates:
                    conn.execute("update uploads set content_hash = ? where id = ?", (update["contentHash"], update["id"]))
                conn.execute("update assets set tags = '' where trim(coalesce(tags, '')) <> ''")
                conn.execute("update asset_history set tags = '' where trim(coalesce(tags, '')) <> ''")
                conn.execute("update report_storyline_collections set tags = '' where trim(coalesce(tags, '')) <> ''")
                for upload in zero_uploads:
                    conn.execute("delete from import_tasks where upload_id = ?", (upload["id"],))
                    conn.execute("delete from uploads where id = ?", (upload["id"],))
            for path in removable_files + backup_files:
                path.unlink(missing_ok=True)
            for path in removable_dirs:
                shutil.rmtree(path)
        finally:
            conn.close()
    else:
        conn.close()

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
