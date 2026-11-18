#!/usr/bin/env python3
"""Exercise malformed requests against the real HTTP handler on a local port."""

import http.client
import json
import socket
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server


class QuietHandler(server.Handler):
    def setup(self):
        super().setup()
        self.connection.settimeout(0.2)

    def log_message(self, *_):
        pass


class TestServer(ThreadingHTTPServer):
    def handle_error(self, *_):
        pass


class RequestChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = TestServer(("127.0.0.1", 0), QuietHandler)
        cls.worker = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.worker.join(timeout=5)

    def post(self, body, *, path="/api/temp-reports", headers=None, finish=True):
        with socket.create_connection(self.http.server_address, timeout=2) as connection:
            fields = {"Host": "127.0.0.1", "Content-Type": "application/json", "Content-Length": str(len(body)), **(headers or {})}
            request = f"POST {path} HTTP/1.0\r\n" + "".join(f"{key}: {value}\r\n" for key, value in fields.items())
            connection.sendall(request.encode("ascii") + b"\r\n" + body)
            if finish:
                connection.shutdown(socket.SHUT_WR)
            with http.client.HTTPResponse(connection) as response:
                response.begin()
                self.assertIn("application/json", response.getheader("Content-Type", ""))
                return response.status, json.loads(response.read())

    def assert_error(self, status, payload, expected):
        self.assertEqual(status, expected)
        self.assertIs(payload.get("ok"), False)
        self.assertTrue(payload.get("error"))

    def test_malformed_json_is_rejected_across_mutation_routes(self):
        for path in (
            "/api/temp-reports", "/api/assets", "/api/assets/manual-merge",
            "/api/assets/example/title", "/api/reports/example/arrangement",
            "/api/reports/example/exports", "/api/reports/example/pages",
            "/api/reports/example/controls", "/api/reports", "/api/import-tasks/drive",
        ):
            with self.subTest(path=path):
                self.assert_error(*self.post(b"{", path=path), 400)

    def test_json_body_must_be_an_object(self):
        for body in (b"[]", b"null", b"1", b'"text"'):
            with self.subTest(body=body):
                self.assert_error(*self.post(body), 400)

    def test_invalid_content_length_is_rejected(self):
        for length in ("invalid", "-1"):
            with self.subTest(length=length):
                status, payload = self.post(b"{}", headers={"Content-Length": length})
                self.assert_error(status, payload, 400)
                self.assertIn("Content-Length", payload["error"])

    def test_oversized_body_is_rejected_before_reading(self):
        self.assert_error(*self.post(b"", headers={"Content-Length": "131073"}, finish=False), 413)

    def test_truncated_body_is_rejected(self):
        status, payload = self.post(b"{}", headers={"Content-Length": "30"})
        self.assert_error(status, payload, 400)
        self.assertIn("不完整", payload["error"])

    def test_stalled_body_returns_timeout(self):
        self.assert_error(*self.post(b"", headers={"Content-Length": "10"}, finish=False), 408)

    def test_unsupported_transfer_encoding_is_rejected(self):
        status, payload = self.post(b"", headers={"Transfer-Encoding": "chunked"})
        self.assert_error(status, payload, 400)
        self.assertIn("Transfer-Encoding", payload["error"])

    def test_invalid_utf8_is_rejected(self):
        self.assert_error(*self.post(b'{"name":"\xff"}'), 400)

    def test_excessively_nested_json_is_rejected(self):
        self.assert_error(*self.post(b'{"nested":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}"), 400)

    def test_conflicting_content_lengths_are_rejected(self):
        self.assert_error(*self.post(b"{}", headers={"Content-Length": "2\r\nContent-Length: 3"}), 400)

    def test_empty_body_keeps_existing_validation(self):
        status, payload = self.post(b"")
        self.assert_error(status, payload, 400)
        self.assertEqual(payload["error"], "请先勾选页面素材")

    def test_server_remains_available_after_a_bad_request(self):
        self.assert_error(*self.post(b"{"), 400)
        connection = http.client.HTTPConnection(*self.http.server_address, timeout=2)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/version")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIs(json.loads(response.read())["ok"], True)


if __name__ == "__main__":
    unittest.main()
