#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minem.db import connect_database
from minem.page_duplicates import (
    FINGERPRINT_VERSION,
    attach_duplicate_version,
    fingerprint_file,
    is_auto_reusable_visual,
    thumbnail_difference,
)


def asset_path(runtime_root: Path, row) -> Path | None:
    upload_id = str(row["upload_id"] or "").strip()
    source_path = str(row["source_path"] or "").strip()
    if not upload_id or not source_path:
        return None
    candidate = (runtime_root / "extracted" / upload_id / source_path).resolve()
    extracted = (runtime_root / "extracted").resolve()
    return candidate if candidate.is_file() and candidate.is_relative_to(extracted) else None


def reference_count(conn, asset_id: str) -> int:
    return int(
        conn.execute(
            "select count(*) from report_page_slots where control_id = ?",
            (asset_id,),
        ).fetchone()[0]
        or 0
    )


def choose_primary(conn, rows):
    return min(
        rows,
        key=lambda row: (
            -reference_count(conn, row["id"]),
            int(row["created_at"] or 0),
            str(row["asset_code"] or ""),
            str(row["id"]),
        ),
    )


def page_identity(runtime_root: Path, row) -> dict:
    stored_fingerprint = (
        str(row["semantic_fingerprint"] or "")
        if "semantic_fingerprint" in row.keys()
        else ""
    )
    stored_version = (
        int(row["semantic_fingerprint_version"] or 0)
        if "semantic_fingerprint_version" in row.keys()
        else 0
    )
    if stored_fingerprint and stored_version == FINGERPRINT_VERSION:
        return {
            "fingerprint": stored_fingerprint,
            "semanticKey": str(row["semantic_key"] or ""),
            "textHash": str(row["semantic_text_hash"] or ""),
        }
    identity = fingerprint_file(asset_path(runtime_root, row))
    return {
        "fingerprint": identity.fingerprint,
        "semanticKey": identity.page_key,
        "textHash": identity.text_hash,
    }


def classify_groups(conn, runtime_root: Path) -> tuple[list[dict], dict]:
    rows = conn.execute(
        """
        select *
        from assets
        where asset_type = 'control'
          and version_parent_id = ''
        order by created_at, asset_code, id
        """
    ).fetchall()
    groups = {}
    fingerprinted = 0
    for row in rows:
        identity = page_identity(runtime_root, row)
        if not identity["fingerprint"]:
            continue
        fingerprinted += 1
        groups.setdefault(identity["fingerprint"], []).append((row, identity))

    result = []
    thumbnails = runtime_root / "thumbnails"
    for fingerprint, items in groups.items():
        version_groups = {
            row["version_group"] or row["id"] for row, _ in items
        }
        if len(items) < 2 or len(version_groups) < 2:
            continue
        primary, primary_identity = choose_primary(
            conn,
            [row for row, _ in items],
        ), None
        for row, identity in items:
            if row["id"] == primary["id"]:
                primary_identity = identity
                break
        comparisons = []
        auto_ids = []
        review_ids = []
        for row, _ in items:
            if row["id"] == primary["id"]:
                continue
            metrics = thumbnail_difference(
                thumbnails / f"{primary['id']}.png",
                thumbnails / f"{row['id']}.png",
                image_module=Image,
            )
            reusable = is_auto_reusable_visual(metrics)
            comparisons.append(
                {
                    "assetId": row["id"],
                    "assetCode": row["asset_code"],
                    "title": row["title"],
                    "uploadId": row["upload_id"],
                    "versionGroup": row["version_group"] or row["id"],
                    "referenceCount": reference_count(conn, row["id"]),
                    "classification": "auto-reuse" if reusable else "review",
                    "metrics": metrics,
                }
            )
            (auto_ids if reusable else review_ids).append(row["id"])
        result.append(
            {
                "fingerprint": fingerprint,
                "semanticKey": primary_identity["semanticKey"],
                "textHash": primary_identity["textHash"],
                "primary": {
                    "assetId": primary["id"],
                    "assetCode": primary["asset_code"],
                    "title": primary["title"],
                    "uploadId": primary["upload_id"],
                    "versionGroup": primary["version_group"] or primary["id"],
                    "referenceCount": reference_count(conn, primary["id"]),
                },
                "comparisons": comparisons,
                "autoReuseIds": auto_ids,
                "reviewIds": review_ids,
            }
        )
    return result, {
        "visibleControls": len(rows),
        "fingerprinted": fingerprinted,
        "version": FINGERPRINT_VERSION,
    }


def apply_groups(conn, groups: list[dict]) -> dict:
    merged_ids = []
    for group in groups:
        primary_id = group["primary"]["assetId"]
        for comparison in group["comparisons"]:
            if comparison["classification"] != "auto-reuse":
                continue
            if attach_duplicate_version(
                conn,
                asset_id=comparison["assetId"],
                primary_id=primary_id,
                similarity_score=comparison["metrics"].get("score", 1.0),
                timestamp=int(time.time() * 1000),
            ):
                merged_ids.append(comparison["assetId"])
    return {"merged": len(merged_ids), "mergedIds": merged_ids}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit semantically identical page materials without deleting files or changing report slots."
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path.home() / "Library" / "Application Support" / "MineM",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    runtime_root = args.runtime_root.expanduser().resolve()
    db_path = runtime_root / "data" / "materials.db"
    if not db_path.is_file():
        raise SystemExit(f"数据库不存在：{db_path}")
    wal_path = db_path.with_name(f"{db_path.name}-wal")
    if not args.apply and wal_path.is_file() and wal_path.stat().st_size > 0:
        raise SystemExit("数据库仍有未归并的 WAL；请先停止 MineM 服务后再执行只读重复审计")
    probe = sqlite3.connect(
        f"file:{db_path}?mode=ro&immutable=1" if not args.apply else str(db_path),
        uri=not args.apply,
    )
    probe.row_factory = sqlite3.Row
    try:
        columns = {
            row["name"]
            for row in probe.execute("pragma table_info(assets)").fetchall()
        }
    finally:
        probe.close()
    if args.apply and not {
        "semantic_key",
        "semantic_text_hash",
        "semantic_fingerprint",
        "semantic_fingerprint_version",
        "semantic_dedupe_status",
    }.issubset(columns):
        raise SystemExit("当前数据库尚未升级到页面语义指纹 Schema；请先启动当前版本 MineM")
    conn = (
        connect_database(db_path, timeout=30)
        if args.apply
        else sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    )
    conn.row_factory = sqlite3.Row
    try:
        before_slots = conn.execute(
            "select report_id,page_number,control_id from report_page_slots order by report_id,page_number"
        ).fetchall()
        groups, fingerprint_state = classify_groups(conn, runtime_root)
        apply_result = {"merged": 0, "mergedIds": []}
        if args.apply:
            apply_result = apply_groups(conn, groups)
        after_slots = conn.execute(
            "select report_id,page_number,control_id from report_page_slots order by report_id,page_number"
        ).fetchall()
        if [tuple(row) for row in before_slots] != [tuple(row) for row in after_slots]:
            conn.rollback()
            raise RuntimeError("页面重复归并不得修改汇报页槽")
        if args.apply:
            conn.commit()
    finally:
        conn.close()

    payload = {
        "apply": args.apply,
        "runtimeRoot": str(runtime_root),
        "fingerprints": fingerprint_state,
        "summary": {
            "candidateGroups": len(groups),
            "autoReuseRecords": sum(
                len(group["autoReuseIds"]) for group in groups
            ),
            "reviewRecords": sum(len(group["reviewIds"]) for group in groups),
            **apply_result,
        },
        "groups": groups,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
