"""Recursive local dependency checks for imported HTML packages."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse


HTML_SUFFIXES = {".html", ".htm"}
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", re.IGNORECASE)
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
    text = re.sub(r"/\*.*?\*/", "", text or "", flags=re.S)
    return [match.group(2).strip() for match in CSS_URL_RE.finditer(text) if match.group(2).strip()]


def is_external(value: str) -> bool:
    value = (value or "").strip()
    if not value or value in {"location.href", "a.href", "blob"} or value.startswith(("#", "data:", "blob:", "mailto:", "tel:", "javascript:")):
        return True
    parsed = urlparse(value)
    return bool(parsed.scheme or parsed.netloc)


def local_path(root: Path, source: Path, base_href: str, value: str) -> Path | None:
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
    text = _read(path)
    if path.suffix.lower() == ".css":
        return "", [("css-url", value) for value in css_references(text)]
    parser = DependencyParser()
    parser.feed(text[:4_000_000])
    parser.close()
    parser.finish()
    return parser.base_href, list(parser.references)


def audit_dependency_closure(root: Path) -> dict:
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
    checked = 0
    while queue and checked < MAX_REFERENCES:
        entry, current = queue.pop()
        current = current.resolve()
        if current in visited or not current.exists():
            continue
        visited.add(current)
        base_href, refs = _refs_for(current)
        for kind, value in refs:
            if checked >= MAX_REFERENCES:
                break
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
            if target.suffix.lower() in HTML_SUFFIXES | {".css"}:
                queue.append((entry, target))
    deduped = []
    seen = set()
    for item in missing:
        key = (item["entry"], item["source"], item["resolved"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return {"entryCount": len(entries), "checkedReferences": checked, "missing": deduped, "truncated": checked >= MAX_REFERENCES}


def write_dependency_audit(root: Path, audit: dict) -> Path:
    path = Path(root) / ".minem-dependency-audit.json"
    path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
