#!/usr/bin/env python3
"""Run the controlled taxonomy across every MineM asset."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minem.tag_tasks import create_task, ensure_schema, public_task, run_task


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "materials.db")
    parser.add_argument("--extracted", type=Path, default=ROOT / "extracted")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    ids = [row["id"] for row in conn.execute(
        "select id from assets order by updated_at desc, created_at desc"
    )]
    if not args.apply:
        print(json.dumps({"ok": True, "dryRun": True, "assetCount": len(ids)}, ensure_ascii=False))
        return
    result = create_task(
        conn,
        ids,
        trigger_type="admin",
        scope_type="all",
        apply_mode="confirmed",
    )
    conn.commit()
    conn.close()
    if not result.get("ok"):
        raise SystemExit(result.get("error") or "无法创建标签任务")
    run_task(args.db, args.extracted, result["taskId"])
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    task = conn.execute("select * from tag_analysis_tasks where id=?", (result["taskId"],)).fetchone()
    tagged = conn.execute("select count(*) count from assets where trim(tags)<>''").fetchone()["count"]
    relations = conn.execute("select count(*) count from asset_tags").fetchone()["count"]
    print(json.dumps({
        "ok": task["status"] == "completed",
        "task": public_task(task),
        "taggedAssets": tagged,
        "confirmedRelations": relations,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
