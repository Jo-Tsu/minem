#!/usr/bin/env python3
"""Temporary-database regression test for report canvas derived versions."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from minem.db import create_core_schema, ensure_asset_schema, run_compat_migrations
from minem.report_canvas import normalize_report_page_canvases
from minem.thumbnails import detect_html_dimensions


def now_ms():
    return int(time.time() * 1000)


def next_code(conn, base):
    return f"{base}-C{conn.execute('select count(*) from assets').fetchone()[0] + 1:03d}"


def next_version(conn, group):
    return conn.execute("select coalesce(max(version_no), 0) + 1 from assets where version_group = ?", (group,)).fetchone()[0]


def tags(*groups):
    values = []
    for group in groups:
        values.extend((group.split(",") if isinstance(group, str) else group))
    return list(dict.fromkeys(value for value in values if value))


def insert_asset(conn, asset_id, asset_type, upload_id, source_path, source_hash, *, group="", parent="", code=""):
    timestamp = now_ms()
    conn.execute(
        """
        insert into assets
        (id,title,category,usage,tags,snippet,asset_type,asset_code,media_kind,resource_kind,source_type,source_path,preview_url,upload_id,source_hash,version_group,version_no,version_parent_id,similarity_score,similarity_method,tag_seeded,created_at,updated_at)
        values (?,?, 'page','','','', ?,?,'html','','test',?,?,?, ?,?,1,?,1.0,'',1,?,?)
        """,
        (asset_id, asset_id, asset_type, code or asset_id, source_path, f"/extracted/{upload_id}/{source_path}", upload_id, source_hash, group or asset_id, parent, timestamp, timestamp),
    )


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "extracted"
        upload = root / "upload-1"
        (upload / "pages").mkdir(parents=True)
        (upload / "report.html").write_text("<style>.slide { width: 1920px; height: 1080px; }</style>", encoding="utf-8")
        (upload / "pages/page.html").write_text("<style>.slide { width: 1280px; height: 720px; }</style>", encoding="utf-8")
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_core_schema(conn)
        ensure_asset_schema(conn)
        run_compat_migrations(conn)
        insert_asset(conn, "report-1", "report", "upload-1", "report.html", "report-hash", code="RPT-TEST-001")
        insert_asset(conn, "control-1", "control", "upload-1", "pages/page.html", "control-hash", code="CTRL-TEST-001")
        conn.execute("insert into report_page_slots values ('report-1',1,'page','attached','control-1','','',?,?)", (now_ms(), now_ms()))
        conn.commit()
        args = dict(extracted_root=root, detect_dimensions=detect_html_dimensions, now_ms=now_ms, next_candidate_asset_code=next_code, next_asset_version_no=next_version, merge_tags=tags, read_text_sample=lambda path: Path(path).read_text(encoding="utf-8")[:500])
        first = normalize_report_page_canvases(conn, "report-1", **args)
        assert first["normalized"] == 1 and len(first["created"]) == 1, first
        normalized_id = conn.execute("select control_id from report_page_slots where report_id = 'report-1'").fetchone()[0]
        assert normalized_id != "control-1"
        normalized = conn.execute("select * from assets where id = ?", (normalized_id,)).fetchone()
        assert normalized["version_group"] == "control-1" and normalized["version_parent_id"] == "control-1"
        wrapper_path = root / normalized["upload_id"] / normalized["source_path"]
        wrapper_html = wrapper_path.read_text(encoding="utf-8")
        assert 'src="/extracted/' not in wrapper_html, wrapper_html
        assert "pages/page.html?embed=1" in wrapper_html, wrapper_html
        assert conn.execute("select count(*) from assets where id = 'control-1'").fetchone()[0] == 1
        assert conn.execute("select count(*) from report_page_normalizations").fetchone()[0] == 1
        second = normalize_report_page_canvases(conn, "report-1", **args)
        assert second["normalized"] == 0 and second["reused"] >= 1, second
        assert conn.execute("select count(*) from assets where asset_type = 'control'").fetchone()[0] == 2
        wrapper_path.write_text(
            re.sub(r'src="[^"]+"', 'src="/extracted/upload-1/pages/page.html?embed=1"', wrapper_html, count=1),
            encoding="utf-8",
        )
        conn.execute("delete from report_page_slots where report_id = 'report-1'")
        conn.commit()
        repaired = normalize_report_page_canvases(conn, "report-1", **args)
        assert len(repaired["refreshed"]) == 1, repaired
        assert 'src="/extracted/' not in wrapper_path.read_text(encoding="utf-8")
    print("report canvas normalization: passed")


if __name__ == "__main__":
    main()
