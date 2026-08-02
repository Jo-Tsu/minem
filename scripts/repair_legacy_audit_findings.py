#!/usr/bin/env python3
"""Repair audited legacy tags and thumbnail metadata with a logical rollback snapshot."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from minem.tag_tasks import (  # noqa: E402
    MODEL_VERSION,
    TAXONOMY_VERSION,
    _store_candidates,
    collect_evidence,
    fingerprint as tag_fingerprint,
    now_ms,
)
from minem.tag_taxonomy import confirmed_candidates  # noqa: E402


TAG_TABLES = (
    "asset_tag_evidence",
    "asset_tag_suggestions",
    "asset_tags",
    "tag_analysis_tasks",
)


def parse_args() -> argparse.Namespace:
    default_root = Path.home() / "Library" / "Application Support" / "MineM"
    parser = argparse.ArgumentParser(
        description="Repair untagged visible assets and stale thumbnail fingerprints.",
    )
    parser.add_argument("--runtime-root", type=Path, default=default_root)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", type=Path)
    return parser.parse_args()


def connect_database(path: Path, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{path.resolve().as_posix()}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(path, timeout=30)
        conn.execute("pragma busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_expected_schema(conn: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in conn.execute("select name from sqlite_master where type='table'").fetchall()
    }
    missing = sorted({"assets", *TAG_TABLES} - tables)
    if missing:
        raise RuntimeError(f"标签治理表不完整：{', '.join(missing)}")


@contextmanager
def runtime_lock(runtime_root: Path):
    lock_path = runtime_root / "data" / "minem.server.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.seek(0)
        owner = handle.read().strip() or "unknown"
        handle.close()
        raise RuntimeError(f"MineM 服务仍在使用运行库：{owner}") from error
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def load_server(runtime_root: Path):
    os.environ["MINEM_DATA_DIR"] = str(runtime_root)
    import server

    if server.RUNTIME_ROOT != runtime_root.resolve():
        raise RuntimeError("服务端运行根目录与修复目标不一致")
    return server


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def rows_for_ids(
    conn: sqlite3.Connection,
    table: str,
    asset_ids: list[str],
) -> list[dict]:
    if not asset_ids:
        return []
    placeholders = ",".join("?" for _ in asset_ids)
    rows = conn.execute(
        f"select * from {table} where asset_id in ({placeholders})",
        asset_ids,
    ).fetchall()
    return [dict(row) for row in rows]


def tag_plan(conn: sqlite3.Connection, extracted_root: Path) -> dict:
    rows = conn.execute(
        """
        select *
        from assets
        where version_parent_id = ''
          and trim(coalesce(tags, '')) = ''
        order by asset_type, asset_code, id
        """
    ).fetchall()
    assets = []
    relation_count = 0
    stale_evidence = 0
    for row in rows:
        evidence_row = conn.execute(
            "select source_fingerprint from asset_tag_evidence where asset_id = ?",
            (row["id"],),
        ).fetchone()
        current_fingerprint = tag_fingerprint(dict(row))
        evidence_current = bool(
            evidence_row and evidence_row["source_fingerprint"] == current_fingerprint
        )
        stale_evidence += not evidence_current
        evidence = collect_evidence(conn, row, extracted_root)
        selected = confirmed_candidates(evidence["candidates"])
        if not selected:
            raise RuntimeError(f"素材无法生成受控标签：{row['asset_code']}")
        relation_count += len(selected)
        assets.append(
            {
                "id": row["id"],
                "assetCode": row["asset_code"],
                "assetType": row["asset_type"],
                "evidenceCurrent": evidence_current,
                "tags": [candidate["tag"] for candidate in selected],
            }
        )
    return {
        "assetCount": len(assets),
        "relationCount": relation_count,
        "staleEvidenceCount": stale_evidence,
        "assets": assets,
    }


def thumbnail_plan(conn: sqlite3.Connection, runtime_root: Path, server) -> dict:
    rows = conn.execute(
        """
        select *
        from assets
        where version_parent_id = ''
          and asset_type in ('report', 'control')
          and media_kind = 'html'
        order by asset_type, asset_code, id
        """
    ).fetchall()
    stale = []
    unsafe = []
    for row in rows:
        metadata_path = runtime_root / "thumbnails" / f"{row['id']}.json"
        thumbnail_path = runtime_root / "thumbnails" / f"{row['id']}.png"
        if not metadata_path.is_file() or not thumbnail_path.is_file():
            continue
        try:
            metadata_text = metadata_path.read_text(encoding="utf-8")
            metadata = json.loads(metadata_text)
        except (OSError, json.JSONDecodeError):
            continue
        expected = server.thumbnail_source_fingerprint(row)
        current = str(metadata.get("sourceFingerprint") or "")
        version = int(metadata.get("version") or 0)
        if version == server.THUMBNAIL_META_VERSION and current == expected:
            continue
        html_path = server.local_html_preview_path(row)
        generated_at = int(metadata.get("updatedAt") or 0)
        source_modified_at = 0
        if html_path and html_path.is_file():
            source_modified_at = html_path.stat().st_mtime_ns // 1_000_000
        item = {
            "assetId": row["id"],
            "assetCode": row["asset_code"],
            "metadataPath": str(metadata_path),
            "previousText": metadata_text,
            "expectedFingerprint": expected,
            "sourceModifiedAt": source_modified_at,
            "thumbnailGeneratedAt": generated_at,
        }
        if not expected or not source_modified_at or generated_at < source_modified_at:
            unsafe.append(item)
        else:
            stale.append(item)
    return {
        "checkedCount": len(rows),
        "staleCount": len(stale),
        "requiresRenderCount": len(unsafe),
        "stale": stale,
        "requiresRender": unsafe,
    }


def snapshot_rows(conn: sqlite3.Connection, tag_asset_ids: list[str]) -> dict:
    placeholders = ",".join("?" for _ in tag_asset_ids)
    assets = (
        [
            dict(row)
            for row in conn.execute(
                f"select id, tags, tag_seeded from assets where id in ({placeholders})",
                tag_asset_ids,
            ).fetchall()
        ]
        if tag_asset_ids
        else []
    )
    return {
        "assets": assets,
        "assetTagEvidence": rows_for_ids(conn, "asset_tag_evidence", tag_asset_ids),
        "assetTagSuggestions": rows_for_ids(
            conn,
            "asset_tag_suggestions",
            tag_asset_ids,
        ),
        "assetTags": rows_for_ids(conn, "asset_tags", tag_asset_ids),
    }


def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    for row in rows:
        columns = list(row)
        placeholders = ",".join("?" for _ in columns)
        conn.execute(
            f"insert into {table} ({','.join(columns)}) values ({placeholders})",
            [row[column] for column in columns],
        )


def restore_snapshot(snapshot_path: Path, runtime_root: Path) -> dict:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if Path(payload["runtimeRoot"]).resolve() != runtime_root.resolve():
        raise RuntimeError("回滚快照不属于当前运行目录")
    database_path = Path(payload["database"])
    tag_asset_ids = [row["id"] for row in payload["databaseRows"]["assets"]]
    conn = connect_database(database_path, readonly=False)
    try:
        conn.execute("begin immediate")
        if tag_asset_ids:
            placeholders = ",".join("?" for _ in tag_asset_ids)
            for table in ("asset_tags", "asset_tag_suggestions", "asset_tag_evidence"):
                conn.execute(
                    f"delete from {table} where asset_id in ({placeholders})",
                    tag_asset_ids,
                )
            for row in payload["databaseRows"]["assets"]:
                conn.execute(
                    "update assets set tags = ?, tag_seeded = ? where id = ?",
                    (row["tags"], row["tag_seeded"], row["id"]),
                )
            insert_rows(
                conn,
                "asset_tag_evidence",
                payload["databaseRows"]["assetTagEvidence"],
            )
            insert_rows(
                conn,
                "asset_tag_suggestions",
                payload["databaseRows"]["assetTagSuggestions"],
            )
            insert_rows(conn, "asset_tags", payload["databaseRows"]["assetTags"])
        conn.execute(
            "delete from tag_analysis_tasks where id = ?",
            (payload["repairTaskId"],),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for item in payload["thumbnailMetadata"]:
        atomic_write_text(Path(item["metadataPath"]), item["previousText"])
    payload["status"] = "rolled-back"
    payload["rolledBackAt"] = now_ms()
    atomic_write_text(
        snapshot_path,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    return {
        "ok": True,
        "rollback": str(snapshot_path),
        "restoredAssets": len(tag_asset_ids),
        "restoredThumbnails": len(payload["thumbnailMetadata"]),
    }


def apply_tags(
    conn: sqlite3.Connection,
    extracted_root: Path,
    asset_ids: list[str],
    task_id: str,
) -> int:
    timestamp = now_ms()
    conn.execute(
        """
        insert into tag_analysis_tasks(
          id,status,trigger_type,scope_type,scope_json,total_count,processed_count,
          error_count,message,error,model_version,taxonomy_version,apply_mode,
          created_at,updated_at
        ) values (?, 'running', 'admin-repair', 'untagged-visible', ?, ?, 0, 0,
                  '正在补齐受控标签', '', ?, ?, 'confirmed', ?, ?)
        """,
        (
            task_id,
            json.dumps(asset_ids, ensure_ascii=False),
            len(asset_ids),
            MODEL_VERSION,
            TAXONOMY_VERSION,
            timestamp,
            timestamp,
        ),
    )
    applied = 0
    for index, asset_id in enumerate(asset_ids, 1):
        asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not asset:
            raise RuntimeError(f"素材在修复期间消失：{asset_id}")
        if asset["version_parent_id"] or str(asset["tags"] or "").strip():
            raise RuntimeError(f"素材在修复期间发生变化：{asset['asset_code']}")
        evidence = collect_evidence(conn, asset, extracted_root)
        timestamp = now_ms()
        conn.execute(
            """
            insert into asset_tag_evidence(
              asset_id,source_fingerprint,evidence_json,status,collected_at,updated_at
            ) values (?, ?, ?, 'classified', ?, ?)
            on conflict(asset_id) do update set
              source_fingerprint=excluded.source_fingerprint,
              evidence_json=excluded.evidence_json,
              status='classified',
              updated_at=excluded.updated_at
            """,
            (
                asset_id,
                evidence["fingerprint"],
                json.dumps(evidence, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        applied += _store_candidates(conn, asset_id, evidence, "confirmed")
        conn.execute(
            """
            update tag_analysis_tasks
            set processed_count = ?, message = ?, updated_at = ?
            where id = ?
            """,
            (
                index,
                f"已补齐 {index}/{len(asset_ids)} 个素材",
                timestamp,
                task_id,
            ),
        )
    conn.execute(
        """
        update tag_analysis_tasks
        set status='completed', message=?, updated_at=?
        where id=?
        """,
        (f"存量标签修复完成；已确认 {applied} 条正式标签", now_ms(), task_id),
    )
    return applied


def update_thumbnail_metadata(items: list[dict], server) -> None:
    for item in items:
        metadata = {
            "version": server.THUMBNAIL_META_VERSION,
            "assetId": item["assetId"],
            "sourceFingerprint": item["expectedFingerprint"],
            "updatedAt": now_ms(),
        }
        atomic_write_text(
            Path(item["metadataPath"]),
            json.dumps(metadata, ensure_ascii=False, indent=2),
        )


def validate_result(
    conn: sqlite3.Connection,
    runtime_root: Path,
    server,
) -> dict:
    untagged = conn.execute(
        """
        select count(*)
        from assets
        where version_parent_id = ''
          and trim(coalesce(tags, '')) = ''
        """
    ).fetchone()[0]
    invalid_relations = conn.execute(
        """
        select count(*)
        from asset_tags relation
        left join tag_definitions definition
          on definition.tag = relation.tag and definition.active = 1
        where definition.tag is null
        """
    ).fetchone()[0]
    thumbnail_state = thumbnail_plan(conn, runtime_root, server)
    return {
        "untaggedVisible": untagged,
        "invalidTagRelations": invalid_relations,
        "staleThumbnails": thumbnail_state["staleCount"],
        "requiresThumbnailRender": thumbnail_state["requiresRenderCount"],
    }


def main() -> int:
    args = parse_args()
    runtime_root = args.runtime_root.expanduser().resolve()
    database_path = runtime_root / "data" / "materials.db"
    if not database_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{database_path}")
    if args.apply and args.rollback:
        raise RuntimeError("--apply 与 --rollback 不能同时使用")
    server = load_server(runtime_root)

    if args.rollback:
        with runtime_lock(runtime_root):
            result = restore_snapshot(args.rollback.expanduser().resolve(), runtime_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    conn = connect_database(database_path, readonly=not args.apply)
    try:
        ensure_expected_schema(conn)
        tags = tag_plan(conn, runtime_root / "extracted")
        thumbnails = thumbnail_plan(conn, runtime_root, server)
        dry_run = {
            "ok": thumbnails["requiresRenderCount"] == 0,
            "apply": args.apply,
            "runtimeRoot": str(runtime_root),
            "database": str(database_path),
            "tags": {
                "assetCount": tags["assetCount"],
                "relationCount": tags["relationCount"],
                "staleEvidenceCount": tags["staleEvidenceCount"],
                "sample": tags["assets"][:30],
            },
            "thumbnails": {
                "checkedCount": thumbnails["checkedCount"],
                "staleCount": thumbnails["staleCount"],
                "requiresRenderCount": thumbnails["requiresRenderCount"],
                "sample": [
                    {
                        key: item[key]
                        for key in (
                            "assetCode",
                            "assetId",
                            "sourceModifiedAt",
                            "thumbnailGeneratedAt",
                        )
                    }
                    for item in thumbnails["stale"][:30]
                ],
            },
        }
        if not args.apply:
            print(json.dumps(dry_run, ensure_ascii=False, indent=2))
            return 0 if dry_run["ok"] else 1
        if thumbnails["requiresRender"]:
            raise RuntimeError("存在早于源 HTML 的缩略图，拒绝仅校准指纹")

        task_id = f"tag-repair-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        snapshot_dir = runtime_root / "state" / "repairs"
        snapshot_path = snapshot_dir / f"{task_id}.json"
        tag_asset_ids = [item["id"] for item in tags["assets"]]
        snapshot = {
            "schemaVersion": 1,
            "status": "prepared",
            "createdAt": now_ms(),
            "runtimeRoot": str(runtime_root),
            "database": str(database_path),
            "repairTaskId": task_id,
            "databaseRows": snapshot_rows(conn, tag_asset_ids),
            "thumbnailMetadata": thumbnails["stale"],
        }
        atomic_write_text(
            snapshot_path,
            json.dumps(snapshot, ensure_ascii=False, indent=2),
        )

        with runtime_lock(runtime_root):
            try:
                conn.execute("begin immediate")
                applied_relations = apply_tags(
                    conn,
                    runtime_root / "extracted",
                    tag_asset_ids,
                    task_id,
                )
                conn.commit()
                update_thumbnail_metadata(thumbnails["stale"], server)
                validation = validate_result(conn, runtime_root, server)
                if any(validation.values()):
                    raise RuntimeError(f"修复后验证失败：{validation}")
            except Exception:
                conn.close()
                restore_snapshot(snapshot_path, runtime_root)
                raise

        snapshot["status"] = "completed"
        snapshot["completedAt"] = now_ms()
        snapshot["appliedRelations"] = applied_relations
        atomic_write_text(
            snapshot_path,
            json.dumps(snapshot, ensure_ascii=False, indent=2),
        )
        print(
            json.dumps(
                {
                    **dry_run,
                    "ok": True,
                    "snapshot": str(snapshot_path),
                    "appliedRelations": applied_relations,
                    "validation": validation,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
