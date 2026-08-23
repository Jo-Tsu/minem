"""Integration tests for upload safety module."""

import zipfile
from pathlib import Path

import pytest
from minem.upload_safety import (
    UploadLimitError,
    copy_limited_stream,
    safe_extract_zip,
    validate_upload_request_size,
)


class TestValidateUploadRequestSize:
    def test_passes_within_limit(self):
        validate_upload_request_size(100, max_bytes=200)

    def test_raises_over_limit(self):
        with pytest.raises(UploadLimitError):
            validate_upload_request_size(300, max_bytes=200)

    def test_zero_content_length_passes(self):
        validate_upload_request_size(0, max_bytes=200)


class TestCopyLimitedStream:
    def test_copies_small_file(self, tmp_path):
        import io
        source = io.BytesIO(b"hello world")
        dest = tmp_path / "output.bin"
        total = copy_limited_stream(source, dest, max_bytes=1024)
        assert total == 11
        assert dest.read_bytes() == b"hello world"

    def test_raises_on_oversized_file(self, tmp_path):
        import io
        source = io.BytesIO(b"x" * 200)
        dest = tmp_path / "output.bin"
        with pytest.raises(UploadLimitError):
            copy_limited_stream(source, dest, max_bytes=100)
        assert not dest.exists()


class TestSafeExtractZip:
    def test_extracts_valid_zip(self, tmp_path):
        zip_path = tmp_path / "test.zip"
        target = tmp_path / "out"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("hello.txt", "world")
            zf.writestr("sub/nested.txt", "nested content")

        extracted = safe_extract_zip(zip_path, target)
        assert len(extracted) == 2
        assert (target / "hello.txt").read_text() == "world"
        assert (target / "sub" / "nested.txt").read_text() == "nested content"

    def test_rejects_too_many_files(self, tmp_path):
        zip_path = tmp_path / "many.zip"
        target = tmp_path / "out"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i in range(10):
                zf.writestr(f"file{i}.txt", f"content {i}")

        with pytest.raises(UploadLimitError, match="文件数过多"):
            safe_extract_zip(zip_path, target, max_files=5)

    def test_rejects_path_traversal(self, tmp_path):
        zip_path = tmp_path / "evil.zip"
        target = tmp_path / "out"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../escape.txt", "escaped!")

        with pytest.raises(UploadLimitError, match="上级目录"):
            safe_extract_zip(zip_path, target)

    def test_rejects_absolute_path(self, tmp_path):
        zip_path = tmp_path / "abs.zip"
        target = tmp_path / "out"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("/etc/passwd", "root:x:0:0")

        with pytest.raises(UploadLimitError, match="绝对路径"):
            safe_extract_zip(zip_path, target)
