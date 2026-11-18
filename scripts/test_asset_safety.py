#!/usr/bin/env python3
"""Check asset identifiers and non-destructive metadata updates in isolation."""

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema


class QuietHandler(server.Handler):
    def log_message(self, *_):
        pass


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, *_):
        pass


class AssetSafetyChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="minem-asset-safety-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "assets.db"
        with sqlite3.connect(self.database) as conn:
            conn.row_factory = sqlite3.Row
            create_core_schema(conn)
            ensure_asset_schema(conn)
            ensure_upload_schema(conn)
            conn.execute("insert into assets(id,title,asset_type,asset_code,media_kind,source_type,source_path,preview_url,upload_id,created_at,updated_at,source_hash,version_group,version_no) values('linked','Original','control','CTRL-PAGE-001','html','upload','index.html','/extracted/upload/index.html','upload',1,1,'original-hash','linked',2)")

        @contextmanager
        def connect():
            connection = sqlite3.connect(self.database)
            connection.row_factory = sqlite3.Row
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

        database_patch = patch.object(server, "db", connect)
        database_patch.start()
        self.addCleanup(database_patch.stop)
        self.http = QuietServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)

    def save(self, payload):
        host, port = self.http.server_address
        request = Request(f"http://{host}:{port}/api/assets", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_thumbnail_deletion_cannot_leave_thumbnail_directory(self):
        thumbnails = self.root / "thumbnails"
        thumbnails.mkdir()
        outside = self.root / "outside.png"
        outside.write_bytes(b"must remain")
        with patch.object(server, "THUMBNAILS", thumbnails):
            self.assertFalse(server.delete_asset_thumbnail("../outside"))
        self.assertEqual(outside.read_bytes(), b"must remain")

    def test_thumbnail_symlink_cannot_delete_outside_file(self):
        thumbnails = self.root / "thumbnails"
        thumbnails.mkdir()
        outside = self.root / "outside.png"
        outside.write_bytes(b"must remain")
        (thumbnails / "linked.png").symlink_to(outside)
        with patch.object(server, "THUMBNAILS", thumbnails):
            self.assertFalse(server.delete_asset_thumbnail("linked"))
        self.assertEqual(outside.read_bytes(), b"must remain")

    def test_normal_thumbnail_can_be_deleted(self):
        thumbnails = self.root / "thumbnails"
        thumbnails.mkdir()
        thumbnail = thumbnails / "normal.png"
        thumbnail.write_bytes(b"thumbnail")
        with patch.object(server, "THUMBNAILS", thumbnails):
            self.assertTrue(server.delete_asset_thumbnail("normal"))
        self.assertFalse(thumbnail.exists())

    def test_deletion_preserves_a_source_shared_by_another_asset(self):
        extracted = self.root / "extracted"
        source = extracted / "upload" / "index.html"
        source.parent.mkdir(parents=True)
        source.write_text("<h1>Shared page</h1>")
        with server.db() as conn:
            conn.execute("insert into assets(id,title,upload_id,source_path,created_at,updated_at) values('alias','Alias','upload','index.html',1,1)")
            asset = conn.execute("select * from assets where id = 'linked'").fetchone()
            with patch.object(server, "EXTRACTED", extracted):
                self.assertFalse(server.delete_library_file(asset, conn))
        self.assertEqual(source.read_text(), "<h1>Shared page</h1>")

    def test_unsafe_identifiers_are_rejected(self):
        for identifier in ("../outside", "/absolute", "..\\outside", ".", "..", "bad\x00id", {"invalid": 1}):
            with self.subTest(identifier=identifier):
                status, payload = self.save({"id": identifier, "title": "Test"})
                self.assertEqual(status, 400)
                self.assertIs(payload["ok"], False)

    def test_metadata_update_preserves_preview_source_and_version(self):
        status, _ = self.save({"id": "linked", "title": "Renamed"})
        self.assertEqual(status, 200)
        with sqlite3.connect(self.database) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("select * from assets where id='linked'").fetchone()
            self.assertEqual(row["title"], "Renamed")
            self.assertEqual(row["media_kind"], "html")
            self.assertEqual(row["source_path"], "index.html")
            self.assertEqual(row["preview_url"], "/extracted/upload/index.html")
            self.assertEqual(row["upload_id"], "upload")
            self.assertEqual(row["source_hash"], "original-hash")
            self.assertEqual(row["version_group"], "linked")
            self.assertEqual(row["version_no"], 2)
            self.assertEqual(row["created_at"], 1)

    def test_invalid_metadata_has_a_json_error(self):
        for changes in ({"title": None}, {"asset_type": "unknown"}, {"tags": [{}]}):
            with self.subTest(changes=changes):
                self.assertEqual(self.save({"id": "new", "title": "Test", **changes})[0], 400)


if __name__ == "__main__":
    unittest.main()
