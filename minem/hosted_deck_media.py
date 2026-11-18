"""Archive playback media from Feishu Deck's published HTML."""

import hashlib
import html
import mimetypes
import re
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from minem.config import MAX_ZIP_FILES, MAX_ZIP_MEMBER_BYTES, MAX_ZIP_TOTAL_BYTES
from minem.offline_bundle import HTMLReferences, resolve_reference

MEDIA_DIRECTORY = "deck-media"
FEISHU_APP_HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.feishuapp\.cn")
FEISHU_DECK_PATH = re.compile(r"/app/[A-Za-z0-9_-]+/deck/")


class DeckOriginRedirects(HTTPRedirectHandler):
    def __init__(self, base):
        self.base = base

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not inside_deck(urlsplit(newurl), self.base):
            raise ValueError("飞书播放素材跳转出了原汇报目录")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def inside_deck(url, base):
    path = unquote(url.path)
    return (
        url.scheme == "https" and url.netloc == base.netloc
        and path.startswith(base.path) and not path.endswith("/")
        and not {"..", "."}.intersection(path.split("/"))
        and not any(character in path for character in ("\\", "\x00"))
    )


def check_mp4(path, size):
    """Reject a truncated MP4 even when the source omits Content-Length."""
    with path.open("rb") as stream:
        offset = 0
        boxes = set()
        while offset < size:
            stream.seek(offset)
            header = stream.read(8)
            if len(header) != 8:
                break
            length, kind = struct.unpack(">I4s", header)
            minimum = 8
            if length == 1:
                extended = stream.read(8)
                if len(extended) != 8:
                    break
                length = struct.unpack(">Q", extended)[0]
                minimum = 16
            elif length == 0:
                length = size - offset
            if length < minimum or offset + length > size:
                break
            offset += length
            boxes.add(kind)
        if offset != size or not {b"moov", b"mdat"}.issubset(boxes):
            raise HTTPException("MP4 数据不完整")


def fetch_media(url, destination, base):
    temporary = destination.with_suffix(".part")
    try:
        opener = build_opener(DeckOriginRedirects(base))
        with opener.open(Request(url, headers={"Accept-Encoding": "identity"}), timeout=30) as response:
            if response.status != 200:
                raise ValueError("源地址未返回完整文件")
            mime = response.headers.get_content_type()
            expected = (mimetypes.guess_type(destination.name)[0] or "").partition("/")[0]
            if mime in {"text/html", "application/json"} or (
                expected in {"image", "audio", "video"} and not (
                    mime.startswith(expected + "/") or mime == "application/octet-stream"
                )
            ):
                raise ValueError("源地址未返回相应的媒体文件")
            content_length = response.headers.get("Content-Length")
            declared_size = int(content_length) if content_length else None
            if declared_size is not None and declared_size > MAX_ZIP_MEMBER_BYTES:
                raise ValueError("单个播放素材超过导入大小限制")
            size = 0
            deadline = time.monotonic() + 600
            with temporary.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    if time.monotonic() >= deadline:
                        raise ValueError("播放素材下载超时")
                    size += len(chunk)
                    if size > MAX_ZIP_MEMBER_BYTES:
                        raise ValueError("单个播放素材超过导入大小限制")
                    stream.write(chunk)
            if not size or (declared_size is not None and declared_size != size):
                raise HTTPException("源文件为空或传输不完整")
            if destination.suffix.lower() in {".mp4", ".m4v", ".mov", ".m4a"}:
                check_mp4(temporary, size)
        temporary.replace(destination)
        return size
    finally:
        temporary.unlink(missing_ok=True)


def download_media(url, destination, base):
    for attempt in range(3):
        try:
            return fetch_media(url, destination, base)
        except (OSError, ValueError, HTTPException) as error:
            retryable = not isinstance(error, ValueError) and (
                not isinstance(error, HTTPError) or error.code >= 500 or error.code in {408, 429}
            )
            if not retryable or attempt == 2:
                name = unquote(Path(urlsplit(url).path).name)
                raise ValueError(f"无法下载飞书播放素材 {name}：{error}") from error
            time.sleep(attempt + 1)


def localize_hosted_deck_media(entry):
    document = entry.read_text(encoding="utf-8", errors="replace")
    references = HTMLReferences(document)
    references.feed(document)
    references.close()
    base = urlsplit(html.unescape(references.base or ""))
    if base.scheme != "https" or not FEISHU_APP_HOST.fullmatch(base.netloc) or not FEISHU_DECK_PATH.fullmatch(base.path):
        return False

    directory = entry.parent / MEDIA_DIRECTORY
    downloads = {}
    rewrites = []
    for start, end, raw, is_base, escape in references.spans:
        if is_base:
            value = "./"
        elif reference := resolve_reference(base.geturl(), raw):
            absolute, url = reference
            if start in references.media_spans and inside_deck(url, base):
                source = url._replace(fragment="").geturl()
                leaf = re.sub(r"[^a-zA-Z0-9._-]", "-", unquote(Path(url.path).name))[-120:] or "media"
                name = hashlib.sha256(source.encode()).hexdigest()[:16] + "-" + leaf
                downloads[source] = directory / name
                value = f"{MEDIA_DIRECTORY}/{name}"
                if url.fragment:
                    value += f"#{url.fragment}"
            else:
                # Other assets retain their original URLs when the base switches to local playback.
                original = urlsplit(html.unescape(raw.strip()))
                if original.scheme or original.netloc or raw.startswith("%23"):
                    continue
                value = absolute
        else:
            continue
        rewrites.append((start, end, html.escape(value, quote=True) if escape else value))

    if not downloads:
        return False
    if len(downloads) > MAX_ZIP_FILES:
        raise ValueError("飞书汇报的播放素材数量超过导入限制")
    directory.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        sizes = pool.map(lambda item: download_media(*item, base), downloads.items())
        if sum(sizes) > MAX_ZIP_TOTAL_BYTES:
            raise ValueError("飞书汇报的播放素材总大小超过导入限制")

    parts = []
    cursor = 0
    for start, end, value in rewrites:
        parts.extend((document[cursor:start], value))
        cursor = end
    parts.append(document[cursor:])
    temporary = entry.with_suffix(".localized")
    temporary.write_text("".join(parts), encoding="utf-8")
    temporary.replace(entry)
    return True
