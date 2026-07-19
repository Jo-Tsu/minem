import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from .paths import is_path_within


def _preview_source_text(html_path):
    html_path = Path(html_path)
    try:
        html = html_path.read_text(encoding="utf-8", errors="ignore")[:1_000_000]
    except OSError:
        return ""
    chunks = [html]
    for href in re.findall(r'<link\b[^>]*href=["\']([^"\']+\.css(?:\?[^"\']*)?)["\']', html, re.I)[:16]:
        parsed = urlparse(href)
        if parsed.scheme or parsed.netloc:
            continue
        rel = unquote(parsed.path or "")
        if not rel or rel.startswith("/"):
            continue
        css_path = (html_path.parent / rel).resolve()
        if not is_path_within(css_path, html_path.parent) or not css_path.exists() or not css_path.is_file():
            continue
        try:
            chunks.append(css_path.read_text(encoding="utf-8", errors="ignore")[:500_000])
        except OSError:
            continue
    return "\n".join(chunks)


def _valid_preview_size(raw_width, raw_height):
    try:
        width = int(round(float(raw_width)))
        height = int(round(float(raw_height)))
    except (TypeError, ValueError):
        return None
    if not (320 <= width <= 8000 and 240 <= height <= 6000):
        return None
    ratio = width / height
    return (width, height) if 0.2 <= ratio <= 8 else None


def detect_html_dimensions(html_path):
    source = _preview_source_text(html_path)
    if not source:
        return 1920, 1080
    dimension_patterns = [
        r"const\s+DESIGN_W\s*=\s*([0-9.]+)\s*;\s*const\s+DESIGN_H\s*=\s*([0-9.]+)",
        r"const\s+DESIGN_WIDTH\s*=\s*([0-9.]+)\s*;\s*const\s+DESIGN_HEIGHT\s*=\s*([0-9.]+)",
        r"\.material-control-stage\s*\{[^}]*width\s*:\s*([0-9.]+)px(?:\s*!important)?\s*;[^}]*height\s*:\s*([0-9.]+)px",
        r"\.slide-viewport\s*\{[^}]*width\s*:\s*calc\(\s*([0-9.]+)px[^;]*;[^}]*height\s*:\s*calc\(\s*([0-9.]+)px",
        r"\.(?:slide-shell|lvg-slide|ls-slide-inner)\s*\{[^}]*width\s*:\s*([0-9.]+)px[^}]*height\s*:\s*([0-9.]+)px",
        r"\.slide-frame\s+\.slide\s*\{[^}]*width\s*:\s*([0-9.]+)px[^}]*height\s*:\s*([0-9.]+)px",
        r"\.slide\s*\{[^}]*width\s*:\s*([0-9.]+)px[^}]*height\s*:\s*([0-9.]+)px",
    ]
    for pattern in dimension_patterns:
        match = re.search(pattern, source, re.I | re.S)
        if match:
            size = _valid_preview_size(match.group(1), match.group(2))
            if size:
                return size

    ratio_patterns = [
        r"\.(?:material-control-stage|slide-viewport|slide-frame|stage)\s*\{[^}]*aspect-ratio\s*:\s*([0-9.]+)\s*/\s*([0-9.]+)",
        r"\.(?:material-control-stage|slide-viewport|slide-frame|stage)\s*\{[^}]*aspect-ratio\s*:\s*([0-9.]+)",
    ]
    for pattern in ratio_patterns:
        match = re.search(pattern, source, re.I | re.S)
        if not match:
            continue
        try:
            ratio = float(match.group(1)) / float(match.group(2)) if match.lastindex == 2 else float(match.group(1))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if 0.25 <= ratio <= 6:
            return 1920, max(320, min(6000, int(round(1920 / ratio))))
    return 1920, 1080


def detect_html_aspect_ratio(html_path):
    width, height = detect_html_dimensions(html_path)
    return width / height if width > 0 and height > 0 else 16 / 9


def detect_html_viewport(html_path):
    width, height = detect_html_dimensions(html_path)
    return width, max(480, min(4000, height))


def save_contained_thumbnail(source_image, output_path, html_path, *, image_module):
    if not image_module:
        return False
    image = image_module.open(source_image).convert("RGB")
    ratio = detect_html_aspect_ratio(html_path)
    if ratio > 0 and image.width > 0:
        expected_height = int(round(image.width / ratio))
        if 0 < expected_height < image.height * 0.96:
            image = image.crop((0, 0, image.width, expected_height))
    canvas_w, canvas_h = 1280, 720
    canvas = image_module.new("RGB", (canvas_w, canvas_h), "#0b1020")
    image.thumbnail((canvas_w, canvas_h), image_module.LANCZOS)
    left = (canvas_w - image.width) // 2
    top = (canvas_h - image.height) // 2
    canvas.paste(image, (left, top))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return True


def nearby_preview_image(html_path):
    candidates = [
        html_path.with_name("preview.png"),
        html_path.with_name("preview.jpg"),
        html_path.with_name("preview.jpeg"),
        html_path.with_name("poster.png"),
        html_path.with_name("cover.png"),
        html_path.parent / "assets" / "poster.png",
        html_path.parent / "assets" / "preview.png",
        html_path.parent / "assets" / "cover.png",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def thumbnail_is_low_variance(path, *, image_module):
    if not image_module or not path.exists():
        return True
    try:
        image = image_module.open(path).convert("RGB").resize((64, 36))
        return sum(high - low for low, high in image.getextrema()) < 20
    except Exception:
        return True


def chrome_path():
    candidates = [
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return ""


def capture_html_with_chrome(html_path, output_path, *, image_module):
    chrome = chrome_path()
    if not chrome or not image_module:
        return False
    width, height = detect_html_viewport(html_path)
    with tempfile.TemporaryDirectory(prefix="minem-html-thumb-") as temp_dir:
        screenshot = Path(temp_dir) / "screenshot.png"
        command = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--hide-scrollbars",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-pings",
            "--no-sandbox",
            "--force-prefers-reduced-motion=reduce",
            "--virtual-time-budget=5000",
            "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE localhost, EXCLUDE 127.0.0.1",
            f"--window-size={width},{height}",
            f"--screenshot={screenshot}",
            Path(html_path).resolve().as_uri(),
        ]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=24,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0 or not screenshot.exists() or screenshot.stat().st_size < 1000:
            return False
        save_contained_thumbnail(screenshot, output_path, html_path, image_module=image_module)
        return not thumbnail_is_low_variance(output_path, image_module=image_module)


def load_preview_font(size, *, image_font_module):
    if not image_font_module:
        return None
    candidates = [
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        try:
            return image_font_module.truetype(candidate, size)
        except Exception:
            continue
    return image_font_module.load_default()


def wrapped_lines(draw, text, font, max_width, max_lines):
    chars = list(text or "")
    lines = []
    current = ""
    for char in chars:
        trial = current + char
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
            continue
        lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len("".join(lines)) < len(text or ""):
        lines[-1] = lines[-1].rstrip("，。、；; ") + "..."
    return lines


def extract_preview_text(html_path, *, read_text_sample):
    text_path = html_path.parent / "texts.md"
    if text_path.exists():
        raw = text_path.read_text(encoding="utf-8", errors="ignore")
        lines = [line.strip(" -#\t") for line in raw.splitlines() if line.strip(" -#\t")]
        if lines:
            return lines[0], lines[1:7]
    html = read_text_sample(html_path, 300000)
    title_match = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else html_path.stem
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [line.strip() for line in re.split(r"\s{2,}|[。！？!?]\s*", text) if line.strip()]
    return title, lines[:6]


def save_text_thumbnail(
    output_path,
    html_path,
    *,
    image_module,
    image_draw_module,
    image_font_module,
    read_text_sample,
):
    if not image_module or not image_draw_module:
        return False
    canvas_w, canvas_h = 1280, 720
    canvas = image_module.new("RGB", (canvas_w, canvas_h), "#0b1020")
    draw = image_draw_module.Draw(canvas)
    title, lines = extract_preview_text(html_path, read_text_sample=read_text_sample)
    ratio = detect_html_aspect_ratio(html_path)
    content_h = int(canvas_w / ratio) if ratio > 16 / 9 else canvas_h
    content_h = max(320, min(canvas_h, content_h))
    top = (canvas_h - content_h) // 2
    draw.rectangle((0, top, canvas_w, top + content_h), fill="#10192d")
    draw.rectangle((0, top, canvas_w, top + 6), fill="#2f75e8")
    title_font = load_preview_font(46, image_font_module=image_font_module)
    body_font = load_preview_font(24, image_font_module=image_font_module)
    meta_font = load_preview_font(18, image_font_module=image_font_module)
    x = 74
    y = top + 64
    draw.text((x, y), "HTML PREVIEW", fill="#7db7ff", font=meta_font)
    y += 44
    for line in wrapped_lines(draw, title, title_font, canvas_w - 148, 2):
        draw.text((x, y), line, fill="#f7f9ff", font=title_font)
        y += 58
    y += 12
    for line in lines[:5]:
        for wrapped in wrapped_lines(draw, line, body_font, canvas_w - 180, 1):
            draw.text((x + 18, y), wrapped, fill="#cbd6e8", font=body_font)
            draw.ellipse((x, y + 12, x + 6, y + 18), fill="#7db7ff")
            y += 36
        if y > top + content_h - 72:
            break
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return True


def generate_html_thumbnail(
    asset_id,
    html_path,
    *,
    thumbnails_dir,
    image_module,
    image_draw_module,
    image_font_module,
    read_text_sample,
    allow_text_fallback=True,
):
    html_path = Path(html_path)
    if not html_path.exists() or html_path.suffix.lower() not in {".html", ".htm"}:
        return False
    output_path = Path(thumbnails_dir) / f"{asset_id}.png"

    def fallback():
        if not allow_text_fallback:
            return False
        return bool(
            image_module
            and save_text_thumbnail(
                output_path,
                html_path,
                image_module=image_module,
                image_draw_module=image_draw_module,
                image_font_module=image_font_module,
                read_text_sample=read_text_sample,
            )
        )

    def use_nearby_preview():
        if not image_module:
            return False
        image_path = nearby_preview_image(html_path)
        if not image_path:
            return False
        return save_contained_thumbnail(image_path, output_path, html_path, image_module=image_module)

    try:
        if use_nearby_preview():
            return output_path.exists() and output_path.stat().st_size > 0
        if capture_html_with_chrome(html_path, output_path, image_module=image_module):
            return output_path.exists() and output_path.stat().st_size > 0
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                ["qlmanage", "-t", "-s", "1280", "-o", temp_dir, str(html_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                return fallback()
            candidates = sorted(Path(temp_dir).glob("*.png"))
            if not candidates:
                return fallback()
            if image_module:
                save_contained_thumbnail(candidates[0], output_path, html_path, image_module=image_module)
                if thumbnail_is_low_variance(output_path, image_module=image_module):
                    fallback()
            else:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidates[0], output_path)
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception:
        return fallback()


def generate_upload_thumbnails(upload_id, *, connect, extracted_dir, generate_thumbnail):
    created = 0
    with connect() as conn:
        rows = conn.execute(
            "select id, source_path from assets where upload_id = ? and asset_type in ('report', 'control')",
            (upload_id,),
        ).fetchall()
    upload_root = (Path(extracted_dir) / upload_id).resolve()
    for row in rows:
        html_path = (upload_root / row["source_path"]).resolve()
        if not is_path_within(html_path, upload_root):
            continue
        if generate_thumbnail(row["id"], html_path):
            created += 1
    return created
