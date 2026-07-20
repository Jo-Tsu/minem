import hashlib
import re
import shutil
from pathlib import Path

from .paths import is_path_within


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_download_name(value):
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "material"


def page_number_from_slide_path(path):
    match = re.search(r"slide[-_]?(\d+)", Path(path).as_posix(), re.IGNORECASE)
    return int(match.group(1)) if match else 0


def report_code_to_control_code(report_code, page_number):
    if report_code and report_code.startswith("RPT-"):
        stem = report_code.removeprefix("RPT-")
        return f"CTRL-{stem}-{page_number:03d}"
    return ""


def variant_page_rel(source_rel, variant, digest):
    source = Path(source_rel)
    token = safe_download_name(f"{variant}-{source.parent.name if source.parent.name else source.stem}-{digest[:10]}")
    if source.name.lower() in {"index.html", "index.htm"} and source.parent.as_posix() not in {"", "."}:
        return (source.parent.parent / token / source.name).as_posix()
    suffix = source.suffix or ".html"
    return (source.parent / f"{safe_download_name(source.stem)}-{variant}-{digest[:10]}{suffix}").as_posix()


def copy_page_variant(extract_root, source_rel, variant, source_hash):
    extract_root = Path(extract_root)
    source = (extract_root / source_rel).resolve()
    root = extract_root.resolve()
    if not is_path_within(source, root) or not source.exists():
        return None, ""
    target_rel = variant_page_rel(source_rel, variant, hashlib.sha1(source_hash.encode("utf-8")).hexdigest())
    target = (extract_root / target_rel).resolve()
    if not is_path_within(target, root):
        return None, ""
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.name.lower() in {"index.html", "index.htm"} and source.parent != extract_root:
        if target.parent.exists():
            shutil.rmtree(target.parent)
        shutil.copytree(source.parent, target.parent)
    else:
        shutil.copyfile(source, target)
    return target, target_rel


def load_report_package_manifest(extract_root, *, read_json_file):
    extract_root = Path(extract_root)
    legacy_path = extract_root / "asset-manifest.json"
    if legacy_path.exists():
        return read_json_file(legacy_path), "legacy"
    report_path = extract_root / "manifest.json"
    if report_path.exists():
        manifest = read_json_file(report_path)
        if manifest.get("asset_type") == "report" or isinstance(manifest.get("pages"), list):
            return manifest, "report"
    if (extract_root / "report" / "index.html").exists() or any((extract_root / "controls").glob("slide-*/index.html")):
        return {}, "legacy"

    # A downloaded Deck is commonly a self-contained HTML file, but its ZIP can
    # also carry supporting demos and prototypes. Detect the shallowest deck
    # entry with multiple slide roots instead of requiring the entire package
    # to contain exactly one HTML file.
    html_files = sorted(
        path for path in extract_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".html", ".htm"}
        and "_minem_pages" not in path.relative_to(extract_root).parts
    )
    inline_candidates = []
    for inline_html in html_files:
        try:
            content = inline_html.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        slide_frames = len(re.findall(r'<(?:div|section|article)\b[^>]*\bslide-frame\b', content, re.IGNORECASE))
        slide_nodes = len(re.findall(r'<(?:div|section|article)\b[^>]*\bdata-(?:slide|page)\b', content, re.IGNORECASE))
        is_deck = bool(re.search(r'<meta\b[^>]*\bfs-deck-generator\b', content, re.IGNORECASE) or slide_frames)
        if is_deck and max(slide_frames, slide_nodes) > 1:
            rel = inline_html.relative_to(extract_root)
            inline_candidates.append((
                len(rel.parts),
                0 if inline_html.name.lower() in {"index.html", "index.htm"} else 1,
                -max(slide_frames, slide_nodes),
                rel.as_posix(),
                inline_html,
                content,
            ))
    if inline_candidates:
        _, _, _, entry, inline_html, content = min(inline_candidates)
        title_match = re.search(r"<title\b[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else inline_html.stem.replace("-", " ")
        return {"entry": entry, "title": title}, "html-report"

    if (extract_root / "index.html").exists():
        package_manifest = read_json_file(extract_root / "package-manifest.json")
        deck_manifest = read_json_file(extract_root / "deck.json")
        html_entries = [
            path
            for path in extract_root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".html", ".htm"}
            and path.name.lower() in {"index.html", "index.htm", "page.html", "slide.html"}
        ]
        package_pages = package_manifest.get("pages") if isinstance(package_manifest.get("pages"), list) else []
        deck_slides = deck_manifest.get("slides") if isinstance(deck_manifest.get("slides"), list) else []
        has_explicit_report_contract = bool(
            package_manifest.get("asset_type") == "report"
            or len(package_pages) > 1
            or len(deck_slides) > 1
        )
        if len(html_entries) > 1 and not has_explicit_report_contract:
            return {}, ""
        # A generated deck with one slide is a reusable page material, not a
        # complete report. The scanner will store it as a control asset.
        if not has_explicit_report_contract:
            return {}, ""
        deck_title = ""
        if isinstance(deck_manifest.get("deck"), dict):
            deck_title = deck_manifest.get("deck", {}).get("title") or ""
        elif isinstance(deck_manifest.get("deck"), str):
            deck_title = deck_manifest.get("deck") or ""
        return {
            **package_manifest,
            "entry": package_manifest.get("entry") or "index.html",
            "title": package_manifest.get("title") or deck_title or package_manifest.get("deck") or "",
        }, "html-report"
    return {}, ""


def report_package_entry_path(extract_root, manifest, manifest_kind):
    extract_root = Path(extract_root)
    entry = str(manifest.get("entry") or "").strip()
    candidates = []
    if entry:
        candidates.append(entry)
    if manifest_kind == "legacy":
        candidates.extend(["report/index.html", "index.html"])
    else:
        candidates.extend(["index.html", "report/index.html"])
    for candidate in candidates:
        path = extract_root / candidate
        if path.exists() and path.is_file():
            return path, Path(candidate).as_posix()
    return None, ""


def report_manifest_page_items(extract_root, manifest, manifest_kind, *, read_json_file, merge_tags):
    extract_root = Path(extract_root)
    if manifest_kind == "report" and isinstance(manifest.get("pages"), list):
        items = []
        for index, item in enumerate(manifest.get("pages") or []):
            if not isinstance(item, dict):
                continue
            rel = str(item.get("control_path") or item.get("path") or "").strip()
            if not rel:
                continue
            html_path = extract_root / rel
            if not html_path.exists():
                continue
            display_page = safe_int(item.get("display_page"), index + 1) or index + 1
            page_manifest = read_json_file(html_path.parent / "manifest.json")
            items.append({
                "path": html_path,
                "rel": rel,
                "page": display_page,
                "title": page_manifest.get("title") or item.get("title") or f"第 {display_page} 页",
                "role": page_manifest.get("role") or item.get("role") or "",
                "tags": merge_tags(item.get("tags") or [], page_manifest.get("tags") or []),
                "source_code": item.get("control_asset_code") or page_manifest.get("asset_code") or "",
                "preview": item.get("preview_url") or page_manifest.get("preview_url") or "",
                "note": item.get("update_note") or page_manifest.get("notes") or "",
            })
        return sorted(items, key=lambda item: item["page"])

    controls_by_page = {}
    manifest_controls = manifest.get("controls") if isinstance(manifest.get("controls"), list) else []
    for item in manifest_controls:
        if not isinstance(item, dict):
            continue
        page = safe_int(item.get("page") or item.get("page_number"), 0)
        if page and item.get("path"):
            controls_by_page[page] = item

    items = []
    for control_html in sorted((extract_root / "controls").glob("slide-*/index.html")):
        page_number = page_number_from_slide_path(control_html.parent)
        if not page_number:
            continue
        rel = control_html.relative_to(extract_root).as_posix()
        info = controls_by_page.get(page_number, {})
        ingestion = read_json_file(control_html.parent / "ingestion-manifest.json")
        items.append({
            "path": control_html,
            "rel": rel,
            "page": page_number,
            "title": ingestion.get("title") or info.get("title") or f"{page_number:02d} 汇报页面",
            "role": ingestion.get("role") or info.get("role") or "",
            "tags": merge_tags(ingestion.get("tags") or [], info.get("tags") or []),
            "source_code": ingestion.get("asset_code") or info.get("asset_code") or "",
            "preview": info.get("preview_url") or "",
            "note": ingestion.get("notes") or info.get("note") or "",
        })
    return items


def discover_report_package_roots(extracted_dir, conn, *, load_manifest):
    extracted_dir = Path(extracted_dir)
    if not extracted_dir.exists():
        return []
    package_roots = {
        manifest_path.parent
        for pattern in ("*/asset-manifest.json", "*/manifest.json")
        for manifest_path in extracted_dir.glob(pattern)
    }
    for row in conn.execute("select distinct upload_id from assets where asset_type = 'report' and upload_id != ''").fetchall():
        root = extracted_dir / row["upload_id"]
        if root.exists():
            package_roots.add(root)
    for row in conn.execute("select id from uploads").fetchall():
        root = extracted_dir / row["id"]
        if root.exists() and load_manifest(root)[1]:
            package_roots.add(root)
    return sorted(package_roots)
