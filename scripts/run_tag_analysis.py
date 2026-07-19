#!/usr/bin/env python3
"""Run MineM's asynchronous evidence-only tag analysis outside the web UI.

Designed for cron at 00:00: `0 0 * * * /path/to/python scripts/run_tag_analysis.py`.
The server also runs the same changed-material scan at local midnight.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minem.tag_tasks import changed_asset_ids, create_task, ensure_schema, run_task  # noqa: E402


def main() -> int:
    db_path = ROOT / "data" / "materials.db"
    conn = sqlite3.connect(db_path, timeout=30); conn.row_factory = sqlite3.Row
    with conn:
        ensure_schema(conn)
        ids = changed_asset_ids(conn)
        result = create_task(conn, ids, trigger_type="scheduled", scope_type="changed-assets") if ids else {"ok": True, "skipped": True}
    conn.close()
    if result.get("taskId"):
        run_task(db_path, ROOT / "extracted", result["taskId"])
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
