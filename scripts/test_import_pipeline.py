#!/usr/bin/env python3
"""Isolated regression checks for MineM import classification and rollback."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
import minem.thumbnails as thumbnail_module
from minem.asset_deletion import AssetDeletionError, apply_asset_deletion_plan, build_asset_deletion_plan
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema
from minem.imports import normalized_package_hash
from minem.import_tasks import ImportTaskStore
from minem.report_exports import REPORT_EXPORT_TASKS_SCHEMA
from minem.tag_tasks import SCHEMA as TAG_SCHEMA
from minem.thumbnails import detect_html_dimensions


def prepare(conn):
    conn.row_factory = sqlite3.Row
    create_core_schema(conn)
    ensure_asset_schema(conn)
    ensure_upload_schema(conn)


def main():
    with tempfile.TemporaryDirectory(prefix="minem-import-test-") as temp_dir:
        task_store = ImportTaskStore(Path(temp_dir) / "task-recovery.db")
        task_store.create({
            "id": "interrupted-import",
            "status": "running",
            "progress": 38,
            "message": "正在事务性写入素材库",
            "fileName": "interrupted.zip",
        })
        assert task_store.recover_interrupted() == 1
        recovered = task_store.get("interrupted-import")
        assert recovered["status"] == "failed", recovered
        assert recovered["progress"] == 100, recovered
        assert "点击重试" in recovered["error"], recovered
        assert task_store.recover_interrupted() == 0
        assert server.copy_package_preview_thumbnail(
            "test-deferred-thumbnail",
            Path(temp_dir),
            "",
            Path(temp_dir) / "index.html",
        ) is False

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

        nested_marker_root = Path(temp_dir) / "single-page-deck"
        nested_marker_root.mkdir()
        nested_marker_html = nested_marker_root / "page-46.html"
        nested_marker_html.write_text(
            """<!doctype html><html><head><title>单页增量价值</title>
            <meta name="fs-deck-generator" content="render-deck"></head><body>
            <div class="deck">
              <div class="slide-frame" data-page="1">
                <div class="slide" data-slide-key="value">
                  <section data-page-component="before">门店现状</section>
                  <section data-page-component="after">增量结果</section>
                  <div data-slide-component="metric">86.3 万</div>
                  <iframe src="before.html"></iframe>
                  <iframe src="after.html"></iframe>
                  <iframe src="report.html"></iframe>
                </div>
              </div>
            </div></body></html>""",
            encoding="utf-8",
        )
        assert server.detect_report_page_count(nested_marker_html) == 1
        nested_manifest, nested_kind = server.load_report_package_manifest(nested_marker_root)
        assert not nested_kind and nested_manifest == {}, (nested_manifest, nested_kind)
        with conn:
            conn.execute(
                "insert into uploads (id, filename, stored_path, extract_path, created_at) values ('test-single-deck', 'page-46.html', '', ?, 1)",
                (str(nested_marker_root),),
            )
            server.scan_upload("test-single-deck", nested_marker_root, conn=conn)
        nested_rows = conn.execute(
            "select asset_type from assets where upload_id = 'test-single-deck'"
        ).fetchall()
        assert len(nested_rows) == 1 and nested_rows[0]["asset_type"] == "control", nested_rows

        report_root = Path(temp_dir) / "report-with-supporting-html"
        report_entry = report_root / "wrapped" / "site" / "index.html"
        report_entry.parent.mkdir(parents=True)
        report_assets = report_entry.parent / "assets"
        report_assets.mkdir()
        (report_assets / "deck.css").write_text(".slide { color: white; }", encoding="utf-8")
        (report_assets / "cover.png").write_bytes(b"test-image")
        report_entry.write_text(
            """<!doctype html><html><head><title>完整汇报</title>
            <meta name="fs-deck-generator" content="render-deck">
            <link rel="stylesheet" href="assets/deck.css"></head><body>
            <div class="deck">
              <div class="slide-frame"><div class="slide" data-slide-key="cover"><img src="assets/cover.png">封面</div></div>
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
        first_page_html = page_items[0]["path"].read_text(encoding="utf-8")
        expected_base = server.external_report_page_base_href(report_entry, page_items[0]["path"])
        assert f'<base href="{expected_base}">' in first_page_html, first_page_html[:1000]
        resolved_asset = (page_items[0]["path"].parent / unquote(expected_base) / "assets" / "cover.png").resolve()
        assert resolved_asset == (report_assets / "cover.png").resolve() and resolved_asset.exists(), resolved_asset
        assert detect_html_dimensions(page_items[0]["path"]) == (1920, 1080)
        assert "animation: none !important" not in first_page_html

        native_root = Path(temp_dir) / "native-canvas-report"
        native_entry = native_root / "deck" / "index.html"
        native_entry.parent.mkdir(parents=True)
        native_entry.write_text(
            """<!doctype html><html><head><title>原尺寸汇报</title>
            <meta name="fs-deck-generator" content="render-deck">
            <style>.slide { width: 1600px; height: 900px; }</style></head><body>
            <div class="deck"><div class="slide-frame"><div class="slide">原尺寸页面</div></div>
            <div class="slide-frame"><div class="slide">第二页</div></div></div></body></html>""",
            encoding="utf-8",
        )
        native_manifest, native_kind = server.load_report_package_manifest(native_root)
        native_pages = server.report_manifest_page_items(native_root, native_manifest, native_kind)
        assert len(native_pages) == 2, native_pages
        assert detect_html_dimensions(native_pages[0]["path"]) == (1600, 900)
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

        conn.executescript(TAG_SCHEMA)
        conn.executescript(REPORT_EXPORT_TASKS_SCHEMA)
        with conn:
            conn.execute(
                "insert into uploads (id, filename, stored_path, extract_path, asset_count, created_at) values ('delete-test', 'delete-test.zip', '', '', 2, 4)"
            )
            conn.execute(
                """
                insert into assets
                (id, title, category, asset_type, asset_code, media_kind, source_path, preview_url,
                 upload_id, source_hash, version_group, created_at, updated_at)
                values
                ('delete-report', '待删除汇报', 'report', 'report', 'RPT-DELETE-001', 'html',
                 'report/index.html', '/reports/delete-report/index.html', 'delete-test',
                 'delete-report-hash', 'delete-report', 4, 4),
                ('delete-control', '受保护页面', 'page', 'control', 'CTRL-DELETE-001', 'html',
                 'control/index.html', '/pages/delete-control/index.html', 'delete-test',
                 'delete-control-hash', 'delete-control', 4, 4)
                """
            )
            conn.execute(
                "insert into report_page_slots values ('delete-report', 1, '受保护页面', 'completed', 'delete-control', '', '', 4, 4)"
            )
            conn.execute(
                """
                update assets
                set usage = '从汇报素材 RPT-DELETE-001 自动同步的第 1 页页面素材。',
                    source_type = 'report-material-sync'
                where id = 'delete-control'
                """
            )
            conn.execute(
                "insert into report_page_arrangements values ('delete-report', '[\"delete-control\"]', '[]', 'test', 4)"
            )
            conn.execute(
                """
                insert into report_export_tasks
                (id, report_id, format, status, progress, message, page_count, filename, output_path, error, created_at, updated_at)
                values ('delete-export', 'delete-report', 'html', 'completed', 100, '完成', 1, 'delete.zip', '', '', 4, 4)
                """
            )
            conn.execute(
                "insert into asset_tags values ('delete-report', '汇报材料', 'asset_role', 'manual', 1, '[]', 4, 4)"
            )

        try:
            build_asset_deletion_plan(conn, "delete-control")
            raise AssertionError("referenced control deletion should be rejected")
        except AssetDeletionError as error:
            assert error.status == 409, error.status
            assert error.details["referenceCodes"] == ["RPT-DELETE-001"], error.details
        assert conn.execute("select 1 from assets where id = 'delete-control'").fetchone()
        assert conn.execute(
            "select control_id from report_page_slots where report_id = 'delete-report'"
        ).fetchone()["control_id"] == "delete-control"

        with conn:
            report_plan = build_asset_deletion_plan(conn, "delete-report")
            report_result = apply_asset_deletion_plan(conn, report_plan, timestamp=5)
        assert report_result["deleted_count"] == 1, report_result
        assert report_result["retained_control_count"] == 1, report_result
        assert not conn.execute("select 1 from assets where id = 'delete-report'").fetchone()
        retained_control = conn.execute(
            "select usage, source_type from assets where id = 'delete-control'"
        ).fetchone()
        assert retained_control
        assert retained_control["usage"] == "从已删除汇报保留的页面素材。", retained_control
        assert retained_control["source_type"] == "retained-report-page", retained_control
        assert not conn.execute("select 1 from report_page_slots where report_id = 'delete-report'").fetchone()
        assert not conn.execute("select 1 from report_page_arrangements where report_id = 'delete-report'").fetchone()
        assert not conn.execute("select 1 from report_export_tasks where report_id = 'delete-report'").fetchone()
        assert not conn.execute("select 1 from asset_tags where asset_id = 'delete-report'").fetchone()

        with conn:
            control_plan = build_asset_deletion_plan(conn, "delete-control")
            control_result = apply_asset_deletion_plan(conn, control_plan, timestamp=6)
        assert control_result["deleted_count"] == 1, control_result
        assert not conn.execute("select 1 from assets where id = 'delete-control'").fetchone()

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

        thumbnail_root = Path(temp_dir) / "thumbnail-priority"
        thumbnail_root.mkdir()
        thumbnail_html = thumbnail_root / "index.html"
        thumbnail_html.write_text("<!doctype html><html><body>当前页面</body></html>", encoding="utf-8")
        (thumbnail_root / "preview.png").write_bytes(b"stale-preview")
        thumbnail_output = thumbnail_root / "output"
        calls = []
        original_capture = thumbnail_module.capture_html_with_chrome
        original_save = thumbnail_module.save_contained_thumbnail
        original_subprocess = thumbnail_module.subprocess.run
        try:
            def fake_capture(_html_path, output_path, *, image_module):
                calls.append("live")
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"live-render" * 200)
                return True

            def fake_package_preview(*args, **kwargs):
                calls.append("package-preview")
                return True

            thumbnail_module.capture_html_with_chrome = fake_capture
            thumbnail_module.save_contained_thumbnail = fake_package_preview
            created = thumbnail_module.generate_html_thumbnail(
                "test-thumbnail",
                thumbnail_html,
                thumbnails_dir=thumbnail_output,
                image_module=object(),
                image_draw_module=None,
                image_font_module=None,
                read_text_sample=lambda *_: "",
            )
            assert created and calls == ["live"], calls

            calls.clear()
            thumbnail_module.capture_html_with_chrome = lambda *_args, **_kwargs: calls.append("live-failed") or False
            thumbnail_module.subprocess.run = lambda *_args, **_kwargs: type("Result", (), {"returncode": 1})()
            failed = thumbnail_module.generate_html_thumbnail(
                "test-thumbnail-failed",
                thumbnail_html,
                thumbnails_dir=thumbnail_output,
                image_module=object(),
                image_draw_module=None,
                image_font_module=None,
                read_text_sample=lambda *_: "",
                allow_text_fallback=False,
            )
            assert not failed and calls == ["live-failed"], calls
        finally:
            thumbnail_module.capture_html_with_chrome = original_capture
            thumbnail_module.save_contained_thumbnail = original_save
            thumbnail_module.subprocess.run = original_subprocess

        nested_path = thumbnail_root / "nested.png"
        nested = server.Image.new("RGB", (1280, 720), "#000000")
        nested.paste(server.Image.new("RGB", (1092, 614), "#071426"), (0, 0))
        nested.save(nested_path)
        assert thumbnail_module.thumbnail_has_nested_canvas(nested_path, thumbnail_html, image_module=server.Image)
        full_path = thumbnail_root / "full.png"
        server.Image.new("RGB", (1280, 720), "#071426").save(full_path)
        assert not thumbnail_module.thumbnail_has_nested_canvas(full_path, thumbnail_html, image_module=server.Image)

        background_path = thumbnail_root / "background-only.png"
        background = server.Image.new("RGB", (1280, 720), "#071426")
        background.save(background_path)
        assert thumbnail_module.thumbnail_is_background_only(background_path, image_module=server.Image)

        visible_path = thumbnail_root / "visible-content.png"
        visible = server.Image.new("RGB", (1280, 720), "#071426")
        visible.paste(server.Image.new("RGB", (360, 80), "#f7fbff"), (80, 80))
        visible.save(visible_path)
        assert not thumbnail_module.thumbnail_is_background_only(visible_path, image_module=server.Image)

        existing_control = conn.execute(
            "select * from assets where upload_id = 'test-single' and asset_type = 'control' limit 1"
        ).fetchone()
        created_report_root = Path(temp_dir) / "created-report"
        created_page = created_report_root / "pages" / "page-01" / "index.html"
        created_page.parent.mkdir(parents=True)
        created_page.write_text("<!doctype html><html><body>页面副本</body></html>", encoding="utf-8")
        assets_before = conn.execute("select count(*) from assets").fetchone()[0]
        with conn:
            created_ids = server.register_created_report_pages(
                conn,
                report_id="test-created-report",
                report_code="RPT-TEST-001",
                report_title="测试汇报",
                target_root=created_report_root,
                manifest_pages=[{
                    "display_page": 1,
                    "title": existing_control["title"],
                    "source_control_id": existing_control["id"],
                    "control_path": "pages/page-01/index.html",
                }],
                timestamp=4,
            )
        slot = conn.execute(
            "select control_id from report_page_slots where report_id = 'test-created-report' and page_number = 1"
        ).fetchone()
        assert created_ids == []
        assert conn.execute("select count(*) from assets").fetchone()[0] == assets_before
        assert slot and slot["control_id"] == existing_control["id"], slot

        migration_root = Path(temp_dir) / "single-page-migration"
        migration_data = migration_root / "data"
        migration_extracted = migration_root / "extracted"
        migration_thumbnails = migration_root / "thumbnails"
        migration_exports = migration_root / "report-exports"
        migration_data.mkdir(parents=True)
        report_file = migration_extracted / "migration-upload" / "report" / "index.html"
        control_file = migration_extracted / "migration-upload" / "control" / "index.html"
        incomplete_report_file = migration_extracted / "incomplete-upload" / "report" / "index.html"
        report_file.parent.mkdir(parents=True)
        control_file.parent.mkdir(parents=True)
        incomplete_report_file.parent.mkdir(parents=True)
        report_file.write_text(
            """<!doctype html><html><body><div class="slide-frame" data-page="1">
            <div class="slide" data-slide-key="one">单页汇报误分类</div></div></body></html>""",
            encoding="utf-8",
        )
        control_file.write_text("<!doctype html><html><body>单页页面素材</body></html>", encoding="utf-8")
        incomplete_report_file.write_text(
            """<!doctype html><html><body><div class="slide-frame" data-page="1">
            <div class="slide">页槽尚未同步的正常汇报</div></div></body></html>""",
            encoding="utf-8",
        )
        original_runtime_paths = (
            server.DB_PATH,
            server.EXTRACTED,
            server.THUMBNAILS,
            server.REPORT_EXPORTS,
        )
        try:
            server.DB_PATH = migration_data / "materials.db"
            server.EXTRACTED = migration_extracted
            server.THUMBNAILS = migration_thumbnails
            server.REPORT_EXPORTS = migration_exports
            migration_thumbnails.mkdir(parents=True)
            migration_exports.mkdir(parents=True)
            with server.db() as migration_conn:
                create_core_schema(migration_conn)
                ensure_asset_schema(migration_conn)
                ensure_upload_schema(migration_conn)
                migration_conn.execute(
                    """
                    insert into uploads
                    (id, filename, stored_path, extract_path, file_count, asset_count, created_at)
                    values
                    ('migration-upload', 'page-46.html', '', '', 2, 2, 7),
                    ('incomplete-upload', 'incomplete-report.html', '', '', 1, 1, 8)
                    """
                )
                migration_conn.execute(
                    """
                    insert into assets
                    (id, title, category, asset_type, asset_code, media_kind, source_type,
                     source_path, preview_url, upload_id, source_hash, version_group, created_at, updated_at)
                    values
                    ('migration-report', '单页方案 | 完整汇报材料', 'report', 'report', 'RPT-MIGRATION-001',
                     'html', 'report-material-sync', 'report/index.html', '/reports/migration-report/index.html',
                     'migration-upload', 'migration-report-hash', 'migration-report', 7, 7),
                    ('migration-control', '01 单页方案', 'page', 'control', 'CTRL-MIGRATION-001',
                     'html', 'report-material-sync', 'control/index.html', '/pages/migration-control/index.html',
                     'migration-upload', 'migration-control-hash', 'migration-control', 7, 7),
                    ('incomplete-report', '页槽尚未同步的正常汇报', 'report', 'report', 'RPT-MIGRATION-002',
                     'html', 'report-material-sync', 'report/index.html', '/reports/incomplete-report/index.html',
                     'incomplete-upload', 'incomplete-report-hash', 'incomplete-report', 8, 8)
                    """
                )
                migration_conn.execute(
                    """
                    insert into report_page_slots
                    values ('migration-report', 1, '01 单页方案', 'completed',
                            'migration-control', '', '', 7, 7)
                    """
                )
            assert server.reclassify_single_page_report_assets() == 1
            trusted_entry = server.validate_report_trusted_entry_by_id("incomplete-report")
            assert trusted_entry["ok"] is True, trusted_entry
            assert trusted_entry["exists"] is True, trusted_entry
            assert trusted_entry["size"] > 0, trusted_entry
            with server.db() as migration_conn:
                assert not migration_conn.execute(
                    "select 1 from assets where id = 'migration-report'"
                ).fetchone()
                migrated_control = migration_conn.execute(
                    "select * from assets where id = 'migration-control'"
                ).fetchone()
                assert migrated_control and migrated_control["asset_type"] == "control", migrated_control
                assert migrated_control["title"] == "单页方案", migrated_control["title"]
                incomplete_report = migration_conn.execute(
                    "select * from assets where id = 'incomplete-report'"
                ).fetchone()
                assert incomplete_report and incomplete_report["asset_type"] == "report", incomplete_report
                assert incomplete_report["trusted_entry_ok"] == 1, dict(incomplete_report)
                assert incomplete_report["trusted_size"] > 0, dict(incomplete_report)
                assert migration_conn.execute(
                    "select asset_count from uploads where id = 'migration-upload'"
                ).fetchone()["asset_count"] == 1
            assert not report_file.exists()
            assert control_file.exists()
        finally:
            (
                server.DB_PATH,
                server.EXTRACTED,
                server.THUMBNAILS,
                server.REPORT_EXPORTS,
            ) = original_runtime_paths
    print("import pipeline checks passed")


if __name__ == "__main__":
    main()
