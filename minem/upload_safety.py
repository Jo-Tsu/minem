import re
import stat
import zipfile
from pathlib import Path

from .config import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_REQUEST_BYTES,
    MAX_ZIP_COMPRESSION_RATIO,
    MAX_ZIP_FILES,
    MAX_ZIP_MEMBER_BYTES,
    MAX_ZIP_TOTAL_BYTES,
    STREAM_CHUNK_BYTES,
)
from .paths import is_path_within


class UploadLimitError(ValueError):
    """Raised when an upload or archive exceeds configured safety limits."""


def human_bytes(value):
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f}{unit}" if unit == "B" else f"{amount:.1f}{unit}"
        amount /= 1024
    return f"{value}B"


def validate_upload_request_size(content_length, max_bytes=MAX_UPLOAD_REQUEST_BYTES):
    if content_length and content_length > max_bytes:
        raise UploadLimitError(f"上传请求过大，最大支持 {human_bytes(max_bytes)}")


def copy_limited_stream(source, dest, max_bytes=MAX_UPLOAD_BYTES):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = source.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadLimitError(f"上传文件过大，最大支持 {human_bytes(max_bytes)}")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return total


def _validate_member_name(name):
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise UploadLimitError("压缩包包含不安全的绝对路径")
    if ".." in Path(normalized).parts:
        raise UploadLimitError("压缩包包含不安全的上级目录路径")
    return normalized


def _is_symlink(member):
    mode = member.external_attr >> 16
    return stat.S_ISLNK(mode)


def safe_extract_zip(
    zip_path,
    target_dir,
    max_files=MAX_ZIP_FILES,
    max_member_bytes=MAX_ZIP_MEMBER_BYTES,
    max_total_bytes=MAX_ZIP_TOTAL_BYTES,
    max_compression_ratio=MAX_ZIP_COMPRESSION_RATIO,
):
    target_dir = Path(target_dir)
    target_root = target_dir.resolve()
    validated = []
    total_size = 0
    file_count = 0

    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            if _is_symlink(member):
                raise UploadLimitError("压缩包包含符号链接，已拒绝导入")
            file_count += 1
            if file_count > max_files:
                raise UploadLimitError(f"压缩包文件数过多，最大支持 {max_files} 个文件")
            file_size = max(member.file_size, 0)
            if file_size > max_member_bytes:
                raise UploadLimitError(f"压缩包内单个文件过大，最大支持 {human_bytes(max_member_bytes)}")
            total_size += file_size
            if total_size > max_total_bytes:
                raise UploadLimitError(f"压缩包解压后过大，最大支持 {human_bytes(max_total_bytes)}")
            if member.compress_size > 0 and file_size > 1024 * 1024:
                ratio = file_size / member.compress_size
                if ratio > max_compression_ratio:
                    raise UploadLimitError("压缩包压缩比异常，已拒绝导入")
            name = _validate_member_name(member.filename)
            dest = (target_dir / name).resolve()
            if not is_path_within(dest, target_root):
                raise UploadLimitError("压缩包目标路径越界，已拒绝导入")
            validated.append((member, dest))

        target_dir.mkdir(parents=True, exist_ok=True)
        extracted = []
        try:
            for member, dest in validated:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(dest, "wb") as out:
                    while True:
                        chunk = src.read(STREAM_CHUNK_BYTES)
                        if not chunk:
                            break
                        out.write(chunk)
                extracted.append(dest)
        except Exception:
            for path in extracted:
                path.unlink(missing_ok=True)
            raise
    return extracted
