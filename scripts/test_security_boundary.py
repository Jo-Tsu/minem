#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minem.runtime_discovery import read_service_manifest, resolve_session_token
from minem.security import (
    API_TOKEN_HEADER,
    atomic_write_private,
    browser_write_origin_allowed,
    request_token,
    rotate_session_token,
    same_origin,
    token_matches,
)


class Headers(dict):
    def get(self, key, default=None):
        lowered = key.lower()
        for header, value in self.items():
            if header.lower() == lowered:
                return value
        return default


def available_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request(base_url: str, path: str, *, method: str = "GET", headers=None, body: bytes | None = None):
    target = urllib.request.Request(
        base_url + path,
        data=body,
        method=method,
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(target, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()
    except urllib.error.URLError:
        return 0, {}, b""


def live_http_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="minem-security-http-") as temp_dir:
        root = Path(temp_dir)
        port = available_port()
        token = "security-http-test-token-0123456789"
        environment = {
            **os.environ,
            "MINEM_DATA_DIR": str(root),
            "MINEM_SESSION_TOKEN": token,
            "MINEM_SKIP_PORT_PRECHECK": "1",
            "PORT": str(port),
        }
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py")],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=1)
                    raise AssertionError(
                        "isolated security service exited early\n"
                        f"stdout:\n{stdout}\nstderr:\n{stderr}"
                    )
                status, _, _ = request(base_url, "/api/version")
                if status == 200:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("isolated security service did not become ready")

            status, _, payload = request(
                base_url,
                "/api/assets",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=b"{}",
            )
            assert status == 401, payload

            status, _, payload = request(
                base_url,
                "/api/reports/missing/trusted-entry",
            )
            assert status == 401, payload

            status, _, payload = request(
                base_url,
                "/api/reports/missing/trusted-entry",
                headers={
                    API_TOKEN_HEADER: token,
                    "Origin": "https://evil.example",
                    "Sec-Fetch-Site": "cross-site",
                },
            )
            assert status == 403, payload

            status, _, payload = request(
                base_url,
                "/api/assets",
                method="POST",
                headers={
                    API_TOKEN_HEADER: token,
                    "Origin": "https://evil.example",
                    "Sec-Fetch-Site": "cross-site",
                    "Content-Type": "application/json",
                },
                body=b"{}",
            )
            assert status == 403, payload

            status, _, payload = request(
                base_url,
                "/api/assets",
                method="POST",
                headers={
                    API_TOKEN_HEADER: token,
                    "Origin": base_url,
                    "Sec-Fetch-Site": "same-origin",
                    "Content-Type": "application/json",
                },
                body=b'{"id":"security-http","title":"Security HTTP"}',
            )
            assert status == 200, payload

            status, _, payload = request(
                base_url,
                "/api/version",
                headers={"Host": "evil.example"},
            )
            assert status == 421, payload

            status, response_headers, management = request(base_url, "/")
            assert status == 200
            document = management.decode("utf-8")
            assert f'content="{token}"' in document
            csp = response_headers.get("Content-Security-Policy") or response_headers.get("Content-security-policy") or ""
            assert "frame-ancestors 'self'" in csp
            assert "connect-src 'self'" in csp

            source = root / "extracted" / "manual-source" / "index.html"
            source.parent.mkdir(parents=True)
            source.write_text(
                "<!doctype html><html><head><title>Source</title>"
                "<script>localStorage.setItem('source', 'ok')</script></head><body>source</body></html>",
                encoding="utf-8",
            )
            source_data = source.parent / "data.json"
            source_data.write_text('{"ok":true}', encoding="utf-8")
            package_asset = source.parent / "assets" / "theme.json"
            package_asset.parent.mkdir()
            package_asset.write_text('{"theme":"dark"}', encoding="utf-8")
            other_data = root / "extracted" / "other-source" / "private.json"
            other_data.parent.mkdir(parents=True)
            other_data.write_text('{"private":true}', encoding="utf-8")
            status, _, shell = request(base_url, "/extracted/manual-source/index.html")
            assert status == 200
            shell_text = shell.decode("utf-8")
            assert "class=\"deck-frame\"" in shell_text
            assert "allow-same-origin" not in shell_text
            assert token not in shell_text
            status, source_headers, embedded = request(
                base_url,
                "/extracted/manual-source/index.html?embed=1",
            )
            assert status == 200
            embedded_text = embedded.decode("utf-8")
            assert embedded_text.count(token) == 0
            assert embedded_text.index('id="minem-embedded-preview-compat"') < embedded_text.index(
                "localStorage.setItem('source', 'ok')"
            )
            capability_match = re.search(
                r"const capability = \"([^\"]+)\";",
                embedded_text,
            )
            assert capability_match, embedded_text[:2000]
            capability = capability_match.group(1)
            source_csp = source_headers.get("Content-Security-Policy") or source_headers.get("Content-security-policy") or ""
            assert source_csp.startswith("sandbox ")
            assert "allow-same-origin" not in source_csp
            capability_query = urllib.parse.urlencode({"minem_preview_capability": capability})
            status, data_headers, payload = request(
                base_url,
                f"/extracted/manual-source/data.json?{capability_query}",
                headers={"Origin": "null"},
            )
            assert status == 200 and payload == b'{"ok":true}'
            assert data_headers.get("Access-Control-Allow-Origin") == "null"
            status, asset_headers, payload = request(
                base_url,
                f"/extracted/manual-source/assets/theme.json?{capability_query}",
                headers={"Origin": "null"},
            )
            assert status == 200 and payload == b'{"theme":"dark"}'
            assert asset_headers.get("Access-Control-Allow-Origin") == "null"
            status, no_capability_headers, _ = request(
                base_url,
                "/extracted/manual-source/data.json",
                headers={"Origin": "null"},
            )
            assert status == 200
            assert "Access-Control-Allow-Origin" not in no_capability_headers
            status, other_headers, _ = request(
                base_url,
                f"/extracted/other-source/private.json?{capability_query}",
                headers={"Origin": "null"},
            )
            assert status == 200
            assert "Access-Control-Allow-Origin" not in other_headers

            token_path = root / "runtime" / "session-token"
            assert token_path.read_text(encoding="utf-8").strip() == token
            assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="minem-security-") as temp_dir:
        root = Path(temp_dir)
        token_path = root / "runtime" / "session-token"
        first = rotate_session_token(token_path)
        assert len(first) >= 40
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
        second = rotate_session_token(token_path)
        assert second != first
        assert token_matches(second, second)
        assert not token_matches(first, second)

        configured = "configured-local-session-token"
        atomic_write_private(token_path, configured)
        assert token_path.read_text(encoding="utf-8").strip() == configured
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600

        headers = Headers({API_TOKEN_HEADER: configured})
        assert request_token(headers) == configured
        bearer = Headers({"Authorization": f"Bearer {configured}"})
        assert request_token(bearer) == configured

        origin = "http://127.0.0.1:8790"
        assert same_origin(origin, origin)
        assert browser_write_origin_allowed(
            Headers({"Origin": origin, "Sec-Fetch-Site": "same-origin"}),
            origin,
        )
        assert not browser_write_origin_allowed(
            Headers({"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}),
            origin,
        )
        assert not browser_write_origin_allowed(
            Headers({"Sec-Fetch-Site": "same-site"}),
            origin,
        )

        manifest_path = root / "runtime" / "service.json"
        manifest_path.write_text(
            json.dumps({
                "status": "running",
                "managedByClient": True,
                "baseUrl": "http://127.0.0.1:9123",
                "port": 9123,
            }),
            encoding="utf-8",
        )
        manifest = read_service_manifest(root)
        assert manifest and manifest["baseUrl"] == "http://127.0.0.1:9123"
        session_manifest_path = root / "runtime" / "session.json"
        session_manifest_path.write_text(
            json.dumps({
                "status": "running",
                "baseUrl": "http://127.0.0.1:9123",
                "pid": os.getpid(),
            }),
            encoding="utf-8",
        )
        previous_data_dir = os.environ.get("MINEM_DATA_DIR")
        previous_environment_token = os.environ.get("MINEM_SESSION_TOKEN")
        try:
            os.environ["MINEM_DATA_DIR"] = str(root)
            os.environ.pop("MINEM_SESSION_TOKEN", None)
            with patch(
                "minem.runtime_discovery.candidate_data_roots",
                return_value=[root],
            ):
                assert resolve_session_token("http://127.0.0.1:9123") == configured
                assert resolve_session_token("http://127.0.0.1:8790") == ""
                session_manifest_path.unlink()
                assert resolve_session_token("http://127.0.0.1:9123") == ""
                session_manifest_path.write_text(
                    json.dumps({
                        "status": "running",
                        "baseUrl": "http://127.0.0.1:9123",
                        "pid": 999_999_999,
                    }),
                    encoding="utf-8",
                )
                assert resolve_session_token("http://127.0.0.1:9123") == ""
                os.environ["MINEM_SESSION_TOKEN"] = "environment-token"
                assert resolve_session_token("http://127.0.0.1:9123") == "environment-token"
                os.environ.pop("MINEM_SESSION_TOKEN", None)
                assert resolve_session_token("https://team.example") == ""
        finally:
            if previous_data_dir is None:
                os.environ.pop("MINEM_DATA_DIR", None)
            else:
                os.environ["MINEM_DATA_DIR"] = previous_data_dir
            if previous_environment_token is None:
                os.environ.pop("MINEM_SESSION_TOKEN", None)
            else:
                os.environ["MINEM_SESSION_TOKEN"] = previous_environment_token

    live_http_checks()
    print("security boundary checks passed")


if __name__ == "__main__":
    main()
