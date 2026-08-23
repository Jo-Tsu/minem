import hashlib
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import server
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema


class ExistingImportLineageTest(unittest.TestCase):
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

    @staticmethod
    def insert_report(
        conn: sqlite3.Connection,
        *,
        asset_id: str,
        asset_code: str,
        upload_id: str,
        source_hash: str,
        updated_at: int,
    ) -> None:
        conn.execute(
            """
            insert into assets
            (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
             preview_url,upload_id,source_hash,version_group,created_at,updated_at)
            values (?,?,'report','report',?,'html','test','index.html',?,?,?,?,1,?)
            """,
            (
                asset_id,
                asset_code,
                asset_code,
                f"/reports/{asset_id}/index.html",
                upload_id,
                source_hash,
                asset_id,
                updated_at,
            ),
        )

    def run_lookup(self, manifest_report: dict, *, expected_explicit_match: bool):
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            database = runtime / "materials.db"
            extract_root = runtime / "incoming"
            extract_root.mkdir()
            page = extract_root / "index.html"
            page.write_text("<!doctype html><title>Shared export content</title>", encoding="utf-8")
            shared_hash = hashlib.sha1(page.read_bytes()).hexdigest()
            (extract_root / "minem-export-manifest.json").write_text(
                json.dumps({"schemaVersion": 1, "format": "html", "report": manifest_report}),
                encoding="utf-8",
            )
            self.prepare_database(database)

            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            try:
                self.insert_report(
                    conn,
                    asset_id="report-exported",
                    asset_code="RPT-20260806-002",
                    upload_id="upload-exported",
                    source_hash="original-report-hash",
                    updated_at=1,
                )
                self.insert_report(
                    conn,
                    asset_id="report-hash-match",
                    asset_code="RPT-20260808-001",
                    upload_id="upload-hash-match",
                    source_hash=shared_hash,
                    updated_at=2,
                )
                conn.commit()
            finally:
                conn.close()

            with (
                patch.object(server, "DB_PATH", database),
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", runtime / "extracted"),
                patch.object(server, "THUMBNAILS", runtime / "thumbnails"),
            ):
                result = server.existing_import_result_for_extract_root(extract_root)

            expected_id = "report-exported" if expected_explicit_match else "report-hash-match"
            expected_code = "RPT-20260806-002" if expected_explicit_match else "RPT-20260808-001"
            expected_upload = "upload-exported" if expected_explicit_match else "upload-hash-match"
            self.assertEqual(result["assetId"], expected_id)
            self.assertEqual(result["assetCode"], expected_code)
            self.assertEqual(result["sourceUploadId"], expected_upload)
            return result

    def test_export_manifest_report_id_wins_over_content_hash_match(self) -> None:
        result = self.run_lookup(
            {"id": "report-exported", "code": "RPT-20260806-002"},
            expected_explicit_match=True,
        )

        self.assertEqual(result["previewUrl"], "/reports/report-exported/index.html")

    def test_export_manifest_report_code_is_used_when_id_is_stale(self) -> None:
        self.run_lookup(
            {"id": "missing-report", "code": "RPT-20260806-002"},
            expected_explicit_match=True,
        )

    def test_hash_heuristic_remains_fallback_when_manifest_has_no_valid_match(self) -> None:
        self.run_lookup(
            {"id": "missing-report", "code": "RPT-MISSING"},
            expected_explicit_match=False,
        )


if __name__ == "__main__":
    unittest.main()
