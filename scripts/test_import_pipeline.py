#!/usr/bin/env python3
"""Isolated regression checks for MineM import classification and rollback."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema
from minem.imports import normalized_package_hash


def prepare(conn):
    conn.row_factory = sqlite3.Row
    create_core_schema(conn)
    ensure_asset_schema(conn)
    ensure_upload_schema(conn)


def main():
    with tempfile.TemporaryDirectory(prefix="minem-import-test-") as temp_dir:
        root = Path(temp_dir) / "single-page"
        root.mkdir()
        (root / "index.html").write_text(
            "<!doctype html><html><head><title>单页方案</title></head><body><main>页面内容</main></body></html>",
            encoding="utf-8",
        )
        conn = sqlite3.connect(":memory:")
        prepare(conn)
        with conn:
            conn.execute(
                "insert into uploads (id, filename, stored_path, extract_path, created_at) values ('test-single', 'index.html', '', ?, 1)",
                (str(root),),
            )
            server.scan_upload("test-single", root, conn=conn)
        row = conn.execute("select asset_type, tags from assets").fetchone()
        assert row and row["asset_type"] == "control", row
        assert row["tags"] == "", row

        report_root = Path(temp_dir) / "report-with-supporting-html"
        report_entry = report_root / "wrapped" / "site" / "index.html"
        report_entry.parent.mkdir(parents=True)
        report_entry.write_text(
            """<!doctype html><html><head><title>完整汇报</title>
            <meta name="fs-deck-generator" content="render-deck"></head><body>
            <div class="deck">
              <div class="slide-frame"><div class="slide" data-slide-key="cover">封面</div></div>
              <div class="slide-frame"><div class="slide" data-slide-key="summary">总结</div></div>
            </div></body></html>""",
            encoding="utf-8",
        )
        supporting = report_root / "wrapped" / "site" / "prototypes" / "index.html"
        supporting.parent.mkdir(parents=True)
        supporting.write_text("<!doctype html><html><body>辅助原型</body></html>", encoding="utf-8")
        manifest, manifest_kind = server.load_report_package_manifest(report_root)
        assert manifest_kind == "html-report", (manifest, manifest_kind)
        assert manifest["entry"] == "wrapped/site/index.html", manifest
        page_items = server.report_manifest_page_items(report_root, manifest, manifest_kind)
        assert len(page_items) == 2, page_items
        assert all(item["path"].exists() for item in page_items), page_items
        with conn:
            conn.execute(
                "insert into uploads (id, filename, stored_path, extract_path, created_at) values ('test-report', 'report.zip', '', ?, 2)",
                (str(report_root),),
            )
            original_thumbnail_writer = server.copy_package_preview_thumbnail
            server.copy_package_preview_thumbnail = lambda *args, **kwargs: True
            try:
                server.scan_upload("test-report", report_root, conn=conn)
            finally:
                server.copy_package_preview_thumbnail = original_thumbnail_writer
        report_types = conn.execute(
            "select asset_type, count(*) as count from assets where upload_id = 'test-report' group by asset_type"
        ).fetchall()
        assert {row["asset_type"]: row["count"] for row in report_types} == {"control": 2, "report": 1}, report_types
        report_id = conn.execute(
            "select id from assets where upload_id = 'test-report' and asset_type = 'report'"
        ).fetchone()["id"]
        linked_pages = conn.execute(
            "select count(*) from report_page_slots where report_id = ? and control_id <> ''",
            (report_id,),
        ).fetchone()[0]
        assert linked_pages == 2, linked_pages
        with conn:
            original_thumbnail_writer = server.copy_package_preview_thumbnail
            server.copy_package_preview_thumbnail = lambda *args, **kwargs: True
            try:
                server.scan_upload("test-report", report_root, conn=conn)
            finally:
                server.copy_package_preview_thumbnail = original_thumbnail_writer
        repeated_types = conn.execute(
            "select asset_type, count(*) as count from assets where upload_id = 'test-report' group by asset_type"
        ).fetchall()
        assert {row["asset_type"]: row["count"] for row in repeated_types} == {"control": 2, "report": 1}, repeated_types

        multi_root = Path(temp_dir) / "independent-pages"
        for name in ("alpha", "beta"):
            page_root = multi_root / name
            page_root.mkdir(parents=True)
            (page_root / "index.html").write_text(
                f"<!doctype html><html><head><title>{name}</title></head><body>{name}</body></html>",
                encoding="utf-8",
            )
        with conn:
            conn.execute(
                "insert into uploads (id, filename, stored_path, extract_path, created_at) values ('test-multi', 'pages.zip', '', ?, 2)",
                (str(multi_root),),
            )
            server.scan_upload("test-multi", multi_root, conn=conn)
        rows = conn.execute("select asset_type from assets where upload_id = 'test-multi'").fetchall()
        assert len(rows) == 2 and {row["asset_type"] for row in rows} == {"control"}, rows

        direct_root = Path(temp_dir) / "direct"
        direct_root.mkdir()
        first = direct_root / "first.png"
        second = direct_root / "renamed.png"
        first.write_bytes(b"same-resource-content")
        second.write_bytes(first.read_bytes())
        with conn:
            conn.execute(
                "insert into uploads (id, filename, stored_path, extract_path, created_at) values ('test-direct', 'manual', '', ?, 3)",
                (str(direct_root),),
            )
            assert server.import_direct_file(conn, first, "test-direct", direct_root / "stored") is True
            assert server.import_direct_file(conn, second, "test-direct", direct_root / "stored") is False
        assert conn.execute("select count(*) from assets where upload_id = 'test-direct'").fetchone()[0] == 1

        same_root = Path(temp_dir) / "same-content"
        same_root.mkdir()
        (same_root / "index.html").write_bytes((root / "index.html").read_bytes())
        assert normalized_package_hash(root) == normalized_package_hash(same_root)

        rollback_conn = sqlite3.connect(":memory:")
        prepare(rollback_conn)
        try:
            with rollback_conn:
                rollback_conn.execute(
                    "insert into uploads (id, filename, stored_path, extract_path, created_at) values ('test-rollback', 'index.html', '', ?, 1)",
                    (str(root),),
                )
                server.scan_upload("test-rollback", root, conn=rollback_conn)
                raise RuntimeError("simulate validation failure")
        except RuntimeError:
            pass
        assert rollback_conn.execute("select count(*) from uploads").fetchone()[0] == 0
        assert rollback_conn.execute("select count(*) from assets").fetchone()[0] == 0
    print("import pipeline checks passed")


if __name__ == "__main__":
    main()
