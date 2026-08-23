import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import server
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema


class PresenterScriptLifecycleTest(unittest.TestCase):
    @staticmethod
    def prepare_database(path: Path) -> None:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            create_core_schema(conn)
            ensure_asset_schema(conn)
            ensure_upload_schema(conn)
            conn.execute(
                """
                insert into assets
                (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                 preview_url,upload_id,source_hash,version_group,created_at,updated_at)
                values ('report-a','Report','report','report','RPT-1','html','test','index.html',
                        '/extracted/upload-a/index.html','upload-a','report-a','report-a',1,1)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def test_delete_and_restore_preserves_script_and_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            database = runtime / "materials.db"
            extracted = runtime / "extracted"
            upload_root = extracted / "upload-a"
            upload_root.mkdir(parents=True)
            self.prepare_database(database)
            (upload_root / "index.html").write_text("<!doctype html><title>Report</title>", encoding="utf-8")
            presenter = upload_root / "ai-presenter.html"
            presenter.write_text(
                """
                <script>
                const pages = [{"id":"page-01","title":"Page 1","src":"index.html"}];
                const defaultSpeakerNotes = {"page-01":"保留这段演讲稿。"};
                let currentIndex = 0;
                </script>
                """,
                encoding="utf-8",
            )
            metadata = presenter.with_suffix(".meta.json")
            metadata.write_text(
                json.dumps({
                    "sourceType": "minutes",
                    "minutesUrl": "https://example.com/minutes",
                    "updatedAt": 123456,
                }),
                encoding="utf-8",
            )
            original_html = presenter.read_bytes()

            with (
                patch.object(server, "DB_PATH", database),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
            ):
                initial = server.report_presenter_status("report-a")
                deleted = server.delete_report_presenter_script("report-a")
                presenter_missing_after_delete = not presenter.exists()
                restored = server.restore_report_presenter_script("report-a")

            self.assertTrue(initial["hasScript"])
            self.assertEqual(initial["sourceType"], "minutes")
            self.assertEqual(initial["minutesUrl"], "https://example.com/minutes")
            self.assertEqual(initial["updatedAt"], 123456)
            self.assertTrue(deleted["deleted"])
            self.assertFalse(deleted["hasScript"])
            self.assertTrue(deleted["canRestore"])
            self.assertTrue(presenter_missing_after_delete)
            self.assertTrue(restored["restored"])
            self.assertTrue(restored["hasScript"])
            self.assertFalse(restored["canRestore"])
            self.assertEqual(restored["sourceType"], "minutes")
            self.assertEqual(restored["minutesUrl"], "https://example.com/minutes")
            self.assertEqual(presenter.read_bytes(), original_html)

    def test_restore_refuses_to_overwrite_existing_presenter(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            database = runtime / "materials.db"
            extracted = runtime / "extracted"
            upload_root = extracted / "upload-a"
            trash = upload_root / "_presenter_trash"
            trash.mkdir(parents=True)
            self.prepare_database(database)
            (upload_root / "index.html").write_text("<!doctype html>", encoding="utf-8")
            (upload_root / "ai-presenter.html").write_text("current", encoding="utf-8")
            (trash / "1-ai-presenter.html").write_text("deleted", encoding="utf-8")

            with (
                patch.object(server, "DB_PATH", database),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
            ):
                result = server.restore_report_presenter_script("report-a")

            self.assertFalse(result["ok"])
            self.assertIn("不能覆盖恢复", result["error"])
            self.assertEqual((upload_root / "ai-presenter.html").read_text(encoding="utf-8"), "current")

    def test_save_one_page_note_preserves_other_page_notes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            database = runtime / "materials.db"
            extracted = runtime / "extracted"
            upload_root = extracted / "upload-a"
            upload_root.mkdir(parents=True)
            self.prepare_database(database)
            (upload_root / "index.html").write_text("<!doctype html><title>Report</title>", encoding="utf-8")
            presenter = upload_root / "ai-presenter.html"
            presenter.write_text(
                """
                <script>
                const pages = [{"id":"legacy-01","title":"Page 1","src":"index.html"}];
                const defaultSpeakerNotes = {"control-b":"另一页提示词"};
                </script>
                """,
                encoding="utf-8",
            )
            arranged_pages = [{
                "id": "control-a",
                "code": "CTRL-A",
                "title": "当前页",
                "src": "/pages/control-a/index.html",
                "thumbnailUrl": "/thumbnails/control-a.png",
            }]

            with (
                patch.object(server, "DB_PATH", database),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "report_public_page_items", return_value=({"ok": True}, arranged_pages)),
            ):
                result = server.save_report_presenter_page_note(
                    "report-a",
                    {"pageId": "CTRL-A", "note": "修改后的当前页提示词"},
                )
                notes = server.read_presenter_notes(presenter)

            self.assertTrue(result["ok"])
            self.assertEqual(result["pageId"], "control-a")
            self.assertEqual(notes["control-a"], "修改后的当前页提示词")
            self.assertEqual(notes["control-b"], "另一页提示词")


if __name__ == "__main__":
    unittest.main()
