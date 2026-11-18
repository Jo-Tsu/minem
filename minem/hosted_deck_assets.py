"""Save the source Deck's static dependencies inside each owned page."""

import hashlib
import html
import os
import shutil
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, build_opener

from minem.config import MAX_ZIP_FILES, MAX_ZIP_MEMBER_BYTES, MAX_ZIP_TOTAL_BYTES
from minem.drive_fonts import localize_drive_fonts
from minem.html_dependencies import local_path
from minem.hosted_deck_media import DeckOriginRedirects, FEISHU_APP_HOST, check_mp4, inside_deck
from minem.offline_bundle import HTMLReferences, css_spans, resolve_reference


class HostedDeckAssets:
    def __init__(self, entry, base, cache):
        self.entry = entry
        self.base = base
        self.cache = cache
        self.saved = {}
        self.size = 0

    def add(self, url):
        source = url._replace(fragment="").geturl()
        if source in self.saved:
            return self.saved[source]
        if not inside_deck(url, self.base):
            raise ValueError("播放依赖跳出了原飞书汇报目录")
        suffix = Path(unquote(url.path)).suffix.lower()
        key = hashlib.sha256(source.encode()).hexdigest()[:24] + suffix
        cached = self.cache / key
        if not cached.is_file():
            temporary = cached.with_suffix(cached.suffix + ".part")
            try:
                with build_opener(DeckOriginRedirects(self.base)).open(
                    Request(source, headers={"Accept-Encoding": "identity"}), timeout=30,
                ) as response, temporary.open("wb") as out:
                    if response.status != 200:
                        raise ValueError("飞书未返回完整播放资源")
                    if suffix not in {".html", ".htm"} and response.headers.get_content_type() == "text/html":
                        raise ValueError(f"飞书返回了登录或错误页面：{url.path}")
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_ZIP_MEMBER_BYTES:
                            raise ValueError("播放资源超过单文件限制")
                        out.write(chunk)
                    length = response.headers.get("Content-Length")
                    if not size or length is not None and int(length) != size:
                        raise ValueError("飞书播放资源传输不完整")
                if suffix in {".mp4", ".m4v", ".mov", ".m4a"}:
                    check_mp4(temporary, size)
                temporary.replace(cached)
            finally:
                temporary.unlink(missing_ok=True)
        self.size += cached.stat().st_size
        if self.size > MAX_ZIP_TOTAL_BYTES or len(self.saved) >= MAX_ZIP_FILES:
            raise ValueError("播放依赖超过素材包限制")
        target = self.entry.parent / "deck-assets" / key
        target.parent.mkdir(exist_ok=True)
        self.saved[source] = target
        if suffix in {".html", ".htm", ".css", ".svg"}:
            document = self.rewrite(cached.read_text(encoding="utf-8"), source, target, suffix)
            target.write_text(document, encoding="utf-8")
        else:
            shutil.copyfile(cached, target)
        return target

    def rewrite(self, document, source_url, destination, suffix):
        if suffix == ".css":
            spans = [(start, end, value, False, False) for start, end, value in css_spans(document)]
            base = source_url
            dependencies = {start for start, *_ in spans}
            local_base = ""
        else:
            parser = HTMLReferences(document)
            parser.feed(document)
            parser.close()
            spans, dependencies = parser.spans, parser.dependency_spans
            base = urljoin(source_url, html.unescape(parser.base or ""))
            local_base = html.unescape(parser.base or "")
        parts = []
        cursor = 0
        for start, end, raw, is_base, escape in spans:
            if is_base:
                replacement = "./"
            else:
                reference = resolve_reference(base, raw)
                if not reference:
                    continue
                absolute, url = reference
                local = local_path(self.entry.parent, destination, local_base, raw)
                if local and local.is_file():
                    replacement = Path(os.path.relpath(local, destination.parent)).as_posix()
                    if urlsplit(raw).fragment:
                        replacement += "#" + urlsplit(raw).fragment
                elif start in dependencies and inside_deck(url, self.base):
                    target = self.add(url)
                    replacement = Path(os.path.relpath(target, destination.parent)).as_posix()
                    if url.fragment:
                        replacement += "#" + url.fragment
                else:
                    replacement = absolute
            parts.extend((document[cursor:start], html.escape(replacement, quote=True) if escape else replacement))
            cursor = end
        parts.append(document[cursor:])
        return "".join(parts)


def localize_hosted_deck_assets(entry, cache):
    document = entry.read_text(encoding="utf-8")
    parser = HTMLReferences(document)
    parser.feed(document)
    parser.close()
    bases = [parser.base or "", *(value for _, _, value, _, _ in parser.spans)]
    base = next((urlsplit(html.unescape(value)) for value in bases if
                 FEISHU_APP_HOST.fullmatch(urlsplit(html.unescape(value)).netloc)
                 and "/deck/" in urlsplit(html.unescape(value)).path), None)
    if base is None:
        return False
    base = base._replace(path=base.path.split("/deck/", 1)[0] + "/deck/", query="", fragment="")
    cache.mkdir(parents=True, exist_ok=True)
    bundle = HostedDeckAssets(entry, base, cache)
    localized = bundle.rewrite(document, base.geturl(), entry, ".html")
    temporary = entry.with_suffix(".localized")
    temporary.write_text(localized, encoding="utf-8")
    temporary.replace(entry)
    localize_drive_fonts(entry.parent, cache / "fonts")
    return True
