from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import server
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema


class SinglePageReclassificationTest(unittest.TestCase):
    def test_uploaded_single_page_report_without_slots_becomes_control(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            database = runtime / "data" / "materials.db"
            extracted = runtime / "extracted"
            page = extracted / "upload-a" / "page-014" / "index.html"
            incomplete_report = extracted / "upload-b" / "index.html"
            deck_input_page = extracted / "upload-c" / "publisher" / "input" / "p8-active-chat.html"
            database.parent.mkdir(parents=True)
            page.parent.mkdir(parents=True)
            incomplete_report.parent.mkdir(parents=True)
            deck_input_page.parent.mkdir(parents=True)
            page.write_text(
                "<!doctype html><html><head><title>Standalone page</title></head>"
                "<body><main>One page only</main></body></html>",
                encoding="utf-8",
            )
            incomplete_report.write_text(
                "<!doctype html><html><head><title>Incomplete report</title></head>"
                "<body><main>Report sync still pending</main></body></html>",
                encoding="utf-8",
            )
            deck_input_page.write_text(
                "<!doctype html><html><head><title>Deck input page</title></head><body>"
                "<section class='slide-frame'>Component A</section>"
                "<section class='slide-frame'>Component B</section>"
                "<section class='slide-frame'>Component C</section>"
                "</body></html>",
                encoding="utf-8",
            )
            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            try:
                create_core_schema(conn)
                ensure_asset_schema(conn)
                ensure_upload_schema(conn)
                conn.execute(
                    """
                    insert into uploads
                    (id,filename,stored_path,extract_path,file_count,asset_count,created_at)
                    values
                    ('upload-a','single-page.zip','','extracted/upload-a',1,1,1),
                    ('upload-b','report.zip','','extracted/upload-b',1,1,1),
                    ('upload-c','deck-source.zip','','extracted/upload-c',1,1,1)
                    """
                )
                conn.execute(
                    """
                    insert into assets
                    (id,title,category,usage,asset_type,asset_code,media_kind,source_type,
                     source_path,preview_url,upload_id,source_hash,version_group,
                     version_parent_id,created_at,updated_at)
                    values ('single-page','Standalone page','page','Imported','report',
                            'RPT-TEST-001','html','upload','page-014/index.html',
                            '/extracted/upload-a/page-014/index.html','upload-a',
                            'single-page-hash','single-page','',1,1),
                           ('incomplete-report','Incomplete report','report','Imported','report',
                            'RPT-TEST-002','html','upload','index.html',
                            '/extracted/upload-b/index.html','upload-b',
                            'incomplete-report-hash','incomplete-report','',1,1),
                           ('deck-input-page','Deck input page','page','Imported','report',
                            'RPT-TEST-003','html','upload','publisher/input/p8-active-chat.html',
                            '/extracted/upload-c/publisher/input/p8-active-chat.html','upload-c',
                            'deck-input-page-hash','deck-input-page','',1,1)
                    """
                )
                conn.commit()
            finally:
                conn.close()

            with (
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "DATA", database.parent),
                patch.object(server, "DB_PATH", database),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "THUMBNAILS", runtime / "thumbnails"),
                patch.object(server, "REPORT_EXPORTS", runtime / "report-exports"),
            ):
                self.assertEqual(server.reclassify_single_page_report_assets(), 2)

            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "select asset_type,asset_code,source_type,category from assets where id='single-page'"
                ).fetchone()
                self.assertEqual(row["asset_type"], "control")
                self.assertTrue(row["asset_code"].startswith("CTRL-"))
                self.assertEqual(row["source_type"], "single-page-import")
                self.assertEqual(row["category"], "page")
                retained = conn.execute(
                    "select asset_type,asset_code from assets where id='incomplete-report'"
                ).fetchone()
                self.assertEqual(retained["asset_type"], "report")
                self.assertEqual(retained["asset_code"], "RPT-TEST-002")
                deck_page = conn.execute(
                    "select asset_type,asset_code from assets where id='deck-input-page'"
                ).fetchone()
                self.assertEqual(deck_page["asset_type"], "control")
                self.assertTrue(deck_page["asset_code"].startswith("CTRL-"))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
