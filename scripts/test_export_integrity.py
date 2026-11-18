#!/usr/bin/env python3
"""Regression checks for resource collection, delivery metadata and PDF failures."""

import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from minem.db import create_core_schema, ensure_asset_schema
from minem.html_dependencies import audit_dependency_closure, css_references
from minem.pdf_capture import add_pdf_checks, capture
from minem.thumbnails import chrome_path


class ExportIntegrityChecks(unittest.TestCase):
    def test_public_covers_and_private_runtime_overrides_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            with patch.object(server, "RUNTIME_ROOT", runtime):
                default = server.report_cover_path("cover-1")
                self.assertEqual(default, server.REPORT_COVERS / "cover-1.webp")
                self.assertTrue(default.is_file())
                custom = runtime / "config/report-covers/cover-1.webp"
                custom.parent.mkdir(parents=True)
                custom.write_bytes(b"private template bytes")
                self.assertEqual(server.report_cover_path("cover-1"), custom)
                output = runtime / "report"
                output.mkdir()
                entry = server.write_report_cover(output, "cover-1")
                self.assertTrue((output / entry).is_file())
                self.assertEqual((output / entry).with_name("cover.webp").read_bytes(), custom.read_bytes())
                self.assertEqual(server.report_cover_path("cover-2"), server.REPORT_COVERS / "cover-2.webp")
            for name in server.REPORT_COVER_IDS:
                with self.subTest(name=name), server.Image.open(server.REPORT_COVERS / (name+".webp")) as image:
                    self.assertEqual(image.size, (1920,1080))

    def test_css_svg_and_large_documents_are_checked_completely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text(
                '<link href="theme.css" rel="stylesheet"><img src="chart.svg"><!--' +
                "x" * 4_000_000 + '--><img src="late-missing.png">'
            )
            (root / "theme.css").write_text('@import "missing-layout.css";')
            (root / "chart.svg").write_text('<svg><image href="missing-image.png"/></svg>')
            audit = audit_dependency_closure(root)
            self.assertEqual({item["resolved"] for item in audit["missing"]}, {
                "missing-layout.css", "missing-image.png", "late-missing.png",
            })
            data = 'data:image/svg+xml,<svg filter="url(%23n)"/>'
            self.assertEqual(css_references(f"background:url('{data}')"), [data])

    def test_single_page_preserves_root_css_and_its_nested_resources(self):
        with tempfile.TemporaryDirectory() as directory, sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            create_core_schema(conn)
            ensure_asset_schema(conn)
            extracted = Path(directory)
            root = extracted / "upload"
            root.mkdir()
            (root / "index.html").write_text('<html><head><link rel="stylesheet" href="theme.css"></head><body>Page</body></html>')
            (root / "theme.css").write_text('@import "layout.css";')
            (root / "layout.css").write_text('body{background:url("picture.svg")}')
            (root / "picture.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            conn.execute("insert into assets (id,title,asset_type,asset_code,upload_id,source_path,media_kind,created_at,updated_at) values ('page','中文名称','control','CTRL-1','upload','index.html','html',1,1)")
            with patch.object(server, "db", lambda: nullcontext(conn)), patch.object(server, "EXTRACTED", extracted):
                data, error, filename = server.export_asset_zip("page")
            self.assertFalse(error)
            self.assertEqual(filename, "中文名称.zip")
            destination = extracted / "unpacked"
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.extractall(destination)
                self.assertIn("README.md", archive.namelist())
                self.assertIn("assets-manifest.yaml", archive.namelist())
            audit = audit_dependency_closure(destination, require_local=True)
            self.assertFalse(audit["missing"] or audit["remote"])
            files = json.loads((destination / "ingestion-manifest.json").read_text())["resources"]
            self.assertTrue(any(item["path"].endswith("/theme.css") for item in files))
            for item in files:
                self.assertEqual(hashlib.sha256((destination / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    @unittest.skipUnless(chrome_path(), "Chromium is required for rendering")
    def test_pdf_rejects_page_errors_and_accepts_rendered_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "source.html"
            wrapper = root / "wrapper.html"
            image = root / "render.png"
            def render(document):
                page.write_text(add_pdf_checks(document))
                wrapper.write_text(f'<html><body><iframe src="{page.as_uri()}"></iframe></body></html>')
                capture(chrome_path(), wrapper, image)
            render("<html><head></head><body><h1>Rendered page</h1></body></html>")
            self.assertGreater(image.stat().st_size, 1024)
            with self.assertRaises(ValueError):
                render('<html><head></head><body><script>throw Error("broken page")</script></body></html>')
            with self.assertRaises(ValueError):
                render('<html><head></head><body><img src="missing.png"></body></html>')


if __name__ == "__main__":
    unittest.main()
