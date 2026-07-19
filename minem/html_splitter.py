import json
import re
from pathlib import Path


def find_balanced_element(html, start, tag):
    pattern = re.compile(rf"<(/?){tag}\b[^>]*>", re.IGNORECASE)
    depth = 0
    for match in pattern.finditer(html, start):
        token = match.group(0)
        closing = bool(match.group(1))
        self_closing = token.rstrip().endswith("/>")
        if not closing:
            depth += 1
            if self_closing:
                depth -= 1
        else:
            depth -= 1
        if depth == 0:
            return html[start:match.end()]
    return ""


def find_balanced_element_span(html, start, tag):
    node = find_balanced_element(html, start, tag)
    if not node:
        return None
    return start, start + len(node), node


def extract_page_node_spans(html):
    selectors = [
        r'<(?P<tag>div|section|article)\b(?=[^>]*class=["\'][^"\']*\bslide-frame\b[^"\']*["\'])[^>]*>',
        r'<(?P<tag>div|section|article)\b(?=[^>]*class=["\'][^"\']*\bslide\b[^"\']*["\'])[^>]*>',
        r'<(?P<tag>div|section|article)\b(?=[^>]*(?:data-slide|data-page))[^>]*>',
        r'<(?P<tag>section)\b[^>]*>',
    ]
    for selector in selectors:
        spans = []
        for match in re.finditer(selector, html, re.IGNORECASE):
            span = find_balanced_element_span(html, match.start(), match.group("tag"))
            if span:
                spans.append(span)
        if spans:
            return spans
    return []


def extract_page_nodes(html):
    return [span[2] for span in extract_page_node_spans(html)]


def strip_outer_element(node, tag):
    pattern = re.compile(rf"^<%s\b[^>]*>(?P<body>[\s\S]*)</%s>$" % (tag, tag), re.IGNORECASE)
    match = pattern.match(node.strip())
    return match.group("body").strip() if match else node.strip()


def extract_control_page_node(control_html):
    main_match = re.search(
        r'<(?P<tag>main|div|section)\b(?=[^>]*data-material-control=["\']?true["\']?)[^>]*>',
        control_html,
        re.IGNORECASE,
    )
    if main_match:
        main_node = find_balanced_element(control_html, main_match.start(), main_match.group("tag"))
        inner = strip_outer_element(main_node, main_match.group("tag"))
        page_nodes = extract_page_nodes(inner)
        return page_nodes[0] if page_nodes else inner
    page_nodes = extract_page_nodes(control_html)
    if page_nodes:
        return page_nodes[0]
    body_match = re.search(r"<body\b[^>]*>(?P<body>[\s\S]*?)</body>", control_html, re.IGNORECASE)
    return body_match.group("body").strip() if body_match else control_html.strip()


def replace_report_page_node(report_html, page_number, page_html):
    spans = extract_page_node_spans(report_html)
    if page_number < 1 or page_number > len(spans):
        return report_html, False
    start, end, existing = spans[page_number - 1]
    replacement = page_html.strip()
    if not replacement or existing.strip() == replacement:
        return report_html, False
    return f"{report_html[:start]}{replacement}{report_html[end:]}", True


def viewer_pages_array_span(report_html):
    match = re.search(r"\bconst\s+pages\s*=\s*\[", report_html)
    if not match:
        return None
    start = match.start()
    array_start = report_html.find("[", match.start())
    depth = 0
    in_string = ""
    escaped = False
    for index in range(array_start, len(report_html)):
        char = report_html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = ""
            continue
        if char in {'"', "'", "`"}:
            in_string = char
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                semicolon = report_html.find(";", index)
                if semicolon == -1:
                    semicolon = index
                return start, semicolon + 1
    return None


def viewer_pages_array_count(report_html):
    span = viewer_pages_array_span(report_html)
    if not span:
        return 0
    array_text = report_html[span[0]:span[1]]
    return len(re.findall(r"[\"']?src[\"']?\s*:\s*[\"'][^\"']+[\"']", array_text))


def is_manifest_driven_report(source, report_html, *, read_json_file):
    if not source:
        return False
    root = source.parent.parent if source.parent.name == "report" else source.parent
    manifest = read_json_file(root / "manifest.json")
    if manifest.get("navigation_mode") == "single-slide-viewer" or isinstance(manifest.get("pages"), list):
        return True
    return "const pages = [" in report_html and re.search(r"\bsrc\s*:\s*[\"']pages/", report_html)


def manifest_page_id(page_item, index, *, slugify):
    modal_hash = str(page_item.get("modal_hash") or "").strip().lstrip("#")
    if modal_hash:
        return modal_hash
    rel = str(page_item.get("control_path") or page_item.get("path") or f"page-{index + 1}").strip()
    return slugify(Path(rel).parent.name or f"page-{index + 1}")


def build_viewer_pages_from_manifest(manifest, *, safe_int, slugify):
    pages = []
    for index, item in enumerate(manifest.get("pages") or []):
        if not isinstance(item, dict):
            continue
        rel = str(item.get("control_path") or item.get("path") or "").strip()
        if not rel:
            continue
        display_page = safe_int(item.get("display_page"), index + 1) or index + 1
        page = {
            "id": manifest_page_id(item, index, slugify=slugify),
            "label": f"Page {display_page:02d}",
            "title": str(item.get("title") or f"第 {display_page} 页").strip(),
            "code": str(item.get("control_asset_code") or item.get("asset_code") or "").strip(),
            "src": rel,
        }
        chapter = str(item.get("chapter") or "").strip()
        if chapter:
            page["chapter"] = chapter
        role = str(item.get("role") or "").strip()
        if role:
            page["role"] = role
        pages.append(page)
    return pages


def sync_manifest_viewer_pages(source, *, read_json_file, safe_int, slugify):
    if not source or not source.exists():
        return {"updated": False, "reason": "source-missing", "pageCount": 0, "viewerPageCount": 0}
    root = source.parent.parent if source.parent.name == "report" else source.parent
    manifest = read_json_file(root / "manifest.json")
    manifest_pages = manifest.get("pages") if isinstance(manifest.get("pages"), list) else []
    if not manifest_pages:
        return {"updated": False, "reason": "manifest-pages-missing", "pageCount": 0, "viewerPageCount": 0}
    report_html = source.read_text(encoding="utf-8", errors="ignore")
    span = viewer_pages_array_span(report_html)
    if not span:
        return {"updated": False, "reason": "viewer-pages-missing", "pageCount": len(manifest_pages), "viewerPageCount": 0}
    pages = build_viewer_pages_from_manifest(manifest, safe_int=safe_int, slugify=slugify)
    page_json = json.dumps(pages, ensure_ascii=False, indent=6)
    replacement = "const pages = " + page_json.replace("\n", "\n    ") + ";"
    new_html = f"{report_html[:span[0]]}{replacement}{report_html[span[1]:]}"
    new_html = re.sub(
        r'(<span class="page-count">)\s*1\s*/\s*\d+\s*(</span>)',
        rf"\g<1>1 / {len(pages)}\g<2>",
        new_html,
        count=1,
    )
    if new_html == report_html:
        return {"updated": False, "reason": "already-current", "pageCount": len(pages), "viewerPageCount": len(pages)}
    source.write_text(new_html, encoding="utf-8")
    return {"updated": True, "reason": "viewer-pages-synced", "pageCount": len(pages), "viewerPageCount": len(pages)}


def detect_report_page_count(source, *, read_json_file, safe_int):
    if not source or not source.exists():
        return 0
    roots = [source.parent]
    if source.parent.name == "report":
        roots.append(source.parent.parent)
    for root in roots:
        manifest = read_json_file(root / "manifest.json")
        if isinstance(manifest.get("pages"), list):
            return len(manifest["pages"])
        legacy = read_json_file(root / "asset-manifest.json")
        if isinstance(legacy.get("controls"), list):
            return len(legacy["controls"])
        if safe_int(legacy.get("slides"), 0):
            return safe_int(legacy.get("slides"), 0)
    try:
        html = source.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    iframe_count = len(re.findall(r"<iframe\b", html, re.IGNORECASE))
    if iframe_count:
        return iframe_count
    return len(extract_page_nodes(html))


def extract_head(html):
    match = re.search(r"<head\b[^>]*>.*?</head>", html, re.IGNORECASE | re.DOTALL)
    if match:
        head = match.group(0)
    else:
        head = '<head><meta charset="utf-8"></head>'
    control_style = """
<style>
  html, body { margin: 0; width: 100%; height: 100%; background: #000; overflow: hidden; }
  .material-control-stage {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: auto;
    width: 1280px;
    height: 720px;
    max-width: 100vw;
    max-height: 100vh;
    max-height: 100dvh;
    overflow: hidden;
    background: #000;
    --fs-scale: 0.6666667;
  }
  .material-control-stage > .deck[data-material-control-deck] {
    position: absolute !important;
    inset: 0 !important;
    width: 100% !important;
    height: 100% !important;
    overflow: hidden !important;
  }
  .material-control-stage > .deck[data-material-control-deck] .slide-frame {
    position: absolute !important;
    inset: 0 !important;
    width: 100% !important;
    height: 100% !important;
    aspect-ratio: auto !important;
  }
  .material-control-stage .slide-frame:first-child,
  .material-control-stage .slide-frame.is-current {
    opacity: 1 !important;
    pointer-events: auto !important;
    content-visibility: visible !important;
  }
  .material-control-stage > .deck[data-material-control-deck] .slide-frame .slide {
    position: absolute !important;
    top: 0 !important;
    left: 0 !important;
    margin: 0 !important;
    width: 1920px !important;
    height: 1080px !important;
    transform: scale(var(--fs-scale, 0.6666667)) translateZ(0) !important;
    transform-origin: top left !important;
  }
  .material-control-stage .slide-frame.is-current .slide,
  .material-control-stage .slide-frame.is-current .slide * {
    animation: none !important;
    transition: none !important;
  }
  /* Decks that use fs-reveal start direct slide children at opacity: 0.
     A standalone material deliberately disables motion, so restore their
     final visual state instead of leaving the page body transparent. */
  .material-control-stage .slide-frame.is-current .slide > * {
    opacity: 1 !important;
    transform: none !important;
  }
</style>
"""
    return head.replace("</head>", f"{control_style}</head>", 1)


def extract_body_scripts(html):
    body_match = re.search(r"<body\b[^>]*>(?P<body>.*?)</body>", html, re.IGNORECASE | re.DOTALL)
    body = body_match.group("body") if body_match else html
    scripts = re.findall(r"<script\b[^>]*>.*?</script>", body, re.IGNORECASE | re.DOTALL)
    filtered = []
    for script in scripts:
        src_match = re.search(r'\bsrc=["\']([^"\']+)["\']', script, re.IGNORECASE)
        src = src_match.group(1) if src_match else ""
        if src.endswith("assets/feishu-deck.js") or src.endswith("assets/edit-mode/deck-edit-mode.js"):
            continue
        # Imported decks can embed their editor runtime as an inline script. It
        # mutates every slide-frame and is not part of the presentation itself.
        if not src and ("enterEditMode" in script or "deck-edit-mode" in script):
            continue
        filtered.append(script)
    return "\n".join(filtered)


def build_control_html(report_html, page_html, title):
    lang_match = re.search(r"<html\b[^>]*lang=[\"']([^\"']+)[\"']", report_html, re.IGNORECASE)
    lang = lang_match.group(1) if lang_match else "zh-CN"
    head = extract_head(report_html)
    scripts = extract_body_scripts(report_html)
    page_html = re.sub(r'(<(?:div|section|article)\b[^>]*class=["\'][^"\']*\bslide-frame\b)([^"\']*)(["\'])', r'\1 is-current\2\3', page_html, count=1, flags=re.IGNORECASE)
    return f"""<!doctype html>
<html lang="{lang}">
{head}
<body>
  <main class="material-control-stage" data-material-control="true">
    <div class="deck" data-mode="present" data-material-control-deck="true" aria-label="{title}">
{page_html}
    </div>
  </main>
{scripts}
</body>
</html>
"""
