import sqlite3
import tempfile
import unittest
from pathlib import Path

from minem.report_package_writer import sync_report_material_package


class ReportPackageRecoveryTests(unittest.TestCase):
    def test_same_hash_repairs_missing_generated_page_in_place(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            page = root / "_minem_pages" / "page-001" / "index.html"
            page.parent.mkdir(parents=True)
            page.write_text("<html><body>restored</body></html>", encoding="utf-8")
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.execute(
                """create table assets (
                id text primary key, title text, category text, usage text,
                tags text, snippet text, asset_type text, asset_code text,
                media_kind text, resource_kind text, source_type text,
                source_path text, preview_url text, upload_id text,
                source_hash text, version_group text, version_no integer,
                version_parent_id text, similarity_score real,
                similarity_method text, tag_seeded integer, created_at integer,
                updated_at integer)"""
            )
            conn.execute(
                """insert into assets values
                ('page-a','Page','page','','','','control','CTRL-001','html','',
                'report-material-sync','_minem_pages/deleted/index.html','/missing',
                'upload-a','sync-control:page-hash','page-a',1,'',1.0,'',1,1,1)"""
            )
            conn.execute("create table uploads (id text primary key, file_count integer, asset_count integer)")
            conn.execute("insert into uploads values ('upload-a',0,1)")
            conn.execute(
                """create table report_page_slots (
                report_id text, page_number integer, control_id text)"""
            )

            def asset_path(row):
                return root / row["source_path"]

            sync_report_material_package(
                conn,
                "upload-a",
                root,
                load_report_package_manifest=lambda _: ({}, "report"),
                report_package_entry_path=lambda *_: (None, ""),
                find_existing_asset_by_code=lambda c, code, kind: c.execute(
                    "select * from assets where asset_code=? and asset_type=?", (code, kind)
                ).fetchone(),
                next_report_revision_code=lambda *_: "",
                next_asset_code=lambda *_: "",
                clean_report_title=lambda value: value,
                report_material_title=lambda value: value,
                merge_tags=lambda *values: [],
                read_text_sample=lambda path: path.read_text(),
                file_hash=lambda path: "page-hash",
                copy_package_preview_thumbnail=lambda *args: None,
                report_manifest_page_items=lambda *_: [{
                    "path": page, "rel": "_minem_pages/page-001/index.html",
                    "page": 1, "title": "Page", "tags": [], "role": "",
                    "source_code": "", "preview": "", "note": "",
                }],
                report_code_to_control_code=lambda *_: "CTRL-001",
                find_existing_asset=lambda *_: conn.execute("select * from assets where id='page-a'").fetchone(),
                control_display_title=lambda title, page_number: title,
                asset_library_path=asset_path,
                next_candidate_asset_code=lambda *_: "",
                copy_page_variant=lambda *_: (None, ""),
                insert_control_asset=lambda *args, **kwargs: None,
                next_asset_version_no=lambda *_: 1,
                attach_report_page_control=lambda *args, **kwargs: {"attached": False},
                sync_report_index_from_slots=lambda *args, **kwargs: None,
                sync_report_package_resources=lambda *args, **kwargs: 0,
                now_ms=lambda: 2,
            )

            repaired = conn.execute("select * from assets where id='page-a'").fetchone()
            self.assertEqual(repaired["source_path"], "_minem_pages/page-001/index.html")
            self.assertEqual(repaired["preview_url"], "/extracted/upload-a/_minem_pages/page-001/index.html")
            self.assertEqual(repaired["version_group"], "page-a")
            self.assertEqual(conn.execute("select count(*) from assets").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
