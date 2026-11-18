"""Store large inline raster images once in an offline HTML bundle."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from minem.paths import is_path_within


MIN_INLINE_IMAGE_BYTES = 16 * 1024
IMAGE_EXTENSIONS = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "gif": ".gif", "webp": ".webp"}
IMAGE_DATA = r"data:image/(?P<format>png|jpe?g|gif|webp);base64,(?P<payload>[a-zA-Z0-9+/=\s]+)"
INLINE_IMAGE = re.compile(IMAGE_DATA, re.IGNORECASE)
CSS_IMAGE = re.compile(
    r"""(?P<skip>/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')"""
    r"""|(?<![\w-])url\(\s*(?P<quote>['"]?)(?P<image>""" + IMAGE_DATA + r""")(?P=quote)\s*\)""",
    re.IGNORECASE | re.DOTALL,
)
ATTRIBUTE = re.compile(
    r"""(?P<name>[^\s=/><]+)(?:\s*=\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>[^\s>]+)))?"""
)


class InlineImageReferences(HTMLParser):
    def __init__(self, document: str):
        super().__init__(convert_charrefs=False)
        self.line_offsets = [0, *(match.end() for match in re.finditer("\n", document))]
        self.references = []
        self.base_href = None
        self.in_style = False

    def document_offset(self):
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def add_css_references(self, css, offset):
        for match in CSS_IMAGE.finditer(css):
            if match["image"] is not None:
                self.references.append((offset + match.start("image"), offset + match.end("image"), match))

    def handle_starttag(self, tag, attrs):
        if tag == "base" and self.base_href is None:
            self.base_href = dict(attrs).get("href")
        if tag == "style":
            self.in_style = True
        raw = self.get_starttag_text()
        # Consume whole attribute values, so strings in event handlers and
        # metadata that happen to contain HTML are left alone.
        start = re.match(r"<[^\s/>]+", raw).end()
        offset = self.document_offset()
        for attribute in ATTRIBUTE.finditer(raw, start):
            field = next((key for key in ("double", "single", "bare") if attribute[key] is not None), None)
            if field is None:
                continue
            name = attribute["name"].lower()
            value = attribute[field]
            value_offset = offset + attribute.start(field)
            if name == "style":
                self.add_css_references(value, value_offset)
            elif (tag, name) in {("img", "src"), ("video", "poster")}:
                match = INLINE_IMAGE.fullmatch(value.strip())
                if match:
                    self.references.append((value_offset, offset + attribute.end(field), match))

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.add_css_references(data, self.document_offset())


def extract_bundle_images(document: str, page: Path, bundle_root: Path, store_image) -> str:
    """Replace eligible image references and pass each decoded file to the bundle writer."""
    if not re.search("base64,", document, re.IGNORECASE):
        return document

    parser = InlineImageReferences(document)
    parser.feed(document)
    parser.close()
    if not parser.references:
        return document

    base = page.parent
    if parser.base_href:
        try:
            href = urlsplit(parser.base_href.strip())
        except ValueError:
            return document
        href_path = unquote(href.path)
        if href.scheme or href.netloc or href_path.startswith("/"):
            return document
        if href_path:
            base_path = (base / href_path).resolve()
            base = base_path if href_path.endswith("/") else base_path.parent
    if not is_path_within(base.resolve(), bundle_root.resolve()):
        return document

    parts = []
    last = 0
    for start, end, match in parser.references:
        encoded = match["payload"]
        if len(encoded) < MIN_INLINE_IMAGE_BYTES * 4 // 3:
            continue
        try:
            image = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
        except (ValueError, binascii.Error):
            continue
        if len(image) < MIN_INLINE_IMAGE_BYTES:
            continue
        digest = hashlib.sha256(image).hexdigest()
        suffix = IMAGE_EXTENSIONS[match["format"].lower()]
        target = bundle_root / "assets" / "_minem_inline" / f"{digest}{suffix}"
        store_image(target, image)
        parts.extend((document[last:start], Path(os.path.relpath(target, base)).as_posix()))
        last = end
    return "".join([*parts, document[last:]]) if parts else document
