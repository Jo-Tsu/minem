#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, parse_qs, quote, unquote, urlparse
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import cgi
from collections import defaultdict
from contextlib import contextmanager, nullcontext
import fcntl
import gzip
import hashlib
import html
import io
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

from minem.assets import list_assets_response, save_asset_metadata
from minem.agent import AgentRuntime
from minem.case_groups import load_case_groups
from minem.db import connect_database, initialize_database
from minem.html_splitter import (
    build_control_html,
    detect_report_page_count as split_detect_report_page_count,
    extract_control_page_node,
    extract_page_node_spans as split_page_node_spans,
    extract_page_nodes,
    is_manifest_driven_report as split_manifest_driven_report,
    replace_report_page_node,
    sync_manifest_viewer_pages as split_sync_manifest_viewer_pages,
    viewer_pages_array_count,
)
from minem.imports import (
    auto_import_sources as run_auto_import_sources,
    create_import_task as create_import_task_record,
    get_import_task as get_import_task_record,
    import_direct_file as import_direct_asset_file,
    import_zip_file as import_zip_archive,
    iter_import_candidates as iter_import_source_candidates,
    list_import_tasks as list_import_task_records,
    load_import_sources as load_import_source_config,
    runtime_record_path,
    run_import_task as execute_import_task,
    update_import_task as update_import_task_record,
)
from minem.html_assets import extract_bundle_images
from minem.http_requests import RequestBodyError, read_json_request, request_content_length
from minem.html_dependencies import DependencyParser, audit_dependency_closure, css_references, is_external, normalize_reference
from minem.drive_fonts import localize_drive_fonts
from minem.drive_import import DRIVE_DOWNLOAD_SECONDS, DRIVE_JOB_ID, DRIVE_QUEUE_SECONDS, MAX_DRIVE_LINKS, drive_import_queue, drive_worker_alive, parse_drive_folder_link, write_json_atomically
from minem.config import MAX_UPLOAD_REQUEST_BYTES, MAX_ZIP_FILES, MAX_ZIP_TOTAL_BYTES
from minem.offline_bundle import OfflineBundle, validate_offline_package
from minem.delivery import download_name, write_delivery_inventory
from minem.hosted_deck_media import MEDIA_DIRECTORY
from minem.native_deck import external_deck_base, read_native_deck, render_native_deck, resolve_deck_base
from minem.runtime_layout import history_root
from minem.import_tasks import ImportTaskStore
from minem.image_deck import prepare_image_deck
from minem.spark_package import UNPACKAGED_ERROR, has_online_spark_storage, spark_package_root
from minem.report_exports import ReportExportTaskStore
from minem.lineage import (
    asset_lineage_details as build_asset_lineage_details,
    attach_source_batches as hydrate_source_batches,
    pipeline_summary as build_pipeline_summary,
    upload_batch_summaries as summarize_upload_batches,
)
from minem.paths import is_path_within, is_safe_filename_stem
from minem.player_bridge import add_player_bridge
from minem.pdf_capture import add_pdf_checks, capture as capture_pdf_page
from minem.reports import (
    attach_report_page_control as attach_slot_control,
    get_report_page_slots as load_report_page_slots,
    normalize_page_numbers,
    register_report_page_candidate as register_slot_candidate,
    upsert_report_page_slots as save_report_page_slots,
)
from minem.report_package_importer import (
    copy_page_variant,
    discover_report_package_roots as import_discover_report_package_roots,
    html_document_title,
    load_report_package_manifest as import_load_report_package_manifest,
    report_code_to_control_code,
    report_manifest_page_items as import_report_manifest_page_items,
    report_package_entry_path,
    safe_int,
)
from minem.report_package_writer import sync_report_material_package as write_report_material_package
from minem.report_canvas import normalize_report_page_canvases as normalize_report_canvas_versions
from minem.resource_importer import sync_report_package_resources as write_report_package_resources
from minem.similarity import merge_similar_resource_versions as run_merge_similar_resource_versions
from minem.media import resource_kind_for as classify_resource_kind, split_tags
from minem.thumbnails import (
    chrome_path as preview_chrome_path,
    detect_html_dimensions as detected_html_preview_size,
    generate_html_thumbnail as render_html_thumbnail,
    save_contained_thumbnail as render_contained_thumbnail,
)
from minem.upload_safety import UploadLimitError, copy_limited_stream, safe_extract_zip

try:
    from PIL import Image, ImageDraw, ImageFont, ImageSequence
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageSequence = None

RESOURCE_ROOT = Path(os.environ.get("MINEM_APP_ROOT") or getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).expanduser().resolve()
RUNTIME_ROOT = Path(os.environ.get("MINEM_DATA_DIR") or RESOURCE_ROOT).expanduser().resolve()
ROOT = RESOURCE_ROOT
PUBLIC = RESOURCE_ROOT / "public"
REPORT_COVERS = RESOURCE_ROOT / "templates" / "report-covers"
DEFAULT_REPORT_COVER = "cover-1"
REPORT_COVER_IDS = frozenset((DEFAULT_REPORT_COVER, "cover-2", "cover-3"))
DATA = RUNTIME_ROOT / "data"
UPLOADS = RUNTIME_ROOT / "uploads"
EXTRACTED = RUNTIME_ROOT / "extracted"
THUMBNAILS = RUNTIME_ROOT / "thumbnails"
REPORT_EXPORTS = RUNTIME_ROOT / "report-exports"
LEGACY_HISTORY_DIR = EXTRACTED / "_history"
HISTORY_DIR = history_root(RUNTIME_ROOT) / "asset-snapshots"
DB_PATH = DATA / "materials.db"
AUTO_IMPORT_CONFIG = RUNTIME_ROOT / "import-sources.json"
VERSION_MANIFEST_PATH = RESOURCE_ROOT / "product-version.json"


def load_product_version():
    fallback = {"product": "MineM", "version": "0.0.0-dev", "channel": "unknown", "apiVersion": 1}
    try:
        payload = json.loads(VERSION_MANIFEST_PATH.read_text(encoding="utf-8"))
        return {**fallback, **payload}
    except (OSError, ValueError, TypeError):
        return fallback


PRODUCT_VERSION = load_product_version()
IMPORT_TASK_STORE = ImportTaskStore(DB_PATH)
REPORT_EXPORT_TASK_STORE = ReportExportTaskStore(DB_PATH)
AGENT_RUNTIME = AgentRuntime(ROOT, DATA)
THUMBNAIL_META_VERSION = 2
TEMP_REPORT_TTL_MS = 60 * 60 * 1000
TEMP_REPORT_STALE_MS = 15 * 1000
TEMP_REPORT_SESSIONS = {}
TEMP_REPORT_LOCK = threading.Lock()
INSTANCE_LOCK_HANDLE = None
THUMBNAIL_REFRESH_QUEUE = queue.Queue()
THUMBNAIL_REFRESH_ENQUEUED = set()
THUMBNAIL_REFRESH_FAILED = {}
THUMBNAIL_REFRESH_LOCK = threading.Lock()
THUMBNAIL_REFRESH_WORKER = None

ALLOWED_SUFFIXES = {".html", ".htm", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".m4v", ".webm"}
ZIP_SUFFIXES = {".zip"}
IMPORT_SUFFIXES = ALLOWED_SUFFIXES | ZIP_SUFFIXES
STATS_CACHE = {"payload": None, "expires_at": 0}
PREVIEW_META_CACHE = {}
RESOURCE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".m4v", ".webm"}
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def truthy_env(name, default="0"):
    return os.environ.get(name, default).strip().lower() in TRUTHY_ENV_VALUES


def agent_internal_api_enabled():
    return truthy_env("MINEM_AGENT_INTERNAL_API") or bool(os.environ.get("MINEM_AGENT_API_TOKEN", "").strip())


def agent_internal_api_token():
    return os.environ.get("MINEM_AGENT_API_TOKEN", "").strip()


def default_import_sources_from_env():
    raw = os.environ.get("MINEM_IMPORT_ROOTS", "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(os.pathsep) if part.strip()]


DEFAULT_IMPORT_SOURCES = default_import_sources_from_env()
DEFAULT_EXCLUDES = {
    ".git",
    "__pycache__",
    "node_modules",
    "minem",
    "deepagents-main",
}
EXCLUDED_FILE_KEYWORDS = {
    "deepagents-main",
    "node_modules",
}

CATEGORIES = {
    "report": "完整汇报",
    "page": "页面素材",
    "storytelling": "汇报结构",
    "proof": "证据与指标",
    "workflow": "流程与路径",
    "mock": "页面素材",
    "story": "叙事表达",
    "visual": "视觉素材",
    "code": "代码片段",
}

ASSET_TYPES = {
    "report": "汇报素材",
    "control": "页面素材",
    "resource": "资源素材",
}

PIPELINE_STAGES = [
    {
        "key": "report",
        "label": "汇报素材",
        "codePrefix": "RPT",
        "description": "一次完整汇报的原始成果，可继续导出 HTML、PDF 或 PPT。",
    },
    {
        "key": "control",
        "label": "页面素材",
        "codePrefix": "CTRL",
        "description": "从完整汇报拆出的单页素材，可按需拼接成新的 HTML 汇报。",
    },
    {
        "key": "resource",
        "label": "资源素材",
        "codePrefix": "RES",
        "description": "页面依赖的图片、Logo、图标、GIF 与视频等基础资源。",
    },
]

MEDIA_KINDS = {
    "image": "图片",
    "video": "视频",
    "gif": "GIF",
    "svg": "SVG",
    "code": "代码",
    "html": "HTML",
    "none": "无",
}

RESOURCE_KINDS = {
    "image": "图片",
    "logo": "Logo",
    "icon": "图标",
    "gif": "GIF",
    "video": "视频",
    "svg": "SVG",
    "other": "其他",
}

SOURCE_TYPES = {
    "auto": "自动扫描导入",
    "upload": "文件扫描导入",
    "template": "模板包导入",
    "slide-control-import": "汇报单页导入",
    "control-resource-import": "资源素材抽取",
    "manual-version-import": "手动版本导入",
    "report-material-sync": "汇报材料同步",
    "report-material-candidate": "汇报候选页",
    "created-report": "新建汇报",
}

CONTROL_CODE_PARTS = {
    "page": "PAGE",
    "storytelling": "PAGE",
    "proof": "PROOF",
    "workflow": "FLOW",
    "mock": "PAGE",
    "story": "STORY",
    "visual": "VIS",
    "code": "CODE",
}

SEED_ASSETS = []
CONTROL_TEMPLATE_REQUIRED = {"index.html", "ingestion-manifest.json", "deck.json", "assets-manifest.yaml"}


def slugify(value):
    value = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff._-]+", "-", value).strip("-")
    return value[:80] or f"asset-{int(time.time())}"


def now_ms():
    return int(time.time() * 1000)


@contextmanager
def db():
    conn = connect_database(DB_PATH, timeout=30)
    try:
        with conn:
            yield conn
    finally:
        conn.close()




def date_key():
    return time.strftime("%Y%m%d")


def media_kind_for(path):
    suffix = path.suffix.lower()
    if suffix == ".gif":
        return "gif"
    if suffix == ".svg":
        return "svg"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if suffix in {".mp4", ".mov", ".m4v", ".webm"}:
        return "video"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix in {".css", ".js", ".json", ".md"}:
        return "code"
    return "none"




def resource_kind_for(path, media_kind, title="", tags=""):
    return classify_resource_kind(path, media_kind, title, tags, image_module=Image, image_sequence_module=ImageSequence)


def is_page_level_html(path):
    probe = path.as_posix().lower()
    page_markers = ("slide", "page", "screen", "chapter", "section", "control", "component", "widget", "card", "片", "页", "页面", "组件")
    report_markers = ("index.html", "report", "deck", "presentation", "汇报", "材料")
    if any(marker in probe for marker in page_markers):
        return not any(marker in probe for marker in report_markers[:1])
    return False


def report_page_count_hint(text):
    value = text or ""
    labels = set(re.findall(r'"label"\s*:\s*"Page\s+\d+', value))
    if len(labels) > 1:
        return len(labels)
    frame_count = len(re.findall(r"data-page-index\s*=", value))
    if frame_count > 1:
        return frame_count
    match = re.search(r'page-count[^>]*>\s*1\s*/\s*(\d+)', value, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0


def is_report_entry_html(path, context=""):
    probe = f"{path.as_posix()} {context}".lower()
    page_count = report_page_count_hint(context)
    if "/pages/" in probe and page_count <= 1:
        return False
    if page_count > 1:
        return True
    if any(marker in probe for marker in ("report-material-library", "/30-report-")) and "/pages/" not in probe:
        if path.suffix.lower() in {".html", ".htm"}:
            return True
    if any(marker in probe for marker in ("完整汇报材料", "完整汇报")) and path.name.lower() in {"index.html", "index.htm"}:
        return True
    if "const pages" in probe and "slide-viewport" in probe and "iframe" in probe:
        return True
    return False


def asset_type_for(path, category, context=""):
    kind = media_kind_for(path)
    if kind in {"image", "video", "gif", "svg"}:
        return "resource"
    if kind == "html":
        if is_report_entry_html(path, context):
            return "report"
        if is_page_level_html(path):
            return "control"
        probe = path.as_posix().lower()
        if path.name.lower() in {"index.html", "index.htm", "report.html", "deck.html", "presentation.html"}:
            inline_slide_count = len(re.findall(r'<(?:div|section|article)\b[^>]*\bslide-frame\b', context, re.IGNORECASE))
            if "fs-deck-generator" in context.lower() and inline_slide_count <= 1:
                return "control"
            return "report"
        if any(marker in probe for marker in ("report", "deck", "presentation", "汇报", "材料")):
            return "report"
        return "control"
    return None


def code_prefix(asset_type, category, media_kind):
    if asset_type in {"report", "page"}:
        return f"RPT-{date_key()}"
    if asset_type == "resource":
        parts = {"image": "IMG", "video": "VID", "gif": "GIF", "svg": "SVG"}
        return f"RES-{parts.get(media_kind, 'FILE')}-{date_key()}"
    return f"CTRL-{CONTROL_CODE_PARTS.get(category, 'GEN')}"


def next_asset_code(conn, asset_type, category, media_kind):
    prefix = code_prefix(asset_type, category, media_kind)
    rows = conn.execute("select asset_code from assets where asset_code like ?", (f"{prefix}-%",)).fetchall()
    max_num = 0
    for row in rows:
        try:
            max_num = max(max_num, int(row["asset_code"].rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{prefix}-{max_num + 1:03d}"


def backfill_asset_codes(conn):
    rows = conn.execute("select id, category, asset_code from assets order by created_at, id").fetchall()
    for row in rows:
        if row["asset_code"]:
            continue
        category = row["category"]
        conn.execute(
            "update assets set asset_type = ?, asset_code = ?, media_kind = ? where id = ?",
            ("control", next_asset_code(conn, "control", category, "none"), "none", row["id"]),
        )


def init_db():
    if LEGACY_HISTORY_DIR.is_dir() and not LEGACY_HISTORY_DIR.is_symlink() and not HISTORY_DIR.exists():
        HISTORY_DIR.parent.mkdir(parents=True, exist_ok=True)
        LEGACY_HISTORY_DIR.rename(HISTORY_DIR)
    initialize_database(
        data_dir=DATA,
        uploads_dir=UPLOADS,
        extracted_dir=EXTRACTED,
        history_dir=HISTORY_DIR,
        thumbnails_dir=THUMBNAILS,
        connect=db,
        import_task_store=IMPORT_TASK_STORE,
        backfill_asset_codes=backfill_asset_codes,
        backfill_resource_kinds=backfill_resource_kinds,
        journal_mode=os.environ.get("SQLITE_JOURNAL_MODE", "wal"),
        on_warning=print,
    )
    REPORT_EXPORTS.mkdir(parents=True, exist_ok=True)
    REPORT_EXPORT_TASK_STORE.ensure_schema()
    # Reports are served through a stable public entry.  It composes their
    # existing page slots and makes future arrangement changes visible to both
    # newly opened and previously copied report links without modifying source
    # packages under extracted/.
    with db() as conn:
        interrupted = ("任务已中断", "服务重启中断了任务，请重新提交。", now_ms())
        active = conn.execute("select id from import_tasks where status in ('queued', 'running')").fetchall()
        queue_root = drive_import_queue(RUNTIME_ROOT)
        conn.executemany(
            "update import_tasks set status='failed', message=?, error=?, updated_at=? where id=?",
            [(*interrupted, row["id"]) for row in active if not (
                DRIVE_JOB_ID.fullmatch(row["id"]) and (queue_root / row["id"] / "job.json").is_file()
            )],
        )
        conn.execute(
            "update report_export_tasks set status='failed', progress=100, message=?, error=?, updated_at=? where status in ('queued', 'running')",
            interrupted,
        )
        conn.execute(
            """
            update assets
            set preview_url = '/reports/' || id || '/index.html'
            where asset_type = 'report'
              and exists (
                select 1 from report_page_slots slot
                where slot.report_id = assets.id and slot.control_id <> ''
              )
            """
        )
    reclassify_single_page_report_assets()
    # Existing reports are normalized once at startup as well. The operation
    # is idempotent and only creates a derived version when a slot's canvas
    # differs from the report canvas.
    with db() as conn:
        report_ids = [row["id"] for row in conn.execute(
            "select id from assets where asset_type = 'report' and exists (select 1 from report_page_slots slot where slot.report_id = assets.id and slot.control_id <> '')"
        ).fetchall()]
    for report_id in report_ids:
        try:
            normalize_report_page_canvases(report_id)
        except Exception as error:
            print(f"Report canvas normalization skipped for {report_id}: {error}")


def canonical_preview_url(data):
    data = dict(data)
    preview_url = data.get("preview_url") or ""
    # A confirmed arrangement has a stable public report entry.  Keep it as
    # the canonical URL instead of falling back to the imported source file.
    if preview_url.startswith("/extracted/_history/") or preview_url.startswith("/reports/"):
        return preview_url
    if data.get("asset_type") == "report" and data.get("source_type") == "created-report":
        return report_public_url(data["id"])
    upload_id = data.get("upload_id") or ""
    source_path = data.get("source_path") or ""
    if upload_id and source_path:
        path = EXTRACTED / upload_id / source_path
        if path.exists():
            return f"/extracted/{upload_id}/{source_path}"
    return preview_url


# Source packages occasionally carry their own deck navigation and utility bar.
# The platform shell is the sole owner of these controls while a page is embedded.
PREVIEW_EMBED_STYLE = """
<style id="minem-embedded-preview-style">
  #minem-page-tools, [data-minem-page-tools],
  body:has([data-material-control="true"]) :is(.page-pill,.slide-controls,.slide-navigation,
      .slide-nav,.deck-controls,.deck-navigation,.presentation-controls,[data-slide-navigation],[data-deck-navigation]) {
    display: none !important;
  }
  html[data-minem-player-paused] *, html[data-minem-player-paused] *::before,
  html[data-minem-player-paused] *::after { animation-play-state: paused !important; }
</style>
<script>
(() => {
  const frame = window.frameElement;
  if (!frame?.hasAttribute("data-player-page")) return;
  document.documentElement.toggleAttribute("data-minem-player-paused", frame.hidden);
  document.addEventListener("play", event => {
    if (frame.hidden) {
      event.target.dataset.minemPlayerResume = "1";
      event.target.pause();
    }
  }, true);
})();
</script>
"""


def inject_embedded_preview_style(html_text):
    if "minem-embedded-preview-style" in html_text:
        return add_player_bridge(html_text)
    marker = re.search(r"</head\s*>", html_text, flags=re.IGNORECASE)
    if marker:
        return add_player_bridge(f"{html_text[:marker.start()]}{PREVIEW_EMBED_STYLE}{html_text[marker.start():]}")
    return add_player_bridge(f"{PREVIEW_EMBED_STYLE}{html_text}")


def thumbnail_path(asset_id):
    return THUMBNAILS / f"{asset_id}.png"


def thumbnail_meta_path(asset_id):
    return THUMBNAILS / f"{asset_id}.json"


def local_html_preview_path(data):
    preview_url = canonical_preview_url(data)
    preview_path = unquote(urlparse(preview_url).path)
    if preview_path.startswith("/extracted/_history/"):
        html_path = history_snapshot_file(preview_path.removeprefix("/extracted/"))
    elif preview_path.startswith("/extracted/"):
        html_path = extracted_url_to_path(preview_path)
    elif preview_path.startswith("/reports/"):
        html_path = asset_library_path(data)
    else:
        return None
    if html_path and html_path.is_file() and html_path.suffix.lower() in {".html", ".htm"}:
        return html_path
    return None


def thumbnail_source_fingerprint(data):
    data = dict(data)
    preview_url = canonical_preview_url(data)
    parts = [
        "thumb-v2",
        str(data.get("source_hash") or ""),
        str(preview_url or ""),
        str(data.get("source_path") or ""),
    ]
    if data.get("asset_type") in {"report", "page"}:
        parts.append("arrangement:" + str(data.get("updated_at") or 0))
    html_path = local_html_preview_path({**dict(data), "preview_url": preview_url})
    if html_path:
        try:
            stat = html_path.stat()
            relative = html_path.relative_to(RUNTIME_ROOT).as_posix()
            parts.append(f"file:{relative}:{stat.st_size}:{stat.st_mtime_ns}")
        except (OSError, ValueError):
            pass
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def start_thumbnail_refresh_worker():
    global THUMBNAIL_REFRESH_WORKER
    with THUMBNAIL_REFRESH_LOCK:
        if THUMBNAIL_REFRESH_WORKER and THUMBNAIL_REFRESH_WORKER.is_alive():
            return
        THUMBNAIL_REFRESH_WORKER = threading.Thread(
            target=thumbnail_refresh_loop,
            name="minem-thumbnail-refresh",
            daemon=True,
        )
        THUMBNAIL_REFRESH_WORKER.start()


def enqueue_thumbnail_refresh(asset_id, html_path, source_fingerprint):
    if not asset_id or not html_path or not source_fingerprint:
        return
    key = f"{asset_id}:{source_fingerprint}"
    timestamp = now_ms()
    with THUMBNAIL_REFRESH_LOCK:
        failed_at = THUMBNAIL_REFRESH_FAILED.get(key, 0)
        if failed_at and timestamp - failed_at < 5 * 60 * 1000:
            return
        if key in THUMBNAIL_REFRESH_ENQUEUED:
            return
        THUMBNAIL_REFRESH_ENQUEUED.add(key)
    start_thumbnail_refresh_worker()
    THUMBNAIL_REFRESH_QUEUE.put((key, asset_id, str(html_path), source_fingerprint))


def thumbnail_refresh_loop():
    while True:
        key, asset_id, html_path, source_fingerprint = THUMBNAIL_REFRESH_QUEUE.get()
        success = False
        try:
            path = Path(html_path)
            if path.exists() and path.suffix.lower() in {".html", ".htm"}:
                success = generate_html_thumbnail(asset_id, path, source_fingerprint, allow_text_fallback=False)
        finally:
            with THUMBNAIL_REFRESH_LOCK:
                THUMBNAIL_REFRESH_ENQUEUED.discard(key)
                if success:
                    THUMBNAIL_REFRESH_FAILED.pop(key, None)
                else:
                    THUMBNAIL_REFRESH_FAILED[key] = now_ms()
                    if len(THUMBNAIL_REFRESH_FAILED) > 2048:
                        cutoff = now_ms() - 10 * 60 * 1000
                        for failed_key, failed_at in list(THUMBNAIL_REFRESH_FAILED.items()):
                            if failed_at < cutoff:
                                THUMBNAIL_REFRESH_FAILED.pop(failed_key, None)
            THUMBNAIL_REFRESH_QUEUE.task_done()


def thumbnail_meta_matches(asset_id, source_fingerprint=""):
    if not source_fingerprint:
        return True
    meta_path = thumbnail_meta_path(asset_id)
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if int(meta.get("version") or 0) != THUMBNAIL_META_VERSION:
        return False
    stored = str(meta.get("sourceFingerprint") or "")
    return not stored or stored == source_fingerprint


def write_thumbnail_meta(asset_id, source_fingerprint=""):
    if not source_fingerprint:
        return
    meta_path = thumbnail_meta_path(asset_id)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "version": THUMBNAIL_META_VERSION,
        "assetId": asset_id,
        "sourceFingerprint": source_fingerprint,
        "updatedAt": now_ms(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def thumbnail_url(asset_id, source_fingerprint=""):
    if not thumbnail_meta_matches(asset_id, source_fingerprint):
        return ""
    thumb = thumbnail_path(asset_id)
    try:
        version = thumb.stat().st_mtime_ns
    except FileNotFoundError:
        return ""
    return f"/thumbnails/{asset_id}.png?v={version}"


def asset_thumbnail_url(data):
    data = dict(data)
    fingerprint = thumbnail_source_fingerprint(data)
    url = thumbnail_url(data["id"], fingerprint)
    if url:
        return url
    html_path = local_html_preview_path(data)
    thumb = thumbnail_path(data["id"])
    if html_path and thumb.exists():
        try:
            if (not thumbnail_meta_path(data["id"]).exists()
                and thumb.stat().st_mtime_ns >= html_path.stat().st_mtime_ns
                and thumb.stat().st_mtime_ns >= int(data.get("updated_at") or 0) * 1_000_000):
                write_thumbnail_meta(data["id"], fingerprint)
                return thumbnail_url(data["id"], fingerprint)
        except OSError:
            pass
    if html_path and data.get("media_kind") == "html":
        enqueue_thumbnail_refresh(data["id"], html_path, fingerprint)
    return ""


def preview_meta_for_asset(data):
    preview_url = data.get("preview_url") or ""
    media_kind = data.get("media_kind") or ""
    if media_kind != "html" or not preview_url.startswith("/"):
        return {"width": 0, "height": 0, "aspectRatio": 0, "longPage": False}
    html_path = local_html_preview_path(data)
    if html_path is None:
        return {"width": 1920, "height": 1080, "aspectRatio": round(16 / 9, 6), "longPage": False}
    try:
        stat = html_path.stat()
    except OSError:
        return {"width": 1920, "height": 1080, "aspectRatio": round(16 / 9, 6), "longPage": False}
    cache_key = (str(html_path), stat.st_mtime_ns, stat.st_size)
    cached = PREVIEW_META_CACHE.get(cache_key)
    if cached:
        return cached
    width, height = detected_html_preview_size(html_path)
    meta = {
        "width": width,
        "height": height,
        "aspectRatio": round(width / height, 6) if height else 0,
        "longPage": bool(height and height / max(width, 1) > 1.35),
    }
    if len(PREVIEW_META_CACHE) > 512:
        PREVIEW_META_CACHE.clear()
    PREVIEW_META_CACHE[cache_key] = meta
    return meta


def row_to_asset(row):
    data = dict(row)
    data["snippet"] = ""
    data["categoryLabel"] = CATEGORIES.get(data["category"], data["category"])
    if data["asset_type"] == "page":
        data["asset_type"] = "report"
    data["preview_url"] = canonical_preview_url(data)
    data["typeLabel"] = ASSET_TYPES.get(data["asset_type"], data["asset_type"])
    data["mediaLabel"] = MEDIA_KINDS.get(data["media_kind"], data["media_kind"])
    data["resourceKindLabel"] = RESOURCE_KINDS.get(data.get("resource_kind") or "", data.get("resource_kind") or "")
    data["thumbnail_url"] = asset_thumbnail_url(data)
    if data["asset_type"] == "report" and data["media_kind"] == "html" and data["preview_url"].startswith("/reports/"):
        data["cover_preview_url"] = f"{report_public_url(data['id'])}?cover=1&v={data['updated_at'] or 0}"
    data["preview_meta"] = preview_meta_for_asset(data)
    data["tags"] = split_tags(data["tags"])
    data["versionCount"] = data.get("version_count", 1) or 1
    data["isPrimaryVersion"] = not data.get("version_parent_id")
    data["versionLabel"] = f"V{data.get('version_no', 1) or 1}"
    if data.get("asset_type") == "report" and data.get("trusted_checked_at"):
        data["trustedEntry"] = trusted_entry_from_row(data)
    return data


def row_to_asset_history(row):
    data = dict(row)
    data["thumbnail_url"] = asset_thumbnail_url(data)
    data["tags"] = split_tags(data.get("tags", ""))
    data["versionLabel"] = f"V{data.get('version_no', 1) or 1}"
    data["preview_url"] = canonical_preview_url(data)
    data["previewUrl"] = data.get("preview_url", "")
    data["assetCode"] = data.get("asset_code", "")
    return data




def get_asset_history(asset_id):
    with db() as conn:
        asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not asset:
            return {"ok": False, "error": "素材不存在"}
        rows = conn.execute(
            "select * from asset_history where asset_id = ? order by version_no desc",
            (asset_id,),
        ).fetchall()
        history = [row_to_asset_history(row) for row in rows]
        current = add_version_counts(conn, [asset])[0]
        current["historyVersionNo"] = len(history) + 1
        current["historyVersionLabel"] = f"V{len(history) + 1}"
    return {"ok": True, "asset": current, "history": history}


def backfill_resource_kinds(conn):
    rows = conn.execute(
        "select * from assets where asset_type = 'resource' and (resource_kind = '' or resource_kind is null)"
    ).fetchall()
    for row in rows:
        path = asset_library_path(row)
        if not path:
            path = Path(row["source_path"] or row["title"] or "")
        kind = resource_kind_for(path, row["media_kind"], row["title"], row["tags"])
        conn.execute(
            "update assets set resource_kind = ?, updated_at = ? where id = ?",
            (kind, now_ms(), row["id"]),
        )


def safe_extract(zip_path, target_dir):
    return safe_extract_zip(zip_path, target_dir)


def read_text_sample(path, limit=9000):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def category_for(path):
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".mov", ".m4v", ".webm"}:
        return "visual"
    if suffix in {".html", ".htm"}:
        return "page"
    if suffix in {".css", ".js", ".json", ".md"}:
        return "code"
    return "code"


def file_hash(path):
    digest = hashlib.sha1()
    with open(path, "rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()




def asset_exists(conn, source_hash):
    return bool(source_hash and conn.execute("select 1 from assets where source_hash = ? limit 1", (source_hash,)).fetchone())


def asset_library_path(asset):
    asset = dict(asset)
    if not asset.get("upload_id") or not asset.get("source_path"):
        return None
    path = (EXTRACTED / asset["upload_id"] / asset["source_path"]).resolve()
    if not is_path_within(path, EXTRACTED):
        return None
    return path


def reclassify_single_page_report_assets():
    """A one-page upload is a reusable page material, never a report card."""
    timestamp = now_ms()
    with db() as conn:
        candidates = conn.execute(
            """
            select asset.* from assets asset
            where (
                asset.asset_type = 'report'
                and not exists (
                  select 1 from report_page_slots slot
                  where slot.report_id = asset.id and slot.control_id <> ''
                )
              ) or (
                asset.asset_type = 'control'
                and asset.source_type = 'single-page-reclassified'
              )
            order by asset.created_at, asset.id
            """
        ).fetchall()
        known_controls = conn.execute(
            """
            select * from assets
            where asset_type = 'control' and source_type <> 'single-page-reclassified'
            order by case when version_parent_id = '' then 0 else 1 end, created_at, id
            """
        ).fetchall()
        content_index = {}
        for control in known_controls:
            control_path = asset_library_path(control)
            if control_path and control_path.exists():
                try:
                    content_index.setdefault(file_hash(control_path), control)
                except OSError:
                    continue
        for asset in candidates:
            source = asset_library_path(asset)
            if not source or source.suffix.lower() not in {'.html', '.htm'}:
                continue
            if asset["asset_type"] == 'report' and detect_report_page_count(source) > 1:
                continue
            try:
                same_content = content_index.get(file_hash(source))
            except OSError:
                same_content = None
            code = asset["asset_code"] if asset["asset_type"] == 'control' else next_asset_code(conn, "control", "page", "html")
            tags = []
            group_id = same_content["version_group"] or same_content["id"] if same_content else (asset["version_group"] or asset["id"])
            parent_id = same_content["id"] if same_content else (asset["version_parent_id"] or "")
            version_no = next_asset_version_no(conn, group_id) if same_content and asset["version_group"] != group_id else (asset["version_no"] or 1)
            conn.execute(
                """
                update assets
                set asset_type = 'control', category = 'page', asset_code = ?,
                    usage = ?, tags = ?, source_type = 'single-page-reclassified',
                    version_group = ?, version_no = ?, version_parent_id = ?,
                    similarity_score = ?, similarity_method = ?,
                    updated_at = ?
                where id = ?
                """,
                (
                    code,
                    "单页 HTML 导入，已自动归类为页面素材。",
                    ",".join(tags),
                    group_id,
                    version_no,
                    parent_id,
                    1.0,
                    "single-page-reclassified-version" if same_content else "single-page-reclassified",
                    timestamp,
                    asset["id"],
                ),
            )


def safe_download_name(value):
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "material"


def read_json_file(path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return {}


def control_template_manifest(extract_root):
    files = {path.relative_to(extract_root).as_posix() for path in extract_root.rglob("*") if path.is_file()}
    if not CONTROL_TEMPLATE_REQUIRED.issubset(files):
        return None
    manifest = read_json_file(extract_root / "ingestion-manifest.json")
    primary = manifest.get("primary_html", "index.html")
    if manifest.get("package_type") != "feishu-deck-h5-library":
        return None
    if not (extract_root / primary).exists():
        return None
    if int(manifest.get("slide_count") or 0) != 1:
        return None
    return manifest


def insert_control_resource_assets(conn, extract_root, upload_id, control, description=""):
    inserted = 0
    for file_path in extract_root.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in RESOURCE_SUFFIXES:
            continue
        rel = file_path.relative_to(extract_root).as_posix()
        media_kind = media_kind_for(file_path)
        source_hash = file_hash(file_path)
        asset_id = f"{slugify(file_path.stem)}-{source_hash[:10]}"
        title = file_path.stem.replace("-", " ").replace("_", " ").strip() or file_path.name
        resource_kind = resource_kind_for(file_path, media_kind, title, "")
        usage = f"从页面素材 {control['asset_code']} 提取"
        if description:
            usage += f"；上传描述：{description}"
        existing = conn.execute(
            "select id, tags, usage from assets where asset_type = 'resource' and source_hash = ? limit 1",
            (source_hash,),
        ).fetchone()
        if existing:
            conn.execute(
                "update assets set tags = ?, usage = ?, updated_at = ? where id = ?",
                (
                    "",
                    existing["usage"] if control["asset_code"] in (existing["usage"] or "") else f"{existing['usage']}；复用到页面素材 {control['asset_code']}",
                    now_ms(),
                    existing["id"],
                ),
            )
            continue
        asset_code = next_asset_code(conn, "resource", "visual", media_kind)
        conn.execute(
            """
            insert into assets
            (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, source_path, preview_url, upload_id, source_hash, tag_seeded, created_at, updated_at)
            values (?, ?, 'visual', ?, ?, '', 'resource', ?, ?, ?, 'control-resource', ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                asset_id,
                title,
                usage,
                "",
                asset_code,
                media_kind,
                resource_kind,
                rel,
                f"/extracted/{upload_id}/{rel}",
                upload_id,
                source_hash,
                now_ms(),
                now_ms(),
            ),
        )
        inserted += 1
    return inserted


def insert_control_template_asset(conn, extract_root, upload_id, source_type="template", description=""):
    manifest = control_template_manifest(extract_root)
    if not manifest:
        return None, 0
    primary = manifest.get("primary_html", "index.html")
    primary_path = extract_root / primary
    source_hash = file_hash(primary_path)
    if asset_exists(conn, source_hash):
        existing = conn.execute("select id, asset_code, title from assets where source_hash = ?", (source_hash,)).fetchone()
        if existing:
            resources = insert_control_resource_assets(conn, extract_root, upload_id, existing, description)
            return existing["id"], resources
        return None, 0
    deck_id = manifest.get("deck_id") or primary_path.stem
    asset_id = f"{slugify(deck_id)}-{source_hash[:10]}"
    asset_code = next_asset_code(conn, "control", "page", "html")
    title = manifest.get("title") or primary_path.stem.replace("-", " ")
    tags = []
    snippet = read_text_sample(primary_path)
    usage = "从标准页面模板包导入；导出时保持 feishu-deck-h5-library 包结构"
    if description:
        usage += f"；上传描述：{description}"
    conn.execute(
        """
        insert into assets
        (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, source_type, source_path, preview_url, upload_id, source_hash, created_at, updated_at)
        values (?, ?, 'page', ?, ?, ?, 'control', ?, 'html', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            title,
            usage,
            ",".join(tags),
            snippet,
            asset_code,
            source_type,
            primary,
            f"/extracted/{upload_id}/{primary}",
            upload_id,
            source_hash,
            now_ms(),
            now_ms(),
        ),
    )
    resources = insert_control_resource_assets(conn, extract_root, upload_id, {"asset_code": asset_code, "title": title}, description)
    return asset_id, resources








def is_manifest_driven_report(source, report_html):
    return split_manifest_driven_report(source, report_html, read_json_file=read_json_file)




def sync_manifest_viewer_pages(source):
    return split_sync_manifest_viewer_pages(source, read_json_file=read_json_file, safe_int=safe_int, slugify=slugify)


def detect_report_page_count(source):
    return split_detect_report_page_count(source, read_json_file=read_json_file, safe_int=safe_int)






def iter_export_support_files(root):
    include_prefixes = ("assets/", "input/")
    include_names = {"viewer-style-1.css", "viewer-style-2.css", "assets-manifest.yaml"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith("manual-controls/"):
            continue
        if rel in {"index.html", "deck.json", "ingestion-manifest.json", "texts.md"}:
            continue
        if rel.startswith(include_prefixes) or rel in include_names:
            yield path, rel


def build_export_manifest(asset, deck_id, title):
    return {
        "schema_version": "1.0",
        "package_type": "feishu-deck-h5-library",
        "deck_id": deck_id,
        "title": title,
        "primary_html": "index.html",
        "generated_by": "minem",
        "source": asset["source_type"],
        "slide_count": 1,
        "slides": [
            {
                "slide_id": asset["id"],
                "source_deck": asset["upload_id"] or "manual",
                "source_slide_key": asset["asset_code"],
                "version": "1",
            }
        ],
    }


def build_texts_markdown(title):
    return f"""# 下载素材文本

## 1. {title}

# {title}

## 主标题

{title}

## 正文

该文件由 MineM 导出为标准页面模板包。
"""


def build_deck_json(title, html):
    body_match = re.search(r"<body\b[^>]*>(.*?)</body>", html, re.IGNORECASE | re.DOTALL)
    body = body_match.group(1).strip() if body_match else html
    return {
        "version": "1.0",
        "deck": {"title": title},
        "slides": [
            {
                "key": "material-control",
                "layout": "raw",
                "data": {"html": body},
            }
        ],
    }


def export_asset_zip(asset_id):
    with db() as conn:
        asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not asset or asset["asset_type"] != "control":
            return None, "请选择可导出的页面素材", ""
        source = asset_library_path(asset)
        if not source or not source.is_file():
            return None, "找不到页面素材 HTML 文件", ""
        frame = native_control_frames(conn, [asset_id]).get(asset_id)
    try:
        with tempfile.TemporaryDirectory(prefix="minem-page-export-") as temporary:
            package = Path(temporary).resolve() / "page"
            package.mkdir()
            owned = read_json_file(source.parent / "manifest.json").get("format")
            if owned in {"minem-owned-page", "minem-owned-native-page"}:
                shutil.copytree(source.parent, package, dirs_exist_ok=True)
                if source.name != "index.html":
                    shutil.copyfile(package / source.name, package / "index.html")
            elif frame:
                write_native_deck_export(frame[0], [frame[1]], package / "index.html", package, single_page=True)
            else:
                bundle = OfflineBundle(EXTRACTED, package, excluded=report_export_excluded_path)
                copied = bundle.add(source)
                relative = quote(copied.relative_to(package).as_posix(), safe="/")
                (package / "index.html").write_text(report_viewer_html(asset["title"], [{
                    "title": asset["title"], "src": relative, "canvas": preview_meta_for_asset(dict(asset)),
                }]), encoding="utf-8")
            validate_offline_package(package)
            document = (package / "index.html").read_text(encoding="utf-8")
            (package / "deck.json").write_text(json.dumps(build_deck_json(asset["title"], document), ensure_ascii=False), encoding="utf-8")
            manifest = build_export_manifest(asset, safe_download_name(asset["asset_code"]), asset["title"])
            write_delivery_inventory(package, manifest, "ingestion-manifest.json")
            destination = Path(temporary) / "page.zip"
            zip_report_export_directory(package, destination)
            return destination.read_bytes(), "", download_name(asset["title"]) + ".zip"
    except (OSError, ValueError) as error:
        return None, str(error), ""


def report_export_page_html(title, source_url, dimensions=None):
    """Fit the page's original viewport to a presentation-sized PDF sheet."""
    dimensions = dimensions or {}
    width = dimensions.get("width") or 1920
    height = dimensions.get("height") or 1080
    scale = min(1920 / width, 1080 / height)
    left, top = (1920 - width * scale) / 2, (1080 - height * scale) / 2
    safe_title = html.escape(title or "汇报页面", quote=True)
    safe_src = html.escape(source_url, quote=True)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{safe_title}</title>
    <style>html,body{{margin:0;width:1920px;height:1080px;overflow:hidden;background:#030712}}iframe{{position:absolute;left:{left}px;top:{top}px;width:{width}px;height:{height}px;border:0;transform:scale({scale});transform-origin:0 0;background:#030712}}</style>
    </head><body><iframe title="{safe_title}" src="{safe_src}"></iframe></body></html>"""




def report_export_excluded_path(path):
    """AI 演讲、语音模型与运行时只服务平台，不属于汇报交付物。"""
    parts = [part.lower() for part in Path(path).parts]
    name = Path(path).name.lower()
    excluded_parts = {"ai-tts", "ai-presenter", "kokoro-js", "kokoro-voices", "kokoro-zh", "presenter"}
    model_suffixes = {".onnx", ".bin", ".tflite", ".pt", ".pth", ".safetensors"}
    return bool(excluded_parts.intersection(parts)) or name == "ai-presenter.html" or Path(name).suffix in model_suffixes


def write_native_deck_export(source, numbers, destination, bundle_root, *, single_page=False, extracted_root=None):
    source = source.resolve()
    deck = read_native_deck(source)
    if external_deck_base(deck):
        document = render_native_deck(deck, numbers, deck.base_href, single_page=single_page)
    else:
        source_root = (extracted_root or EXTRACTED).resolve()
        source_rel = source.relative_to(source_root)
        upload_root = source_root / source_rel.parts[0]
        archive_root = bundle_root / "deck-resources" / source_rel.parts[0]
        source_url = "/" + quote(source.relative_to(upload_root).as_posix(), safe="/")
        base_url = resolve_deck_base(deck, source_url)
        base_path = unquote(urlparse(base_url).path)
        archive_base = archive_root / base_path.lstrip("/")
        bundled_base = Path(os.path.relpath(archive_base, destination.parent)).as_posix()
        bundled_base = quote(bundled_base, safe="/")
        if base_path.endswith("/"):
            bundled_base += "/"
        document = render_native_deck(deck, numbers, bundled_base, single_page=single_page)
        parser = DependencyParser()
        parser.feed(document)
        parser.close()
        parser.finish()
        pending = [(base_url, value) for _, value in parser.references]
        copied = set()
        while pending:
            reference_base, value = pending.pop()
            value = normalize_reference(value)
            if is_external(value):
                continue
            reference = urljoin(reference_base, value)
            relative = unquote(urlparse(reference).path).lstrip("/")
            if not relative or "\x00" in relative or any(len(part.encode("utf-8")) > 255 for part in relative.split("/")):
                continue
            resource = (upload_root / relative).resolve()
            if (resource == source or resource in copied or not resource.is_relative_to(upload_root.resolve())
                    or not resource.is_file() or report_export_excluded_path(resource)):
                continue
            copied.add(resource)
            target = archive_root / resource.relative_to(upload_root.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resource, target)
            if resource.suffix.lower() == ".css":
                pending.extend((reference, name) for name in css_references(resource.read_text(encoding="utf-8", errors="ignore")))
            elif resource.suffix.lower() in {".html", ".htm"}:
                document_parser = DependencyParser()
                document_parser.feed(resource.read_text(encoding="utf-8", errors="ignore"))
                document_parser.close()
                document_parser.finish()
                page_base = urljoin(reference, document_parser.base_href or "")
                pending.extend((page_base, name) for _, name in document_parser.references)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")


def copy_report_export_sources(target_root, page_items, progress=None):
    """Materialize each page with its local resource tree."""
    bundle = OfflineBundle(EXTRACTED, target_root, excluded=report_export_excluded_path)
    exported_pages = []
    for index, item in enumerate(page_items, start=1):
        source = extracted_url_to_path(item.get("src"))
        bundle_manifest = read_json_file(source.parent / "manifest.json") if source else {}
        if source and bundle_manifest.get("format") == "minem-owned-native-page":
            relative = f"pages/page-{index:03d}/index.html"
            shutil.copytree(source.parent, (target_root / relative).parent)
        elif frame := item.get("nativeFrame"):
            source, number = frame
            relative = f"pages/page-{index:03d}/index.html"
            write_native_deck_export(source, [number], target_root / relative, target_root, single_page=True)
        else:
            if not source or not source.is_file():
                raise ValueError(f"第 {index} 页的原始 HTML 不存在")
            destination = bundle.add(source)
            relative = quote(destination.relative_to(bundle.target).as_posix(), safe="/")
        exported_pages.append({**item, "src": relative, "displaySrc": relative})
        if progress:
            progress(index, len(page_items))
    return exported_pages


def report_export_manifest(report, page_items, export_format):
    return {
        "schemaVersion": 1,
        "product": PRODUCT_VERSION.get("product", "MineM"),
        "productVersion": PRODUCT_VERSION.get("version", ""),
        "format": export_format,
        "report": {"id": report["id"], "code": report["asset_code"], "title": report["title"]},
        "pageCount": len(page_items),
        "pages": [
            {"order": index, "title": item.get("title") or "", "code": item.get("code") or "", "source": item.get("src") or ""}
            for index, item in enumerate(page_items, start=1)
        ],
        "exportedAt": now_ms(),
        "mediaPolicy": "媒体文件按原始字节复制，不作重新编码或压缩",
    }


def zip_report_export_directory(source_root, destination):
    text_suffixes = {".html", ".htm", ".css", ".js", ".json", ".md", ".txt"}
    # Imported archives can retain timestamps from before the ZIP epoch.  The
    # package must remain exportable; Python clamps only the archive metadata,
    # never the copied file content.
    with zipfile.ZipFile(destination, "w", strict_timestamps=False) as archive:
        for path in sorted(source_root.rglob("*")):
            if not path.is_file():
                continue
            # Media and binary files are stored verbatim. Text receives only
            # ZIP compression, never a semantic minifier transformation.
            compression = zipfile.ZIP_DEFLATED if path.suffix.lower() in text_suffixes else zipfile.ZIP_STORED
            archive.write(path, path.relative_to(source_root).as_posix(), compress_type=compression)


def generate_report_html_export(task_id, report, page_items, progress=None):
    output_dir = REPORT_EXPORTS / task_id
    package_root = output_dir / "html"
    shutil.rmtree(output_dir, ignore_errors=True)
    package_root.mkdir(parents=True, exist_ok=True)
    index = package_root / "index.html"
    owned_native = any(
        source and read_json_file(source.parent / "manifest.json").get("format") == "minem-owned-native-page"
        for source in (extracted_url_to_path(item.get("src")) for item in page_items)
    )
    if not owned_native and (native := native_deck_view(page_items)):
        source, numbers = native
        write_native_deck_export(source, numbers, index, package_root)
        exported_pages = [{**item, "src": f"index.html#{page}"} for page, item in enumerate(page_items, start=1)]
        if progress:
            progress(len(page_items), len(page_items))
    else:
        exported_pages = copy_report_export_sources(package_root, page_items, progress=progress)
        index.write_text(report_viewer_html(report["title"], exported_pages), encoding="utf-8")
    for item in exported_pages:
        source = package_root / unquote(urlparse(item["src"]).path)
        source.write_text(add_player_bridge(source.read_text(encoding="utf-8")), encoding="utf-8")
    saved_images = set()

    def store_image(path, data):
        if path not in saved_images:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            saved_images.add(path)

    # Iterate only over page documents and nested HTML copied into this bundle.
    for page in list(package_root.rglob("*")):
        if not page.is_file() or page.suffix.lower() not in {".htm", ".html"}:
            continue
        document = page.read_text(encoding="utf-8")
        lightweight = extract_bundle_images(document, page, package_root, store_image)
        if lightweight != document:
            page.write_text(lightweight, encoding="utf-8")
    validate_offline_package(package_root)
    write_delivery_inventory(package_root, report_export_manifest(report, exported_pages, "html"))
    filename = download_name(report["title"]) + ".zip"
    destination = output_dir / filename
    zip_report_export_directory(package_root, destination)
    return destination, filename


def capture_report_export_page(wrapper_path, screenshot_path):
    chrome = preview_chrome_path()
    if not chrome:
        raise RuntimeError("当前运行环境未安装 Chromium，无法生成 PDF")
    capture_pdf_page(chrome, wrapper_path, screenshot_path)


def generate_report_pdf_export(task_id, report, page_items, progress):
    if not Image:
        raise RuntimeError("当前运行环境缺少 PDF 图像渲染组件")
    output_dir = REPORT_EXPORTS / task_id
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    images = []
    try:
        with tempfile.TemporaryDirectory(prefix="minem-report-pdf-") as temp_dir:
            root = Path(temp_dir)
            package = root / "content"
            exported = copy_report_export_sources(package, page_items)
            validate_offline_package(package)
            for page in package.rglob("*"):
                if page.suffix.lower() in {".html", ".htm"} and page.is_file():
                    page.write_text(add_pdf_checks(page.read_text(encoding="utf-8")), encoding="utf-8")
            for index, item in enumerate(exported, start=1):
                source = package / unquote(urlparse(item["src"]).path)
                wrapper = root / f"page-{index:03d}.html"
                wrapper.write_text(report_export_page_html(item.get("title") or f"第 {index} 页", source.resolve().as_uri(), item.get("canvas")), encoding="utf-8")
                screenshot = root / f"page-{index:03d}.png"
                try:
                    capture_report_export_page(wrapper, screenshot)
                except (ValueError, RuntimeError) as error:
                    raise ValueError(f"第 {index} 页：{error}") from error
                with Image.open(screenshot) as captured:
                    images.append(captured.convert("RGB"))
                progress(index, len(exported), f"已完成第 {index}/{len(exported)} 页渲染")
            filename = download_name(report["title"]) + ".pdf"
            destination = output_dir / filename
            images[0].save(destination, "PDF", save_all=True, append_images=images[1:], resolution=150.0)
        return destination, filename
    finally:
        for image in images:
            image.close()


def run_report_export_task(task_id, page_items):
    task = REPORT_EXPORT_TASK_STORE.get(task_id, include_private=True)
    if not task:
        return
    REPORT_EXPORT_TASK_STORE.update(task_id, status="running", progress=15, message="正在准备页面素材", error="")
    try:
        with db() as conn:
            report = conn.execute("select * from assets where id = ? and asset_type = 'report'", (task["reportId"],)).fetchone()
        if not report:
            raise ValueError("汇报素材不存在")
        if task["format"] == "html":
            output_path, filename = generate_report_html_export(
                task_id, report, page_items,
                progress=lambda index, total: REPORT_EXPORT_TASK_STORE.update(
                    task_id, progress=min(94, 15 + int(index / max(total, 1) * 78)), message=f"正在整理第 {index}/{total} 页"
                ),
            )
        elif task["format"] == "pdf":
            output_path, filename = generate_report_pdf_export(
                task_id, report, page_items,
                lambda index, total, message: REPORT_EXPORT_TASK_STORE.update(
                    task_id, progress=min(94, 15 + int(index / max(total, 1) * 78)), message=message
                ),
            )
        else:
            raise ValueError("不支持的导出格式")
        REPORT_EXPORT_TASK_STORE.update(
            task_id, status="completed", progress=100, message="导出完成", filename=filename, outputPath=str(output_path), error=""
        )
    except Exception as error:
        shutil.rmtree(REPORT_EXPORTS / task_id, ignore_errors=True)
        REPORT_EXPORT_TASK_STORE.update(task_id, status="failed", progress=100, message="导出失败", error=str(error) or "导出失败")


def create_report_export_task(report_id, export_format):
    export_format = str(export_format or "").strip().lower()
    if export_format not in {"html", "pdf"}:
        return {"ok": False, "error": "导出格式仅支持 HTML 或 PDF"}
    result, page_items = report_public_page_items(report_id)
    if not result.get("ok") or not page_items:
        return {"ok": False, "error": result.get("error") or "该汇报没有可导出的可见页面"}
    if any(has_online_spark_storage(extracted_url_to_path(page.get("src"))) for page in page_items):
        return {"ok": False, "error": UNPACKAGED_ERROR}
    task_id = f"export-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
    task = REPORT_EXPORT_TASK_STORE.create({"id": task_id, "reportId": report_id, "format": export_format, "pageCount": len(page_items)})
    threading.Thread(target=run_report_export_task, args=(task_id, page_items), name=f"report-export-{task_id}", daemon=True).start()
    return {"ok": True, "task": task}


def next_candidate_asset_code(conn, base_code):
    base = (base_code or next_asset_code(conn, "control", "page", "html")).strip()
    prefix = f"{base}-C"
    rows = conn.execute(
        "select asset_code from assets where asset_code like ?",
        (f"{prefix}%",),
    ).fetchall()
    max_no = 0
    for row in rows:
        match = re.match(rf"^{re.escape(prefix)}(\d+)$", row["asset_code"] or "")
        if match:
            max_no = max(max_no, safe_int(match.group(1), 0))
    return f"{prefix}{max_no + 1:03d}"


def next_asset_version_no(conn, version_group):
    if not version_group:
        return 1
    return (conn.execute(
        "select coalesce(max(version_no), 0) + 1 from assets where version_group = ?",
        (version_group,),
    ).fetchone()[0] or 1)


def promote_asset_version(conn, asset_id):
    asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
    if not asset:
        return
    old_group = asset["version_group"] or asset["id"]
    rows = conn.execute(
        """
        select id from assets
        where version_group = ? and id <> ?
        order by version_no, created_at, asset_code
        """,
        (old_group, asset_id),
    ).fetchall()
    conn.execute(
        """
        update assets
        set version_group = ?, version_no = 1, version_parent_id = '', similarity_score = 1.0, similarity_method = 'current-control'
        where id = ?
        """,
        (asset_id, asset_id),
    )
    for index, row in enumerate(rows, start=2):
        conn.execute(
            """
            update assets
            set version_group = ?, version_no = ?, version_parent_id = ?, similarity_method = case when similarity_method = '' then 'candidate-history' else similarity_method end
            where id = ?
            """,
            (asset_id, index, asset_id, row["id"]),
        )


def manual_merge_asset_versions(payload):
    asset_ids = []
    for value in payload.get("assetIds") or payload.get("asset_ids") or []:
        asset_id = str(value or "").strip()
        if asset_id and asset_id not in asset_ids:
            asset_ids.append(asset_id)
    primary_id = str(payload.get("primaryAssetId") or payload.get("primary_asset_id") or "").strip()
    mode = str(payload.get("mode") or "version").strip()
    if mode not in {"keep", "version"}:
        return {"ok": False, "error": "合并方式必须是 keep 或 version"}
    if len(asset_ids) < 2:
        return {"ok": False, "error": "至少选择两个素材"}
    if primary_id not in asset_ids:
        return {"ok": False, "error": "主素材必须在已选素材中"}

    with db() as conn:
        placeholders = ",".join("?" for _ in asset_ids)
        selected_rows = conn.execute(f"select * from assets where id in ({placeholders})", asset_ids).fetchall()
        if len(selected_rows) != len(asset_ids):
            return {"ok": False, "error": "部分素材不存在"}
        selected_by_id = {row["id"]: row for row in selected_rows}
        primary = selected_by_id.get(primary_id)
        if not primary:
            return {"ok": False, "error": "主素材不存在"}
        asset_type = primary["asset_type"]
        if asset_type not in {"control", "resource"}:
            return {"ok": False, "error": "当前仅支持页面素材和资源素材人工合并"}
        if any(row["asset_type"] != asset_type for row in selected_rows):
            return {"ok": False, "error": "只能合并同一种素材类型"}

        groups = sorted({row["version_group"] or row["id"] for row in selected_rows})
        group_placeholders = ",".join("?" for _ in groups)
        affected_rows = conn.execute(
            f"""
            select * from assets
            where version_group in ({group_placeholders})
               or id in ({placeholders})
            """,
            groups + asset_ids,
        ).fetchall()
        affected_by_id = {row["id"]: row for row in affected_rows if row["asset_type"] == asset_type}
        ordered = [affected_by_id[primary_id]]
        ordered.extend(
            sorted(
                [row for row_id, row in affected_by_id.items() if row_id != primary_id],
                key=lambda row: (
                    0 if row["id"] in asset_ids else 1,
                    row["version_no"] or 1,
                    row["created_at"] or 0,
                    row["asset_code"] or "",
                    row["id"],
                ),
            )
        )
        timestamp = now_ms()
        method = "manual-keep" if mode == "keep" else "manual-version"
        conn.execute(
            """
            update assets
            set version_group = ?, version_no = 1, version_parent_id = '',
                similarity_score = 1.0, similarity_method = ?, updated_at = ?
            where id = ?
            """,
            (primary_id, f"{method}-primary", timestamp, primary_id),
        )
        child_ids = []
        for index, row in enumerate(ordered[1:], start=2):
            child_ids.append(row["id"])
            conn.execute(
                """
                update assets
                set version_group = ?, version_no = ?, version_parent_id = ?,
                    similarity_score = 1.0, similarity_method = ?, updated_at = ?
                where id = ?
                """,
                (primary_id, index, primary_id, method, timestamp, row["id"]),
            )
        updated_references = 0
        if mode == "keep" and asset_type == "control" and child_ids:
            child_placeholders = ",".join("?" for _ in child_ids)
            cursor = conn.execute(
                f"update report_page_slots set control_id = ?, updated_at = ? where control_id in ({child_placeholders})",
                [primary_id, timestamp, *child_ids],
            )
            updated_references += cursor.rowcount or 0
            conn.execute(
                f"""
                delete from report_page_candidates
                where control_id in ({child_placeholders})
                  and exists (
                    select 1
                    from report_page_candidates kept
                    where kept.report_id = report_page_candidates.report_id
                      and kept.page_number = report_page_candidates.page_number
                      and kept.control_id = ?
                  )
                """,
                [*child_ids, primary_id],
            )
            cursor = conn.execute(
                f"update report_page_candidates set control_id = ?, updated_at = ? where control_id in ({child_placeholders})",
                [primary_id, timestamp, *child_ids],
            )
            updated_references += cursor.rowcount or 0

        rows = conn.execute(
            "select * from assets where version_group = ? order by version_no, created_at, asset_code",
            (primary_id,),
        ).fetchall()
        versions = add_version_counts(conn, rows)
        primary_asset = next((asset for asset in versions if asset["id"] == primary_id), versions[0] if versions else row_to_asset(primary))
        invalidate_stats_cache()
        return {
            "ok": True,
            "mode": mode,
            "groupId": primary_id,
            "assetType": asset_type,
            "primary": primary_asset,
            "versions": versions,
            "versionCount": len(versions),
            "mergedCount": max(0, len(versions) - 1),
            "updatedReferences": updated_references,
        }


def register_report_page_candidate(conn, report_id, page_number, control_id, title="", note=""):
    return register_slot_candidate(conn, report_id, page_number, control_id, title, note, slugify=slugify, now_ms=now_ms)


def attach_report_page_control(conn, report_id, page_number, control_id, title="", note="", replace=False):
    return attach_slot_control(
        conn,
        report_id,
        page_number,
        control_id,
        title,
        note,
        replace,
        register_candidate=register_report_page_candidate,
        now_ms=now_ms,
    )


def upsert_report_page_slots(report_id, pages, title_prefix="", note=""):
    return save_report_page_slots(report_id, pages, title_prefix, note, connect=db, now_ms=now_ms, get_slots=get_report_page_slots)


def get_report_page_slots(report_id, conn=None):
    return load_report_page_slots(
        report_id,
        connect=db if conn is None else lambda: nullcontext(conn),
        row_to_asset=row_to_asset,
        asset_library_path=asset_library_path,
        detect_report_page_count=detect_report_page_count,
        validate_report_trusted_entry=validate_report_trusted_entry,
    )


def report_arrangement_payload(report_id):
    with db() as conn:
        conn.execute("begin")
        slots_result = get_report_page_slots(report_id, conn)
        if not slots_result.get("ok"):
            return slots_result
        controls = [slot["control_id"] for slot in slots_result["slots"] if slot.get("control")]
        native = native_control_frames(conn, controls)
        row = conn.execute("select * from report_page_arrangements where report_id = ?", (report_id,)).fetchone()
    slots = [slot for slot in slots_result.get("slots", []) if slot.get("control")]
    if not slots:
        return {"ok": False, "error": "该汇报暂未关联可编排的页面素材", "slots": []}
    try:
        saved_order = json.loads(row["page_order"]) if row else []
        hidden_ids = set(json.loads(row["hidden_page_ids"]) if row else [])
    except (TypeError, ValueError, json.JSONDecodeError):
        saved_order, hidden_ids = [], set()
    # A historical failed import can attach the same control more than once.
    # The arrangement model deliberately uses one control once per report, so
    # keep the first (source-order) slot until confirmation repairs the rows.
    by_id = {}
    for slot in slots:
        by_id.setdefault(slot["control_id"], slot)
    order = [item for item in saved_order if item in by_id]
    order.extend(item for item in by_id if item not in order)
    pages = []
    for index, control_id in enumerate(order, start=1):
        slot = by_id[control_id]
        control = slot["control"]
        page = {
            "id": control_id,
            "slotNumber": slot["page_number"],
            "order": index,
            "title": control.get("title") or slot.get("title") or f"第 {index} 页",
            "code": control.get("asset_code") or "",
            "previewUrl": canonical_preview_url(control),
            "thumbnailUrl": control.get("thumbnail_url") or "",
            "canvas": control.get("preview_meta"),
            "hidden": control_id in hidden_ids,
        }
        if frame := native.get(control_id):
            deck = read_native_deck(frame[0])
            live_cover = deck and (
                (deck.external_runtime and (index == 1 or frame[1] == 1))
                or re.search(r'<img\b[^>]*\bcover-art\b', deck.frames[frame[1] - 1][2], re.IGNORECASE)
            )
            if live_cover:
                page["thumbnailFrameUrl"] = control_public_url(control_id) + "?cover=1"
        pages.append(page)
    return {
        "ok": True,
        "reportId": report_id,
        "pages": pages,
        "updatedAt": int(row["updated_at"] or 0) if row else 0,
        "previewUrl": f"/reports/{quote(report_id, safe='')}/index.html",
    }


def normalize_report_page_canvases(report_id):
    """Ensure a report only references pages sized for its own canvas."""
    with db() as conn:
        report = conn.execute("select * from assets where id = ? and asset_type = 'report'", (report_id,)).fetchone()
        if report and read_native_deck(asset_library_path(report)):
            return {"normalized": 0, "created": [], "refreshed": []}
        result = normalize_report_canvas_versions(
            conn,
            report_id,
            extracted_root=EXTRACTED,
            detect_dimensions=detected_html_preview_size,
            now_ms=now_ms,
            next_candidate_asset_code=next_candidate_asset_code,
            next_asset_version_no=next_asset_version_no,
            read_text_sample=read_text_sample,
        )
    refresh_items = [*result.get("created", []), *result.get("refreshed", [])]
    refresh_ids = [item.get("id") for item in refresh_items if item.get("id")]
    refresh_assets = {}
    if refresh_ids:
        placeholders = ",".join("?" for _ in refresh_ids)
        with db() as conn:
            refresh_assets = {
                row["id"]: dict(row)
                for row in conn.execute(f"select * from assets where id in ({placeholders})", refresh_ids).fetchall()
            }
    for item in refresh_items:
        try:
            asset = refresh_assets[item["id"]]
            enqueue_thumbnail_refresh(item["id"], item["path"], thumbnail_source_fingerprint(asset))
        except (KeyError, OSError):
            continue
    if result.get("normalized"):
        invalidate_stats_cache()
    return result


def report_public_url(report_id):
    return f"/reports/{quote(report_id, safe='')}/index.html"


def control_public_url(control_id):
    return f"/pages/{quote(control_id, safe='')}/index.html"


def native_control_frames(conn, control_ids):
    """Map imported and existing canvas-derived pages back to native frames."""
    if not control_ids:
        return {}
    placeholders = ",".join("?" for _ in control_ids)
    rows = conn.execute(
        f"""
        select c.id, coalesce(parent.upload_id, c.upload_id) as upload_id,
               coalesce(parent.source_path, c.source_path) as source_path,
               coalesce(parent.source_type, c.source_type) as source_type,
               (select r.source_path from assets r where r.upload_id = coalesce(parent.upload_id, c.upload_id)
                and r.asset_type = 'report' and r.source_type = 'report-material-sync'
                order by r.created_at limit 1) as report_path
        from assets c left join assets parent on c.source_type = 'report-canvas-normalized' and parent.id = c.version_parent_id
        where c.id in ({placeholders}) and c.asset_type = 'control'
        """,
        control_ids,
    ).fetchall()
    result = {}
    for row in rows:
        batch = (EXTRACTED / (row["upload_id"] or "")).resolve()
        if not batch.is_relative_to(EXTRACTED.resolve()):
            continue
        match = re.fullmatch(r"_minem_pages/(?:current-)?page-(\d+)(?:-[a-f0-9]+)?/index\.html", row["source_path"] or "")
        if row["source_type"] == "report-material-sync" and match and row["report_path"]:
            page_file = (batch / row["source_path"]).resolve()
            if page_file.is_relative_to(batch) and read_json_file(page_file.parent / "manifest.json").get("format") == "minem-owned-native-page":
                path, index = page_file, 1
            else:
                path = (batch / row["report_path"]).resolve()
                index = int(match[1])
        elif row["source_type"] == "created-report-page" and row["source_path"]:
            path = (batch / row["source_path"]).resolve()
            index = 1
        else:
            continue
        if not path.is_relative_to(batch):
            continue
        deck = read_native_deck(path)
        if deck and 1 <= index <= len(deck.frames):
            result[row["id"]] = (path, index)
    return result


def native_deck_view(page_items):
    """A contiguous viewer can use native navigation for any order of one deck."""
    frames = [item.get("nativeFrame") for item in page_items]
    if not frames or not all(frames):
        return None
    source = frames[0][0]
    if any(path != source for path, _ in frames):
        return None
    return source, [number for _, number in frames]


def online_native_deck(source, numbers, *, single_page=False, cover_title=None):
    deck = read_native_deck(source)
    source_url = "/extracted/" + quote(source.relative_to(EXTRACTED.resolve()).as_posix(), safe="/")
    return render_native_deck(deck, numbers, resolve_deck_base(deck, source_url), single_page=single_page, cover_title=cover_title)


def report_public_page_items(report_id):
    """Return the current visible arrangement for the public report entry."""
    result = report_arrangement_payload(report_id)
    if not result.get("ok"):
        return result, []
    visible = [page for page in result["pages"] if not page["hidden"]]
    with db() as conn:
        native_frames = native_control_frames(conn, [page["id"] for page in visible])
    page_items = []
    for page in visible:
        item = {"title": page["title"], "code": page["code"], "src": page["previewUrl"], "canvas": page.get("canvas")}
        if native_frame := native_frames.get(page["id"]):
            item.update(nativeFrame=native_frame, displaySrc=control_public_url(page["id"]), canvas=None)
        page_items.append(item)
    return result, page_items


def update_report_arrangement(report_id, payload):
    staged = []
    try:
        return save_report_arrangement(report_id, payload, staged)
    except (OSError, ValueError) as error:
        for path in staged:
            shutil.rmtree(path, ignore_errors=True)
        return {"ok": False, "error": f"页面素材封装失败：{error}"}


def save_report_arrangement(report_id, payload, staged):
    if not isinstance(payload, dict):
        return {"ok": False, "error": "编排参数格式无效"}
    expected = payload.get("expectedUpdatedAt")
    if expected is not None and (type(expected) is not int or expected < 0):
        return {"ok": False, "error": "编排版本格式无效"}

    fields = {}
    for camel, snake in (
        ("pageOrder", "page_order"),
        ("insertedControlIds", "inserted_control_ids"),
        ("removedPageIds", "removed_page_ids"),
        ("hiddenPageIds", "hidden_page_ids"),
    ):
        value = payload.get(camel, payload.get(snake, []))
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return {"ok": False, "error": "编排页面参数格式无效"}
        fields[camel] = list(dict.fromkeys(filter(None, value)))

    with db() as conn:
        conn.execute("begin immediate")
        report = conn.execute("select * from assets where id = ? and asset_type = 'report'", (report_id,)).fetchone()
        if not report:
            return {"ok": False, "error": "汇报不存在"}
        saved = conn.execute("select page_order, updated_at from report_page_arrangements where report_id = ?", (report_id,)).fetchone()
        revision = int(saved["updated_at"] or 0) if saved else 0
        if expected is not None and expected != revision:
            return {"ok": False, "code": "ARRANGEMENT_CONFLICT", "error": "汇报编排已更新，请重新打开编排后再保存。"}

        slots = conn.execute(
            """
            select s.*, a.title as asset_title from report_page_slots s
            left join assets a on a.id = s.control_id and a.asset_type = 'control'
            where s.report_id = ? order by s.page_number
            """,
            (report_id,),
        ).fetchall()
        existing = {}
        for slot in slots:
            if slot["asset_title"] is not None:
                existing.setdefault(slot["control_id"], slot)
        try:
            prior = json.loads(saved["page_order"]) if saved else []
            prior = prior if isinstance(prior, list) else []
        except (TypeError, ValueError):
            prior = []
        known_ids = list(dict.fromkeys([*(key for key in prior if isinstance(key, str) and key in existing), *existing]))

        new_ids = fields["insertedControlIds"]
        inserted = {}
        if new_ids:
            placeholders = ",".join("?" for _ in new_ids)
            inserted = {
                row["id"]: row["title"] for row in conn.execute(
                    f"select id, title from assets where asset_type = 'control' and id in ({placeholders})",
                    new_ids,
                )
            }
            if set(new_ids) != inserted.keys():
                return {"ok": False, "error": "部分所选页面已不存在，请重新选择。"}

        removed = set(fields["removedPageIds"])
        allowed = (existing.keys() | inserted.keys()) - removed
        order = list(dict.fromkeys(key for key in [*fields["pageOrder"], *known_ids, *new_ids] if key in allowed))
        hidden = [key for key in fields["hiddenPageIds"] if key in allowed]
        if not set(order).difference(hidden):
            return {"ok": False, "error": "汇报至少需要保留一张可见页面。"}

        timestamp = max(now_ms(), revision + 1)
        copies = {}
        for control_id in new_ids:
            if control_id not in order or control_id in existing:
                continue
            if conn.execute("select 1 from report_page_slots where control_id=? and report_id<>? limit 1",
                            (control_id, report_id)).fetchone():
                source = conn.execute("select * from assets where id=?", (control_id,)).fetchone()
                copies[control_id] = copy_page_for_arrangement(conn, report, source, timestamp, staged)
        conn.execute("delete from report_page_slots where report_id = ?", (report_id,))
        for index, control_id in enumerate(order, 1):
            old = existing.get(control_id)
            title = (old["title"] or old["asset_title"]) if old else inserted[control_id]
            note = old["note"] if old else "人工编排插入页面"
            conn.execute(
                """insert into report_page_slots
                (report_id, page_number, title, status, control_id, task_key, note, created_at, updated_at)
                values (?, ?, ?, 'attached', ?, ?, ?, ?, ?)""",
                (report_id, index, title or f"第 {index} 页", copies.get(control_id, control_id),
                 old["task_key"] if old else "", note, old["created_at"] if old else timestamp, timestamp),
            )
        # Planned pages are not visible in the player but retain their relative
        # order and task metadata when the attached pages are rearranged.
        for index, slot in enumerate((slot for slot in slots if not slot["control_id"]), len(order) + 1):
            conn.execute(
                """insert into report_page_slots
                (report_id, page_number, title, status, control_id, task_key, note, created_at, updated_at)
                values (?, ?, ?, ?, '', ?, ?, ?, ?)""",
                (report_id, index, slot["title"], slot["status"], slot["task_key"], slot["note"], slot["created_at"], timestamp),
            )
        conn.execute(
            """
            insert into report_page_arrangements (report_id, page_order, hidden_page_ids, updated_by, updated_at)
            values (?, ?, ?, 'manual-arrangement', ?)
            on conflict(report_id) do update set page_order=excluded.page_order,
                hidden_page_ids=excluded.hidden_page_ids, updated_by=excluded.updated_by, updated_at=excluded.updated_at
            """,
            (report_id, json.dumps([copies.get(key, key) for key in order]),
             json.dumps([copies.get(key, key) for key in hidden]), timestamp),
        )
        conn.execute("update assets set preview_url = ?, updated_at = ? where id = ?", (report_public_url(report_id), timestamp, report_id))
    staged.clear()
    invalidate_stats_cache()
    return report_arrangement_payload(report_id)






def insert_control_asset(
    conn,
    *,
    asset_id,
    title,
    usage,
    tags,
    snippet,
    asset_code,
    source_type,
    source_path,
    preview_url,
    upload_id,
    source_hash,
    version_group="",
    version_no=1,
    version_parent_id="",
    created_at=None,
):
    timestamp = now_ms()
    conn.execute(
        """
        insert into assets
        (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, source_path, preview_url, upload_id, source_hash, version_group, version_no, version_parent_id, similarity_score, similarity_method, tag_seeded, created_at, updated_at)
        values (?, ?, 'page', ?, ?, ?, 'control', ?, 'html', '', ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, 1, ?, ?)
        """,
        (
            asset_id,
            title,
            usage,
            ",".join(tags) if isinstance(tags, (list, tuple)) else tags,
            snippet,
            asset_code,
            source_type,
            source_path,
            preview_url,
            upload_id,
            source_hash,
            version_group or asset_id,
            version_no,
            version_parent_id,
            "parallel-candidate" if version_parent_id else "",
            created_at or timestamp,
            timestamp,
        ),
    )


def report_trusted_url(report):
    if not report:
        return ""
    preview_url = report["preview_url"] if "preview_url" in report.keys() else ""
    if (preview_url or "").startswith("/reports/"):
        return preview_url
    upload_id = report["upload_id"] if "upload_id" in report.keys() else ""
    source_path = report["source_path"] if "source_path" in report.keys() else ""
    if upload_id and source_path:
        return f"/extracted/{upload_id}/{source_path}"
    return preview_url


def trusted_entry_from_row(report):
    url = report_trusted_url(report)
    cached_url = report["trusted_entry_url"] if "trusted_entry_url" in report.keys() else ""
    checked_at = report["trusted_checked_at"] if "trusted_checked_at" in report.keys() else 0
    return {
        "ok": bool((report["trusted_entry_ok"] if "trusted_entry_ok" in report.keys() else 0) and checked_at),
        "assetId": report["id"],
        "assetCode": report["asset_code"],
        "title": report["title"],
        "url": cached_url or url,
        "sourcePath": report["source_path"],
        "uploadId": report["upload_id"],
        "exists": bool(report["trusted_size"] if "trusted_size" in report.keys() else 0),
        "size": report["trusted_size"] if "trusted_size" in report.keys() else 0,
        "pageCount": report["trusted_page_count"] if "trusted_page_count" in report.keys() else 0,
        "viewerPageCount": report["trusted_viewer_page_count"] if "trusted_viewer_page_count" in report.keys() else 0,
        "hash": report["trusted_hash"] if "trusted_hash" in report.keys() else "",
        "checkedAt": checked_at,
        "message": "可信入口验证成功" if (report["trusted_entry_ok"] if "trusted_entry_ok" in report.keys() else 0) else "可信入口未校验或验证失败",
    }


def report_slot_page_count(conn, report_id):
    row = conn.execute(
        """
        select count(*) count, coalesce(max(page_number), 0) max_page
        from report_page_slots
        where report_id = ? and control_id <> ''
        """,
        (report_id,),
    ).fetchone()
    if not row:
        return 0
    return max(int(row["count"] or 0), int(row["max_page"] or 0))


def validate_report_trusted_entry(conn, report_id, refresh=False):
    report = conn.execute("select * from assets where id = ? and asset_type in ('report', 'page')", (report_id,)).fetchone()
    if not report:
        return {"ok": False, "error": "汇报素材不存在", "url": "", "pageCount": 0}
    if not refresh and "trusted_checked_at" in report.keys():
        trusted_entry = trusted_entry_from_row(report)
        trusted_entry["pageCount"] = max(trusted_entry.get("pageCount", 0), report_slot_page_count(conn, report_id))
        return trusted_entry
    source = asset_library_path(report)
    exists = bool(source and source.exists() and source.is_file())
    size = source.stat().st_size if exists else 0
    detected_page_count = detect_report_page_count(source) if exists else 0
    page_count = max(detected_page_count, report_slot_page_count(conn, report_id))
    viewer_page_count = 0
    if exists:
        try:
            viewer_page_count = viewer_pages_array_count(source.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            viewer_page_count = 0
    playable_ok = not viewer_page_count or viewer_page_count == page_count
    digest = file_hash(source) if exists else ""
    url = report_trusted_url(report)
    trusted_entry = {
        "ok": bool(exists and size > 0 and page_count > 0 and playable_ok),
        "assetId": report["id"],
        "assetCode": report["asset_code"],
        "title": report["title"],
        "url": url,
        "sourcePath": report["source_path"],
        "uploadId": report["upload_id"],
        "exists": exists,
        "size": size,
        "pageCount": page_count,
        "viewerPageCount": viewer_page_count,
        "hash": digest,
        "message": "可信入口验证成功" if exists and size > 0 and page_count > 0 and playable_ok else "可信入口验证失败",
    }
    if "trusted_checked_at" in report.keys():
        conn.execute(
            """
            update assets
            set trusted_entry_ok = ?,
                trusted_entry_url = ?,
                trusted_page_count = ?,
                trusted_viewer_page_count = ?,
                trusted_hash = ?,
                trusted_size = ?,
                trusted_checked_at = ?
            where id = ?
            """,
            (
                1 if trusted_entry["ok"] else 0,
                trusted_entry["url"],
                trusted_entry["pageCount"],
                trusted_entry["viewerPageCount"],
                trusted_entry["hash"],
                trusted_entry["size"],
                now_ms(),
                report["id"],
            ),
        )
    return trusted_entry


def validate_report_trusted_entry_by_id(report_id):
    with db() as conn:
        return validate_report_trusted_entry(conn, report_id)


def sync_report_index_from_slots(conn, report_id, page_numbers=None, change_note="同步当前页到最新汇报 index"):
    report = conn.execute("select * from assets where id = ? and asset_type in ('report', 'page')", (report_id,)).fetchone()
    if not report:
        return {"synced": False, "reason": "report-not-found", "pages": [], "trustedEntry": {"ok": False, "error": "汇报素材不存在", "url": "", "pageCount": 0}}
    source = asset_library_path(report)
    if not source or not source.exists():
        return {"synced": False, "reason": "report-source-missing", "pages": [], "trustedEntry": validate_report_trusted_entry(conn, report_id)}
    try:
        report_html = source.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"synced": False, "reason": "report-read-failed", "pages": [], "trustedEntry": validate_report_trusted_entry(conn, report_id)}
    if is_manifest_driven_report(source, report_html):
        sync_manifest_viewer_pages(source)
        digest = file_hash(source)
        conn.execute(
            "update assets set snippet = ?, source_hash = ?, preview_url = ?, updated_at = ? where id = ?",
            (read_text_sample(source), f"trusted-report:{report['id']}:{digest}", report_trusted_url(report), now_ms(), report["id"]),
        )
        return {"synced": False, "reason": "manifest-driven-entry-verified", "pages": [], "trustedEntry": validate_report_trusted_entry(conn, report_id, refresh=True)}

    params = [report_id]
    sql = """
        select slot.page_number, asset.*
        from report_page_slots slot
        join assets asset on asset.id = slot.control_id
        where slot.report_id = ? and slot.control_id <> '' and asset.asset_type = 'control'
    """
    wanted_pages = normalize_page_numbers(page_numbers) if page_numbers else []
    if wanted_pages:
        placeholders = ",".join("?" for _ in wanted_pages)
        sql += f" and slot.page_number in ({placeholders})"
        params.extend(wanted_pages)
    sql += " order by slot.page_number"

    changed_pages = []
    new_html = report_html
    for row in conn.execute(sql, params).fetchall():
        control_path = asset_library_path(row)
        if not control_path or not control_path.exists():
            continue
        try:
            control_html = control_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        page_html = extract_control_page_node(control_html)
        new_html, replaced = replace_report_page_node(new_html, row["page_number"], page_html)
        if replaced:
            changed_pages.append(row["page_number"])

    if not changed_pages:
        return {"synced": False, "reason": "no-page-change", "pages": [], "trustedEntry": validate_report_trusted_entry(conn, report_id)}

    try:
        source.write_text(new_html, encoding="utf-8")
    except OSError:
        return {"synced": False, "reason": "report-write-failed", "pages": changed_pages, "trustedEntry": validate_report_trusted_entry(conn, report_id)}

    timestamp = now_ms()
    source_hash = f"slot-sync-report:{report['id']}:{file_hash(source)}"
    rel = report["source_path"]
    conn.execute(
        """
        update assets
        set snippet = ?, preview_url = ?, source_hash = ?, updated_at = ?
        where id = ?
        """,
        (
            read_text_sample(source),
            f"/extracted/{report['upload_id']}/{rel}",
            source_hash,
            timestamp,
            report["id"],
        ),
    )
    # The next metadata read queues a thumbnail after this transaction ends.
    trusted_entry = validate_report_trusted_entry(conn, report_id, refresh=True)
    invalidate_stats_cache()
    return {"synced": True, "reason": change_note, "pages": changed_pages, "sourcePath": rel, "trustedEntry": trusted_entry}


def import_report_page_as_control(report_id, page_number, title=""):
    if page_number < 1:
        return {"ok": False, "error": "页码必须从 1 开始"}
    thumbnail_path = None
    with db() as conn:
        report = conn.execute("select * from assets where id = ?", (report_id,)).fetchone()
        if not report or report["asset_type"] not in {"report", "page"}:
            return {"ok": False, "error": "汇报素材不存在"}
        source = asset_library_path(report)
        if not source or not source.exists():
            return {"ok": False, "error": "找不到汇报 HTML 文件"}
        html = source.read_text(encoding="utf-8", errors="ignore")
        pages = extract_page_nodes(html)
        if not pages:
            return {"ok": False, "error": "没有识别到可拆分的单页结构"}
        if page_number > len(pages):
            return {"ok": False, "error": f"页码超出范围，当前识别到 {len(pages)} 页"}

        control_title = title.strip() or f"{report['title']} 第 {page_number} 页"
        control_html = build_control_html(html, pages[page_number - 1], control_title)
        source_hash = hashlib.sha1(f"report-page:{report_id}:{page_number}:{hashlib.sha1(control_html.encode('utf-8')).hexdigest()}".encode("utf-8")).hexdigest()
        base_rel = f"manual-controls/{slugify(report['id'])}-p{page_number:02d}-{source_hash[:10]}.html"
        dest = EXTRACTED / report["upload_id"] / base_rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        slot = conn.execute(
            "select * from report_page_slots where report_id = ? and page_number = ?",
            (report_id, page_number),
        ).fetchone()
        current_asset = None
        if slot and slot["control_id"]:
            current_asset = conn.execute(
                "select * from assets where id = ? and asset_type = 'control'",
                (slot["control_id"],),
            ).fetchone()
        if current_asset and current_asset["source_hash"] == source_hash:
            attach_report_page_control(conn, report_id, page_number, current_asset["id"], control_title, "从汇报拆页挂载", replace=True)
            sync_result = sync_report_index_from_slots(conn, report_id, [page_number], "当前页面素材确认后同步最新汇报 index")
            return {
                "ok": True,
                "id": current_asset["id"],
                "assetCode": current_asset["asset_code"],
                "pageCount": len(pages),
                "created": False,
                "updated": False,
                "candidate": False,
                "reportSync": sync_result,
            }

        existing = conn.execute(
            "select * from assets where source_hash = ? and asset_type = 'control' limit 1",
            (source_hash,),
        ).fetchone()
        tags = []
        usage = f"从汇报素材 {report['asset_code']} 手动导入的第 {page_number} 页"

        if current_asset:
            if existing:
                asset_id = existing["id"]
                asset_code = existing["asset_code"]
                thumbnail_path = asset_library_path(existing)
                created = False
            else:
                dest.write_text(control_html, encoding="utf-8")
                asset_id = f"{slugify(report['id'])}-p{page_number:02d}-{source_hash[:10]}"
                asset_code = next_candidate_asset_code(conn, current_asset["asset_code"] or report_code_to_control_code(report["asset_code"], page_number))
                version_group = current_asset["version_group"] or current_asset["id"]
                insert_control_asset(
                    conn,
                    asset_id=asset_id,
                    title=control_title,
                    usage=usage,
                    tags=tags,
                    snippet=control_html[:9000],
                    asset_code=asset_code,
                    source_type="report-page-candidate",
                    source_path=base_rel,
                    preview_url=f"/extracted/{report['upload_id']}/{base_rel}",
                    upload_id=report["upload_id"],
                    source_hash=source_hash,
                    version_group=version_group,
                    version_no=next_asset_version_no(conn, version_group),
                    version_parent_id=current_asset["id"],
                )
                thumbnail_path = dest
                created = True
            candidate_id = register_report_page_candidate(conn, report_id, page_number, asset_id, control_title, "手动拆页候选，未覆盖当前页")
            refresh_upload_count(conn, report["upload_id"])
            result = {
                "ok": True,
                "id": asset_id,
                "assetCode": asset_code,
                "candidateId": candidate_id,
                "pageCount": len(pages),
                "created": created,
                "updated": False,
                "candidate": True,
            }
        else:
            if existing:
                asset_id = existing["id"]
                asset_code = existing["asset_code"]
                if existing["version_parent_id"]:
                    promote_asset_version(conn, asset_id)
                thumbnail_path = asset_library_path(existing)
                created = False
            else:
                dest.write_text(control_html, encoding="utf-8")
                asset_id = f"{slugify(report['id'])}-p{page_number:02d}-{source_hash[:10]}"
                asset_code = next_asset_code(conn, "control", "page", "html")
                insert_control_asset(
                    conn,
                    asset_id=asset_id,
                    title=control_title,
                    usage=usage,
                    tags=tags,
                    snippet=control_html[:9000],
                    asset_code=asset_code,
                    source_type="report-page",
                    source_path=base_rel,
                    preview_url=f"/extracted/{report['upload_id']}/{base_rel}",
                    upload_id=report["upload_id"],
                    source_hash=source_hash,
                )
                thumbnail_path = dest
                created = True
            attach_report_page_control(conn, report_id, page_number, asset_id, control_title, "从汇报拆页挂载", replace=True)
            sync_result = sync_report_index_from_slots(conn, report_id, [page_number], "单页导入后同步最新汇报 index")
            refresh_upload_count(conn, report["upload_id"])
            result = {
                "ok": True,
                "id": asset_id,
                "assetCode": asset_code,
                "pageCount": len(pages),
                "created": created,
                "updated": False,
                "candidate": False,
                "reportSync": sync_result,
            }
    try:
        if thumbnail_path:
            generate_html_thumbnail(result["id"], thumbnail_path, source_hash)
    except Exception:
        pass
    return result


def import_report_pages_as_controls(report_id, pages, title_prefix=""):
    page_numbers = normalize_page_numbers(pages)
    if not page_numbers:
        return {"ok": False, "error": "请输入页码，例如 2,3,4,6"}
    results = []
    for page in page_numbers:
        title = f"{title_prefix.strip()} 第 {page} 页" if title_prefix.strip() else ""
        result = import_report_page_as_control(report_id, page, title)
        result["pageNumber"] = page
        results.append(result)
    failed = [item for item in results if not item.get("ok")]
    created = [item for item in results if item.get("ok") and item.get("created")]
    candidates = [item for item in results if item.get("ok") and item.get("candidate")]
    attached = [item for item in results if item.get("ok") and not item.get("candidate")]
    trusted_entry = validate_report_trusted_entry_by_id(report_id)
    return {
        "ok": len(failed) == 0,
        "results": results,
        "failed": failed,
        "createdCount": len(created),
        "candidateCount": len(candidates),
        "attachedCount": len(attached),
        "pageCount": results[0].get("pageCount", 0) if results else 0,
        "trustedEntry": trusted_entry,
    }


def insert_asset_record(
    conn,
    *,
    file_path,
    rel,
    upload_id,
    source_type,
    source_hash,
    usage,
    asset_type_override="",
):
    suffix = file_path.suffix.lower()
    digest = hashlib.sha1(f"{upload_id}/{rel}/{source_hash}".encode("utf-8")).hexdigest()[:10]
    asset_id = f"{slugify(file_path.stem)}-{digest}"
    category = category_for(file_path)
    snippet = read_text_sample(file_path) if suffix in {".html", ".htm"} else ""
    asset_type = asset_type_override or asset_type_for(file_path, category, " ".join([rel, usage, snippet[:5000]]))
    media_kind = media_kind_for(file_path)
    if not asset_type:
        return None
    asset_code = next_asset_code(conn, asset_type, category, media_kind)
    title = file_path.stem.replace("-", " ").replace("_", " ").strip() or file_path.name
    if media_kind == "html" and asset_type == "control":
        with file_path.open(encoding="utf-8-sig", errors="replace") as source:
            title = html_document_title(source.read(65536)) or title
    tags = ""
    resource_kind = resource_kind_for(file_path, media_kind, title, tags) if asset_type == "resource" else ""
    preview_url = ""

    if asset_type in {"report", "page", "control"} and not snippet:
        snippet = read_text_sample(file_path)
    if asset_type in {"report", "page", "resource", "control"}:
        preview_url = f"/extracted/{upload_id}/{rel}"

    conn.execute(
        """
        insert or ignore into assets
        (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, source_path, preview_url, upload_id, source_hash, tag_seeded, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (asset_id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, rel, preview_url, upload_id, source_hash, 0, now_ms(), now_ms()),
    )
    return asset_id


def insert_scanned_asset(conn, file_path, upload_id, extract_root, *, multi_page_resource_import=False, single_html_import=False):
    rel = file_path.relative_to(extract_root).as_posix()
    source_hash = file_hash(file_path)
    if asset_exists(conn, source_hash):
        return None
    page_from_resource_import = (multi_page_resource_import or single_html_import) and file_path.suffix.lower() in {".html", ".htm"}
    return insert_asset_record(
        conn,
        file_path=file_path,
        rel=rel,
        upload_id=upload_id,
        source_type="control-resource-import" if page_from_resource_import else "upload",
        source_hash=source_hash,
        usage=("从无清单多页面包逐页导入" if multi_page_resource_import else "从单页 HTML 导入") if page_from_resource_import else "从上传文件自动扫描入库",
        asset_type_override="control" if page_from_resource_import else "",
    )


def is_multi_page_resource_import(files):
    """Treat an unmanifested bundle of HTML entries as pages, not a report."""
    html_entries = [
        path
        for path in files
        if path.suffix.lower() in {".html", ".htm"}
        and path.name.lower() in {"index.html", "index.htm", "page.html", "slide.html"}
    ]
    return len(html_entries) > 1


def scan_upload(upload_id, extract_root, description="", conn=None):
    if conn is None:
        with db() as owned_conn:
            return scan_upload(upload_id, extract_root, description, conn=owned_conn)
    prepare_image_deck(extract_root, report_viewer_html)
    files = [path for path in extract_root.rglob("*") if path.is_file()]
    if control_template_manifest(extract_root):
        control_id, resource_count = insert_control_template_asset(conn, extract_root, upload_id, "template", description)
        inserted = (1 if control_id else 0) + resource_count
        conn.execute(
            "update uploads set file_count = ?, asset_count = ? where id = ?",
            (len(files), inserted, upload_id),
        )
        return len(files), inserted
    manifest, manifest_kind = load_report_package_manifest(extract_root)
    if manifest_kind:
        sync_report_material_package(conn, upload_id, extract_root)
        refresh_report_trusted_entries_for_upload(conn, upload_id)
        asset_count = conn.execute("select count(*) from assets where upload_id = ?", (upload_id,)).fetchone()[0]
        file_count = sum(1 for path in extract_root.rglob("*") if path.is_file())
        conn.execute(
            "update uploads set file_count = ?, asset_count = ? where id = ?",
            (file_count, asset_count, upload_id),
        )
        invalidate_stats_cache()
        expected_pages = report_manifest_page_items(extract_root, manifest, manifest_kind)
        if expected_pages:
            report = conn.execute(
                "select id from assets where upload_id = ? and asset_type = 'report' order by created_at limit 1",
                (upload_id,),
            ).fetchone()
            linked_pages = conn.execute(
                "select count(*) from report_page_slots where report_id = ? and control_id <> ''",
                (report["id"],),
            ).fetchone()[0] if report else 0
            if linked_pages < len(expected_pages):
                raise RuntimeError(f"汇报页面拆分未完成：应生成 {len(expected_pages)} 页，实际关联 {linked_pages} 页")
            refresh_report_trusted_entries_for_upload(conn, upload_id)
            asset_count = conn.execute("select count(*) from assets where upload_id = ?", (upload_id,)).fetchone()[0]
            conn.execute("update uploads set file_count = ?, asset_count = ? where id = ?", (file_count, asset_count, upload_id))
        return file_count, asset_count
    assets = [path for path in files if path.suffix.lower() in ALLOWED_SUFFIXES]
    multi_page_resource_import = is_multi_page_resource_import(assets)
    html_assets = [path for path in assets if path.suffix.lower() in {".html", ".htm"}]
    single_html_import = len(html_assets) == 1
    inserted = 0
    for path in assets:
        if insert_scanned_asset(
            conn, path, upload_id, extract_root,
            multi_page_resource_import=multi_page_resource_import,
            single_html_import=single_html_import,
        ):
            inserted += 1
    refresh_report_trusted_entries_for_upload(conn, upload_id)
    conn.execute("update uploads set file_count = ?, asset_count = ? where id = ?", (len(files), inserted, upload_id))
    invalidate_stats_cache()
    return len(files), inserted




def find_existing_asset(conn, upload_id, source_path, asset_type):
    return conn.execute(
        """
        select * from assets
        where upload_id = ? and source_path = ? and asset_type = ?
        limit 1
        """,
        (upload_id, source_path, asset_type),
    ).fetchone()


def clean_report_title(title):
    value = str(title or "").strip()
    value = re.sub(r"^RPT-[A-Z0-9-]+\s*", "", value).strip()
    value = re.sub(r"(?:｜完整汇报材料)+$", "", value).strip()
    value = re.sub(r"(?:完整汇报材料|完整汇报)+$", "", value).strip(" ｜|-")
    return value or "未命名汇报"


def report_material_title(title):
    return f"{clean_report_title(title)}｜完整汇报材料"


def control_display_title(title, page_number):
    value = str(title or "").strip() or f"第 {page_number} 页"
    number = str(page_number)
    padded = f"{page_number:02d}"
    value = re.sub(
        rf"^\s*0?{re.escape(number)}\s+0?{re.escape(number)}\b[\s:：._-]*",
        f"{padded} ",
        value,
        count=1,
    ).strip()
    if re.match(rf"^\s*0?{re.escape(number)}\b", value):
        return re.sub(rf"^\s*0?{re.escape(number)}\b", padded, value, count=1).strip()
    return f"{padded} {value}"


def load_report_package_manifest(extract_root):
    return import_load_report_package_manifest(extract_root, read_json_file=read_json_file)


def clean_slide_label(value):
    value = html.unescape(str(value or "")).strip()
    value = re.sub(r"\s*\(TODO\)\s*$", "", value, flags=re.I).strip()
    value = re.sub(r"^\s*\d{1,3}\s+", "", value).strip()
    value = value.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", value).strip()


def slide_key_from_node(node):
    match = re.search(r'data-slide-key=["\']([^"\']+)["\']', node or "", flags=re.I)
    return match.group(1).strip() if match else ""


def slide_label_from_node(node):
    match = re.search(r'data-screen-label=["\']([^"\']+)["\']', node or "", flags=re.I)
    return clean_slide_label(match.group(1)) if match else ""


def deck_slide_title(slide):
    if not isinstance(slide, dict):
        return ""
    data = slide.get("data") if isinstance(slide.get("data"), dict) else {}
    return clean_slide_label(data.get("title") or slide.get("title") or slide.get("screen_label") or slide.get("label") or "")


def load_deck_slides(extract_root):
    deck = read_json_file(Path(extract_root) / "deck.json")
    slides = deck.get("slides") if isinstance(deck.get("slides"), list) else []
    by_key = {str(item.get("key") or ""): item for item in slides if isinstance(item, dict) and item.get("key")}
    slide_index = read_json_file(Path(extract_root) / "slide-index.json")
    index_slides = slide_index.get("slides") if isinstance(slide_index.get("slides"), list) else []
    index_by_key = {str(item.get("key") or ""): item for item in index_slides if isinstance(item, dict) and item.get("key")}
    return slides, by_key, index_slides, index_by_key


def external_report_page_title(page_number, page_node, deck_slides, deck_by_key, index_slides, index_by_key):
    key = slide_key_from_node(page_node)
    candidates = [
        deck_slide_title(deck_by_key.get(key)),
        deck_slide_title(index_by_key.get(key)),
        deck_slide_title(deck_slides[page_number - 1] if page_number - 1 < len(deck_slides) else None),
        deck_slide_title(index_slides[page_number - 1] if page_number - 1 < len(index_slides) else None),
        slide_label_from_node(page_node),
    ]
    return next((item for item in candidates if item), f"第 {page_number} 页")


def inject_html_base_href(document, href):
    if re.search(r"<base\b", document or "", flags=re.I):
        return document
    base = f'<base href="{href}">'
    if re.search(r"<head\b[^>]*>", document or "", flags=re.I):
        return re.sub(r"(<head\b[^>]*>)", rf"\1\n  {base}", document, count=1, flags=re.I)
    return document


def generated_external_report_page_items(extract_root, manifest, manifest_kind):
    if manifest_kind != "html-report":
        return []
    report_html_path, _ = report_package_entry_path(extract_root, manifest, manifest_kind)
    if not report_html_path or not report_html_path.exists():
        return []
    try:
        report_html = report_html_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    native_deck = read_native_deck(report_html_path)
    spark_root = spark_package_root(Path(extract_root)) if native_deck else None
    has_archived_media = (report_html_path.parent / MEDIA_DIRECTORY).is_dir()
    own_native_pages = native_deck and (report_html_path.parent == spark_root or has_archived_media)
    page_spans = native_deck.frames if native_deck else split_page_node_spans(report_html)
    if not page_spans:
        return []
    deck_slides, deck_by_key, index_slides, index_by_key = load_deck_slides(extract_root)
    generated_root = Path(extract_root) / "_minem_pages"
    items = []
    for page_number, (_, _, page_node) in enumerate(page_spans, start=1):
        title = external_report_page_title(page_number, page_node, deck_slides, deck_by_key, index_slides, index_by_key)
        rel = f"_minem_pages/page-{page_number:03d}/index.html"
        target = generated_root / f"page-{page_number:03d}" / "index.html"
        if own_native_pages:
            write_native_deck_export(report_html_path, [page_number], target, target.parent, single_page=True)
            if has_archived_media:
                audit = audit_dependency_closure(target.parent)
                if audit["missing"] or audit["truncated"]:
                    raise ValueError(f"第 {page_number} 页的播放资源检查未通过")
            page_manifest = {"format": "minem-owned-native-page", "title": title, "sourcePage": page_number}
            (target.parent / "manifest.json").write_text(json.dumps(page_manifest, ensure_ascii=False), encoding="utf-8")
            page_html = target.read_text(encoding="utf-8")
        elif native_deck:
            source_url = "/" + quote(report_html_path.relative_to(extract_root).as_posix(), safe="/")
            native_base = resolve_deck_base(native_deck, source_url)
            if not external_deck_base(native_deck):
                base_path = unquote(urlparse(native_base).path)
                base_file = extract_root / base_path.lstrip("/")
                native_base = quote(Path(os.path.relpath(base_file, target.parent)).as_posix(), safe="/")
                if base_path.endswith("/"):
                    native_base += "/"
            page_html = render_native_deck(native_deck, [page_number], native_base, single_page=True)
        else:
            source_base = Path(os.path.relpath(report_html_path.parent, target.parent)).as_posix()
            page_html = inject_html_base_href(build_control_html(report_html, page_node, title), quote(source_base, safe="/") + "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError:
            current = ""
        if current != page_html:
            target.write_text(page_html, encoding="utf-8")
        role = ""
        key = slide_key_from_node(page_node)
        if key and key in index_by_key:
            role = str(index_by_key[key].get("layout") or "").strip()
        items.append({
            "path": target,
            "rel": rel,
            "page": page_number,
            "title": title,
            "role": role,
            "tags": ["外部导入", "自动拆页"],
            "source_code": "",
            "preview": "",
            "note": "外部汇报导入时自动拆页",
        })
    return items


def report_manifest_page_items(extract_root, manifest, manifest_kind):
    items = import_report_manifest_page_items(
        extract_root,
        manifest,
        manifest_kind,
        read_json_file=read_json_file,
    )
    if items:
        return items
    return generated_external_report_page_items(extract_root, manifest, manifest_kind)



def find_existing_asset_by_code(conn, asset_code, asset_type):
    if not asset_code:
        return None
    return conn.execute(
        "select * from assets where asset_code = ? and asset_type = ? limit 1",
        (asset_code, asset_type),
    ).fetchone()


def next_report_revision_code(conn, desired_code):
    if not desired_code or not desired_code.startswith("RPT-"):
        return desired_code
    if not find_existing_asset_by_code(conn, desired_code, "report"):
        return desired_code
    match = re.match(r"^(?P<stem>RPT-.+)-(?P<num>\d{3})$", desired_code)
    if not match:
        return next_asset_code(conn, "report", "report", "html")
    stem = match.group("stem")
    rows = conn.execute(
        "select asset_code from assets where asset_type = 'report' and asset_code like ?",
        (f"{stem}-%",),
    ).fetchall()
    max_no = safe_int(match.group("num"), 0)
    for row in rows:
        row_match = re.match(rf"^{re.escape(stem)}-(\d{{3}})$", row["asset_code"] or "")
        if row_match:
            max_no = max(max_no, safe_int(row_match.group(1), max_no))
    return f"{stem}-{max_no + 1:03d}"


def copy_package_preview_thumbnail(asset_id, extract_root, preview_rel, html_path, source_fingerprint=""):
    preview_path = extract_root / preview_rel if preview_rel else None
    if preview_path and preview_path.exists() and preview_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        output_path = THUMBNAILS / f"{asset_id}.png"
        try:
            if Image:
                render_contained_thumbnail(preview_path, output_path, html_path, image_module=Image)
            else:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(preview_path, output_path)
            write_thumbnail_meta(asset_id, source_fingerprint)
            return True
        except Exception:
            pass
    # Scanning owns a write transaction. Browser rendering belongs to the
    # post-commit preview phase (or the lazy thumbnail endpoint), otherwise a
    # large report blocks every unrelated edit while its pages render.
    return False


def sync_report_package_resources(conn, upload_id, extract_root, report_code, report_title):
    return write_report_package_resources(
        conn,
        upload_id,
        extract_root,
        report_code,
        report_title,
        resource_suffixes=RESOURCE_SUFFIXES,
        media_kind_for=media_kind_for,
        file_hash=file_hash,
        find_existing_asset=find_existing_asset,
        resource_kind_for=resource_kind_for,
        slugify=slugify,
        next_asset_code=next_asset_code,
        now_ms=now_ms,
    )


def sync_report_material_package(conn, upload_id, extract_root):
    return write_report_material_package(
        conn,
        upload_id,
        extract_root,
        load_report_package_manifest=load_report_package_manifest,
        report_package_entry_path=report_package_entry_path,
        find_existing_asset_by_code=find_existing_asset_by_code,
        next_report_revision_code=next_report_revision_code,
        next_asset_code=next_asset_code,
        clean_report_title=clean_report_title,
        report_material_title=report_material_title,
        read_text_sample=read_text_sample,
        file_hash=file_hash,
        copy_package_preview_thumbnail=copy_package_preview_thumbnail,
        report_manifest_page_items=report_manifest_page_items,
        report_code_to_control_code=report_code_to_control_code,
        find_existing_asset=find_existing_asset,
        control_display_title=control_display_title,
        asset_library_path=asset_library_path,
        next_candidate_asset_code=next_candidate_asset_code,
        copy_page_variant=copy_page_variant,
        insert_control_asset=insert_control_asset,
        next_asset_version_no=next_asset_version_no,
        attach_report_page_control=attach_report_page_control,
        sync_report_index_from_slots=sync_report_index_from_slots,
        sync_report_package_resources=sync_report_package_resources,
        now_ms=now_ms,
    )


def refresh_report_trusted_entries_for_upload(conn, upload_id):
    rows = conn.execute(
        "select id from assets where upload_id = ? and asset_type = 'report'",
        (upload_id,),
    ).fetchall()
    for row in rows:
        validate_report_trusted_entry(conn, row["id"], refresh=True)


def sync_report_materials_from_extracted():
    if not EXTRACTED.exists():
        return 0
    changed = 0
    with db() as conn:
        package_roots = import_discover_report_package_roots(
            EXTRACTED,
            conn,
            load_manifest=load_report_package_manifest,
        )
        for package_root in package_roots:
            upload_id = package_root.name
            if not conn.execute("select 1 from uploads where id = ? limit 1", (upload_id,)).fetchone():
                continue
            changed += sync_report_material_package(conn, upload_id, package_root)
            refresh_report_trusted_entries_for_upload(conn, upload_id)
        if changed:
            invalidate_stats_cache()
    return changed


def create_import_task(task):
    return create_import_task_record(IMPORT_TASK_STORE, task)


def update_import_task(task_id, **updates):
    return update_import_task_record(IMPORT_TASK_STORE, task_id, **updates)


def list_import_tasks():
    return list_import_task_records(IMPORT_TASK_STORE, limit=24)


def get_import_task(task_id):
    return get_import_task_record(IMPORT_TASK_STORE, task_id)


def import_result_for_upload(upload_id):
    with db() as conn:
        rows = conn.execute(
            """
            select *
            from assets
            where upload_id = ?
            order by
              case asset_type when 'report' then 1 when 'control' then 2 when 'resource' then 3 else 4 end,
              asset_code
            """,
            (upload_id,),
        ).fetchall()
        assets = add_version_counts(conn, rows)
    entry = next((asset for asset in assets if asset.get("preview_url") and asset.get("asset_type") in {"report", "control"}), None)
    if not entry:
        entry = next((asset for asset in assets if asset.get("preview_url")), None)
    return {
        "assetId": entry.get("id") if entry else "",
        "assetCode": entry.get("asset_code") if entry else "",
        "previewUrl": entry.get("preview_url") if entry else "",
        "assetTitle": entry.get("title") if entry else "",
        "assetType": entry.get("asset_type") if entry else "",
    }


def existing_import_result_for_extract_root(extract_root):
    """Return a previewable prior asset when an upload is entirely deduplicated."""
    hashes = [
        file_hash(path)
        for path in Path(extract_root).rglob("*")
        if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES
    ]
    if not hashes:
        return {}
    placeholders = ",".join("?" for _ in hashes)
    with db() as conn:
        rows = conn.execute(
            f"""
            select * from assets
            where source_hash in ({placeholders})
            order by
              case asset_type when 'report' then 1 when 'control' then 2 when 'resource' then 3 else 4 end,
              updated_at desc, asset_code
            """,
            hashes,
        ).fetchall()
        assets = add_version_counts(conn, rows)
    entry = next((asset for asset in assets if asset.get("preview_url") and asset.get("asset_type") in {"report", "control"}), None)
    if not entry:
        entry = next((asset for asset in assets if asset.get("preview_url")), None)
    if not entry:
        return {}
    return {
        "assetId": entry["id"],
        "assetCode": entry["asset_code"],
        "previewUrl": entry["preview_url"],
        "assetTitle": entry["title"],
        "assetType": entry["asset_type"],
    }


def generate_html_thumbnail(asset_id, html_path, source_fingerprint="", allow_text_fallback=True):
    html_path = Path(html_path)
    with tempfile.TemporaryDirectory(prefix="minem-native-thumb-") as temporary:
        with db() as conn:
            asset = conn.execute("select asset_type from assets where id=?", (asset_id,)).fetchone()
        if asset and asset["asset_type"] in {"report", "page"}:
            result, pages = report_public_page_items(asset_id)
            if result.get("ok") and pages:
                first = pages[0]
                source = extracted_url_to_path(first.get("src"))
                if frame := first.get("nativeFrame"):
                    html_path = Path(temporary) / "index.html"
                    write_native_deck_export(frame[0], [frame[1]], html_path, Path(temporary), single_page=True)
                elif source and source.is_file():
                    html_path = source
        if Image and (cover := packaged_page_cover_path(html_path)):
            if render_contained_thumbnail(cover, thumbnail_path(asset_id), html_path, image_module=Image):
                write_thumbnail_meta(asset_id, source_fingerprint)
                return True
        if {"_minem_pages", "_minem_normalized"}.intersection(html_path.parts) and not read_native_deck(html_path):
            with db() as conn:
                frame = native_control_frames(conn, [asset_id]).get(asset_id)
            if frame:
                package = Path(temporary)
                html_path = package / "index.html"
                write_native_deck_export(frame[0], [frame[1]], html_path, package, single_page=True)
        created = render_html_thumbnail(
            asset_id,
            html_path,
            thumbnails_dir=THUMBNAILS,
            image_module=Image,
            image_draw_module=ImageDraw,
            image_font_module=ImageFont,
            read_text_sample=read_text_sample,
            allow_text_fallback=allow_text_fallback,
        )
    if created:
        write_thumbnail_meta(asset_id, source_fingerprint)
    return created


def generate_upload_thumbnails(upload_id):
    created = 0
    with db() as conn:
        rows = conn.execute(
            "select id, source_path, preview_url, source_hash from assets where upload_id = ? and asset_type in ('report', 'control')",
            (upload_id,),
        ).fetchall()
    upload_root = (EXTRACTED / upload_id).resolve()
    for row in rows:
        fingerprint = thumbnail_source_fingerprint(row)
        if thumbnail_url(row["id"], fingerprint):
            continue
        html_path = (upload_root / row["source_path"]).resolve()
        if not is_path_within(html_path, upload_root):
            continue
        if generate_html_thumbnail(row["id"], html_path, fingerprint):
            created += 1
    return created


def run_import_task(task_id, stored_path, original, upload_id, description, content_hash=""):
    return execute_import_task(
        task_id,
        stored_path,
        original,
        upload_id,
        description,
        extracted_dir=EXTRACTED,
        zip_suffixes=ZIP_SUFFIXES,
        update_task=update_import_task,
        connect=db,
        safe_extract=safe_extract,
        scan_upload=scan_upload,
        generate_upload_thumbnails=generate_upload_thumbnails,
        import_result_for_upload=import_result_for_upload,
        existing_result_for_extract_root=existing_import_result_for_extract_root,
        now_ms=now_ms,
        content_hash=content_hash,
    )


def build_drive_report_package(job, stored):
    source_root = job / "drive-source"
    source = source_root / "index.html"
    files = []
    size = 0
    for path in source_root.rglob("*"):
        if path.is_symlink():
            raise ValueError("飞书文件夹包含不受支持的文件链接")
        if path.is_file():
            files.append(path)
            size += path.stat().st_size
        if len(files) > MAX_ZIP_FILES or size > MAX_ZIP_TOTAL_BYTES:
            raise ValueError("飞书文件夹超过素材包的大小或文件数量限制")
    deck = read_native_deck(source)
    if not deck or not deck.frames or external_deck_base(deck):
        raise ValueError("文件夹需要包含飞书汇报入口 index.html 和对应的 assets 目录")
    title = html_document_title(deck.source) or "飞书汇报"
    package = job / "package"
    pages = []
    file_size = 0
    file_count = 0
    slide_index = load_deck_slides(source_root)
    for number, (_, _, frame) in enumerate(deck.frames, 1):
        target = package / f"pages/page-{number:03d}/index.html"
        heading = re.search(r"<h[12]\b[^>]*>(.*?)</h[12]>", frame, re.I | re.S)
        page_title = clean_slide_label(re.sub(r"<[^>]+>", " ", heading[1])) if heading else ""
        page_title = page_title or external_report_page_title(number, frame, *slide_index)
        write_native_deck_export(source, [number], target, target.parent, single_page=True, extracted_root=job)
        try:
            localize_drive_fonts(target.parent, package / ".font-cache")
        except ValueError as error:
            raise ValueError(f"第 {number} 页的{error}") from error
        (target.parent / "manifest.json").write_text(json.dumps(
            {"format": "minem-owned-native-page", "title": page_title, "sourcePage": number}, ensure_ascii=False
        ), encoding="utf-8")
        page_audit = audit_dependency_closure(target.parent, require_local=True)
        if page_audit["missing"]:
            sample = "、".join(item["resolved"] for item in page_audit["missing"][:3])
            raise ValueError(f"第 {number} 页缺少本地播放资源：{sample}")
        if page_audit["truncated"]:
            raise ValueError(f"第 {number} 页包含过多资源引用")
        if remote := page_audit["remote"]:
            raise ValueError(f"第 {number} 页的 {remote['source']} 引用了未随包提供的资源（{remote['host']}）")
        for item in target.parent.rglob("*"):
            if item.is_file():
                file_size += item.stat().st_size
                file_count += 1
        if file_size > MAX_ZIP_TOTAL_BYTES or file_count > MAX_ZIP_FILES:
            raise ValueError("独立封装后的汇报超过素材包限制")
        pages.append({"title": page_title, "display_page": number, "path": target.relative_to(package).as_posix()})
    shutil.rmtree(package / ".font-cache", ignore_errors=True)
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(source_root).as_posix().encode() + b"\x00")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    viewer = report_viewer_html(title, [{"title": p["title"], "src": p["path"]} for p in pages])
    (package / "index.html").write_text(viewer + f"\n<!-- Source bundle {digest.hexdigest()} -->\n", encoding="utf-8")
    (package / "manifest.json").write_text(json.dumps(
        {"asset_type": "report", "title": title, "entry": "index.html", "pages": pages}, ensure_ascii=False
    ), encoding="utf-8")
    # This archive is generated locally. The shared ZIP importer still checks
    # entry count, member size and total extracted size before writing files.
    zip_report_export_directory(package, stored)
    return f"{title[:120]}.zip"


def enqueue_drive_import(root, token, index, description, source_url):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    task_id = f"task-{stamp}-{secrets.token_hex(4)}"
    upload_id = f"import-{stamp}-{secrets.token_hex(4)}"
    job = root / task_id
    job.mkdir(mode=0o700)
    try:
        task = create_import_task({
            "id": task_id, "uploadId": upload_id, "fileName": f"飞书文件夹 {index}",
            "status": "queued", "progress": 4, "message": "等待下载",
            "sourceUrl": source_url,
        })
        write_json_atomically(job / "job.json", {"uploadId": upload_id, "token": token, "description": description})
        return task
    except (OSError, sqlite3.Error):
        shutil.rmtree(job, ignore_errors=True)
        task = update_import_task(task_id, status="failed", progress=100, message="无法保存导入任务",
                                  error="请检查本机项目目录和存储空间")
        if task is not None:
            return task
        raise


def process_drive_import(root, job):
    task_id = job.name
    task = get_import_task(task_id)
    if not task or task["status"] in {"success", "failed"}:
        shutil.rmtree(job, ignore_errors=True)
        return
    metadata = read_json_file(job / "job.json")
    upload_id = task["uploadId"]
    stored = UPLOADS / f"{upload_id}.zip"
    try:
        if metadata.get("uploadId") != upload_id:
            raise ValueError("导入任务信息不完整，请重新提交链接")
        if task["status"] == "running" and task["progress"] >= 38:
            with db() as conn:
                committed = conn.execute(
                    "select file_count, asset_count from uploads where id=? and asset_count>0", (upload_id,)
                ).fetchone()
            if committed and (preview := import_result_for_upload(upload_id)).get("previewUrl"):
                update_import_task(task_id, status="success", progress=100, message="已恢复导入结果",
                                   fileCount=committed["file_count"], assetCount=committed["asset_count"], **preview)
                return

        request_path, response = job / "request.json", job / "result.json"
        if not request_path.is_file():
            if not drive_worker_alive(root):
                # Keep the queued task available while the host service restarts.
                return
            write_json_atomically(request_path, {
                "token": metadata["token"], "expires": time.time() + DRIVE_QUEUE_SECONDS,
                "max_files": MAX_ZIP_FILES, "max_bytes": MAX_ZIP_TOTAL_BYTES,
            })
        request = json.loads(request_path.read_text(encoding="utf-8"))
        last_progress = None
        while not response.is_file():
            progress = read_json_file(job / "progress.json")
            if progress:
                started_at = progress.get("startedAt", request["expires"] - DRIVE_QUEUE_SECONDS)
                deadline = started_at + DRIVE_DOWNLOAD_SECONDS + 20
                if progress != last_progress:
                    message = "网络传输中断，正在重试" if progress["attempt"] > 1 else "正在下载飞书文件夹"
                    if progress["bytes"]:
                        message += f" · 已接收 {progress['bytes'] / (1024 * 1024):.1f} MB"
                    update_import_task(task_id, status="running", progress=8, message=message)
                    last_progress = progress
            else:
                deadline = request["expires"] + 5
            if time.time() >= deadline:
                raise ValueError("飞书文件夹下载超时" if progress else "飞书下载排队超时，请重新导入")
            time.sleep(1)

        result = json.loads(response.read_text(encoding="utf-8"))
        if not result.get("ok"):
            raise ValueError(result.get("error") or "飞书文件夹下载失败")
        update_import_task(task_id, status="running", progress=11, message="正在检查完整性并逐页封装")
        shutil.rmtree(job / "package", ignore_errors=True)
        filename = build_drive_report_package(job, stored)
        update_import_task(task_id, fileName=filename, storedPath=runtime_record_path(stored, RUNTIME_ROOT))
        run_import_task(task_id, str(stored), filename, upload_id, metadata["description"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        stored.unlink(missing_ok=True)
        update_import_task(task_id, status="failed", progress=100, message="飞书链接导入失败",
                           error=str(error) if isinstance(error, ValueError) else "文件处理失败，请重试")
    finally:
        current = get_import_task(task_id)
        if current and current["status"] in {"success", "failed"}:
            shutil.rmtree(job, ignore_errors=True)


def drive_import_loop():
    root = drive_import_queue(RUNTIME_ROOT)
    while True:
        try:
            queued = (path for path in root.glob("*/job.json")
                      if DRIVE_JOB_ID.fullmatch(path.parent.name) and not path.parent.is_symlink())
            for path in sorted(queued, key=lambda path: path.stat().st_mtime_ns):
                process_drive_import(root, path.parent)
        except (OSError, sqlite3.Error) as error:
            print(f"读取飞书导入队列失败：{type(error).__name__}", file=sys.stderr)
        time.sleep(.5)


def load_import_sources():
    return load_import_source_config(AUTO_IMPORT_CONFIG, DEFAULT_IMPORT_SOURCES, DEFAULT_EXCLUDES)


def iter_import_candidates(roots, excludes, max_depth):
    yield from iter_import_source_candidates(
        roots,
        excludes,
        max_depth,
        allowed_suffixes=ALLOWED_SUFFIXES,
        zip_suffixes=ZIP_SUFFIXES,
        excluded_file_keywords=EXCLUDED_FILE_KEYWORDS,
    )


def import_direct_file(conn, source_path, import_id, target_root):
    return import_direct_asset_file(
        conn,
        source_path,
        import_id,
        target_root,
        file_hash=file_hash,
        asset_exists=asset_exists,
        insert_asset_record=insert_asset_record,
    )


def import_zip_file(source_path):
    return import_zip_archive(
        source_path,
        connect=db,
        uploads_dir=UPLOADS,
        extracted_dir=EXTRACTED,
        safe_extract=safe_extract,
        scan_upload=scan_upload,
        now_ms=now_ms,
        extraction_errors=(UploadLimitError,),
    )


def auto_import_sources():
    return run_auto_import_sources(
        load_sources=load_import_sources,
        iter_candidates=iter_import_candidates,
        import_zip=import_zip_file,
        import_direct=import_direct_file,
        connect=db,
        extracted_dir=EXTRACTED,
        zip_suffixes=ZIP_SUFFIXES,
        now_ms=now_ms,
    )


def delete_library_file(asset, conn=None):
    upload_id = asset["upload_id"]
    source_path = asset["source_path"]
    if not upload_id or not source_path:
        return False
    if conn is not None:
        references = conn.execute(
            """
            select count(*) from assets
            where upload_id = ? and source_path = ? and id <> ?
            """,
            (upload_id, source_path, asset["id"]),
        ).fetchone()[0]
        if references:
            return False
    path = (EXTRACTED / upload_id / source_path).resolve()
    if not is_path_within(path, EXTRACTED):
        return False
    if path.exists() and path.is_file():
        path.unlink()
        return True
    return False


def history_snapshot_file(relative):
    relative = relative.removeprefix("_history/")
    for root in (HISTORY_DIR, LEGACY_HISTORY_DIR):
        path = (root / relative).resolve()
        if path.is_relative_to(root.resolve()) and path.is_file():
            return path
    return None


def delete_asset_history_files(conn, asset_ids):
    if not asset_ids:
        return
    placeholders = ",".join("?" for _ in asset_ids)
    rows = conn.execute(f"select id, snapshot_path from asset_history where asset_id in ({placeholders})", asset_ids).fetchall()
    for row in rows:
        if row["snapshot_path"]:
            relative = row["snapshot_path"]
            if relative.startswith("_history/"):
                path = history_snapshot_file(relative)
                if path:
                    path.unlink()
            else:
                path = (EXTRACTED / relative).resolve()
                if path.is_relative_to(EXTRACTED.resolve()) and path.is_file():
                    path.unlink()
        thumb = THUMBNAILS / f"{row['id']}.png"
        if thumb.exists() and thumb.is_file():
            thumb.unlink()
    conn.execute(f"delete from asset_history where asset_id in ({placeholders})", asset_ids)


def refresh_upload_count(conn, upload_id):
    if not upload_id:
        return
    count = conn.execute("select count(*) from assets where upload_id = ?", (upload_id,)).fetchone()[0]
    conn.execute("update uploads set asset_count = ? where id = ?", (count, upload_id))


def cleanup_empty_created_upload(conn, upload_id):
    if not upload_id or not str(upload_id).startswith("created-report-"):
        return False
    count = conn.execute("select count(*) from assets where upload_id = ?", (upload_id,)).fetchone()[0]
    if count:
        return False
    conn.execute("delete from uploads where id = ?", (upload_id,))
    upload_root = (EXTRACTED / upload_id).resolve()
    if is_path_within(upload_root, EXTRACTED) and upload_root.exists():
        shutil.rmtree(upload_root, ignore_errors=True)
    return True


def delete_asset_thumbnail(asset_id):
    if not is_safe_filename_stem(asset_id):
        return False
    thumb = (THUMBNAILS / f"{asset_id}.png").resolve()
    if not is_path_within(thumb, THUMBNAILS):
        return False
    if thumb.exists() and thumb.is_file():
        thumb.unlink()
        return True
    return False








def version_candidate_path(row):
    path = asset_library_path(row)
    if path and path.exists():
        return path
    return None


def reset_asset_versions(conn, asset_type="resource"):
    where = "asset_type = ?"
    params = [asset_type]
    conn.execute(
        f"""
        update assets
        set version_group = id,
            version_no = 1,
            version_parent_id = '',
            similarity_score = 1.0,
            similarity_method = ''
        where {where}
        """,
        params,
    )










def merge_similar_resource_versions():
    return run_merge_similar_resource_versions(
        connect=db,
        reset_asset_versions=reset_asset_versions,
        version_candidate_path=version_candidate_path,
        image_module=Image,
        image_sequence_module=ImageSequence,
    )


def add_version_counts(conn, rows, *, include_source_batches=True, include_report_trusted=True):
    if not rows:
        return []
    groups = [row["version_group"] or row["id"] for row in rows]
    placeholders = ",".join("?" for _ in groups)
    counts = {
        row["version_group"]: row["count"]
        for row in conn.execute(
            f"select version_group, count(*) count from assets where version_group in ({placeholders}) group by version_group",
            groups,
        ).fetchall()
    }
    assets = []
    for row in rows:
        item = row_to_asset(row)
        item["versionCount"] = counts.get(row["version_group"] or row["id"], 1)
        assets.append(item)
    report_ids = [asset["id"] for asset in assets if asset.get("asset_type") == "report"]
    if report_ids:
        placeholders = ",".join("?" for _ in report_ids)
        slot_controls = defaultdict(list)
        for slot in conn.execute(
            f"""
            select report_id, control_id
            from report_page_slots
            where report_id in ({placeholders}) and control_id <> ''
            order by report_id, page_number
            """,
            report_ids,
        ).fetchall():
            slot_controls[slot["report_id"]].append(slot["control_id"])
        hidden_by_report = {}
        for arrangement in conn.execute(
            f"select report_id, hidden_page_ids from report_page_arrangements where report_id in ({placeholders})",
            report_ids,
        ).fetchall():
            try:
                hidden_by_report[arrangement["report_id"]] = set(json.loads(arrangement["hidden_page_ids"] or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                hidden_by_report[arrangement["report_id"]] = set()
        for asset in assets:
            if asset.get("asset_type") != "report":
                continue
            hidden = hidden_by_report.get(asset["id"], set())
            asset["displayPageCount"] = sum(control_id not in hidden for control_id in slot_controls.get(asset["id"], []))
    if include_source_batches:
        attach_source_batches(conn, assets)
    if include_report_trusted:
        for asset in assets:
            if asset.get("asset_type") == "report":
                asset["trustedEntry"] = validate_report_trusted_entry(conn, asset["id"])
    return assets


def upload_batch_summaries(conn, upload_ids):
    return summarize_upload_batches(conn, upload_ids, pipeline_stages=PIPELINE_STAGES, validate_report_trusted_entry=validate_report_trusted_entry)


def attach_source_batches(conn, assets):
    return hydrate_source_batches(conn, assets, upload_batch_summaries_fn=upload_batch_summaries)




def asset_lineage_details(asset_id):
    return build_asset_lineage_details(
        asset_id,
        connect=db,
        row_to_asset=row_to_asset,
        upload_batch_summaries_fn=upload_batch_summaries,
        validate_report_trusted_entry=validate_report_trusted_entry,
        asset_types=ASSET_TYPES,
        categories=CATEGORIES,
        resource_kinds=RESOURCE_KINDS,
        source_types=SOURCE_TYPES,
        canonical_preview_url=canonical_preview_url,
    )


def pipeline_summary(conn):
    return build_pipeline_summary(conn, pipeline_stages=PIPELINE_STAGES, upload_batch_summaries_fn=upload_batch_summaries)


def stats_payload(conn):
    now = time.time()
    if STATS_CACHE["payload"] is not None and STATS_CACHE["expires_at"] > now:
        return STATS_CACHE["payload"]
    # Dashboard totals follow the default library view: a version group counts
    # once, while detailed version records remain available on the asset.
    asset_count = conn.execute("select count(*) from assets where version_parent_id = ''").fetchone()[0]
    versioned_asset_count = conn.execute("select count(*) from assets where version_parent_id <> ''").fetchone()[0]
    raw_asset_count = asset_count + versioned_asset_count
    upload_count = conn.execute("select count(*) from uploads").fetchone()[0]
    categories = conn.execute("select category, count(*) count from assets where version_parent_id = '' group by category").fetchall()
    types = conn.execute("select asset_type, count(*) count from assets where version_parent_id = '' group by asset_type").fetchall()
    payload = {
        "assetCount": asset_count,
        "visibleAssetCount": asset_count,
        "rawAssetCount": raw_asset_count,
        "versionedAssetCount": versioned_asset_count,
        "uploadCount": upload_count,
        "categories": {row["category"]: row["count"] for row in categories},
        "types": {row["asset_type"]: row["count"] for row in types},
        "pipeline": pipeline_summary(conn),
    }
    STATS_CACHE["payload"] = payload
    STATS_CACHE["expires_at"] = now + 30
    return payload


def invalidate_stats_cache():
    STATS_CACHE["payload"] = None
    STATS_CACHE["expires_at"] = 0


def normalize_asset_title(value):
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    title = re.sub(r"[<>]", "", title).strip()
    return title[:180]


def update_asset_title(asset_id, title):
    normalized = normalize_asset_title(title)
    if not normalized:
        return {"ok": False, "error": "名称不能为空"}
    with db() as conn:
        asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not asset:
            return {"ok": False, "error": "素材不存在"}
        conn.execute(
            "update assets set title = ?, updated_at = ? where id = ?",
            (normalized, now_ms(), asset_id),
        )
        row = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        updated = add_version_counts(conn, [row])[0]
    return {"ok": True, "asset": updated}


def report_viewer_html(title, page_items, release_url=""):
    pages = []
    for index, item in enumerate(page_items, 1):
        size = item.get("canvas") or {}
        pages.append({
            "id": item.get("code") or f"page-{index}",
            "title": item.get("title") or f"第 {index} 页",
            "src": item.get("displaySrc") or item.get("src") or "",
            "copySrc": item.get("copySrc") or "",
            "width": size.get("width") or 1920,
            "height": size.get("height") or 1080,
        })
    # The script element is parsed as raw HTML text, even with type JSON.
    payload = json.dumps({"pages": pages, "releaseUrl": release_url}, ensure_ascii=False).replace("<", "\\u003c")
    template = (RESOURCE_ROOT / "minem/report_player.html").read_text(encoding="utf-8")
    safe_title = html.escape(title or "汇报素材", quote=True)
    return re.sub(r"\{\{(TITLE|DATA)\}\}", lambda match: {"TITLE": safe_title, "DATA": payload}[match[1]], template)


def packaged_page_cover_path(source):
    if not source or not source.is_file():
        return None
    manifest = read_json_file(source.parent / "manifest.json")
    if manifest.get("format") != "minem-owned-page":
        return None
    resources = manifest.get("resources") or []
    if not isinstance(resources, list) or not resources or not isinstance(resources[0], str):
        return None
    cover = (source.parent / resources[0]).resolve()
    if not cover.is_relative_to(source.parent.resolve()) or not cover.is_file():
        return None
    if cover.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return None
    return cover


def cleanup_temp_report_sessions():
    timestamp = now_ms()
    with TEMP_REPORT_LOCK:
        expired = [token for token, session in TEMP_REPORT_SESSIONS.items() if session.get("expiresAt", 0) < timestamp]
        for token in expired:
            TEMP_REPORT_SESSIONS.pop(token, None)


def normalize_temp_report_control_ids(raw_ids):
    if isinstance(raw_ids, str):
        raw_ids = re.split(r"[\s,，]+", raw_ids)
    if not isinstance(raw_ids, list):
        return []
    seen = set()
    control_ids = []
    for raw_id in raw_ids:
        control_id = str(raw_id or "").strip()
        if not control_id or control_id in seen:
            continue
        seen.add(control_id)
        control_ids.append(control_id)
    return control_ids


def create_temp_report(payload):
    cleanup_temp_report_sessions()
    control_ids = normalize_temp_report_control_ids(payload.get("controlIds") or payload.get("control_ids") or [])
    if not control_ids:
        return {"ok": False, "error": "请先勾选页面素材"}
    if len(control_ids) > 80:
        return {"ok": False, "error": "一次最多预览 80 个页面素材"}

    with db() as conn:
        placeholders = ",".join("?" for _ in control_ids)
        rows = conn.execute(
            f"select * from assets where id in ({placeholders}) and asset_type = 'control'",
            control_ids,
        ).fetchall()
        native_frames = native_control_frames(conn, control_ids)
    controls_by_id = {row["id"]: row for row in rows}
    missing = [control_id for control_id in control_ids if control_id not in controls_by_id]
    if missing:
        return {"ok": False, "error": f"页面素材不存在：{'、'.join(missing[:3])}"}

    page_items = []
    for index, control_id in enumerate(control_ids, start=1):
        control = dict(controls_by_id[control_id])
        preview_url = canonical_preview_url(control)
        preview_path = extracted_url_to_path(preview_url)
        if not preview_url or not preview_path or not preview_path.exists():
            return {"ok": False, "error": f"页面素材无法预览：{control['asset_code']}"}
        page_items.append({
            "title": control["title"] or f"Page {index:02d}",
            "code": control["asset_code"] or "",
            "src": preview_url,
            "displaySrc": control_public_url(control_id) if control_id in native_frames else "",
            "copySrc": control_public_url(control_id),
            "canvas": None if control_id in native_frames else preview_meta_for_asset(control),
        })

    timestamp = now_ms()
    token = f"tmp-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_urlsafe(8)}"
    title = f"临时批量预览 · {len(page_items)} 页"
    session = {
        "id": token,
        "title": title,
        "pageItems": page_items,
        "createdAt": timestamp,
        "expiresAt": timestamp + TEMP_REPORT_TTL_MS,
    }
    with TEMP_REPORT_LOCK:
        TEMP_REPORT_SESSIONS[token] = session
    return {
        "ok": True,
        "id": token,
        "url": f"/temp-reports/{token}/index.html",
        "pageCount": len(page_items),
        "expiresAt": session["expiresAt"],
    }


def temp_report_token_from_path(path):
    match = re.match(r"^/temp-reports/([^/]+)/?(?:index\.html)?$", path)
    return unquote(match.group(1)) if match else ""


def get_temp_report_session(token):
    cleanup_temp_report_sessions()
    with TEMP_REPORT_LOCK:
        return TEMP_REPORT_SESSIONS.get(token)


def touch_temp_report(token, ttl_ms=TEMP_REPORT_STALE_MS):
    timestamp = now_ms()
    with TEMP_REPORT_LOCK:
        session = TEMP_REPORT_SESSIONS.get(token)
        if not session:
            return {"ok": False, "error": "临时预览不存在或已释放", "id": token}
        session["expiresAt"] = timestamp + ttl_ms
        session["lastSeenAt"] = timestamp
        return {"ok": True, "id": token, "expiresAt": session["expiresAt"]}


def release_temp_report(token):
    with TEMP_REPORT_LOCK:
        existed = token in TEMP_REPORT_SESSIONS
        TEMP_REPORT_SESSIONS.pop(token, None)
    return {"ok": True, "released": existed, "id": token}


def copy_control_as_report_page(control, target_root, page_number=1, conn=None):
    source = asset_library_path(control)
    if not source or not source.exists():
        raise ValueError("页面素材文件不存在")
    if has_online_spark_storage(source):
        raise ValueError(UNPACKAGED_ERROR)
    target_dir = target_root / "pages" / f"page-{int(page_number):02d}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    with (db() if conn is None else nullcontext(conn)) as reader:
        frame = native_control_frames(reader, [control["id"]]).get(control["id"])
    if read_json_file(source.parent / "manifest.json").get("format") in {"minem-owned-page", "minem-owned-native-page"}:
        shutil.copytree(source.parent, target_dir)
        return (target_dir / source.name).relative_to(target_root).as_posix()
    if frame:
        native_source, number = frame
        write_native_deck_export(native_source, [number], target_dir / "index.html", target_dir, single_page=True)
    else:
        bundle = OfflineBundle(EXTRACTED, target_dir, excluded=report_export_excluded_path)
        return bundle.add(source).relative_to(target_root).as_posix()
    return f"pages/page-{int(page_number):02d}/index.html"


def copy_page_for_arrangement(conn, report, source, timestamp, staged):
    upload_root = (EXTRACTED / report["upload_id"]).resolve()
    if not report["upload_id"] or not upload_root.is_relative_to(EXTRACTED.resolve()):
        raise ValueError("汇报素材目录无效")
    token = secrets.token_hex(8)
    target = upload_root / "page-copies" / token
    staged.append(target)
    relative = copy_control_as_report_page(source, target, conn=conn)
    path = target / relative
    source_path = path.relative_to(upload_root).as_posix()
    control_id = f"{report['id']}-page-{token}"
    insert_control_asset(
        conn, asset_id=control_id, title=source["title"], usage="独立封装的汇报页面",
        tags=split_tags(source["tags"]), snippet=source["snippet"],
        asset_code=next_asset_code(conn, "control", "page", "html"), source_type="created-report-page",
        source_path=source_path, preview_url=f"/extracted/{report['upload_id']}/{source_path}",
        upload_id=report["upload_id"], source_hash=f"owned-page:{token}:{file_hash(path)}", created_at=timestamp,
    )
    refresh_upload_count(conn, report["upload_id"])
    return control_id


def created_report_page_asset_id(report_id, page_number, source_hash):
    digest = hashlib.sha1(f"{report_id}:{page_number}:{source_hash}".encode("utf-8")).hexdigest()[:10]
    return f"{slugify(report_id)}-p{int(page_number):02d}-{digest}"


def created_report_page_number(value, fallback):
    try:
        page_number = int(value)
        return page_number if page_number > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def register_created_report_pages(conn, *, report_id, report_code, report_title, target_root, manifest_pages, timestamp):
    created = []
    for index, item in enumerate(manifest_pages or [], start=1):
        page_number = created_report_page_number(item.get("display_page") or item.get("page"), index)
        source_rel = str(item.get("control_path") or item.get("path") or "").strip()
        if not source_rel:
            continue
        page_path = (Path(target_root) / source_rel).resolve()
        if not is_path_within(page_path, Path(target_root).resolve()) or not page_path.exists():
            continue
        page_digest = file_hash(page_path)
        source_hash = hashlib.sha1(f"created-report-page:{report_id}:{page_number}:{page_digest}".encode("utf-8")).hexdigest()
        existing = conn.execute(
            "select * from assets where source_hash = ? and asset_type = 'control' limit 1",
            (source_hash,),
        ).fetchone()
        if existing:
            control_id = existing["id"]
            control_code = existing["asset_code"]
        else:
            control_id = created_report_page_asset_id(report_id, page_number, source_hash)
            control_code = report_code_to_control_code(report_code, page_number) or next_asset_code(conn, "control", "page", "html")
            if conn.execute("select 1 from assets where asset_code = ? limit 1", (control_code,)).fetchone():
                control_code = next_asset_code(conn, "control", "page", "html")
            page_title = str(item.get("title") or "").strip() or f"{clean_report_title(report_title)} 第 {page_number} 页"
            source_code = str(item.get("control_asset_code") or item.get("source_code") or "").strip()
            tags = []
            usage = f"从汇报素材 {report_code} 自动登记的第 {page_number} 页"
            if source_code:
                usage += f"；来源页面素材：{source_code}"
            insert_control_asset(
                conn,
                asset_id=control_id,
                title=page_title,
                usage=usage,
                tags=tags,
                snippet=read_text_sample(page_path),
                asset_code=control_code,
                source_type="created-report-page",
                source_path=source_rel,
                preview_url=f"/extracted/{Path(target_root).name}/{source_rel}",
                upload_id=Path(target_root).name,
                source_hash=source_hash,
                created_at=timestamp,
            )
            created.append(control_id)
        attach_report_page_control(
            conn,
            report_id,
            page_number,
            control_id,
            str(item.get("title") or "").strip() or f"第{page_number}页",
            "创建汇报自动登记页面素材",
            replace=True,
        )
    if manifest_pages:
        refresh_upload_count(conn, Path(target_root).name)
    return created


def copy_report_thumbnail(source_id, target_id, source_fingerprint=""):
    source_thumb = THUMBNAILS / f"{source_id}.png"
    target_thumb = THUMBNAILS / f"{target_id}.png"
    if source_thumb.exists():
        target_thumb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_thumb, target_thumb)
        write_thumbnail_meta(target_id, source_fingerprint)


def insert_created_report_asset(conn, *, report_id, title, usage, tags, asset_code, source_type, source_path, preview_url, upload_id, source_hash, timestamp):
    conn.execute(
        """
        insert into assets
        (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, source_path, preview_url, upload_id, source_hash, version_group, version_no, version_parent_id, similarity_score, similarity_method, tag_seeded, created_at, updated_at)
        values (?, ?, 'report', ?, ?, ?, 'report', ?, 'html', '', ?, ?, ?, ?, ?, ?, 1, '', 1.0, '', 1, ?, ?)
        """,
        (
            report_id,
            title,
            usage,
            ",".join(tags),
            "",
            asset_code,
            source_type,
            source_path,
            preview_url,
            upload_id,
            source_hash,
            report_id,
            timestamp,
            timestamp,
        ),
    )


def report_cover_path(cover_id):
    if cover_id not in REPORT_COVER_IDS:
        raise ValueError("请选择可用的封面模板")
    private_root = RUNTIME_ROOT / "config" / "report-covers"
    custom = private_root / f"{cover_id}.webp"
    if custom.is_file() and custom.resolve().is_relative_to(private_root.resolve()):
        return custom
    return REPORT_COVERS / f"{cover_id}.webp"


def write_report_cover(target_root, cover_id):
    target = target_root / "pages" / "page-01"
    target.mkdir(parents=True)
    shutil.copyfile(report_cover_path(cover_id), target / "cover.webp")
    path = target / "index.html"
    path.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>封面</title>'
        '<style>html,body{margin:0;width:100%;height:100%;background:#080f1d}'
        'img{display:block;width:100%;height:100%;object-fit:contain}</style>'
        '<img src="cover.webp" width="1920" height="1080" alt="封面"></html>',
        encoding="utf-8",
    )
    (target / "manifest.json").write_text(json.dumps({
        "format": "minem-owned-page", "title": "封面", "resources": ["cover.webp"], "coverTemplate": cover_id,
    }, ensure_ascii=False), encoding="utf-8")
    return path.relative_to(target_root).as_posix()


def create_report_from_pages(page_ids, title="", note="", cover_id=DEFAULT_REPORT_COVER):
    if cover_id not in REPORT_COVER_IDS:
        return {"ok": False, "error": "请选择可用的封面模板"}
    with db() as conn:
        placeholders = ", ".join("?" for _ in page_ids)
        rows = conn.execute(
            f"select * from assets where asset_type = 'control' and id in ({placeholders})", page_ids
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        missing_ids = [page_id for page_id in page_ids if page_id not in by_id]
        if missing_ids:
            return {"ok": False, "error": f"页面素材不存在：{'、'.join(missing_ids[:3])}"}
        controls = [by_id[page_id] for page_id in page_ids]

    title = clean_report_title(title or controls[0]["title"])
    timestamp = now_ms()
    report_id = f"created-report-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(5)}"
    target_root = EXTRACTED / report_id
    preview_url = report_public_url(report_id)
    report_file = target_root / "index.html"
    page_items = []
    manifest_pages = []
    owns_directory = False
    try:
        target_root.mkdir()
        owns_directory = True
        cover_path = write_report_cover(target_root, cover_id)
        page_items.append({"title": "封面", "src": cover_path})
        manifest_pages.append({"display_page": 1, "title": "封面", "control_path": cover_path})
        with db() as conn:
            for number, control in enumerate(controls, 2):
                path = copy_control_as_report_page(control, target_root, number, conn=conn)
                page_items.append({"title": control["title"], "code": control["asset_code"], "src": path})
                manifest_pages.append({
                    "display_page": number, "title": control["title"], "control_asset_code": control["asset_code"],
                    "source_control_id": control["id"], "control_path": path,
                })

        audit = audit_dependency_closure(target_root)
        if audit["missing"] or audit["truncated"]:
            missing = "、".join(item["resolved"] for item in audit["missing"][:3])
            raise ValueError(f"页面素材缺少播放资源：{missing}" if missing else "页面素材的资源完整性检查未通过")

        report_file.write_text(report_viewer_html(title, page_items), encoding="utf-8")
        usage = f"正文来源：{controls[0]['asset_code']}。"
        if note:
            usage += f" 备注：{note}"
        with db() as conn:
            conn.execute("begin immediate")
            asset_code = next_asset_code(conn, "report", "report", "html")
            manifest = {
                "asset_type": "report", "asset_code": asset_code, "title": title, "entry": "index.html",
                "pages": manifest_pages, "cover_template": cover_id, "created_by": "MineM", "created_at": timestamp,
            }
            (target_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            relative = runtime_record_path(target_root, RUNTIME_ROOT)
            conn.execute(
                "insert into uploads (id, filename, stored_path, extract_path, file_count, asset_count, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                (report_id, title, relative, relative, sum(1 for path in target_root.rglob("*") if path.is_file()), 1, timestamp),
            )
            digest = f"trusted-report:{report_id}:{file_hash(report_file)}"
            insert_created_report_asset(
                conn, report_id=report_id, title=report_material_title(title), usage=usage, tags=[],
                asset_code=asset_code, source_type="created-report", source_path="index.html",
                preview_url=preview_url, upload_id=report_id, source_hash=digest, timestamp=timestamp,
            )
            page_ids = register_created_report_pages(
                conn, report_id=report_id, report_code=asset_code, report_title=title,
                target_root=target_root, manifest_pages=manifest_pages, timestamp=timestamp,
            )
            if len(page_ids) != len(manifest_pages):
                raise ValueError("汇报页面登记不完整")
            entry = validate_report_trusted_entry(conn, report_id, refresh=True)
            if not entry["ok"]:
                raise ValueError("汇报入口检查未通过")
    except (OSError, ValueError, sqlite3.Error) as error:
        if owns_directory:
            shutil.rmtree(target_root, ignore_errors=True)
        return {"ok": False, "error": str(error) if isinstance(error, ValueError) else "创建汇报失败，请重试"}

    invalidate_stats_cache()
    with db() as conn:
        rows = conn.execute("select * from assets where upload_id = ?", (report_id,)).fetchall()
    by_id = {row["id"]: row for row in rows}
    cover_page_id = page_ids[0]
    try:
        if generate_html_thumbnail(cover_page_id, target_root / cover_path, thumbnail_source_fingerprint(by_id[cover_page_id]), allow_text_fallback=False):
            copy_report_thumbnail(cover_page_id, report_id, thumbnail_source_fingerprint(by_id[report_id]))
    except OSError:
        pass
    for source, target_id in zip(controls, page_ids[1:]):
        try:
            copy_report_thumbnail(source["id"], target_id, thumbnail_source_fingerprint(by_id[target_id]))
        except OSError:
            pass
    with db() as conn:
        asset = add_version_counts(conn, [by_id[report_id]])[0]
    asset["trustedEntry"] = entry
    return {"ok": True, "asset": asset, "url": preview_url}


def extracted_url_to_path(url):
    clean_url = str(url or "").split("?", 1)[0]
    if not clean_url.startswith("/extracted/"):
        return None
    rel = unquote(clean_url.removeprefix("/extracted/")).replace("\\", "/")
    path = (EXTRACTED / rel).resolve()
    if not is_path_within(path, EXTRACTED):
        return None
    return path


class Handler(BaseHTTPRequestHandler):
    server_version = f"MineM/{PRODUCT_VERSION['version']}"

    def setup(self):
        self.request.settimeout(30)
        super().setup()

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.write_response_body(body)

    def send_binary(self, data, filename, content_type="application/zip"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{safe_download_name(filename)}"; filename*=UTF-8\'\'{quote(download_name(filename))}')
        self.end_headers()
        self.write_response_body(data)

    def write_response_body(self, body):
        try:
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def stream_response_file(self, path, byte_range=None):
        try:
            with Path(path).open("rb") as source:
                if byte_range is None:
                    shutil.copyfileobj(source, self.wfile, length=1024 * 1024)
                else:
                    start, end = byte_range
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining and (block := source.read(min(remaining, 1024 * 1024))):
                        self.wfile.write(block)
                        remaining -= len(block)
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def send_download_file(self, path, filename):
        path = Path(path)
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{safe_download_name(filename)}"; filename*=UTF-8\'\'{quote(download_name(filename))}')
        self.end_headers()
        self.stream_response_file(path)

    def send_html(self, html_text, status=200, cache_control=""):
        body = html_text.encode("utf-8")
        use_compression = len(body) >= 4096
        compressed = use_compression and bool(re.search(
            r"(?:^|,)\s*gzip\s*(?:;\s*q\s*=\s*(?:1(?:\.0+)?|0\.\d*[1-9]\d*))?\s*(?:,|$)",
            self.headers.get("Accept-Encoding", ""),
            re.IGNORECASE,
        ))
        if compressed:
            body = gzip.compress(body, compresslevel=3)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        if use_compression:
            self.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.write_response_body(body)

    def serve_file(self, path, embedded_preview=False):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        ctype = "image/webp" if path.suffix.lower() == ".webp" else mimetypes.guess_type(str(path))[0]
        ctype = ctype or "application/octet-stream"
        if embedded_preview and path.suffix.lower() in {".html", ".htm"}:
            try:
                html_text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
            else:
                self.send_html(inject_embedded_preview_style(html_text))
                return
        size = path.stat().st_size
        byte_range = None
        media = ctype.startswith(("video/", "audio/"))
        requested = self.headers.get("Range") if media else None
        if requested:
            match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", requested.strip())
            if match and (match[1] or match[2]):
                start = int(match[1]) if match[1] else max(0, size - int(match[2]))
                end = min(size - 1, int(match[2])) if match[1] and match[2] else size - 1
                if 0 <= start <= end:
                    byte_range = (start, end)
            if byte_range is None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if byte_range else 200)
        self.send_header("Content-Type", ctype)
        if media:
            self.send_header("Accept-Ranges", "bytes")
        if byte_range:
            start, end = byte_range
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1 if byte_range else size))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.stream_response_file(path, byte_range)

    def authorize_agent_api(self):
        if not agent_internal_api_enabled():
            self.send_json({"ok": False, "error": "Agent internal API is disabled"}, 404)
            return False
        token = agent_internal_api_token()
        if not token:
            self.send_json({"ok": False, "error": "Agent internal API token is not configured"}, 403)
            return False
        provided = (self.headers.get("X-MineM-Agent-Token") or "").strip()
        bearer = (self.headers.get("Authorization") or "").strip()
        if secrets.compare_digest(provided, token) or secrets.compare_digest(bearer, f"Bearer {token}"):
            return True
        self.send_json({"ok": False, "error": "Agent internal API unauthorized"}, 401)
        return False

    def resolve_extracted_file(self, rel):
        rel = unquote(rel).replace("\\", "/")
        path = (EXTRACTED / rel).resolve()
        if is_path_within(path, EXTRACTED) and path.exists() and path.is_file():
            return path

        parts = rel.split("/")
        if len(parts) >= 3:
            upload_id = parts[0]
            rest = "/".join(parts[1:])
            marker = "/assets/"
            if marker in f"/{rest}":
                asset_rel = f"/{rest}".split(marker, 1)[1]
                fallback = (EXTRACTED / upload_id / "assets" / asset_rel).resolve()
                if is_path_within(fallback, EXTRACTED / upload_id / "assets") and fallback.exists() and fallback.is_file():
                    return fallback
        return path

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/version":
            self.send_json({"ok": True, "release": PRODUCT_VERSION})
            return
        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/exports"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/exports").strip("/"))
            self.send_json({"ok": True, "tasks": REPORT_EXPORT_TASK_STORE.list(report_id)})
            return

        if parsed.path.startswith("/api/report-exports/") and parsed.path.endswith("/download"):
            task_id = unquote(parsed.path.removeprefix("/api/report-exports/").removesuffix("/download").strip("/"))
            task = REPORT_EXPORT_TASK_STORE.get(task_id, include_private=True)
            if not task:
                self.send_json({"ok": False, "error": "导出任务不存在"}, 404)
                return
            if task["status"] != "completed":
                self.send_json({"ok": False, "error": "导出尚未完成"}, 409)
                return
            output = Path(task.get("outputPath") or "").resolve()
            if not is_path_within(output, REPORT_EXPORTS) or not output.exists():
                self.send_json({"ok": False, "error": "导出文件已失效，请重新导出"}, 404)
                return
            self.send_download_file(output, task.get("filename") or output.name)
            return
        if parsed.path.startswith("/api/report-exports/"):
            task_id = unquote(parsed.path.removeprefix("/api/report-exports/").strip("/"))
            if not task_id or "/" in task_id:
                self.send_json({"ok": False, "error": "任务地址无效"}, 400)
                return
            task = REPORT_EXPORT_TASK_STORE.get(task_id)
            if not task:
                self.send_json({"ok": False, "error": "导出任务不存在"}, 404)
                return
            self.send_json({"ok": True, "task": task})
            return
        if parsed.path.startswith("/pages/") and parsed.path.endswith("/index.html"):
            control_id = unquote(parsed.path.removeprefix("/pages/").removesuffix("/index.html").strip("/"))
            if not control_id or "/" in control_id:
                self.send_error(404)
                return
            with db() as conn:
                control = conn.execute(
                    "select * from assets where id = ? and asset_type = 'control'",
                    (control_id,),
                ).fetchone()
                frame = native_control_frames(conn, [control_id]).get(control_id) if control else None
            if not control:
                self.send_error(404)
                return
            source = asset_library_path(control)
            manifest = read_json_file(source.parent / "manifest.json") if source else {}
            if manifest.get("format") == "minem-owned-native-page" and read_native_deck(source):
                frame = (source, 1)
            if frame:
                source, number = frame
                cover_title = control["title"] if parse_qs(parsed.query).get("cover") == ["1"] else None
                self.send_html(online_native_deck(source, [number], single_page=True, cover_title=cover_title), cache_control="no-store")
                return
            source_url = canonical_preview_url(control)
            self.send_html(
                report_viewer_html(control["title"] or f"页面 · {control_id}", [{
                    "title": control["title"],
                    "code": control["asset_code"],
                    "src": source_url,
                    "canvas": preview_meta_for_asset(dict(control)),
                }]),
                cache_control="no-store, max-age=0",
            )
            return

        if parsed.path.startswith("/reports/") and parsed.path.endswith("/index.html"):
            report_id = unquote(parsed.path.removeprefix("/reports/").removesuffix("/index.html").strip("/"))
            if not report_id or "/" in report_id:
                self.send_error(404)
                return
            result, page_items = report_public_page_items(report_id)
            if not result.get("ok"):
                self.send_html(f"<!doctype html><meta charset='utf-8'><body>{html.escape(result.get('error') or '无法加载汇报')}</body>", 404)
                return
            with db() as conn:
                report = conn.execute("select title from assets where id = ? and asset_type = 'report'", (report_id,)).fetchone()
            title = report["title"] if report else f"汇报 · {report_id}"
            if parse_qs(parsed.query).get("cover") == ["1"]:
                cover = page_items[:1]
                image = packaged_page_cover_path(extracted_url_to_path(cover[0]["src"])) if cover else None
                if image:
                    url = "/extracted/" + quote(image.relative_to(EXTRACTED.resolve()).as_posix(), safe="/")
                    document = (
                        '<!doctype html><meta charset=utf-8><style>html,body{margin:0;height:100%;background:#0b1020}'
                        'img{display:block;width:100%;height:100%;object-fit:contain}</style>'
                        f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(title, quote=True)}">'
                    )
                elif native := native_deck_view(cover):
                    document = online_native_deck(*native, single_page=True, cover_title=title)
                else:
                    document = report_viewer_html(title, cover)
            else:
                document = online_native_deck(*native) if (native := native_deck_view(page_items)) else report_viewer_html(title, page_items)
            self.send_html(document, cache_control="no-store, max-age=0")
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/arrangement/viewer"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/arrangement/viewer").strip("/")
            result, page_items = report_public_page_items(unquote(report_id))
            if not result.get("ok"):
                self.send_html(f"<!doctype html><meta charset='utf-8'><body>{html.escape(result.get('error') or '无法加载汇报编排')}</body>", 404)
                return
            document = online_native_deck(*native) if (native := native_deck_view(page_items)) else report_viewer_html(f"汇报编排 · {result['reportId']}", page_items)
            self.send_html(document, cache_control="no-store, max-age=0")
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/arrangement"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/arrangement").strip("/")
            result = report_arrangement_payload(unquote(report_id))
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/export"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").removesuffix("/export").strip("/"))
            data, error, filename = export_asset_zip(asset_id)
            if error:
                self.send_json({"ok": False, "error": error}, 400)
                return
            self.send_binary(data, filename)
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/history"):
            asset_id = parsed.path.removeprefix("/api/assets/").removesuffix("/history").strip("/")
            result = get_asset_history(unquote(asset_id))
            self.send_json(result, 200 if result.get("ok") else 404)
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/versions"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").removesuffix("/versions").strip("/"))
            with db() as conn:
                asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
                if not asset:
                    self.send_json({"ok": False, "error": "素材不存在"}, 404)
                    return
                group_id = asset["version_group"] or asset["id"]
                rows = conn.execute(
                    "select * from assets where version_group = ? order by version_no desc, created_at desc, asset_code desc",
                    (group_id,),
                ).fetchall()
                assets = add_version_counts(conn, rows)
            self.send_json({"ok": True, "groupId": group_id, "versions": assets})
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/lineage"):
            asset_id = parsed.path.removeprefix("/api/assets/").removesuffix("/lineage").strip("/")
            result = asset_lineage_details(unquote(asset_id))
            self.send_json(result, 200 if result.get("ok") else 404)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/pages"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/pages").strip("/")
            result = get_report_page_slots(unquote(report_id))
            self.send_json(result, 200 if result.get("ok") else 404)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/trusted-entry"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/trusted-entry").strip("/")
            result = validate_report_trusted_entry_by_id(unquote(report_id))
            self.send_json(result, 200 if result.get("ok") else 404)
            return

        if parsed.path == "/api/case-groups":
            roots, _, _ = load_import_sources()
            with db() as conn:
                rows = conn.execute(
                    """
                    select * from assets
                    where asset_type in ('report', 'control') and version_parent_id = ''
                    order by updated_at desc, created_at desc, asset_code desc
                    """
                ).fetchall()
                asset_by_code = {}
                for row in rows:
                    code = row["asset_code"] or ""
                    if code and code not in asset_by_code:
                        asset_data = dict(row)
                        asset_by_code[code] = {
                            "title": row["title"],
                            "previewUrl": canonical_preview_url(row),
                            "thumbnailUrl": asset_thumbnail_url(asset_data),
                            "updatedAt": row["updated_at"],
                        }
                resource_paths = [
                    f"{row['source_path']} {row['preview_url']}"
                    for row in conn.execute(
                        "select source_path, preview_url from assets where asset_type = 'resource' and version_parent_id = ''"
                    ).fetchall()
                ]
            groups = load_case_groups(EXTRACTED, roots, asset_by_code, resource_paths)
            self.send_json({"ok": True, "caseGroups": groups, "total": len(groups)})
            return

        if parsed.path.startswith("/api/assets/"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").strip("/"))
            if asset_id and "/" not in asset_id:
                with db() as conn:
                    row = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
                    if not row:
                        self.send_json({"ok": False, "error": "素材不存在"}, 404)
                        return
                    asset = add_version_counts(conn, [row])[0]
                    if has_online_spark_storage(asset_library_path(row)):
                        asset["packageIssue"] = UNPACKAGED_ERROR
                    if asset.get("asset_type") == "report":
                        needs_refresh = not (row["trusted_checked_at"] if "trusted_checked_at" in row.keys() else 0)
                        asset["trustedEntry"] = validate_report_trusted_entry(conn, asset["id"], refresh=needs_refresh)
                self.send_json({"ok": True, "asset": asset})
                return

        if parsed.path == "/api/assets":
            query = parse_qs(parsed.query)
            with db() as conn:
                payload = list_assets_response(
                    conn,
                    query,
                    add_version_counts=add_version_counts,
                    pipeline_summary=pipeline_summary,
                    categories=CATEGORIES,
                    asset_types=ASSET_TYPES,
                    resource_kinds=RESOURCE_KINDS,
                )
            self.send_json(payload)
            return
        if parsed.path == "/api/stats":
            with db() as conn:
                payload = stats_payload(conn)
            self.send_json(payload)
            return
        if parsed.path == "/api/import-sources":
            roots, excludes, max_depth = load_import_sources()
            self.send_json({"roots": [str(root) for root in roots], "excludes": sorted(excludes), "maxDepth": max_depth})
            return

        if parsed.path == "/api/import-tasks":
            self.send_json({"ok": True, "tasks": list_import_tasks()})
            return

        if parsed.path == "/api/internal/agent/map":
            if not self.authorize_agent_api():
                return
            query = parse_qs(parsed.query)
            focus = query.get("focus", [""])[0].strip()
            self.send_json(AGENT_RUNTIME.map(focus=focus))
            return

        if parsed.path == "/api/internal/agent/audit":
            if not self.authorize_agent_api():
                return
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", ["50"])[0])
            except (TypeError, ValueError):
                limit = 50
            self.send_json(AGENT_RUNTIME.audit(limit=max(1, min(limit, 200))))
            return

        if parsed.path.startswith("/api/import-tasks/"):
            task_id = parsed.path.removeprefix("/api/import-tasks/").strip("/")
            task = get_import_task(task_id)
            if not task:
                self.send_json({"ok": False, "error": "任务不存在"}, 404)
                return
            self.send_json({"ok": True, "task": task})
            return

        temp_token = temp_report_token_from_path(parsed.path)
        if temp_token:
            session = get_temp_report_session(temp_token)
            if not session:
                self.send_html("<!doctype html><meta charset='utf-8'><title>临时预览已释放</title><body style='font-family:sans-serif;padding:48px'>临时批量预览已关闭或过期。</body>", 404)
                return
            touch_temp_report(temp_token)
            self.send_html(report_viewer_html(
                session["title"],
                session["pageItems"],
                f"/api/temp-reports/{temp_token}/release",
            ))
            return

        if parsed.path.startswith("/extracted/"):
            rel = parsed.path.removeprefix("/extracted/")
            # Old copied links should follow the current public report entry
            # after an arrangement is confirmed.  Only exact report source
            # entries redirect; linked page assets remain untouched.
            decoded_rel = unquote(rel).strip("/")
            if decoded_rel.startswith("_history/"):
                snapshot = history_snapshot_file(decoded_rel)
                if snapshot:
                    self.serve_file(snapshot, embedded_preview=parse_qs(parsed.query).get("embed", [""])[0] == "1")
                else:
                    self.send_error(404)
                return
            parts = decoded_rel.split("/", 1)
            source_preview_url = f"/extracted/{decoded_rel}"
            if len(parts) == 2:
                with db() as conn:
                    arranged_report = conn.execute(
                        """
                        select id from assets
                        where asset_type = 'report'
                          and (preview_url = ? or (upload_id = ? and source_path = ?))
                          and preview_url like '/reports/%/index.html'
                        limit 1
                        """,
                        (source_preview_url, parts[0], parts[1]),
                    ).fetchone()
                if arranged_report:
                    self.send_response(302)
                    self.send_header("Location", report_public_url(arranged_report["id"]))
                    self.end_headers()
                    return
                    # Kept inside the report branch intentionally: report
                    # sources always take precedence over a same-path control.
            # Direct links to a single page must enter the platform viewer so
            # exported fixed-size layouts are fitted once, consistently. The
            # embedded request used by the viewer stays raw to prevent nesting.
            if parse_qs(parsed.query).get("embed", [""])[0] != "1" and len(parts) == 2:
                with db() as conn:
                    control = conn.execute(
                        """
                        select id from assets
                        where asset_type = 'control'
                          and (preview_url = ? or (upload_id = ? and source_path = ?))
                        limit 1
                        """,
                        (source_preview_url, parts[0], parts[1]),
                    ).fetchone()
                if control:
                    self.send_response(302)
                    self.send_header("Location", control_public_url(control["id"]))
                    self.end_headers()
                    return
            path = self.resolve_extracted_file(rel)
            if is_path_within(path, EXTRACTED):
                # Platform Preview Shell owns copy/refresh/fullscreen controls.
                # Never inject a second toolbar into source HTML.
                self.serve_file(
                    path,
                    embedded_preview=parse_qs(parsed.query).get("embed", [""])[0] == "1",
                )
                return
            self.send_error(403)
            return

        if parsed.path.startswith("/thumbnails/"):
            rel = unquote(parsed.path.removeprefix("/thumbnails/"))
            path = (THUMBNAILS / rel).resolve()
            if is_path_within(path, THUMBNAILS):
                self.serve_file(path)
                return
            self.send_error(403)
            return

        if parsed.path.startswith("/report-covers/"):
            name = parsed.path.removeprefix("/report-covers/")
            if name.endswith(".webp") and name.removesuffix(".webp") in REPORT_COVER_IDS:
                self.serve_file(report_cover_path(name.removesuffix(".webp")))
            else:
                self.send_error(404)
            return

        rel = parsed.path.lstrip("/") or "index.html"
        path = (PUBLIC / rel).resolve()
        if is_path_within(path, PUBLIC):
            self.serve_file(path)
            return
        self.send_error(403)

    def do_POST(self):
        try:
            self.handle_post()
        except RequestBodyError as error:
            self.close_connection = True
            self.send_json({"ok": False, "error": str(error)}, error.status)

    def handle_post(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/exports"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/exports").strip("/"))
            if not report_id or "/" in report_id:
                self.send_json({"ok": False, "error": "汇报地址无效"}, 400)
                return
            payload = read_json_request(self.headers, self.rfile)
            result = create_report_export_task(report_id, payload.get("format"))
            self.send_json(result, 202 if result.get("ok") else 400)
            return
        if parsed.path == "/api/temp-reports":
            payload = read_json_request(self.headers, self.rfile)
            result = create_temp_report(payload)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/temp-reports/") and parsed.path.endswith("/heartbeat"):
            token = unquote(parsed.path.removeprefix("/api/temp-reports/").removesuffix("/heartbeat").strip("/"))
            result = touch_temp_report(token)
            self.send_json(result, 200 if result.get("ok") else 404)
            return

        if parsed.path.startswith("/api/temp-reports/") and parsed.path.endswith("/release"):
            token = unquote(parsed.path.removeprefix("/api/temp-reports/").removesuffix("/release").strip("/"))
            self.send_json(release_temp_report(token))
            return

        if parsed.path == "/api/assets":
            payload = read_json_request(self.headers, self.rfile)
            timestamp = now_ms()
            try:
                with db() as conn:
                    result = save_asset_metadata(
                        conn, payload, timestamp=timestamp,
                        make_id=lambda title: f"{slugify(title)}-{timestamp}-{secrets.token_hex(4)}",
                        next_asset_code=next_asset_code, asset_types=ASSET_TYPES, media_kinds=MEDIA_KINDS,
                    )
            except ValueError as error:
                self.send_json({"ok": False, "error": str(error)}, 400)
                return
            invalidate_stats_cache()
            self.send_json(result)
            return

        if parsed.path == "/api/auto-import":
            self.send_json(auto_import_sources())
            return

        if parsed.path == "/api/sync-report-materials":
            changed = sync_report_materials_from_extracted()
            self.send_json({"ok": True, "changed": changed})
            return

        if parsed.path == "/api/merge-similar":
            self.send_json(merge_similar_resource_versions())
            return

        if parsed.path == "/api/assets/manual-merge":
            payload = read_json_request(self.headers, self.rfile)
            result = manual_merge_asset_versions(payload)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/internal/agent/analyze":
            if not self.authorize_agent_api():
                return
            payload = read_json_request(self.headers, self.rfile)
            task = str(payload.get("task") or "").strip()
            if not task:
                self.send_json({"ok": False, "error": "缺少 task"}, 400)
                return
            self.send_json(AGENT_RUNTIME.analyze(task, focus=str(payload.get("focus") or "")))
            return

        if parsed.path == "/api/internal/agent/checkpoint":
            if not self.authorize_agent_api():
                return
            payload = read_json_request(self.headers, self.rfile)
            self.send_json(AGENT_RUNTIME.checkpoint(
                label=str(payload.get("label") or ""),
                task=str(payload.get("task") or ""),
            ))
            return

        if parsed.path == "/api/internal/agent/validate":
            if not self.authorize_agent_api():
                return
            payload = read_json_request(self.headers, self.rfile)
            checks = payload.get("checks")
            if isinstance(checks, str):
                checks = [checks]
            if checks is not None and not isinstance(checks, list):
                self.send_json({"ok": False, "error": "checks 必须是数组或字符串"}, 400)
                return
            self.send_json(AGENT_RUNTIME.validate(
                checks=checks,
                base_url=str(payload.get("baseUrl") or "http://127.0.0.1:8790"),
            ))
            return

        if parsed.path == "/api/reports":
            try:
                payload = read_json_request(self.headers, self.rfile)
                page_ids = payload.get("pageIds", [payload.get("pageId")])
                if not isinstance(page_ids, list) or not page_ids or any(
                    not isinstance(page_id, str) or not page_id.strip() for page_id in page_ids
                ):
                    raise ValueError
                title, note = payload.get("title", ""), payload.get("note", "")
                cover_id = payload.get("coverTemplateId", DEFAULT_REPORT_COVER)
                if not isinstance(title, str) or not isinstance(note, str) or not isinstance(cover_id, str):
                    raise ValueError
            except ValueError:
                self.send_json({"ok": False, "error": "请提供有效的页面素材与汇报信息"}, 400)
                return
            result = create_report_from_pages([page_id.strip() for page_id in page_ids], title.strip(), note.strip(), cover_id)
            self.send_json(result, 201 if result.get("ok") else 400)
            return

        if parsed.path == "/api/import-tasks/drive":
            if self.headers.get_content_type() != "application/json":
                self.send_json({"ok": False, "error": "请以 JSON 格式提交飞书链接"}, 415)
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{self.headers.get('Host')}", f"https://{self.headers.get('Host')}"}:
                self.send_json({"ok": False, "error": "请在 MineM 内提交飞书链接"}, 403)
                return
            try:
                payload = read_json_request(self.headers, self.rfile, max_bytes=24_000)
                links = payload.get("links")
                if not isinstance(links, list) or not 1 <= len(links) <= MAX_DRIVE_LINKS:
                    raise ValueError(f"每次可添加 1 至 {MAX_DRIVE_LINKS} 个飞书文件夹链接")
                tokens = {}
                for index, link in enumerate(links, 1):
                    try:
                        token = parse_drive_folder_link(link)
                        address = urlparse(link.strip())
                        source_url = f"https://{address.netloc}/drive/folder/{token}"
                        tokens.setdefault(token, (index, source_url))
                    except ValueError:
                        raise ValueError(f"第 {index} 条链接需为飞书云空间文件夹的 HTTPS 链接") from None
            except (TypeError, ValueError) as error:
                self.send_json({"ok": False, "error": str(error)}, 400)
                return
            root = drive_import_queue(RUNTIME_ROOT)
            if not drive_worker_alive(root):
                self.send_json({"ok": False, "error": "本机飞书导入服务未启动，请启动后重试"}, 503)
                return
            description = str(payload.get("description") or "").strip()[:1000]
            try:
                tasks = [
                    enqueue_drive_import(root, token, index, description, source_url)
                    for token, (index, source_url) in tokens.items()
                ]
            except (OSError, sqlite3.Error):
                self.send_json({"ok": False, "error": "无法写入后台导入队列，请检查本机存储"}, 503)
                return
            self.send_json({"ok": True, "tasks": tasks}, 202)
            return

        if parsed.path == "/api/import-tasks":
            request_content_length(self.headers, MAX_UPLOAD_REQUEST_BYTES)
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            })
            file_item = form["file"] if "file" in form else None
            if file_item is None or not file_item.filename:
                self.send_json({"ok": False, "error": "没有收到导入文件"}, 400)
                return
            original = Path(file_item.filename).name
            suffix = Path(original).suffix.lower()
            if suffix not in IMPORT_SUFFIXES:
                self.send_json({"ok": False, "error": "仅支持 HTML、ZIP、图片、SVG、GIF 或视频文件"}, 400)
                return
            task_id = f"task-{time.strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1((original + str(time.time())).encode()).hexdigest()[:8]}"
            upload_id = f"import-{time.strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1((original + task_id).encode()).hexdigest()[:8]}"
            stored = UPLOADS / f"{upload_id}{suffix}"
            try:
                copy_limited_stream(file_item.file, stored)
            except UploadLimitError as error:
                self.send_json({"ok": False, "error": str(error)}, 413)
                return
            content_hash = file_hash(stored)
            with db() as conn:
                existing_upload = conn.execute(
                    """
                    select u.id from uploads u
                    where u.content_hash = ?
                      and exists(select 1 from assets a where a.upload_id = u.id)
                    order by u.created_at desc
                    limit 1
                    """,
                    (content_hash,),
                ).fetchone()
            if existing_upload:
                result = import_result_for_upload(existing_upload["id"])
                stored.unlink(missing_ok=True)
                spark_root = spark_package_root(EXTRACTED / existing_upload["id"]) if suffix in ZIP_SUFFIXES else None
                if has_online_spark_storage(extracted_url_to_path(result.get("previewUrl"))) or (
                    spark_root and has_online_spark_storage(spark_root / "index.html")
                ):
                    self.send_json({"ok": False, "error": UNPACKAGED_ERROR}, 400)
                    return
                timestamp = now_ms()
                task = create_import_task({
                    "id": task_id,
                    "status": "success",
                    "progress": 100,
                    "message": "相同素材已存在，已复用历史批次",
                    "fileName": original,
                    "uploadId": existing_upload["id"],
                    "assetId": result.get("assetId", ""),
                    "assetCode": result.get("assetCode", ""),
                    "assetTitle": result.get("assetTitle", ""),
                    "assetType": result.get("assetType", ""),
                    "previewUrl": result.get("previewUrl", ""),
                    "createdAt": timestamp,
                    "updatedAt": timestamp,
                })
                self.send_json({"ok": True, "task": task, "reused": True}, 200)
                return
            description = form.getfirst("description", "").strip() if hasattr(form, "getfirst") else ""
            task = {
                "id": task_id,
                "status": "queued",
                "progress": 4,
                "message": "等待导入",
                "fileName": original,
                "fileCount": 0,
                "assetCount": 0,
                "thumbnailCount": 0,
                "uploadId": upload_id,
                "assetId": "",
                "assetCode": "",
                "assetTitle": "",
                "assetType": "",
                "previewUrl": "",
                "error": "",
                "createdAt": now_ms(),
                "updatedAt": now_ms(),
                "storedPath": runtime_record_path(stored, RUNTIME_ROOT),
            }
            created_task = create_import_task(task)
            worker = threading.Thread(
                target=run_import_task,
                args=(task_id, str(stored), original, upload_id, description, content_hash),
                daemon=True,
            )
            worker.start()
            self.send_json({"ok": True, "task": created_task}, 202)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/arrangement"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/arrangement").strip("/")
            payload = read_json_request(self.headers, self.rfile)
            result = update_report_arrangement(unquote(report_id), payload)
            status = 200 if result.get("ok") else 409 if result.get("code") == "ARRANGEMENT_CONFLICT" else 400
            self.send_json(result, status)
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/title"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").removesuffix("/title").strip("/"))
            payload = read_json_request(self.headers, self.rfile)
            result = update_asset_title(asset_id, payload.get("title", ""))
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/pages"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/pages").strip("/"))
            payload = read_json_request(self.headers, self.rfile)
            pages = payload.get("pages") or payload.get("page_numbers") or payload.get("page_number")
            result = upsert_report_page_slots(
                report_id,
                pages,
                payload.get("title_prefix", ""),
                payload.get("note", ""),
            )
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/controls"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/controls").strip("/"))
            payload = read_json_request(self.headers, self.rfile)
            if payload.get("page_numbers") is not None or payload.get("pages") is not None:
                pages = payload.get("page_numbers") if payload.get("page_numbers") is not None else payload.get("pages")
                result = import_report_pages_as_controls(report_id, pages, payload.get("title_prefix", ""))
            else:
                try:
                    page_number = int(payload.get("page_number", 1))
                except (TypeError, ValueError):
                    self.send_json({"ok": False, "error": "页码必须是数字"}, 400)
                    return
                result = import_report_page_as_control(report_id, page_number, payload.get("title", ""))
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/uploads":
            # Legacy synchronous ZIP import bypassed dependency validation and
            # could publish partial assets. Keep it closed so every new import
            # uses the guarded asynchronous task pipeline.
            self.send_json({"ok": False, "error": "该旧导入入口已停用，请使用 /api/import-tasks"}, 410)
            return

        self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/temp-reports/"):
            token = unquote(parsed.path.removeprefix("/api/temp-reports/").strip("/"))
            self.send_json(release_temp_report(token))
            return

        if parsed.path.startswith("/api/assets/"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").strip())
            if not asset_id:
                self.send_json({"ok": False, "error": "缺少素材 ID"}, 400)
                return
            with db() as conn:
                asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
                if not asset:
                    self.send_json({"ok": False, "error": "素材不存在"}, 404)
                    return
                group_id = asset["version_group"] or asset["id"]
                targets = conn.execute("select * from assets where version_group = ? or id = ?", (group_id, asset_id)).fetchall() if not asset["version_parent_id"] else [asset]
                target_ids = [target["id"] for target in targets]
                affected_report_ids = set()
                if target_ids:
                    placeholders = ",".join("?" for _ in target_ids)
                    affected_report_ids.update(
                        row["report_id"]
                        for row in conn.execute(
                            f"select distinct report_id from report_page_slots where control_id in ({placeholders})",
                            target_ids,
                        ).fetchall()
                        if row["report_id"] not in target_ids
                    )
                    affected_report_ids.update(
                        row["report_id"]
                        for row in conn.execute(
                            f"select distinct report_id from report_page_candidates where control_id in ({placeholders})",
                            target_ids,
                        ).fetchall()
                        if row["report_id"] not in target_ids
                    )
                removed_file = False
                upload_ids = set()
                for target in targets:
                    removed_file = delete_library_file(target, conn) or removed_file
                    removed_file = delete_asset_thumbnail(target["id"]) or removed_file
                    if target["upload_id"]:
                        upload_ids.add(target["upload_id"])
                conn.executemany("delete from assets where id = ?", [(target["id"],) for target in targets])
                delete_asset_history_files(conn, [target["id"] for target in targets])
                conn.executemany("delete from report_page_slots where report_id = ?", [(target["id"],) for target in targets])
                conn.executemany("delete from report_page_candidates where report_id = ?", [(target["id"],) for target in targets])
                conn.executemany("delete from report_page_candidates where control_id = ?", [(target["id"],) for target in targets])
                conn.executemany(
                    "update report_page_slots set control_id = '', status = 'planned', updated_at = ? where control_id = ?",
                    [(now_ms(), target["id"]) for target in targets],
                )
                for upload_id in upload_ids:
                    refresh_upload_count(conn, upload_id)
                    removed_file = cleanup_empty_created_upload(conn, upload_id) or removed_file
                for report_id in affected_report_ids:
                    if conn.execute("select 1 from assets where id = ? and asset_type = 'report'", (report_id,)).fetchone():
                        validate_report_trusted_entry(conn, report_id, refresh=True)
                invalidate_stats_cache()
            self.send_json({
                "ok": True,
                "id": asset_id,
                "assetCode": asset["asset_code"],
                "removedFile": removed_file,
                "deletedCount": len(targets),
            })
            return

        self.send_error(404)


def local_service_owner(host, port):
    return {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "cwd": str(ROOT),
        "startedAt": now_ms(),
        "docker": Path("/.dockerenv").exists(),
    }


def describe_instance_owner(owner):
    try:
        data = json.loads(owner)
    except (TypeError, ValueError):
        return f"PID {owner or 'unknown'}"
    if not isinstance(data, dict):
        return f"PID {owner or 'unknown'}"
    pid = data.get("pid") or "unknown"
    host = data.get("host") or "unknown"
    port = data.get("port") or "unknown"
    mode = "Docker" if data.get("docker") else "本地"
    return f"{mode} PID {pid}，地址 {host}:{port}"


def assert_service_port_available(host, port):
    if truthy_env("MINEM_SKIP_PORT_PRECHECK"):
        return
    probes = ["127.0.0.1"] if host in {"", "0.0.0.0", "::", "localhost"} else [host]
    for probe in probes:
        try:
            with socket.create_connection((probe, int(port)), timeout=0.25):
                raise RuntimeError(
                    f"{probe}:{port} 已有服务在响应。请先停止旧的 MineM / Docker 实例，再启动当前服务"
                )
        except ConnectionRefusedError:
            continue
        except TimeoutError:
            continue
        except OSError:
            continue


def acquire_instance_lock(host="", port=0):
    """Allow only one local MineM process to own the shared SQLite database."""
    global INSTANCE_LOCK_HANDLE
    DATA.mkdir(parents=True, exist_ok=True)
    lock_path = DATA / "minem.server.lock"
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.seek(0)
        owner = handle.read().strip() or "unknown"
        handle.close()
        raise RuntimeError(
            "MineM 已有实例在使用同一份数据目录"
            f"（{describe_instance_owner(owner)}）。请勿同时启动本地 server.py 和 Docker 服务"
        ) from error
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps(local_service_owner(host, port), ensure_ascii=False))
    handle.flush()
    INSTANCE_LOCK_HANDLE = handle


def main():
    port = int(os.environ.get("PORT", "8790"))
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        assert_service_port_available(host, port)
        acquire_instance_lock(host, port)
    except RuntimeError as error:
        print(f"MineM 启动失败：{error}", file=sys.stderr)
        raise SystemExit(2) from error
    init_db()
    threading.Thread(target=drive_import_loop, name="minem-drive-import", daemon=True).start()
    if os.environ.get("AUTO_IMPORT_ON_START", "0") != "0":
        result = auto_import_sources()
        print(f"Auto import: scanned {result['scanned']} files, added {result['assetCount']} assets")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Material Library: http://{host}:{port}/")
    print(f"Database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
