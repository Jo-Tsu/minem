"""Render compatible Feishu Deck documents with their original layout and runtime."""

from __future__ import annotations

import html
import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urljoin, urlsplit

from minem.html_splitter import extract_page_node_spans


class NativeDeck(NamedTuple):
    source: str
    frames: tuple[tuple[int, int, str], ...]
    base_href: str | None
    base_span: tuple[int, int] | None
    external_runtime: bool = False


class DeckHeader(HTMLParser):
    def __init__(self, source: str):
        super().__init__()
        self.lines = [0, *(m.end() for m in re.finditer("\n", source))]
        self.generator = ""
        self.base_href = None
        self.base_span = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and (values.get("name") or "").lower() == "fs-deck-generator":
            self.generator = values.get("content", "")
        if tag == "base" and "href" in values and self.base_span is None:
            row, column = self.getpos()
            start = self.lines[row - 1] + column
            self.base_span = (start, start + len(self.get_starttag_text()))
            self.base_href = values["href"] or ""


@lru_cache(maxsize=8)
def _read_native_deck(path: Path, stamp: tuple[int, int]) -> NativeDeck | None:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    end = re.search(r"</head\s*>", source, re.I)
    if not end or "fs-deck-generator" not in source[:end.start()].lower():
        return None
    header = DeckHeader(source[:end.start()])
    header.feed(source[:end.start()])
    if header.generator != "render-deck":
        return None
    # The authoring marker also appears on partial fixtures. Require the
    # original Deck container and its frame runtime before using this renderer.
    if not re.search(r'<div\b[^>]*\bclass=["\']deck["\']', source, re.I):
        return None
    external_runtime = False
    for url in re.findall(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', source, re.I):
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or Path(parsed.path).name != "feishu-deck.js":
            continue
        resolved = urlsplit(urljoin(header.base_href or "./", url))
        if resolved.scheme or resolved.netloc:
            continue
        script = (path.parent / unquote(resolved.path)).resolve()
        if script.is_relative_to(path.parent.resolve()) and script.is_file():
            external_runtime = True
            break
    if not (external_runtime or "function goTo(deck, frames," in source or "fs-native-enlarge-script" in source):
        return None
    frames = tuple(extract_page_node_spans(source))
    if not frames or any(not re.search(r'<[^>]*\bclass=["\'][^"\']*\bslide-frame\b', frame, re.I) for _, _, frame in frames):
        return None
    return NativeDeck(source, frames, header.base_href, header.base_span, external_runtime)


def read_native_deck(path: Path | None) -> NativeDeck | None:
    if not path:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return _read_native_deck(path, (stat.st_mtime_ns, stat.st_size))


def resolve_deck_base(deck: NativeDeck, source_url: str) -> str:
    return urljoin(source_url, deck.base_href) if deck.base_href else urljoin(source_url, ".")


def render_native_deck(deck: NativeDeck, numbers: list[int], base_href: str, *, single_page: bool = False, cover_title: str | None = None) -> str:
    """Select frames before the native viewer initializes and preserve its shell."""
    if not numbers or any(not 1 <= number <= len(deck.frames) for number in numbers):
        raise ValueError("Invalid native deck frame range")
    source = deck.source
    if numbers != list(range(1, len(deck.frames) + 1)):
        pieces = []
        cursor = 0
        for index, (start, end, _) in enumerate(deck.frames):
            pieces.append(source[cursor:start])
            if index < len(numbers):
                frame = deck.frames[numbers[index] - 1][2]
                # The current frame's position belongs to this view. Keep
                # other per-slide attributes and styling verbatim.
                head_end = frame.index(">")
                head = re.sub(r'(?<=\s)is-current(?=[\s"\'])', "", frame[:head_end], count=1)
                if index == 0 and not deck.external_runtime:
                    head = re.sub(r'(class=["\'][^"\']*\bslide-frame\b)', r'\1 is-current', head, count=1)
                pieces.extend((head, frame[head_end:]))
            cursor = end
        pieces.append(source[cursor:])
        source = "".join(pieces)

    # Native replaceState must resolve slide hashes against the document URL
    # even when a source-provided <base> points at the author's Feishu app.
    chrome = '<style>.deck-ui,.deck-progress,.deck-controls,.nav-hint,.fs-mobile-back,.fs-mobile-pageno{display:none!important}</style>' if single_page else ""
    if cover_title is not None:
        chrome += f'<meta name="minem-cover-title" content="{html.escape(cover_title, quote=True)}">'
        chrome += """<style>
.deck[data-mode="scroll"]{margin:0!important;padding:0!important}
.deck[data-mode="scroll"] .slide-frame{margin:0!important;border:0!important;border-radius:0!important}
.deck[data-mode="scroll"] .slide-frame::after{content:none!important}
.slide-frame .slide > *{opacity:1!important;animation:none!important}
.minem-cover-fallback{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;padding:0 11%;z-index:1;
font:700 clamp(14px,5vw,60px)/1.35 system-ui,sans-serif;color:#fff;text-align:center;pointer-events:none}
</style><script>
document.addEventListener("DOMContentLoaded", () => {
  const image = document.querySelector(".slide-frame.is-current img.cover-art");
  if (!image) return;
  const showTitle = () => {
    image.style.visibility = "hidden";
    const title = document.createElement("div");
    title.className = "minem-cover-fallback";
    title.textContent = image.alt || document.querySelector('meta[name="minem-cover-title"]').content;
    document.body.append(title);
  };
  if (image.complete && !image.naturalWidth) showTitle();
  else image.addEventListener("error", showTitle, {once:true});
});
</script>"""
    helper = "" if 'name="minem-native-deck"' in source else """<script>
document.addEventListener("click", event => {
  const link = event.target.closest?.("a[href^='#']");
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const target = link.getAttribute("href");
  if (target.length > 1) {
    event.preventDefault();
    location.hash = target;
  }
});
</script>"""
    # Replace only the href, retaining other base attributes such as target.
    tag = f'<base href="{html.escape(base_href, quote=True)}">'
    if deck.base_span:
        start, end = deck.base_span
        original = source[start:end]
        tag = re.sub(r'\bhref\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', lambda _: f'href="{html.escape(base_href, quote=True)}"', original, count=1)
        source = source[:start] + tag + source[end:]
        tag = ""
    source = source.replace("history.replaceState(null, '', newHash)", "history.replaceState(null, '', new URL(newHash, location.href))")
    head = re.search(r"<head\b[^>]*>", source, re.I)
    marker = '<meta name="minem-native-deck" content="1">' if helper else ""
    history_fix = """<script>
const minemReplaceState = history.replaceState.bind(history);
history.replaceState = (state, title, url) => minemReplaceState(state, title,
  typeof url === "string" && url.startsWith("#") ? new URL(url, location.href) : url);
</script>""" if deck.external_runtime and helper else ""
    injection = tag + marker + chrome + helper + history_fix
    return source[:head.end()] + injection + source[head.end():] if head else injection + source


def external_deck_base(deck: NativeDeck) -> bool:
    if not deck.base_href:
        return False
    base = urlsplit(deck.base_href)
    return bool(base.scheme or base.netloc)
