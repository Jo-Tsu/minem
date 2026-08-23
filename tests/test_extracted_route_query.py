import http.client
from http.server import ThreadingHTTPServer
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
from unittest.mock import patch
import unittest
import zipfile

import server
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema


class ExtractedRouteQueryTest(unittest.TestCase):
    @staticmethod
    def prepare_database(path: Path) -> None:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            create_core_schema(connection)
            ensure_asset_schema(connection)
            ensure_upload_schema(connection)
            connection.commit()
        finally:
            connection.close()

    def test_embedded_html_ignores_preview_query_parameters(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            extracted = runtime / "extracted"
            page = extracted / "upload-a" / "page" / "index.html"
            page.parent.mkdir(parents=True)
            page.write_text("<!doctype html><title>Embedded page</title>", encoding="utf-8")

            with (
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "EXTRACTED", extracted),
            ):
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                worker = threading.Thread(target=httpd.serve_forever, daemon=True)
                worker.start()
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                    connection.request(
                        "GET",
                        "/extracted/upload-a/page/index.html?embed=1&v=1786931602795",
                    )
                    response = connection.getresponse()
                    body = response.read().decode("utf-8")
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    worker.join(timeout=2)

            self.assertEqual(response.status, 200)
            self.assertIn("Embedded page", body)

    def test_missing_extraction_is_restored_lazily_from_upload_zip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir).resolve()
            uploads = runtime / "uploads"
            extracted = runtime / "extracted"
            database = runtime / "data" / "materials.db"
            uploads.mkdir(parents=True)
            extracted.mkdir(parents=True)
            database.parent.mkdir(parents=True)
            self.prepare_database(database)

            upload_id = "upload-a"
            archive = uploads / f"{upload_id}.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("page/index.html", "<!doctype html><title>Recovered page</title>")
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """insert into uploads
                       (id, filename, stored_path, extract_path, created_at)
                       values (?, ?, ?, ?, ?)""",
                    (upload_id, "page.zip", f"uploads/{upload_id}.zip", f"extracted/{upload_id}", 1),
                )
                connection.commit()
            finally:
                connection.close()

            with (
                patch.object(server, "RUNTIME_ROOT", runtime),
                patch.object(server, "UPLOADS", uploads),
                patch.object(server, "EXTRACTED", extracted),
                patch.object(server, "DB_PATH", database),
            ):
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                worker = threading.Thread(target=httpd.serve_forever, daemon=True)
                worker.start()
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                    connection.request("GET", "/extracted/upload-a/page/index.html?embed=1")
                    response = connection.getresponse()
                    body = response.read().decode("utf-8")
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    worker.join(timeout=2)

            self.assertEqual(response.status, 200)
            self.assertIn("Recovered page", body)
            self.assertTrue((extracted / upload_id / "page" / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
