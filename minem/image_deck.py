"""Split image-based presentations into independently playable page packages."""

from __future__ import annotations

import base64
import binascii
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

from minem.html_assets import IMAGE_EXTENSIONS, INLINE_IMAGE


DECK_DATA = re.compile(r"<script\b[^>]*>\s*\(\(\)=>\{const images\s*=")


def read_image_deck(document):
    match = DECK_DATA.search(document)
    if not match:
        return None
    decoder = json.JSONDecoder()

    def read_value(position):
        while position < len(document) and document[position].isspace():
            position += 1
        return decoder.raw_decode(document, position)

    images, end = read_value(match.end())
    media_label = re.match(r"\s*,\s*media\s*=", document[end:])
    if not media_label:
        raise ValueError("图片汇报缺少媒体清单")
    media, end = read_value(end + media_label.end())
    base_label = re.match(r"\s*,\s*videoBase\s*=", document[end:])
    if not base_label:
        raise ValueError("图片汇报缺少媒体地址")
    base, end = read_value(end + base_label.end())
    if not isinstance(images, list) or not images or not isinstance(media, dict) or not isinstance(base, str):
        raise ValueError("图片汇报清单格式不受支持")
    if any(not isinstance(item, str) or not INLINE_IMAGE.fullmatch(item) for item in images):
        raise ValueError("图片汇报含缺失或不受支持的页面图片")
    if any(not key.isascii() or not key.isdigit() or not 1 <= int(key) <= len(images) or not isinstance(value, list)
           for key, value in media.items()):
        raise ValueError("图片汇报的视频页码无效")
    if "video.dataset.src=videoBase+item.file" not in document[end:]:
        raise ValueError("图片汇报播放脚本与媒体清单不匹配")
    return match.end(), end, images, media, base


def media_reference(entry, root, asset_dir, base, file_name, number):
    reference = urljoin(base, file_name)
    url = urlsplit(reference)
    if url.scheme in {"https", "http"} and url.netloc:
        # A supplied local copy takes precedence over the original online URL.
        local_path = unquote(urlsplit(file_name).path)
        candidates = [entry.parent / local_path, root / local_path, root / "media" / Path(local_path).name]
    elif not url.scheme and not url.netloc:
        path = unquote(url.path)
        candidates = [entry.parent / path, root / path, root / Path(path).name]
    else:
        raise ValueError("图片汇报含不受支持的视频地址")
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            target = asset_dir / f"video-{number:02d}" / candidate.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate, target)
            return quote(target.relative_to(asset_dir.parent).as_posix(), safe="/")
    if url.scheme in {"https", "http"}:
        return reference
    raise ValueError(f"图片汇报缺少视频文件 {file_name[:120]}")


def prepare_image_deck(root, make_viewer):
    """Return a report manifest when the source provides an image-deck contract."""
    root = root.resolve()
    if (root / "manifest.json").is_file() or (root / "asset-manifest.json").is_file():
        return None
    candidates = [p for p in root.rglob("*") if p.suffix.lower() in {".html", ".htm"} and p.is_file()]
    for entry in sorted(candidates):
        document = entry.read_text(encoding="utf-8-sig", errors="replace")
        parsed = read_image_deck(document)
        if parsed:
            break
    else:
        return None
    start, end, images, media, base = parsed
    title_match = re.search(r"<title\b[^>]*>(.*?)</title>", document, re.I | re.S)
    title = html.unescape(title_match[1]).strip() if title_match else entry.stem
    pages = []
    viewer_pages = []
    for number, source in enumerate(images, 1):
        page_dir = root / "owned-pages" / f"page-{number:03d}"
        assets = page_dir / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        image = INLINE_IMAGE.fullmatch(source)
        image_name = "slide" + IMAGE_EXTENSIONS[image["format"].lower()]
        try:
            (assets / image_name).write_bytes(base64.b64decode("".join(image["payload"].split()), validate=True))
        except binascii.Error as error:
            raise ValueError(f"第 {number} 页图片数据损坏") from error
        resources = [f"assets/{image_name}"]
        page_media = []
        for index, item in enumerate(media.get(str(number), []), 1):
            if not isinstance(item, dict) or not isinstance(item.get("file"), str) or not item["file"]:
                raise ValueError(f"第 {number} 页视频信息无效")
            url = media_reference(entry, root, assets, base, item["file"], index)
            page_media.append({**item, "file": url})
            resources.append(url)
        page_title = f"第 {number} 页"
        metadata = {"format": "minem-owned-page", "title": page_title, "sourcePage": number, "resources": resources}
        (page_dir / "manifest.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        declarations = json.dumps([resources[0]], ensure_ascii=False)
        declarations += ",media=" + json.dumps({"1": page_media}, ensure_ascii=False).replace("<", "\\u003c")
        declarations += ',videoBase=""'
        tail = document[end:]
        # Preserve author CSS, video geometry, autoplay and click-to-fullscreen.
        # The new document has one slide, so page labels and author-specific
        # border rules still refer to its position in the original document.
        tail = tail.replace("'第 '+(i+1)+' 页'", "'第 '+" + str(number) + "+' 页'")
        tail = tail.replace("else if(i+1>=24)", f"else if({number}>=24)")
        tail = tail.replace("video.dataset.src=videoBase+item.file", "video.dataset.src=item.file")
        tail = tail.replace("wrap.append(video,sound)", "video.onclick=()=>{if(video.paused)video.play().catch(()=>{});};wrap.append(video,sound)")
        tail = tail.replace("video.oncanplay=", "video.onerror=()=>{wrap.classList.remove('playing');wrap.title='视频无法加载，请检查源文件或链接';};video.oncanplay=")
        page = document[:start] + declarations + tail
        # References in a template are inert in the browser and visible to the
        # standard dependency collector during individual/report exports.
        links = "".join(f'<a href="{html.escape(link, quote=True)}"></a>' for link in [*resources, "manifest.json"])
        page = re.sub(r"</body\s*>", lambda _: f'<template data-minem-page-resources>{links}</template></body>', page, count=1, flags=re.I)
        page = re.sub(r"</head\s*>", '<style>.bar,.tip,.progress{display:none!important}</style></head>', page, count=1, flags=re.I)
        (page_dir / "index.html").write_text(page, encoding="utf-8")
        relative = page_dir.relative_to(root).as_posix()
        pages.append({"display_page": number, "title": page_title, "path": relative + "/index.html",
                      "preview_url": relative + "/" + resources[0]})
        viewer_pages.append({"title": page_title, "src": relative + "/index.html"})

    (root / "index.html").write_text(make_viewer(title, viewer_pages), encoding="utf-8")
    manifest = {"asset_type": "report", "format": "image-deck", "title": title, "entry": "index.html",
                "preview_url": pages[0]["preview_url"], "pages": pages}
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest
