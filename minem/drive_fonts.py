"""Bundle the public Feishu Miaoda font stylesheet used in Drive prototypes."""

import hashlib
import html
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from minem.config import MAX_ZIP_FILES, MAX_ZIP_TOTAL_BYTES
from minem.html_dependencies import HTML_SUFFIXES, local_path
from minem.offline_bundle import HTMLReferences, css_spans

STYLE_ENDPOINT = "https://miaoda.feishu.cn/fonts/css2"
FONT_URL = re.compile(
    r"https://sf3-scmcdn-cn\.feishucdn\.com/obj/feishu-static/lark-miaoda-fonts/fonts/"
    r"[a-z0-9-]+/[a-zA-Z0-9_-]+\.woff2"
)
FONT_BYTES = 2 * 1024 * 1024


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_font_resource(url, expected_mime):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/131.0.0.0", "Accept-Encoding": "identity"})
    opener = build_opener(NoRedirects)
    for attempt in range(2):
        try:
            with opener.open(request, timeout=15) as response:
                if response.status != 200 or response.headers.get_content_type() not in expected_mime:
                    raise ValueError("飞书妙搭字体服务返回了意外的文件类型")
                data = response.read(FONT_BYTES + 1)
            if len(data) > FONT_BYTES:
                raise ValueError("飞书妙搭字体文件超过大小限制")
            return data
        except (OSError, HTTPException) as error:
            if attempt or isinstance(error, HTTPError) and error.code < 500 and error.code not in {408, 429}:
                raise
            time.sleep(1)


def download_font(url, destination):
    data = read_font_resource(url, {"font/woff2", "application/octet-stream"})
    if len(data) < 48 or data[:4] != b"wOF2" or int.from_bytes(data[8:12], "big") != len(data):
        raise ValueError("飞书妙搭返回的 WOFF2 字体不完整")
    destination.write_bytes(data)
    return len(data)


def bundle_font_stylesheet(url, destination):
    stylesheet = read_font_resource(url, {"text/css"}).decode()
    spans = list(css_spans(stylesheet))
    urls = set(value.strip() for _, _, value in spans)
    if not urls or re.search(r"@import\b", stylesheet, re.I) or any(not FONT_URL.fullmatch(value) for value in urls):
        raise ValueError("飞书妙搭字体样式包含不受支持的资源引用")
    if len(urls) >= MAX_ZIP_FILES:
        raise ValueError("飞书妙搭字体文件数量超过素材包限制")
    files = {value: hashlib.sha256(value.encode()).hexdigest()[:20] + ".woff2" for value in urls}
    destination.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        sizes = pool.map(lambda value: download_font(value, destination / files[value]), sorted(urls))
        if sum(sizes) + len(stylesheet) > MAX_ZIP_TOTAL_BYTES:
            raise ValueError("飞书妙搭字体超过素材包总大小限制")
    parts = []
    cursor = 0
    for start, end, value in spans:
        parts.extend((stylesheet[cursor:start], files[value.strip()]))
        cursor = end
    parts.append(stylesheet[cursor:])
    (destination / "fonts.css").write_text("".join(parts), encoding="utf-8")


def localize_drive_fonts(page_root, cache):
    installed = set()
    for path in sorted(page_root.rglob("*")):
        if path.suffix.lower() not in HTML_SUFFIXES or not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if STYLE_ENDPOINT not in source:
            continue
        parser = HTMLReferences(source)
        parser.feed(source)
        parser.close()
        parts = []
        cursor = 0
        for start, end, raw, _, _ in parser.spans:
            if start not in parser.stylesheet_spans:
                continue
            link = urlsplit(html.unescape(raw))
            if link._replace(query="", fragment="").geturl() != STYLE_ENDPOINT:
                continue
            url = link._replace(fragment="").geturl()
            key = hashlib.sha256(url.encode()).hexdigest()[:20]
            reference = f"_minem_fonts/{key}/fonts.css"
            target = local_path(page_root, path, html.unescape(parser.base or ""), reference)
            if target is None:
                raise ValueError("无法在页面内封装飞书妙搭字体")
            try:
                if not (cache / key / "fonts.css").is_file():
                    bundle_font_stylesheet(url, cache / key)
                if target not in installed:
                    shutil.copytree(cache / key, target.parent)
                    installed.add(target)
            except (OSError, HTTPException, ValueError) as error:
                raise ValueError(f"飞书妙搭字体封装失败：{error}") from error
            parts.extend((source[cursor:start], reference))
            cursor = end
        if parts:
            parts.append(source[cursor:])
            path.write_text("".join(parts), encoding="utf-8")
