"""Integration tests for the multipart form parser."""

import io
from minem.multipart import parse_multipart, UploadedFile


class TestParseMultipart:
    def test_parses_single_file_field(self):
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body = (
            f"------WebKitFormBoundary7MA4YWxkTrZu0gW\r\n"
            f'Content-Disposition: form-data; name="file"; filename="test.html"\r\n'
            f"Content-Type: text/html\r\n"
            f"\r\n"
            f"<html><body>Hello</body></html>\r\n"
            f"------WebKitFormBoundary7MA4YWxkTrZu0gW--\r\n"
        ).encode()

        rfile = io.BytesIO(body)
        content_type = f"multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW"

        result = parse_multipart(rfile, content_type, len(body))

        assert "file" in result
        uploaded = result["file"]
        assert isinstance(uploaded, UploadedFile)
        assert uploaded.filename == "test.html"
        assert uploaded.file.read() == b"<html><body>Hello</body></html>"

    def test_parses_text_field(self):
        boundary = "boundary123"
        body = (
            f"--boundary123\r\n"
            f'Content-Disposition: form-data; name="description"\r\n'
            f"\r\n"
            f"My description\r\n"
            f"--boundary123--\r\n"
        ).encode()

        rfile = io.BytesIO(body)
        content_type = f"multipart/form-data; boundary=boundary123"

        result = parse_multipart(rfile, content_type, len(body))

        assert result["description"] == "My description"

    def test_parses_mixed_fields(self):
        boundary = "testboundary"
        body = (
            f"--testboundary\r\n"
            f'Content-Disposition: form-data; name="description"\r\n'
            f"\r\n"
            f"Test upload\r\n"
            f"--testboundary\r\n"
            f'Content-Disposition: form-data; name="file"; filename="data.zip"\r\n'
            f"Content-Type: application/zip\r\n"
            f"\r\n"
            f"ZIPDATA\r\n"
            f"--testboundary--\r\n"
        ).encode()

        rfile = io.BytesIO(body)
        content_type = f"multipart/form-data; boundary=testboundary"

        result = parse_multipart(rfile, content_type, len(body))

        assert result["description"] == "Test upload"
        assert isinstance(result["file"], UploadedFile)
        assert result["file"].filename == "data.zip"
        assert result["file"].file.read() == b"ZIPDATA"

    def test_empty_body_returns_empty_dict(self):
        rfile = io.BytesIO(b"")
        result = parse_multipart(rfile, "multipart/form-data; boundary=empty", 0)
        assert result == {}

    def test_missing_boundary_returns_empty_dict(self):
        rfile = io.BytesIO(b"some data")
        result = parse_multipart(rfile, "application/json", 9)
        assert result == {}

    def test_quoted_boundary(self):
        boundary = "myboundary"
        body = (
            f"--myboundary\r\n"
            f'Content-Disposition: form-data; name="field"\r\n'
            f"\r\n"
            f"value\r\n"
            f"--myboundary--\r\n"
        ).encode()

        rfile = io.BytesIO(body)
        content_type = 'multipart/form-data; boundary="myboundary"'

        result = parse_multipart(rfile, content_type, len(body))
        assert result["field"] == "value"
