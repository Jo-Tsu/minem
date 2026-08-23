"""Recursive local dependency checks for imported HTML packages."""

from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse


HTML_SUFFIXES = {".html", ".htm"}
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", re.IGNORECASE)
CSS_CLASS_RE = re.compile(r"\.([_a-zA-Z][\w-]*)")
CSS_ID_RE = re.compile(r"#([_a-zA-Z][\w-]*)")
CSS_ATTR_VALUE_RE = re.compile(r"\[([\w-]+)\s*=\s*(['\"]?)([^\]'\"]+)\2\]")
MAX_REFERENCES = 20_000
EPHEMERAL_RUNTIME_REFERENCE_RE = re.compile(
    r"^/decks/[^/?#]+/\.runtime/[^/?#]+/assets/(?P<asset>[^?#]+)(?:[?#].*)?$",
    re.IGNORECASE,
)
HTML_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
HTML_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>\s*</script\s*>", re.IGNORECASE)
TAG_URL_RE = {
    "link": re.compile(r"\bhref\s*=\s*(['\"])(?P<value>.*?)\1", re.IGNORECASE),
    "script": re.compile(r"\bsrc\s*=\s*(['\"])(?P<value>.*?)\1", re.IGNORECASE),
}
RUNTIME_LOCAL_CANDIDATES = {
    "framework/extra-layouts.css": (
        "assets/framework/extra-layouts.css",
        "assets/deck-json/templates/extra-layouts.css",
        "assets/extra-layouts.css",
    ),
    "gsap/gsap.min.js": ("assets/gsap/gsap.min.js", "assets/vendor/gsap.min.js", "assets/gsap.min.js"),
    "gsap/customease.min.js": ("assets/gsap/CustomEase.min.js", "assets/vendor/CustomEase.min.js"),
    "gsap/splittext.min.js": ("assets/gsap/SplitText.min.js", "assets/vendor/SplitText.min.js"),
    "feishu-deck-motion.js": ("assets/feishu-deck-motion.js",),
}


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


def _runtime_root_for_package(root: Path) -> Path | None:
    for candidate in (root, *root.parents):
        if candidate.name == "extracted":
            return candidate.parent
    return None


def _display_path(root: Path, path: Path) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


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
        runtime_root = _runtime_root_for_package(root)
        if runtime_root is None:
            return None
        target = runtime_root / ref.lstrip("/")
    else:
        target = (root / ref.lstrip("/")) if ref.startswith("/") else (base / ref)
    try:
        target = target.resolve()
        runtime_root = _runtime_root_for_package(root)
        allowed_root = (
            (runtime_root / "extracted").resolve()
            if ref.startswith("/extracted/") and runtime_root
            else root.resolve()
        )
        target.relative_to(allowed_root)
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


def _css_reference_may_be_used(css_text: str, reference: str, html_text: str) -> bool:
    """Conservatively detect whether a url() rule can match the source HTML."""
    for match in CSS_URL_RE.finditer(css_text or ""):
        if match.group(2).strip() != reference:
            continue
        block_start = css_text.rfind("{", 0, match.start())
        if block_start < 0:
            return True
        selector_start = css_text.rfind("}", 0, block_start) + 1
        selector_group = css_text[selector_start:block_start].strip()
        if not selector_group or selector_group.startswith("@"):
            return True
        for selector in selector_group.split(","):
            classes = CSS_CLASS_RE.findall(selector)
            ids = CSS_ID_RE.findall(selector)
            attributes = CSS_ATTR_VALUE_RE.findall(selector)
            if not classes and not ids and not attributes:
                return True
            if any(not re.search(rf'class\s*=\s*["\'][^"\']*\b{re.escape(name)}\b', html_text) for name in classes):
                continue
            if any(not re.search(rf'id\s*=\s*["\']{re.escape(name)}["\']', html_text) for name in ids):
                continue
            if any(
                not re.search(
                    rf'{re.escape(name)}\s*=\s*["\']{re.escape(value)}["\']',
                    html_text,
                )
                for name, _quote, value in attributes
            ):
                continue
            return True
    return False


def audit_dependency_closure(root: Path) -> dict:
    """Return missing local resources reachable from every source HTML page."""
    root = Path(root).resolve()
    entries = [
        path for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in HTML_SUFFIXES
        and not any(
            part.startswith(("_minem_", ".", "__MACOSX"))
            for part in path.relative_to(root).parts
        )
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
                # Exported HTML bundles commonly retain generated CSS rules for
                # components that are not present in the final document. A
                # missing url() from such a stylesheet is useful audit data, but
                # it must not reject an otherwise complete package. Structural
                # HTML dependencies and inline-style resources remain blocking.
                optional_css_resource = (
                    current.suffix.lower() == ".css"
                    and kind == "css-url"
                    and not _css_reference_may_be_used(_read(current), value, _read(entry))
                )
                missing.append({
                    "entry": entry.relative_to(root).as_posix(),
                    "source": _display_path(root, current),
                    "kind": kind,
                    "reference": value,
                    "resolved": _display_path(root, target),
                    "severity": "warning" if optional_css_resource else "error",
                    "reason": "stylesheet-optional-resource" if optional_css_resource else "required-local-resource",
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
    blocking_missing = [item for item in deduped if item["severity"] == "error"]
    warning_missing = [item for item in deduped if item["severity"] == "warning"]
    unique_missing = []
    unique_seen = set()
    for item in deduped:
        key = (item["severity"], item["resolved"])
        if key in unique_seen:
            continue
        unique_seen.add(key)
        unique_missing.append(item)
    return {
        "entryCount": len(entries),
        "checkedReferences": checked,
        "missing": deduped,
        "blockingMissing": blocking_missing,
        "warningMissing": warning_missing,
        "uniqueMissing": unique_missing,
        "truncated": checked >= MAX_REFERENCES,
    }


def write_dependency_audit(root: Path, audit: dict) -> Path:
    path = Path(root) / ".minem-dependency-audit.json"
    path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _local_runtime_candidate(root: Path, source: Path, runtime_asset: str) -> str:
    candidates = RUNTIME_LOCAL_CANDIDATES.get(runtime_asset.lower(), ())
    for relative in candidates:
        candidate = root / relative
        if candidate.is_file():
            return Path(os.path.relpath(candidate, source.parent)).as_posix()
    return ""


def normalize_ephemeral_runtime_references(root: Path) -> dict:
    """Remove or localize expired signed runtime CSS/JS references in HTML imports."""
    root = Path(root).resolve()
    changes: list[dict] = []

    def normalize_tag(source: Path, tag_name: str, tag: str) -> str:
        url_match = TAG_URL_RE[tag_name].search(tag)
        if not url_match:
            return tag
        reference = url_match.group("value").strip()
        runtime_match = EPHEMERAL_RUNTIME_REFERENCE_RE.match(reference)
        if not runtime_match:
            return tag
        runtime_asset = unquote(runtime_match.group("asset")).lstrip("/")
        expected_suffix = ".css" if tag_name == "link" else ".js"
        if not runtime_asset.lower().endswith(expected_suffix):
            return tag
        replacement = _local_runtime_candidate(root, source, runtime_asset)
        action = "rewritten" if replacement else "removed"
        changes.append({
            "source": source.relative_to(root).as_posix(),
            "tag": tag_name,
            "reference": reference,
            "runtimeAsset": runtime_asset,
            "action": action,
            "replacement": replacement,
            "reason": "ephemeral-signed-runtime",
        })
        if not replacement:
            return ""
        start, end = url_match.span("value")
        return f"{tag[:start]}{replacement}{tag[end:]}"

    for source in sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in HTML_SUFFIXES):
        text = _read(source)
        if "/.runtime/" not in text:
            continue
        normalized = HTML_LINK_TAG_RE.sub(lambda match: normalize_tag(source, "link", match.group(0)), text)
        normalized = HTML_SCRIPT_TAG_RE.sub(lambda match: normalize_tag(source, "script", match.group(0)), normalized)
        if normalized != text:
            source.write_text(normalized, encoding="utf-8")

    report = {
        "schemaVersion": 1,
        "changedFiles": len({item["source"] for item in changes}),
        "changeCount": len(changes),
        "changes": changes,
    }
    path = root / ".minem-import-normalization.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
