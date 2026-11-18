"""Recursive local dependency checks for imported HTML packages."""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse


HTML_SUFFIXES = {".html", ".htm"}
DOCUMENT_SUFFIXES = HTML_SUFFIXES | {".svg"}
CSS_TOKENS = re.compile(
    r"""(?P<skip>/\*.*?\*/)|"""
    r"""(?P<url>url\(\s*(?:"(?P<double>(?:\\.|[^"\\])*)"|'(?P<single>(?:\\.|[^'\\])*)'|(?P<bare>[^\s)]+))\s*\))|"""
    r"""@import\s+(?P<quote>['"])(?P<import>[^'"]+)(?P=quote)|"""
    r"""["'](?:\\.|[^"'\\])*["']""",
    re.IGNORECASE | re.DOTALL,
)
MAX_REFERENCES = 20_000


class DependencyParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.base_href = ""
        self.references: list[tuple[str, str]] = []
        self._style_depth = 0
        self._style_chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        tag = tag.lower()
        if tag == "style":
            if self._style_depth == 0:
                self._style_chunks = []
            self._style_depth += 1
        if tag == "base" and values.get("href"):
            self.base_href = values["href"]
        for name in ("src", "poster", "data-fs-src"):
            if values.get(name):
                self.references.append((name, values[name]))
        if tag == "link" and values.get("href"):
            self.references.append(("href", values["href"]))
        if tag in {"image", "feimage", "use"}:
            for name in ("href", "xlink:href"):
                if values.get(name):
                    self.references.append((name, values[name]))
        if tag == "object" and values.get("data"):
            self.references.append(("data", values["data"]))
        if values.get("srcset"):
            for item in values["srcset"].split(","):
                source = item.strip().split(" ", 1)[0]
                if source:
                    self.references.append(("srcset", source))
        if values.get("style"):
            self.references.extend(("css-url", value) for value in css_references(values["style"]))

    def handle_data(self, data):
        if self._style_depth:
            self._style_chunks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "style" or not self._style_depth:
            return
        self._style_depth -= 1
        if self._style_depth == 0:
            self._flush_style()

    def finish(self):
        # Keep malformed-but-renderable HTML auditable when </style> is absent.
        if self._style_chunks:
            self._flush_style()
        self._style_depth = 0

    def _flush_style(self):
        text = "".join(self._style_chunks)
        self.references.extend(("css-url", value) for value in css_references(text))
        self._style_chunks = []


def css_references(text: str):
    return [value.strip() for _, _, value in css_spans(text) if value.strip()]


def css_spans(text, offset=0):
    for match in CSS_TOKENS.finditer(text or ""):
        field = next((key for key in ("double", "single", "bare", "import") if match[key] is not None), None)
        if field is not None:
            yield offset + match.start(field), offset + match.end(field), match[field]


def normalize_reference(value: str) -> str:
    """Normalize CSS URLs quoted with HTML entities inside an attribute."""
    value = (value or "").strip()
    quoted = unescape(value) if value.startswith("&") else value
    if len(quoted) >= 2 and quoted[0] == quoted[-1] and quoted[0] in {"'", '"'}:
        return quoted[1:-1].strip()
    return value


def is_external(value: str) -> bool:
    value = (value or "").strip()
    if not value or value in {"location.href", "a.href", "blob"} or value.startswith(("#", "data:", "blob:", "mailto:", "tel:", "javascript:")):
        return True
    parsed = urlparse(value)
    return bool(parsed.scheme or parsed.netloc)


def local_path(root: Path, source: Path, base_href: str, value: str) -> Path | None:
    value = normalize_reference(value)
    if is_external(value):
        return None
    parsed = urlparse(value)
    ref = unquote(parsed.path or value)
    if not ref or ref.startswith("#"):
        return None
    if base_href and not is_external(base_href):
        base_path = unquote(urlparse(base_href).path or base_href)
        base = (root / base_path.lstrip("/")) if base_path.startswith("/") else (source.parent / base_path)
    else:
        base = source.parent
    if ref.startswith(f"/extracted/{root.name}/"):
        target = root / ref.removeprefix(f"/extracted/{root.name}/")
    elif ref.startswith("/extracted/"):
        # A generated platform viewer may point at another managed package;
        # it is validated by that package's own audit rather than this import.
        return None
    else:
        target = (root / ref.lstrip("/")) if ref.startswith("/") else (base / ref)
    try:
        target = target.resolve()
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _refs_for(path: Path):
    if path.suffix.lower() == ".css":
        return "", [("css-url", value) for value in css_references(_read(path))]
    parser = DependencyParser()
    with path.open(encoding="utf-8", errors="replace") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), ""):
            parser.feed(chunk)
    parser.close()
    parser.finish()
    return parser.base_href, list(parser.references)


def audit_dependency_closure(root: Path, *, require_local=False) -> dict:
    """Return missing local resources reachable from every source HTML page."""
    root = Path(root).resolve()
    entries = [
        path for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in HTML_SUFFIXES
        and not any(part.startswith("_minem_") for part in path.relative_to(root).parts)
    ]
    queue = [(path, path) for path in entries]
    visited: set[Path] = set()
    missing: list[dict] = []
    remote = None
    checked = 0
    while queue and checked < MAX_REFERENCES:
        entry, current = queue.pop()
        current = current.resolve()
        if current in visited or not current.exists():
            continue
        visited.add(current)
        base_href, refs = _refs_for(current)
        if require_local and remote is None and (host := urlparse(normalize_reference(base_href)).hostname):
            remote = {"source": current.relative_to(root).as_posix(), "host": host}
        for kind, value in refs:
            if checked >= MAX_REFERENCES:
                break
            if require_local and remote is None and (host := urlparse(normalize_reference(value)).hostname):
                remote = {"source": current.relative_to(root).as_posix(), "host": host}
            target = local_path(root, current, base_href, value)
            if not target:
                continue
            checked += 1
            if not target.exists():
                missing.append({
                    "entry": entry.relative_to(root).as_posix(),
                    "source": current.relative_to(root).as_posix(),
                    "kind": kind,
                    "reference": value,
                    "resolved": target.relative_to(root).as_posix(),
                })
                continue
            if target.suffix.lower() in DOCUMENT_SUFFIXES | {".css"}:
                queue.append((entry, target))
    deduped = []
    seen = set()
    for item in missing:
        key = (item["entry"], item["source"], item["resolved"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    result = {"entryCount": len(entries), "checkedReferences": checked, "missing": deduped, "truncated": checked >= MAX_REFERENCES}
    if require_local:
        result["remote"] = remote
    return result


def write_dependency_audit(root: Path, audit: dict) -> Path:
    path = Path(root) / ".minem-dependency-audit.json"
    path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
