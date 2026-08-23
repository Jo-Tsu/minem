import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import server
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema
from scripts import govern_material_data


class PreviewSourceContractsTest(unittest.TestCase):
    @staticmethod
    def prepare_database(path: Path) -> None:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            create_core_schema(conn)
            ensure_asset_schema(conn)
            ensure_upload_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def test_page_prefers_its_direct_preview_over_parent_report_entry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            extracted = runtime / "extracted"
            direct = extracted / "generated-pages" / "page-a" / "index.html"
            parent = extracted / "parent-report" / "index.html"
            direct.parent.mkdir(parents=True)
            parent.parent.mkdir(parents=True)
            direct.write_text("<title>Standalone page</title>", encoding="utf-8")
            parent.write_text("<title>Complete report</title>", encoding="utf-8")
            row = {
                "asset_type": "control",
                "preview_url": "/extracted/generated-pages/page-a/index.html",
                "upload_id": "parent-report",
                "source_path": "index.html",
            }

            with (
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(govern_material_data, "RUNTIME_ROOT", runtime),
                patch.object(govern_material_data, "EXTRACTED", extracted),
            ):
                self.assertEqual(server.canonical_preview_url(row), row["preview_url"])
                self.assertEqual(server.local_html_preview_path(row), direct.resolve())
                self.assertEqual(govern_material_data.asset_path(row), direct.resolve())

    def test_page_source_doc_reads_ingestion_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            extracted = runtime / "extracted"
            page = extracted / "upload-a" / "index.html"
            page.parent.mkdir(parents=True)
            page.write_text("<title>Case page</title>", encoding="utf-8")
            source_doc = "https://bytedance.larkoffice.com/docx/source-document"
            (page.parent / "ingestion-manifest.json").write_text(
                json.dumps({"sourceDoc": source_doc}),
                encoding="utf-8",
            )
            row = {
                "asset_type": "control",
                "preview_url": "/extracted/upload-a/index.html",
                "upload_id": "upload-a",
                "source_path": "index.html",
            }

            with (
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
            ):
                self.assertEqual(server.control_source_doc(row), source_doc)

    def test_runtime_page_edit_invalidates_thumbnail_fingerprint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            extracted = runtime / "extracted"
            page = extracted / "upload-a" / "page.html"
            page.parent.mkdir(parents=True)
            page.write_text("<title>Version one</title>", encoding="utf-8")
            row = {
                "id": "control-a",
                "asset_type": "control",
                "media_kind": "html",
                "preview_url": "/extracted/upload-a/page.html",
                "upload_id": "upload-a",
                "source_path": "page.html",
                "source_hash": "stable-import-hash",
            }

            with (
                patch.object(server, "ROOT", runtime / "app"),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
            ):
                first = server.thumbnail_source_fingerprint(row)
                page.write_text("<title>Version two has changed</title>", encoding="utf-8")
                os.utime(page, ns=(page.stat().st_atime_ns, page.stat().st_mtime_ns + 1_000_000))
                second = server.thumbnail_source_fingerprint(row)

            self.assertNotEqual(first, second)

    def test_legacy_thumbnail_metadata_migrates_without_redrawing_unchanged_page(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            extracted = runtime / "extracted"
            thumbnails = runtime / "thumbnails"
            page = extracted / "upload-a" / "page.html"
            thumbnail = thumbnails / "control-a.png"
            page.parent.mkdir(parents=True)
            thumbnails.mkdir()
            page.write_text("<title>Unchanged page</title>", encoding="utf-8")
            thumbnail.write_bytes(b"thumbnail")
            page_mtime = page.stat().st_mtime_ns
            os.utime(thumbnail, ns=(page_mtime + 2_000_000, page_mtime + 2_000_000))
            row = {
                "id": "control-a",
                "asset_type": "control",
                "media_kind": "html",
                "preview_url": "/extracted/upload-a/page.html",
                "upload_id": "upload-a",
                "source_path": "page.html",
                "source_hash": "stable-import-hash",
            }

            with (
                patch.object(server, "ROOT", runtime / "app"),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "THUMBNAILS", thumbnails),
            ):
                legacy_fingerprint = server.legacy_thumbnail_source_fingerprint(row)
                (thumbnails / "control-a.json").write_text(
                    json.dumps({
                        "version": server.THUMBNAIL_META_VERSION,
                        "assetId": "control-a",
                        "sourceFingerprint": legacy_fingerprint,
                        "updatedAt": 1,
                    }),
                    encoding="utf-8",
                )
                url = server.asset_thumbnail_url(row)
                metadata = json.loads((thumbnails / "control-a.json").read_text(encoding="utf-8"))
                expected_fingerprint = server.thumbnail_source_fingerprint(row)

            self.assertTrue(url.startswith("/thumbnails/control-a.png?v="), url)
            self.assertEqual(metadata["sourceFingerprint"], expected_fingerprint)

    def test_html_source_queues_thumbnail_even_with_legacy_none_media_kind(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            extracted = runtime / "extracted"
            page = extracted / "upload-a" / "page.html"
            page.parent.mkdir(parents=True)
            page.write_text("<title>Legacy HTML</title>", encoding="utf-8")
            row = {
                "id": "control-a",
                "asset_type": "control",
                "media_kind": "none",
                "preview_url": "/extracted/upload-a/page.html",
                "upload_id": "upload-a",
                "source_path": "page.html",
                "source_hash": "legacy-html",
            }

            with (
                patch.object(server, "ROOT", runtime / "app"),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "THUMBNAILS", runtime / "thumbnails"),
                patch.object(server, "enqueue_thumbnail_refresh") as enqueue,
            ):
                self.assertEqual(server.asset_thumbnail_url(row), "")

            enqueue.assert_called_once()
            self.assertEqual(enqueue.call_args.args[0], "control-a")
            self.assertEqual(enqueue.call_args.args[1], page)

    def test_stale_thumbnail_remains_visible_while_refresh_is_queued(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            extracted = runtime / "extracted"
            thumbnails = runtime / "thumbnails"
            page = extracted / "upload-a" / "page.html"
            thumbnail = thumbnails / "control-a.png"
            page.parent.mkdir(parents=True)
            thumbnails.mkdir()
            page.write_text("<title>Updated page</title>", encoding="utf-8")
            thumbnail.write_bytes(b"stale-thumbnail")
            (thumbnails / "control-a.json").write_text(
                json.dumps({
                    "version": server.THUMBNAIL_META_VERSION,
                    "assetId": "control-a",
                    "sourceFingerprint": "outdated",
                    "updatedAt": 1,
                }),
                encoding="utf-8",
            )
            row = {
                "id": "control-a",
                "asset_type": "control",
                "media_kind": "html",
                "preview_url": "/extracted/upload-a/page.html",
                "upload_id": "upload-a",
                "source_path": "page.html",
                "source_hash": "updated-import-hash",
            }

            with (
                patch.object(server, "ROOT", runtime / "app"),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "THUMBNAILS", thumbnails),
                patch.object(server, "enqueue_thumbnail_refresh") as enqueue,
            ):
                url = server.asset_thumbnail_url(row)

            self.assertTrue(url.startswith("/thumbnails/control-a.png?v="), url)
            enqueue.assert_called_once()

    def test_report_thumbnail_uses_first_visible_page_current_version(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            database = runtime / "materials.db"
            extracted = runtime / "extracted"
            thumbnails = runtime / "thumbnails"
            upload = extracted / "upload-a"
            upload.mkdir(parents=True)
            thumbnails.mkdir()
            self.prepare_database(database)
            for control_id in ("control-a", "control-b"):
                (upload / f"{control_id}.html").write_text(
                    f"<title>{control_id}</title>",
                    encoding="utf-8",
                )

            with (
                patch.object(server, "DB_PATH", database),
                patch.object(server, "ROOT", runtime / "app"),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "THUMBNAILS", thumbnails),
            ):
                with server.db() as conn:
                    for index, control_id in enumerate(("control-a", "control-b"), start=1):
                        conn.execute(
                            """
                            insert into assets
                            (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                             preview_url,upload_id,source_hash,version_group,created_at,updated_at)
                            values (?,?,'page','control',?,'html','test',?,?,'upload-a',?,?,1,1)
                            """,
                            (
                                control_id,
                                control_id,
                                f"CTRL-{index}",
                                f"{control_id}.html",
                                f"/extracted/upload-a/{control_id}.html",
                                control_id,
                                control_id,
                            ),
                        )
                    conn.execute(
                        """
                        insert into assets
                        (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                         preview_url,upload_id,source_hash,version_group,created_at,updated_at)
                        values ('report-a','Report','report','report','RPT-1','html','test','index.html',
                                '/reports/report-a/index.html','upload-a','report-a','report-a',1,1)
                        """
                    )
                    conn.execute(
                        "insert into report_page_slots values ('report-a',1,'A','attached','control-a','','',1,1)"
                    )
                    conn.execute(
                        "insert into report_page_slots values ('report-a',2,'B','attached','control-b','','',1,1)"
                    )
                    conn.execute(
                        "insert into report_page_arrangements values ('report-a',?,?,'test',1)",
                        (
                            json.dumps(["control-b", "control-a"]),
                            json.dumps(["control-b"]),
                        ),
                    )
                    cover = conn.execute("select * from assets where id = 'control-a'").fetchone()
                    report = conn.execute("select * from assets where id = 'report-a'").fetchone()
                    (thumbnails / "control-a.png").write_bytes(b"thumbnail")
                    (thumbnails / "report-a.png").write_bytes(b"report-thumbnail")
                    server.write_thumbnail_meta(
                        "control-a",
                        server.thumbnail_source_fingerprint(cover),
                    )
                    thumbnail_url = server.asset_thumbnail_url(report, conn=conn)

            self.assertTrue(thumbnail_url.startswith("/thumbnails/control-a.png?v="), thumbnail_url)

    def test_report_without_page_thumbnail_queues_first_visible_page_thumbnail(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            database = runtime / "materials.db"
            extracted = runtime / "extracted"
            thumbnails = runtime / "thumbnails"
            upload = extracted / "upload-a"
            upload.mkdir(parents=True)
            thumbnails.mkdir()
            self.prepare_database(database)
            page = upload / "control-a.html"
            page.write_text("<title>Cover</title>", encoding="utf-8")

            with (
                patch.object(server, "DB_PATH", database),
                patch.object(server, "ROOT", runtime / "app"),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "THUMBNAILS", thumbnails),
                patch.object(server, "enqueue_thumbnail_refresh") as enqueue,
            ):
                with server.db() as conn:
                    conn.execute(
                        """
                        insert into assets
                        (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                         preview_url,upload_id,source_hash,version_group,created_at,updated_at)
                        values ('control-a','Cover','page','control','CTRL-1','html','test','control-a.html',
                                '/extracted/upload-a/control-a.html','upload-a','control-a','control-a',1,1)
                        """
                    )
                    conn.execute(
                        """
                        insert into assets
                        (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                         preview_url,upload_id,source_hash,version_group,created_at,updated_at)
                        values ('report-a','Report','report','report','RPT-1','html','test','index.html',
                                '/reports/report-a/index.html','upload-a','report-a','report-a',1,1)
                        """
                    )
                    conn.execute(
                        "insert into report_page_slots values ('report-a',1,'Cover','attached','control-a','','',1,1)"
                    )
                    report = conn.execute("select * from assets where id = 'report-a'").fetchone()
                    self.assertEqual(server.asset_thumbnail_url(report, conn=conn), "")

            enqueue.assert_called_once()
            self.assertEqual(enqueue.call_args.args[0], "control-a")
            self.assertEqual(enqueue.call_args.args[1], page)

    def test_historical_page_thumbnail_uses_current_primary_version(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            database = runtime / "materials.db"
            extracted = runtime / "extracted"
            thumbnails = runtime / "thumbnails"
            upload = extracted / "upload-a"
            upload.mkdir(parents=True)
            thumbnails.mkdir()
            self.prepare_database(database)
            (upload / "old.html").write_text("<title>Old</title>", encoding="utf-8")
            (upload / "new.html").write_text("<title>New</title>", encoding="utf-8")

            with (
                patch.object(server, "DB_PATH", database),
                patch.object(server, "ROOT", runtime / "app"),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "THUMBNAILS", thumbnails),
            ):
                with server.db() as conn:
                    for asset_id, source_path, parent_id, version_no in (
                        ("control-old", "old.html", "control-new", 2),
                        ("control-new", "new.html", "", 1),
                    ):
                        conn.execute(
                            """
                            insert into assets
                            (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                             preview_url,upload_id,source_hash,version_group,version_no,version_parent_id,
                             created_at,updated_at)
                            values (?,?,'page','control',?,'html','test',?,?,'upload-a',?,'control-new',?,?,1,?)
                            """,
                            (
                                asset_id,
                                asset_id,
                                f"CTRL-{version_no}",
                                source_path,
                                f"/extracted/upload-a/{source_path}",
                                asset_id,
                                version_no,
                                parent_id,
                                version_no,
                            ),
                        )
                    current = conn.execute("select * from assets where id = 'control-new'").fetchone()
                    history = conn.execute("select * from assets where id = 'control-old'").fetchone()
                    (thumbnails / "control-new.png").write_bytes(b"current-thumbnail")
                    server.write_thumbnail_meta(
                        "control-new",
                        server.thumbnail_source_fingerprint(current),
                    )
                    thumbnail_url = server.asset_thumbnail_url(history, conn=conn)

            self.assertTrue(thumbnail_url.startswith("/thumbnails/control-new.png?v="), thumbnail_url)

    def test_promoting_page_version_updates_saved_report_arrangement(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "materials.db"
            self.prepare_database(database)
            with patch.object(server, "DB_PATH", database):
                with server.db() as conn:
                    for control_id, version_no, parent_id in (
                        ("control-old", 1, ""),
                        ("control-new", 2, "control-old"),
                    ):
                        conn.execute(
                            """
                            insert into assets
                            (id,title,category,asset_type,asset_code,media_kind,source_type,source_hash,
                             version_group,version_no,version_parent_id,created_at,updated_at)
                            values (?,?,'page','control',?,'html','test',?,'control-old',?,?,1,1)
                            """,
                            (
                                control_id,
                                control_id,
                                f"CTRL-{version_no}",
                                control_id,
                                version_no,
                                parent_id,
                            ),
                        )
                    conn.execute(
                        "insert into report_page_slots values ('report-a',1,'Page','attached','control-old','','',1,1)"
                    )
                    conn.execute(
                        "insert into report_page_arrangements values ('report-a',?,?,'test',1)",
                        (json.dumps(["control-old"]), json.dumps(["control-old"])),
                    )
                    server.promote_asset_version(conn, "control-new")
                    slot = conn.execute(
                        "select control_id from report_page_slots where report_id = 'report-a'"
                    ).fetchone()
                    arrangement = conn.execute(
                        "select page_order, hidden_page_ids from report_page_arrangements where report_id = 'report-a'"
                    ).fetchone()

            self.assertEqual(slot["control_id"], "control-new")
            self.assertEqual(json.loads(arrangement["page_order"]), ["control-new"])
            self.assertEqual(json.loads(arrangement["hidden_page_ids"]), ["control-new"])

    def test_manual_merge_normalizes_every_selected_version_group(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "materials.db"
            self.prepare_database(database)
            with patch.object(server, "DB_PATH", database):
                with server.db() as conn:
                    for asset_id, group_id, version_no, parent_id, updated_at in (
                        ("group-a", "group-a", 1, "", 1),
                        ("group-a-child", "group-a", 2, "group-a", 2),
                        ("group-b", "group-b", 1, "", 3),
                        ("group-b-child", "group-b", 2, "group-b", 4),
                    ):
                        conn.execute(
                            """
                            insert into assets
                            (id,title,category,asset_type,asset_code,media_kind,source_type,source_hash,
                             version_group,version_no,version_parent_id,created_at,updated_at)
                            values (?,?,'page','control',?,'html','test',?,?,?,?,1,?)
                            """,
                            (
                                asset_id,
                                asset_id,
                                f"CTRL-{asset_id}",
                                asset_id,
                                group_id,
                                version_no,
                                parent_id,
                                updated_at,
                            ),
                        )

                result = server.manual_merge_asset_versions({
                    "assetIds": ["group-a-child", "group-b-child"],
                    "primaryAssetId": "group-b-child",
                    "mode": "version",
                })
                self.assertTrue(result["ok"], result)

                with server.db() as conn:
                    rows = conn.execute(
                        """
                        select id, version_group, version_no, version_parent_id
                        from assets
                        order by version_no
                        """
                    ).fetchall()

            self.assertEqual(len(rows), 4)
            self.assertEqual({row["version_group"] for row in rows}, {"group-b-child"})
            self.assertEqual([row["version_no"] for row in rows], [1, 2, 3, 4])
            self.assertEqual(
                [row["id"] for row in rows if not row["version_parent_id"]],
                ["group-b-child"],
            )
            self.assertTrue(
                all(
                    row["id"] == "group-b-child"
                    or row["version_parent_id"] == "group-b-child"
                    for row in rows
                )
            )

    def test_single_page_viewer_hides_redundant_pagination(self) -> None:
        html = server.report_viewer_html(
            "Single page",
            [{"title": "Page", "code": "CTRL-001", "src": "/extracted/page/index.html"}],
        )

        self.assertIn(".page-pill[hidden] { display: none; }", html)
        self.assertIn('if (pages.length <= 1) document.querySelector(".page-pill").hidden = true;', html)

    def test_report_viewer_runs_only_current_and_adjacent_pages(self) -> None:
        html = server.report_viewer_html(
            "Preloaded report",
            [
                {"title": "Page 1", "code": "CTRL-001", "src": "/extracted/page-1/index.html"},
                {"title": "Page 2", "code": "CTRL-002", "src": "/extracted/page-2/index.html"},
            ],
        )

        self.assertIn("function trimFramesAround(index)", html)
        self.assertIn("function warmAdjacentFrames(index)", html)
        self.assertIn("Math.abs(frameIndex - index) > 1", html)
        self.assertIn('frame.setAttribute("sandbox", "allow-scripts")', html)
        self.assertIn('frame.classList.toggle("is-active"', html)
        self.assertIn('refreshButton.addEventListener("click", refreshCurrentPage);', html)
        self.assertNotIn("function preloadAllPages()", html)
        self.assertNotIn('pages.forEach((_, index) => loadFrame(index));', html)
        self.assertNotIn("allow-popups", html)
        self.assertNotIn("allow-modals", html)
        self.assertIn("pageLoadSequences", html)

    def test_report_viewer_only_accepts_valid_navigation_from_active_page(self) -> None:
        html = server.report_viewer_html(
            "Navigation boundary",
            [
                {"title": "Page 1", "code": "CTRL-001", "src": "/extracted/page-1/index.html"},
                {"title": "Page 2", "code": "CTRL-002", "src": "/extracted/page-2/index.html"},
            ],
        )

        self.assertIn(
            "const sourceIndex = frames.findIndex(frame => frame && event.source === frame.contentWindow);",
            html,
        )
        self.assertIn(
            'if (sourceIndex !== currentIndex || event.data?.type !== "report:navigate") return;',
            html,
        )
        self.assertIn("const targetIndex = resolvePageIndex(event.data.target, -1);", html)
        self.assertIn("if (targetIndex < 0) return;", html)
        self.assertIn(
            'const hashTarget = new URLSearchParams(hashValue).get("page");',
            html,
        )
        self.assertNotIn(
            'new URLSearchParams(hashValue).get("page") || hashValue',
            html,
        )
        self.assertIn("syncPageUrl(pages[currentIndex]);", html)

    def test_embedded_preview_keeps_platform_resource_browser_apis(self) -> None:
        html = server.inject_embedded_preview_style(
            "<!doctype html><html><head>"
            '<script src="https://magic.solutionsuite.cn/html-to-image.js"></script>'
            "<script>window.appReady = true;</script></head></html>"
        )

        self.assertIn('id="minem-embedded-preview-style"', html)
        self.assertNotIn("minem-embedded-preview-isolation", html)
        self.assertNotIn("window.BroadcastChannel =", html)
        self.assertNotIn("Object.defineProperty(window, 'parent'", html)
        self.assertNotIn('<script src="https://magic.solutionsuite.cn/html-to-image.js">', html)
        self.assertIn("window.appReady = true", html)

    def test_report_arrangement_cache_reuses_reads_and_invalidates_after_writes(self) -> None:
        payload = {"ok": True, "reportId": "report-a", "pages": []}
        server.invalidate_stats_cache()
        with (
            patch.object(server, "report_arrangement_signature", side_effect=[(1, 1, 1, 1)] * 5),
            patch.object(server, "_build_report_arrangement_payload", return_value=payload) as build,
        ):
            self.assertIs(server.report_arrangement_payload("report-a"), payload)
            self.assertIs(server.report_arrangement_payload("report-a"), payload)
            self.assertEqual(build.call_count, 1)

            server.invalidate_stats_cache()
            self.assertIs(server.report_arrangement_payload("report-a"), payload)
            self.assertEqual(build.call_count, 2)


if __name__ == "__main__":
    unittest.main()
