"""Localize Feishu Miaoda storage references before accepting a code ZIP."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, unquote


APP_ID = re.compile(r"app_[a-z0-9]+")
STORAGE_PATH = re.compile(
    r"(?<![\w/.:])(?P<host>https?://[a-z0-9_.:-]+)?"
    r"(?P<path>/(?:spark/)?app/(?P<app>app_[a-z0-9]+)/runtime/api/v1/storage/object/"
    r"[a-zA-Z0-9_.%~/-]+)(?P<query>\?[^\s\x22\x27<>\\)#]*)?",
    re.I,
)
SOURCE_SUFFIXES = {".html", ".htm", ".css", ".js", ".mjs", ".json"}
UNPACKAGED_ERROR = "此素材缺少妙搭原始媒体文件。请提供包含图片和视频的完整 ZIP 后再封装。"
MEDIA_HEADERS = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".gif": b"GIF8"}


def spark_package_root(root: Path) -> Path | None:
    direct = root / ".spark/meta.json"
    if direct.is_file():
        return root
    wrapped = [meta.parent.parent for meta in root.glob("*/.spark/meta.json") if meta.is_file()]
    return wrapped[0] if len(wrapped) == 1 else None


@lru_cache(maxsize=256)
def _online_storage_in_document(path, stamp):
    return any(match["host"] for match in STORAGE_PATH.finditer(path.read_text(encoding="utf-8", errors="replace")))


def has_online_spark_storage(path):
    """Recognize old packages that were imported with authenticated online URLs."""
    if not path or path.suffix.lower() not in SOURCE_SUFFIXES:
        return False
    try:
        stat = path.stat()
        return _online_storage_in_document(path, (stat.st_mtime_ns, stat.st_size))
    except OSError:
        return False


def valid_resource(path, package):
    if not path.is_file() or not path.resolve().is_relative_to(package):
        return False
    with path.open("rb") as source:
        header = source.read(512)
    suffix = path.suffix.lower()
    if suffix in MEDIA_HEADERS:
        return header.startswith(MEDIA_HEADERS[suffix])
    return bool(header and not re.match(rb"\s*<(?:!doctype\s+html|html\b)", header, re.I))


def prepare_spark_zip(root: Path) -> bool:
    """Require source objects in the ZIP and rewrite references to package files."""
    root = root.resolve()
    package = spark_package_root(root)
    if package is None:
        # A previously exported standalone page can lack the Miaoda metadata.
        if any(has_online_spark_storage(path) for path in root.rglob("*") if path.suffix.lower() in SOURCE_SUFFIXES):
            raise ValueError(UNPACKAGED_ERROR)
        return False
    try:
        meta = json.loads((package / ".spark/meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("妙搭 ZIP 的应用清单无法读取") from error
    if not isinstance(meta, dict) or meta.get("stack") != "design-html":
        return False
    app_id = meta.get("app_id")
    if not isinstance(app_id, str) or not APP_ID.fullmatch(app_id):
        raise ValueError("妙搭 ZIP 的应用标识无效")
    if not (package / "index.html").is_file():
        raise ValueError("妙搭 ZIP 缺少入口 index.html")

    missing = set()
    pending = []
    verified = {}
    for path in package.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES or ".spark" in path.relative_to(package).parts:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")

        def rewrite(match):
            relative = unquote(match["path"].lstrip("/"))
            canonical = relative.removeprefix("spark/")
            if "\x00" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
                raise ValueError("妙搭 ZIP 的资源路径无效")
            candidate = package / relative
            if not candidate.is_file():
                alternate = ("spark/" + relative) if relative == canonical else canonical
                candidate = package / alternate
            if candidate not in verified:
                verified[candidate] = valid_resource(candidate, package)
            if not verified[candidate]:
                missing.add(canonical)
                return match[0]
            target = quote(Path(os.path.relpath(candidate, path.parent)).as_posix(), safe="/")
            # Keep the resource relative even when its source was an absolute URL.
            return ("./" if not target.startswith("../") else "") + target + (match["query"] or "")

        patched = STORAGE_PATH.sub(rewrite, source)
        if patched != source:
            pending.append((path, patched))
    if missing:
        sample = "、".join(Path(name).name for name in sorted(missing)[:3])
        raise ValueError(f"妙搭 ZIP 缺少 {len(missing)} 个原始媒体文件（例如 {sample}）。请补齐后重新导入。")
    for path, patched in pending:
        path.write_text(patched, encoding="utf-8")
    return True
