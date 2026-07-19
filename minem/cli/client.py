"""HTTP transport for the MineM CLI."""

from __future__ import annotations

import http.client
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .contracts import CliError, EXIT_CONNECTION


STATUS_CODES = {
    400: "INVALID_ARGUMENT",
    401: "AUTHENTICATION_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    410: "RETIRED_ENDPOINT",
    413: "FILE_TOO_LARGE",
}


class MineMClient:
    def __init__(self, base_url: str, timeout: float = 30, request_id: str = ""):
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CliError("INVALID_ARGUMENT", f"Invalid MineM server URL: {base_url}", exit_code=2)
        self.base_url = base_url.rstrip("/")
        self.timeout = max(1.0, float(timeout))
        self.request_id = request_id

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "minem-cli/1"}
        if self.request_id:
            headers["X-Request-ID"] = self.request_id
        return headers

    def _error(self, status: int, payload: Any, fallback: str) -> CliError:
        if isinstance(payload, dict):
            raw = payload.get("error") or payload.get("message")
            message = raw.get("message") if isinstance(raw, dict) else raw
        else:
            message = None
        return CliError(
            STATUS_CODES.get(status, "SERVER_ERROR"),
            str(message or fallback or f"MineM returned HTTP {status}"),
            details=payload if isinstance(payload, dict) else None,
        )

    @staticmethod
    def _decode(raw: bytes) -> Any:
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"body": raw.decode("utf-8", errors="replace")[:2000]}

    def request(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        payload = None
        headers = self._headers()
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = self._decode(response.read())
                return result if isinstance(result, dict) else {"data": result}
        except urllib.error.HTTPError as error:
            detail = self._decode(error.read())
            raise self._error(error.code, detail, error.reason) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise CliError(
                "CONNECTION_FAILED",
                f"Cannot connect to MineM at {self.base_url}: {reason}",
                exit_code=EXIT_CONNECTION,
            ) from error

    def upload(self, path: Path, description: str = "") -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(self.base_url)
        boundary = f"----MineMCLI{int(time.time() * 1000)}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        prefix = (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"description\"\r\n\r\n"
            f"{description}\r\n"
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
        base_path = parsed.path.rstrip("/")
        target = f"{base_path}/api/import-tasks" if base_path else "/api/import-tasks"
        connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(parsed.hostname, parsed.port, timeout=max(self.timeout, 60))
        try:
            connection.putrequest("POST", target)
            connection.putheader("Accept", "application/json")
            connection.putheader("User-Agent", "minem-cli/1")
            if self.request_id:
                connection.putheader("X-Request-ID", self.request_id)
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(len(prefix) + path.stat().st_size + len(suffix)))
            connection.endheaders()
            connection.send(prefix)
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    connection.send(chunk)
            connection.send(suffix)
            response = connection.getresponse()
            result = self._decode(response.read())
            if response.status >= 400:
                raise self._error(response.status, result, response.reason)
            return result if isinstance(result, dict) else {"data": result}
        except CliError:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise CliError(
                "CONNECTION_FAILED",
                f"Upload to MineM failed at {self.base_url}: {error}",
                exit_code=EXIT_CONNECTION,
            ) from error
        finally:
            connection.close()

    def download(self, path: str, destination: Path) -> Path:
        request = urllib.request.Request(self.base_url + path, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeout, 120)) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as handle:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
        except urllib.error.HTTPError as error:
            raise self._error(error.code, self._decode(error.read()), error.reason) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise CliError("CONNECTION_FAILED", f"Download failed: {error}", exit_code=EXIT_CONNECTION) from error
        return destination
