"""Collect and relocate static HTML/CSS resources for a portable report."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

from minem.html_assets import ATTRIBUTE
from minem.html_dependencies import audit_dependency_closure, css_spans, normalize_reference


# A CSS URL is optional in @import. Keep comments and string literals opaque
# so examples and CSS custom strings do not turn into asset references.
SRCSET_VALUE = re.compile(r"[^\s,][^\s]*")


def srcset_spans(value, offset):
    position = 0
    while match := SRCSET_VALUE.search(value, position):
        token = match[0].rstrip(",")
        end = match.start() + len(token)
        if token:
            yield offset + match.start(), offset + end, token
        if end != match.end():
            position = match.end()
        else:
            separator = value.find(",", end)
            if separator == -1:
                break
            position = separator + 1


class HTMLReferences(HTMLParser):
    def __init__(self, document):
        super().__init__(convert_charrefs=False)
        self.lines = [0, *(m.end() for m in re.finditer("\n", document))]
        self.base = None
        self.spans = []
        self.media_spans = set()
        self.stylesheet_spans = set()
        self.dependency_spans = set()
        self.in_style = False

    def document_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self.in_style = True
        raw = self.get_starttag_text()
        offset = self.document_offset()
        for attr in ATTRIBUTE.finditer(raw, re.match(r"<[^\s/>]+", raw).end()):
            field = next((key for key in ("double", "single", "bare") if attr[key] is not None), None)
            if field is None:
                continue
            key = attr["name"].lower()
            value = attr[field]
            start = offset + attr.start(field)
            end = offset + attr.end(field)
            if tag == "base" and key == "href":
                if self.base is None:
                    self.base = value
                self.spans.append((start, end, value, True, True))
            elif key in {"src", "href", "xlink:href", "poster", "data-fs-src"} or (tag == "object" and key == "data"):
                self.spans.append((start, end, value, False, True))
                if key != "href" or tag in {"link", "image", "use", "feimage"}:
                    self.dependency_spans.add(start)
                if tag == "link" and key == "href" and "stylesheet" in (dict(attrs).get("rel") or "").lower().split():
                    self.stylesheet_spans.add(start)
                if tag in {"video", "audio", "source", "track"} and key in {"src", "poster", "data-fs-src"}:
                    self.media_spans.add(start)
            elif key in {"srcset", "style"}:
                spans = css_spans(value, start) if key == "style" else srcset_spans(value, start)
                for left, right, ref in spans:
                    self.spans.append((left, right, ref, False, True))
                    self.dependency_spans.add(left)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            for start, end, value in css_spans(data, self.document_offset()):
                self.spans.append((start, end, value, False, False))
                self.dependency_spans.add(start)


class OfflineBundle:
    """Preserve each upload's directory tree and translate cross-upload URLs."""

    def __init__(self, extracted: Path, target: Path, *, excluded):
        self.extracted = extracted.resolve()
        self.target = target.resolve()
        self.excluded = excluded
        self.copied = set()

    def add(self, source):
        source = Path(source).resolve()
        relative = source.relative_to(self.extracted)
        destination = self.target / "sources" / relative
        if source in self.copied:
            return destination
        self.copied.add(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.lower()
        if suffix not in {".html", ".htm", ".css", ".svg"}:
            shutil.copy2(source, destination)
            return destination

        document = source.read_text(encoding="utf-8", errors="replace")
        source_url = "/extracted/" + quote(relative.as_posix(), safe="/")
        if suffix == ".css":
            spans = [(left, right, value, False, False) for left, right, value in css_spans(document)]
            base = source_url
        else:
            parser = HTMLReferences(document)
            parser.feed(document)
            parser.close()
            spans = parser.spans
            base, _ = resolve_reference(source_url, parser.base or "") or (source_url, None)
        output = []
        cursor = 0
        for start, end, raw, is_base, escape in spans:
            value = "./" if is_base else self.rewrite(raw, base, relative.parts[0], destination)
            if value is None:
                continue
            output.extend((document[cursor:start], html.escape(value, quote=True) if escape else value))
            cursor = end
        output.append(document[cursor:])
        destination.write_text("".join(output), encoding="utf-8")
        return destination

    def rewrite(self, value, base, upload_id, destination):
        if not (reference := resolve_reference(base, value)):
            return None
        absolute, parsed = reference
        if parsed.scheme or parsed.netloc:
            return absolute
        path = unquote(parsed.path)
        if path.startswith("/assets/"):
            path = f"/extracted/{upload_id}{path}"
        if not path.startswith("/extracted/") or "\x00" in path or any(len(os.fsencode(part)) > 255 for part in path.split("/")):
            return None
        source = (self.extracted / path.removeprefix("/extracted/")).resolve()
        if not source.is_relative_to(self.extracted) or not source.is_file() or self.excluded(source):
            return None
        copied = self.add(source)
        relative = quote(Path(os.path.relpath(copied, destination.parent)).as_posix(), safe="/")
        query = "?" + parsed.query if parsed.query else ""
        fragment = "#" + parsed.fragment if parsed.fragment else ""
        return relative + query + fragment


def resolve_reference(base, value):
    value = normalize_reference(html.unescape(value))
    if not value or value.startswith(("#", "data:", "blob:", "javascript:", "mailto:", "tel:")):
        return None
    try:
        absolute = urljoin(base, value)
        return absolute, urlsplit(absolute)
    except ValueError:
        return None


def validate_offline_package(root):
    """Do not label an export offline when required local or online media is absent."""
    root = Path(root)
    audit = audit_dependency_closure(root, require_local=True)
    if audit["truncated"]:
        raise ValueError("导出包资源过多，完整性检查未完成")
    if audit["missing"]:
        missing = audit["missing"][0]
        raise ValueError(f"导出包资源缺失：{missing['source']} → {missing['resolved']}")
    if audit["remote"]:
        raise ValueError(f"导出内容仍依赖联网资源：{audit['remote']['source']}，请先补齐本地素材")
    for manifest in root.rglob("manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        resources = data.get("resources") if isinstance(data, dict) else None
        if not isinstance(resources, list):
            continue
        if any(isinstance(resource, str) and urlsplit(resource).scheme in {"http", "https"} for resource in resources):
            raise ValueError(f"导出内容仍依赖联网媒体：{manifest.relative_to(root).as_posix()}，请先补齐本地素材")
