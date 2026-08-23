#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from collections import defaultdict, OrderedDict
from contextlib import contextmanager
from functools import lru_cache
import fcntl
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import runpy
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import zipfile

from minem.assets import list_assets_response
from minem.asset_deletion import (
    AssetDeletionError,
    apply_asset_deletion_plan,
    build_asset_deletion_plan,
)
from minem.case_deletion import (
    apply_case_group_deletion_plan,
    build_case_group_deletion_plan,
)
from minem.agent import AgentRuntime
from minem.case_groups import (
    case_group_asset_codes,
    case_group_control_codes,
    case_group_manifest_paths,
    load_case_groups,
)
from minem.db import (
    SCHEMA_MIGRATIONS,
    connect_database,
    initialize_database,
)
from minem.html_splitter import (
    build_control_html as split_control_html,
    detect_report_page_count as split_detect_report_page_count,
    extract_control_page_node as split_control_page_node,
    extract_page_node_spans as split_page_node_spans,
    extract_page_nodes as split_page_nodes,
    is_manifest_driven_report as split_manifest_driven_report,
    replace_report_page_node as split_replace_report_page_node,
    sync_manifest_viewer_pages as split_sync_manifest_viewer_pages,
    viewer_pages_array_count as split_viewer_pages_array_count,
)
from minem.html_safety import json_for_html_script
from minem.presenter_mode import (
    attach_presenter_notes,
    audience_mode_url,
    presenter_mode_url,
    render_audience_view,
    render_presenter_console,
)
from minem.html_dependencies import (
    audit_dependency_closure,
    normalize_ephemeral_runtime_references,
    write_dependency_audit,
)
from minem.imports import (
    auto_import_sources as run_auto_import_sources,
    copy_html_dependency_bundle,
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
from minem.import_tasks import ImportTaskStore
from minem.jobs import ChannelConfig, JobQueueFullError, JobRuntime
from minem.page_duplicates import (
    FINGERPRINT_VERSION as PAGE_FINGERPRINT_VERSION,
    attach_duplicate_version,
    backfill_page_fingerprints,
    is_auto_reusable_visual,
    refresh_asset_fingerprint,
    thumbnail_difference,
)
from minem.tag_tasks import (
    changed_asset_ids as tag_changed_asset_ids,
    create_task as create_tag_analysis_task_record,
    ensure_schema as ensure_tag_task_schema,
    public_task as public_tag_analysis_task,
    recover_interrupted as recover_interrupted_tag_tasks,
    run_task as run_tag_analysis_task_record,
    taxonomy_definitions,
    update_taxonomy_definitions,
)
from minem.tag_taxonomy import taxonomy_payload
from minem.report_exports import ReportExportTaskStore
from minem.security import (
    API_TOKEN_HEADER,
    browser_write_origin_allowed,
    request_token,
    rotate_session_token,
    token_matches,
)
from minem.lineage import (
    asset_lineage_details as build_asset_lineage_details,
    attach_source_batches as hydrate_source_batches,
    pipeline_summary as build_pipeline_summary,
    upload_batch_summaries as summarize_upload_batches,
)
from minem.paths import is_path_within
from minem.reports import (
    attach_report_page_control as attach_slot_control,
    get_report_page_slots as load_report_page_slots,
    normalize_page_numbers as normalize_report_page_numbers,
    register_report_page_candidate as register_slot_candidate,
    upsert_report_page_slots as save_report_page_slots,
)
from minem.report_package_importer import (
    copy_page_variant as import_copy_page_variant,
    discover_report_package_roots as import_discover_report_package_roots,
    load_report_package_manifest as import_load_report_package_manifest,
    report_code_to_control_code as import_report_code_to_control_code,
    report_manifest_page_items as import_report_manifest_page_items,
    report_package_entry_path as import_report_package_entry_path,
    safe_int as import_safe_int,
)
from minem.report_package_writer import sync_report_material_package as write_report_material_package
from minem.report_canvas import (
    normalize_report_page_canvases as normalize_report_canvas_versions,
    restore_report_canvas_files,
)
from minem.resource_importer import sync_report_package_resources as write_report_package_resources
from minem.similarity import (
    merge_similar_resource_versions as run_merge_similar_resource_versions,
)
from minem.tagging import (
    image_trait_tags as tagging_image_trait_tags,
    infer_tags as tagging_infer_tags,
    infer_tags_from_text as tagging_infer_tags_from_text,
    merge_tags as tagging_merge_tags,
    normalize_role_tags as tagging_normalize_role_tags,
    page_usage_tags as tagging_page_usage_tags,
    resource_kind_for as tagging_resource_kind_for,
    source_process_tags as tagging_source_process_tags,
    split_tags as tagging_split_tags,
    suggest_material_tags as tagging_suggest_material_tags,
    apply_company_logo_metadata as tagging_apply_company_logo_metadata,
)
from minem.thumbnails import (
    chrome_path as preview_chrome_path,
    detect_html_dimensions as detect_preview_dimensions,
    generate_html_thumbnail as render_html_thumbnail,
)
from minem.multipart import parse_multipart
from minem.tag_config import (
    categories as load_categories_config,
    tag_rules as load_tag_rules_config,
    asset_types as load_asset_types_config,
    pipeline_stages as load_pipeline_stages_config,
    media_kinds as load_media_kinds_config,
    resource_kinds as load_resource_kinds_config,
    page_roles as load_page_roles_config,
    source_types as load_source_types_config,
    material_tag_taxonomy as load_material_tag_taxonomy_config,
    company_name_rules as load_company_name_rules_config,
)
from minem.upload_safety import UploadLimitError, copy_limited_stream, safe_extract_zip, validate_upload_request_size

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
DATA = RUNTIME_ROOT / "data"
UPLOADS = RUNTIME_ROOT / "uploads"
EXTRACTED = RUNTIME_ROOT / "extracted"
THUMBNAILS = RUNTIME_ROOT / "thumbnails"
REPORT_EXPORTS = RUNTIME_ROOT / "report-exports"
HISTORY_DIR = EXTRACTED / "_history"
DB_PATH = DATA / "materials.db"
AUTO_IMPORT_CONFIG = RUNTIME_ROOT / "import-sources.json"
STORYLINES_PATH = DATA / "storylines.json"
VERSION_MANIFEST_PATH = RESOURCE_ROOT / "product-version.json"
SESSION_TOKEN_PATH = RUNTIME_ROOT / "runtime" / "session-token"
SESSION_MANIFEST_PATH = RUNTIME_ROOT / "runtime" / "session.json"


def load_product_version():
    fallback = {"product": "MineM", "version": "0.0.0-dev", "channel": "unknown", "apiVersion": 1}
    try:
        payload = json.loads(VERSION_MANIFEST_PATH.read_text(encoding="utf-8"))
        return {**fallback, **payload}
    except (OSError, ValueError, TypeError):
        return fallback


PRODUCT_VERSION = load_product_version()
SESSION_TOKEN = ""
IMPORT_TASK_STORE = ImportTaskStore(DB_PATH)
REPORT_EXPORT_TASK_STORE = ReportExportTaskStore(DB_PATH)
AGENT_RUNTIME = AgentRuntime(ROOT, DATA)
AI_PRESENTER_VERSION = "edgetts5"
AI_PRESENTER_TEMPLATE = ROOT / "templates" / "ai-presenter.html"
THUMBNAIL_META_VERSION = 4
TEMP_REPORT_TTL_MS = 60 * 60 * 1000
TEMP_REPORT_STALE_MS = 5 * 60 * 1000
TEMP_REPORT_SESSIONS = {}
TEMP_REPORT_LOCK = threading.Lock()
INSTANCE_LOCK_HANDLE = None
THUMBNAIL_REFRESH_ENQUEUED = set()
THUMBNAIL_REFRESH_FAILED = {}
THUMBNAIL_REFRESH_LOCK = threading.Lock()
EXTRACT_RESTORE_LOCK = threading.Lock()
EXTRACT_RESTORE_LOCKS = {}
PAGE_DUPLICATE_RECONCILE_PENDING = set()
PAGE_DUPLICATE_RECONCILE_LOCK = threading.Lock()
TAG_SCHEDULER_WORKER = None
DATABASE_MIGRATION_STATE = {
    "currentVersion": 0,
    "targetVersion": max((migration.version for migration in SCHEMA_MIGRATIONS), default=0),
    "applied": [],
    "pending": [],
    "executed": [],
}
JOB_RUNTIME = JobRuntime({
    "imports": ChannelConfig(workers=1, max_pending=8),
    "exports": ChannelConfig(workers=1, max_pending=4),
    "tags": ChannelConfig(workers=1, max_pending=4),
    "thumbnails": ChannelConfig(workers=2, max_pending=512),
})
IMPORT_CANCEL_EVENTS = {}
IMPORT_COMMITTING_TASKS = set()
IMPORT_CANCEL_LOCK = threading.Lock()

ALLOWED_SUFFIXES = {".html", ".htm", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".m4v", ".webm"}
ZIP_SUFFIXES = {".zip"}
IMPORT_SUFFIXES = ALLOWED_SUFFIXES | ZIP_SUFFIXES
STATS_CACHE = {"payload": None, "expires_at": 0}
STATS_CACHE_LOCK = threading.Lock()
CASE_GROUP_CACHE = {"payload": None, "expires_at": 0}
CASE_GROUP_CACHE_LOCK = threading.Lock()
REPORT_ARRANGEMENT_CACHE = OrderedDict()
REPORT_ARRANGEMENT_CACHE_LOCK = threading.Lock()
REPORT_ARRANGEMENT_BUILD_LOCKS = {}
REPORT_ARRANGEMENT_CACHE_GENERATION = 0
REPORT_ARRANGEMENT_CACHE_LIMIT = 256
REPORT_ARRANGEMENT_CACHE_TTL_SECONDS = 15
PREVIEW_META_CACHE = OrderedDict()
PREVIEW_META_CACHE_LOCK = threading.Lock()
PREVIEW_META_CACHE_LIMIT = 512
RESOURCE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".m4v", ".webm"}
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def truthy_env(name, default="0"):
    return os.environ.get(name, default).strip().lower() in TRUTHY_ENV_VALUES


def agent_internal_api_enabled():
    return truthy_env("MINEM_AGENT_INTERNAL_API") or bool(os.environ.get("MINEM_AGENT_API_TOKEN", "").strip())


def agent_internal_api_token():
    return os.environ.get("MINEM_AGENT_API_TOKEN", "").strip()


def session_base_url(host, port):
    browser_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    return f"http://{browser_host}:{int(port)}"


def initialize_session_security(host="127.0.0.1", port=8790):
    global SESSION_TOKEN
    configured = os.environ.get("MINEM_SESSION_TOKEN", "").strip()
    if configured:
        from minem.security import atomic_write_private
        atomic_write_private(SESSION_TOKEN_PATH, configured)
        SESSION_TOKEN = configured
    else:
        SESSION_TOKEN = rotate_session_token(SESSION_TOKEN_PATH)
    from minem.security import atomic_write_private
    atomic_write_private(
        SESSION_MANIFEST_PATH,
        json.dumps(
            {
                "status": "running",
                "baseUrl": session_base_url(host, port),
                "pid": os.getpid(),
                "startedAt": now_ms(),
            },
            ensure_ascii=False,
        ),
    )
    return SESSION_TOKEN


def clear_session_manifest():
    try:
        payload = json.loads(SESSION_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return
    if int(payload.get("pid") or 0) == os.getpid():
        SESSION_MANIFEST_PATH.unlink(missing_ok=True)


def management_index_html(path, token=""):
    document = Path(path).read_text(encoding="utf-8")
    meta = '<meta name="minem-session-token" content="">'
    if token:
        meta = (
            '<meta name="minem-session-token" '
            f'content="{html.escape(token, quote=True)}">'
        )
    marker = "</head>"
    return document.replace(marker, f"  {meta}\n  {marker}", 1) if marker in document else f"{meta}\n{document}"


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

CATEGORIES = load_categories_config()

TAG_RULES = load_tag_rules_config()

ASSET_TYPES = load_asset_types_config()

PIPELINE_STAGES = load_pipeline_stages_config()

MEDIA_KINDS = load_media_kinds_config()

RESOURCE_KINDS = load_resource_kinds_config()

PAGE_ROLES = load_page_roles_config()

SOURCE_TYPES = load_source_types_config()

MATERIAL_TAG_TAXONOMY = load_material_tag_taxonomy_config()

ALL_MATERIAL_TAGS = {
    tag
    for primary, children in MATERIAL_TAG_TAXONOMY.items()
    for tag in [primary, *children]
}

LOGO_ROLE_TAGS = {"企业logo", "客户logo", "飞书logo", "合作伙伴logo", "品牌标识"}
ICON_ROLE_TAGS = {"产品icon", "飞书产品", "协作工具", "管理工具", "AI产品", "第三方产品"}
ICON_SUBTYPE_TAGS = ICON_ROLE_TAGS - {"产品icon"}
RESOURCE_STRUCTURE_TAGS = {"汇报素材", "完整汇报", "HTML汇报", "可导出", "汇报页面", "页面素材", "单页素材", "可拼接页面", "页面片段", "页面模板"}
REFERENCE_TAGS = {"参考截图", "产品截图", "页面截图", "设计参考", "不可直接使用", "仅作参考"}
IDENTITY_MEDIA_EXCLUDED_TAGS = {"页面背景", "封面背景", "内容页背景", "深色科技风", "界面参考", "数据图表", "地图", "柱状图", "时间轴", "矩阵图", "叙事表达"}

COMPANY_NAME_RULES = load_company_name_rules_config()

LOGO_TITLE_BY_SOURCE = {
    "input/input/property-logo-wall.png": ("企业 Logo 墙", "客户logo"),
    "ppt-media/image136.png": ("长鑫存储（CXMT）", "客户logo"),
    "ppt-media/image137.png": ("摩尔精英", "客户logo"),
    "ppt-media/image138.png": ("四维图新", "客户logo"),
    "ppt-media/image139.png": ("地平线", "客户logo"),
    "ppt-media/image141.png": ("华米", "客户logo"),
    "ppt-media/image150.png": ("华润微电子", "客户logo"),
    "ppt-media/image167.png": ("惠伦晶体", "客户logo"),
    "ppt-media/image169.png": ("云脉芯联", "客户logo"),
    "ppt-media/image236.png": ("华峰", "客户logo"),
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




def split_tags(value):
    return tagging_split_tags(value)



def merge_tags(*tag_groups):
    return tagging_merge_tags(*tag_groups)


def normalize_role_tags(tags, asset_type, resource_kind="", identity_text=""):
    return tagging_normalize_role_tags(
        tags,
        asset_type,
        resource_kind,
        identity_text,
        resource_structure_tags=RESOURCE_STRUCTURE_TAGS,
        reference_tags=REFERENCE_TAGS,
        identity_media_excluded_tags=IDENTITY_MEDIA_EXCLUDED_TAGS,
        logo_role_tags=LOGO_ROLE_TAGS,
        icon_role_tags=ICON_ROLE_TAGS,
        icon_subtype_tags=ICON_SUBTYPE_TAGS,
    )


def infer_tags(asset):
    return tagging_infer_tags(
        asset,
        categories=CATEGORIES,
        tag_rules=TAG_RULES,
        asset_library_path=asset_library_path,
        image_trait_tags_fn=image_trait_tags,
    )


def infer_tags_from_text(text):
    return tagging_infer_tags_from_text(text, tag_rules=TAG_RULES)


def ai_tag_assets(asset_type="control"):
    with db() as conn:
        if asset_type == "all":
            rows = conn.execute("select id from assets order by updated_at desc, created_at desc").fetchall()
        elif asset_type in {"control", "report", "resource"}:
            rows = conn.execute(
                "select id from assets where asset_type=? order by updated_at desc, created_at desc",
                (asset_type,),
            ).fetchall()
        else:
            return {"ok": False, "error": "素材类型无效", "updated": 0, "scanned": 0}
    ids = [row["id"] for row in rows]
    result = create_tag_analysis_task(
        ids,
        trigger_type="manual",
        scope_type=asset_type,
        apply_mode="confirmed",
    )
    result.update({"scanned": len(ids), "updated": 0, "assetType": asset_type})
    return result


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




def image_trait_tags(path):
    return tagging_image_trait_tags(path, image_module=Image, image_sequence_module=ImageSequence)


def source_process_tags(source_type):
    return tagging_source_process_tags(source_type)


def page_usage_tags(text):
    return tagging_page_usage_tags(text)


def resource_kind_for(path, media_kind, title="", tags=""):
    return tagging_resource_kind_for(path, media_kind, title, tags, image_module=Image, image_sequence_module=ImageSequence)




def suggest_material_tags(asset_or_text, resource_kind=""):
    return tagging_suggest_material_tags(asset_or_text, resource_kind, tag_rules=TAG_RULES)








def apply_company_logo_metadata(title, tags, source_path="", usage="", resource_kind=""):
    return tagging_apply_company_logo_metadata(
        title,
        tags,
        source_path,
        usage,
        resource_kind,
        logo_title_by_source=LOGO_TITLE_BY_SOURCE,
        company_name_rules=COMPANY_NAME_RULES,
    )


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
    global DATABASE_MIGRATION_STATE
    DATABASE_MIGRATION_STATE = initialize_database(
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
    DATABASE_MIGRATION_STATE.pop("backupPath", None)
    declared_schema_version = int(PRODUCT_VERSION.get("databaseSchemaVersion") or 0)
    target_schema_version = int(DATABASE_MIGRATION_STATE.get("targetVersion") or 0)
    if declared_schema_version and declared_schema_version != target_schema_version:
        raise RuntimeError(
            "数据库迁移目标与产品版本清单不一致"
            f"（manifest={declared_schema_version}, migrations={target_schema_version}）"
        )
    REPORT_EXPORTS.mkdir(parents=True, exist_ok=True)
    REPORT_EXPORT_TASK_STORE.ensure_schema()
    interrupted_imports = IMPORT_TASK_STORE.recover_interrupted()
    if interrupted_imports:
        print(f"Recovered {interrupted_imports} interrupted import task(s)")
    interrupted_exports = REPORT_EXPORT_TASK_STORE.recover_interrupted()
    if interrupted_exports:
        print(f"Recovered {interrupted_exports} interrupted export task(s)")
    with db() as conn:
        ensure_tag_task_schema(conn)
        interrupted_tags = recover_interrupted_tag_tasks(conn)
    if interrupted_tags:
        print(f"Recovered {interrupted_tags} interrupted tag task(s)")
    with db() as conn:
        page_fingerprint_state = backfill_page_fingerprints(
            conn,
            path_for_asset=asset_library_path,
        )
        pending_page_ids = [
            row["id"]
            for row in conn.execute(
                """
                select id
                from assets
                where asset_type = 'control'
                  and version_parent_id = ''
                  and semantic_dedupe_status = 'pending'
                """
            ).fetchall()
        ]
    with PAGE_DUPLICATE_RECONCILE_LOCK:
        PAGE_DUPLICATE_RECONCILE_PENDING.update(pending_page_ids)
    DATABASE_MIGRATION_STATE["pageFingerprints"] = page_fingerprint_state
    # Reports are served through a stable public entry.  It composes their
    # existing page slots and makes future arrangement changes visible to both
    # newly opened and previously copied report links without modifying source
    # packages under extracted/.
    with db() as conn:
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
    # Report-synchronized pages may retain the parent report upload id and a
    # generic ``index.html`` source path. That path is the complete report,
    # while preview_url points at this page's real standalone HTML. Prefer the
    # direct page/resource preview so a single material never nests a report
    # viewer inside another viewer.
    if data.get("asset_type") != "report" and preview_url.startswith("/extracted/"):
        direct_path = (RUNTIME_ROOT / preview_url.lstrip("/")).resolve()
        if is_path_within(direct_path, EXTRACTED) and direct_path.exists():
            return preview_url
    upload_id = data.get("upload_id") or ""
    source_path = data.get("source_path") or ""
    if upload_id and source_path:
        path = EXTRACTED / upload_id / source_path
        if path.exists():
            return f"/extracted/{upload_id}/{source_path}"
    return preview_url


# Source packages occasionally carry their own deck navigation and utility bar.
# The platform shell is the sole owner of these controls while a page is embedded.
# Isolation belongs to the viewer sandbox and its navigation protocol. Embedded
# platform resources keep native history, BroadcastChannel, and postMessage APIs.
PREVIEW_EMBED_STYLE = """
<style id="minem-embedded-preview-style">
  #minem-page-tools, .page-pill, .slide-controls, .slide-navigation,
  .slide-nav, .deck-controls, .deck-navigation, .presentation-controls,
  [data-minem-page-tools], [data-slide-navigation], [data-deck-navigation] {
    display: none !important;
  }
  /* Let the platform canvas own the embedding viewport so source pages are
     not letterboxed a second time inside the report viewer. */
  html, body { width: 100% !important; height: 100% !important; }
  .material-control-stage {
    width: 100vw !important;
    height: 100vh !important;
    max-width: none !important;
    max-height: none !important;
    --fs-scale: 1 !important;
  }
</style>
"""
SOURCE_PREVIEW_CAPABILITY_QUERY = "minem_preview_capability"
SOURCE_PREVIEW_CAPABILITY_TTL_MS = 10 * 60 * 1000
SOURCE_PREVIEW_CAPABILITY_LIMIT = 1024
SOURCE_PREVIEW_CAPABILITIES = OrderedDict()
SOURCE_PREVIEW_CAPABILITIES_LOCK = threading.Lock()


def source_preview_capability_script(token):
    token_json = json_for_html_script(token)
    query_json = json_for_html_script(SOURCE_PREVIEW_CAPABILITY_QUERY)
    return f"""
<script id="minem-embedded-preview-compat">
(() => {{
  const capability = {token_json};
  const capabilityQuery = {query_json};
  const serviceOrigin = new URL(window.location.href).origin;
  const secureSourceUrl = (value) => {{
    try {{
      const target = new URL(String(value), window.location.href);
      if (target.origin === serviceOrigin && target.pathname.startsWith("/extracted/")) {{
        target.searchParams.set(capabilityQuery, capability);
        target.searchParams.set("embed", "1");
        return target.href;
      }}
    }} catch (_) {{}}
    return value;
  }};
  const createMemoryStorage = () => {{
    const values = new Map();
    return {{
      get length() {{ return values.size; }},
      clear() {{ values.clear(); }},
      getItem(key) {{ key = String(key); return values.has(key) ? values.get(key) : null; }},
      key(index) {{ return Array.from(values.keys())[Number(index)] ?? null; }},
      removeItem(key) {{ values.delete(String(key)); }},
      setItem(key, value) {{ values.set(String(key), String(value)); }}
    }};
  }};
  for (const name of ["localStorage", "sessionStorage"]) {{
    try {{
      void window[name].length;
    }} catch (_) {{
      Object.defineProperty(window, name, {{ value: createMemoryStorage(), configurable: true }});
    }}
  }}
  const nativeFetch = window.fetch?.bind(window);
  if (nativeFetch) {{
    window.fetch = (input, init) => {{
      if (typeof Request !== "undefined" && input instanceof Request) {{
        return nativeFetch(new Request(secureSourceUrl(input.url), input), init);
      }}
      return nativeFetch(secureSourceUrl(input), init);
    }};
  }}
  const nativeOpen = window.XMLHttpRequest?.prototype?.open;
  if (nativeOpen) {{
    window.XMLHttpRequest.prototype.open = function(method, url, ...rest) {{
      return nativeOpen.call(this, method, secureSourceUrl(url), ...rest);
    }};
  }}
}})();
</script>
"""


def inject_embedded_preview_style(html_text, preview_capability=""):
    # HTML Box exports bootstrap a remote capture helper even when the page is
    # only being presented. It is unrelated to rendering and makes an offline
    # report perform a network request on every live frame. Keep the authored
    # source untouched, but remove this eager helper from MineM's embedded copy;
    # the source shim can still request it lazily if an explicit capture action
    # is ever invoked outside the read-only viewer.
    html_text = re.sub(
        r'<script\b[^>]*\bsrc=["\']https://magic\.solutionsuite\.cn/html-to-image\.js["\'][^>]*>\s*</script\s*>',
        "",
        html_text,
        flags=re.IGNORECASE,
    )
    additions = []
    if "minem-embedded-preview-style" not in html_text:
        additions.append(PREVIEW_EMBED_STYLE)
    if preview_capability and "minem-embedded-preview-compat" not in html_text:
        additions.append(source_preview_capability_script(preview_capability))
    if not additions:
        return html_text
    injection = "".join(additions)
    marker = re.search(r"<head\b[^>]*>", html_text, flags=re.IGNORECASE)
    if marker:
        return f"{html_text[:marker.end()]}{injection}{html_text[marker.end():]}"
    return f"{injection}{html_text}"


def create_source_preview_capability(path):
    path = Path(path).resolve()
    try:
        relative = path.relative_to(EXTRACTED.resolve())
    except ValueError:
        return ""
    if len(relative.parts) < 2:
        return ""
    scope = (EXTRACTED / relative.parts[0]).resolve()
    timestamp = now_ms()
    token = secrets.token_urlsafe(24)
    with SOURCE_PREVIEW_CAPABILITIES_LOCK:
        expired = [
            key
            for key, item in SOURCE_PREVIEW_CAPABILITIES.items()
            if int(item.get("expiresAt") or 0) <= timestamp
        ]
        for key in expired:
            SOURCE_PREVIEW_CAPABILITIES.pop(key, None)
        SOURCE_PREVIEW_CAPABILITIES[token] = {
            "scope": str(scope),
            "expiresAt": timestamp + SOURCE_PREVIEW_CAPABILITY_TTL_MS,
        }
        while len(SOURCE_PREVIEW_CAPABILITIES) > SOURCE_PREVIEW_CAPABILITY_LIMIT:
            SOURCE_PREVIEW_CAPABILITIES.popitem(last=False)
    return token


def source_preview_capability_allows(token, path):
    token = str(token or "").strip()
    if not token:
        return False
    timestamp = now_ms()
    with SOURCE_PREVIEW_CAPABILITIES_LOCK:
        item = SOURCE_PREVIEW_CAPABILITIES.get(token)
        if not item or int(item.get("expiresAt") or 0) <= timestamp:
            SOURCE_PREVIEW_CAPABILITIES.pop(token, None)
            return False
        scope = Path(item["scope"])
        allowed = is_path_within(Path(path).resolve(), scope)
        if allowed:
            item["expiresAt"] = timestamp + SOURCE_PREVIEW_CAPABILITY_TTL_MS
            SOURCE_PREVIEW_CAPABILITIES.move_to_end(token)
        return allowed


def thumbnail_path(asset_id):
    return THUMBNAILS / f"{asset_id}.png"


def thumbnail_meta_path(asset_id):
    return THUMBNAILS / f"{asset_id}.json"


def local_html_preview_path(data):
    data = dict(data)
    preview_url = canonical_preview_url(data)
    if data.get("asset_type") != "report" and preview_url.startswith("/extracted/"):
        direct_path = (RUNTIME_ROOT / urlparse(preview_url).path.lstrip("/")).resolve()
        if (
            is_path_within(direct_path, EXTRACTED)
            and direct_path.exists()
            and direct_path.is_file()
            and direct_path.suffix.lower() in {".html", ".htm"}
        ):
            return direct_path
    upload_id = str(data.get("upload_id") or "").strip()
    source_path = str(data.get("source_path") or "").strip()
    if upload_id and source_path:
        upload_path = (EXTRACTED / upload_id / source_path).resolve()
        if (
            is_path_within(upload_path, EXTRACTED)
            and upload_path.exists()
            and upload_path.is_file()
            and upload_path.suffix.lower() in {".html", ".htm"}
        ):
            return upload_path
    if not preview_url.startswith("/"):
        return None
    preview_path = urlparse(preview_url).path
    html_path = (RUNTIME_ROOT / preview_path.lstrip("/")).resolve()
    if (
        is_path_within(html_path, RUNTIME_ROOT)
        and html_path.exists()
        and html_path.is_file()
        and html_path.suffix.lower() in {".html", ".htm"}
    ):
        return html_path
    return None


def current_asset_version(data, conn=None):
    data = dict(data)
    if data.get("asset_type") != "control" or not data.get("id"):
        return data
    version_group = str(data.get("version_group") or data["id"]).strip()

    def load_current(active_conn):
        row = active_conn.execute(
            """
            select *
            from assets
            where asset_type = 'control'
              and version_parent_id = ''
              and (version_group = ? or id = ?)
            order by updated_at desc, created_at desc, id desc
            limit 1
            """,
            (version_group, version_group),
        ).fetchone()
        return dict(row) if row else data

    if conn is not None:
        return load_current(conn)
    with db() as active_conn:
        return load_current(active_conn)


def current_asset_versions(rows, conn):
    """Resolve control version groups in one query for report page reads."""
    source_rows = [dict(row) for row in rows]
    groups = list(dict.fromkeys(
        str(row.get("version_group") or row.get("id") or "").strip()
        for row in source_rows
        if row.get("id")
    ))
    current_by_group = {}
    if groups:
        placeholders = ",".join("?" for _ in groups)
        current_rows = conn.execute(
            f"""
            select *
            from assets
            where asset_type = 'control'
              and version_parent_id = ''
              and (version_group in ({placeholders}) or id in ({placeholders}))
            order by updated_at desc, created_at desc, id desc
            """,
            [*groups, *groups],
        ).fetchall()
        for row in current_rows:
            item = dict(row)
            group = str(item.get("version_group") or item["id"]).strip()
            current_by_group.setdefault(group, item)
            current_by_group.setdefault(item["id"], item)
    return {
        row["id"]: current_by_group.get(str(row.get("version_group") or row["id"]).strip(), row)
        for row in source_rows
    }


def report_cover_control(data, conn=None):
    data = dict(data)
    if data.get("asset_type") != "report" or not data.get("id"):
        return None

    def load_cover(active_conn):
        slots = active_conn.execute(
            """
            select control_id
            from report_page_slots
            where report_id = ? and control_id <> ''
            order by page_number
            """,
            (data["id"],),
        ).fetchall()
        slot_ids = list(dict.fromkeys(row["control_id"] for row in slots if row["control_id"]))
        if not slot_ids:
            return None
        arrangement = active_conn.execute(
            "select page_order, hidden_page_ids from report_page_arrangements where report_id = ?",
            (data["id"],),
        ).fetchone()
        try:
            saved_order = json.loads(arrangement["page_order"]) if arrangement else []
            hidden_ids = set(json.loads(arrangement["hidden_page_ids"]) if arrangement else [])
        except (TypeError, ValueError, json.JSONDecodeError):
            saved_order, hidden_ids = [], set()
        ordered_ids = [item for item in saved_order if item in slot_ids] if arrangement else slot_ids
        visible_ids = [item for item in ordered_ids if item not in hidden_ids]
        cover_id = next(iter(visible_ids or ordered_ids), "")
        if not cover_id:
            return None
        row = active_conn.execute(
            "select * from assets where id = ? and asset_type = 'control'",
            (cover_id,),
        ).fetchone()
        return current_asset_version(row, conn=active_conn) if row else None

    if conn is not None:
        return load_cover(conn)
    with db() as active_conn:
        return load_cover(active_conn)


def legacy_thumbnail_source_fingerprint(data):
    data = dict(data)
    preview_url = canonical_preview_url(data)
    parts = [
        "thumb-v4",
        str(data.get("source_hash") or ""),
        str(preview_url or ""),
        str(data.get("source_path") or ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def thumbnail_source_fingerprint(data):
    data = dict(data)
    preview_url = canonical_preview_url(data)
    parts = [
        "thumb-v4",
        str(data.get("source_hash") or ""),
        str(preview_url or ""),
        str(data.get("source_path") or ""),
    ]
    html_path = local_html_preview_path({**dict(data), "preview_url": preview_url})
    if html_path:
        try:
            stat = html_path.stat()
            try:
                relative = html_path.relative_to(RUNTIME_ROOT).as_posix()
            except ValueError:
                relative = html_path.relative_to(ROOT).as_posix()
            parts.append(f"file:{relative}:{stat.st_size}:{stat.st_mtime_ns}")
        except (OSError, ValueError):
            pass
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


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
    try:
        JOB_RUNTIME.submit(
            "thumbnails",
            key,
            thumbnail_refresh_job,
            key,
            asset_id,
            str(html_path),
            source_fingerprint,
        )
    except JobQueueFullError:
        with THUMBNAIL_REFRESH_LOCK:
            THUMBNAIL_REFRESH_ENQUEUED.discard(key)
            THUMBNAIL_REFRESH_FAILED[key] = now_ms()
        sys.stderr.write(f"[thumbnail] refresh queue full for {asset_id}\n")


def thumbnail_refresh_job(key, asset_id, html_path, source_fingerprint):
    success = False
    try:
        path = Path(html_path)
        if path.exists() and path.suffix.lower() in {".html", ".htm"}:
            success = generate_html_thumbnail(asset_id, path, source_fingerprint, allow_text_fallback=False)
            if success:
                reconcile_pending_page_peers(asset_id)
    except Exception as error:
        # One bad asset must not kill the worker and stall every queued
        # thumbnail; log and move on, marking this item failed below.
        sys.stderr.write(f"[thumbnail] refresh failed for {asset_id}: {error}\n")
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
    return success


def thumbnail_meta_matches(asset_id, source_fingerprint=""):
    if not source_fingerprint:
        return True
    meta_path = thumbnail_meta_path(asset_id)
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if int(meta.get("version") or 0) != THUMBNAIL_META_VERSION:
        return False
    stored = str(meta.get("sourceFingerprint") or "")
    return stored == source_fingerprint


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


def existing_thumbnail_url(asset_id):
    thumb = thumbnail_path(asset_id)
    try:
        version = thumb.stat().st_mtime_ns
    except FileNotFoundError:
        return ""
    return f"/thumbnails/{asset_id}.png?v={version}"


def migrate_legacy_thumbnail_meta(data, source_fingerprint, html_path):
    data = dict(data)
    asset_id = data.get("id")
    if not asset_id or not html_path:
        return ""
    thumb = thumbnail_path(asset_id)
    meta_path = thumbnail_meta_path(asset_id)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        thumbnail_stat = thumb.stat()
        html_stat = Path(html_path).stat()
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ""
    if int(meta.get("version") or 0) != THUMBNAIL_META_VERSION:
        return ""
    if str(meta.get("sourceFingerprint") or "") != legacy_thumbnail_source_fingerprint(data):
        return ""
    if html_stat.st_mtime_ns > thumbnail_stat.st_mtime_ns:
        return ""
    write_thumbnail_meta(asset_id, source_fingerprint)
    return thumbnail_url(asset_id, source_fingerprint)


def asset_thumbnail_url(data, conn=None):
    data = dict(data)
    if data.get("asset_type") == "report":
        thumbnail_asset = report_cover_control(data, conn=conn)
        if not thumbnail_asset:
            return ""
    else:
        thumbnail_asset = current_asset_version(data, conn=conn)
    fingerprint = thumbnail_source_fingerprint(thumbnail_asset)
    url = thumbnail_url(thumbnail_asset["id"], fingerprint)
    if url:
        return url
    html_path = local_html_preview_path(thumbnail_asset)
    migrated_url = migrate_legacy_thumbnail_meta(thumbnail_asset, fingerprint, html_path)
    if migrated_url:
        return migrated_url
    if html_path:
        enqueue_thumbnail_refresh(thumbnail_asset["id"], html_path, fingerprint)
    return existing_thumbnail_url(thumbnail_asset["id"])


def detected_html_preview_size(html_path):
    return detect_preview_dimensions(html_path)




def preview_meta_for_asset(data):
    preview_url = data.get("preview_url") or ""
    media_kind = data.get("media_kind") or ""
    if media_kind != "html" or not preview_url.startswith("/"):
        return {"width": 0, "height": 0, "aspectRatio": 0, "longPage": False}
    html_path = (RUNTIME_ROOT / preview_url.lstrip("/")).resolve()
    if not is_path_within(html_path, RUNTIME_ROOT) or not html_path.exists() or html_path.suffix.lower() not in {".html", ".htm"}:
        return {"width": 1920, "height": 1080, "aspectRatio": round(16 / 9, 6), "longPage": False}
    try:
        stat = html_path.stat()
    except OSError:
        return {"width": 1920, "height": 1080, "aspectRatio": round(16 / 9, 6), "longPage": False}
    cache_key = (str(html_path), stat.st_mtime_ns, stat.st_size)
    with PREVIEW_META_CACHE_LOCK:
        cached = PREVIEW_META_CACHE.get(cache_key)
        if cached is not None:
            PREVIEW_META_CACHE.move_to_end(cache_key)
            return cached
    width, height = detected_html_preview_size(html_path)
    meta = {
        "width": width,
        "height": height,
        "aspectRatio": round(width / height, 6) if height else 0,
        "longPage": bool(height and height / max(width, 1) > 1.35),
    }
    with PREVIEW_META_CACHE_LOCK:
        PREVIEW_META_CACHE[cache_key] = meta
        PREVIEW_META_CACHE.move_to_end(cache_key)
        # Evict least-recently-used entries so the long-running sidecar keeps a
        # bounded footprint instead of dropping the whole cache at the limit.
        while len(PREVIEW_META_CACHE) > PREVIEW_META_CACHE_LIMIT:
            PREVIEW_META_CACHE.popitem(last=False)
    return meta


def row_to_asset(row, conn=None):
    data = dict(row)
    data["snippet"] = ""
    data["categoryLabel"] = CATEGORIES.get(data["category"], data["category"])
    if data["asset_type"] == "page":
        data["asset_type"] = "report"
    data["preview_url"] = canonical_preview_url(data)
    data["typeLabel"] = ASSET_TYPES.get(data["asset_type"], data["asset_type"])
    data["mediaLabel"] = MEDIA_KINDS.get(data["media_kind"], data["media_kind"])
    data["resourceKindLabel"] = RESOURCE_KINDS.get(data.get("resource_kind") or "", data.get("resource_kind") or "")
    data["pageRoleLabel"] = PAGE_ROLES.get(data.get("page_role") or "", "")
    data["thumbnail_url"] = asset_thumbnail_url(data, conn=conn)
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
            "update assets set resource_kind=? where id=?",
            (kind, row["id"]),
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


def stable_source_hash(path, kind="file"):
    try:
        stat = path.stat()
        base = f"{kind}:{path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        base = f"{kind}:{path}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def asset_exists(conn, source_hash):
    return bool(source_hash and conn.execute("select 1 from assets where source_hash = ? limit 1", (source_hash,)).fetchone())


def asset_library_path(asset):
    if not asset["upload_id"] or not asset["source_path"]:
        return None
    path = (EXTRACTED / asset["upload_id"] / asset["source_path"]).resolve()
    if not is_path_within(path, EXTRACTED):
        return None
    return path


def refresh_upload_page_fingerprints(conn, upload_id):
    rows = conn.execute(
        """
        select *
        from assets
        where upload_id = ?
          and asset_type = 'control'
        order by created_at, id
        """,
        (upload_id,),
    ).fetchall()
    updated = 0
    candidates = 0
    identities = {}
    for row in rows:
        identity = refresh_asset_fingerprint(
            conn,
            row["id"],
            asset_library_path(row),
            dedupe_status="legacy",
        )
        identities[row["id"]] = identity
        updated += 1
    for row in rows:
        identity = identities[row["id"]]
        has_candidate = bool(
            identity.fingerprint
            and conn.execute(
                """
                select 1
                from assets candidate
                where candidate.asset_type = 'control'
                  and candidate.id <> ?
                  and candidate.version_parent_id = ''
                  and candidate.semantic_fingerprint = ?
                  and candidate.semantic_fingerprint_version = ?
                  and coalesce(nullif(candidate.version_group, ''), candidate.id)
                      <> coalesce(nullif(?, ''), ?)
                limit 1
                """,
                (
                    row["id"],
                    identity.fingerprint,
                    PAGE_FINGERPRINT_VERSION,
                    row["version_group"],
                    row["id"],
                ),
            ).fetchone()
        )
        conn.execute(
            "update assets set semantic_dedupe_status = ? where id = ?",
            ("pending" if has_candidate else "no-match", row["id"]),
        )
        if has_candidate:
            candidates += 1
            with PAGE_DUPLICATE_RECONCILE_LOCK:
                PAGE_DUPLICATE_RECONCILE_PENDING.add(row["id"])
    return {"updated": updated, "candidates": candidates}


def reconcile_page_duplicate(asset_id):
    with db() as conn:
        asset = conn.execute(
            """
            select *
            from assets
            where id = ?
              and asset_type = 'control'
              and version_parent_id = ''
              and semantic_fingerprint <> ''
              and semantic_fingerprint_version = ?
              and semantic_dedupe_status = 'pending'
            """,
            (asset_id, PAGE_FINGERPRINT_VERSION),
        ).fetchone()
        if not asset:
            return {"merged": False, "reason": "asset-not-eligible"}
        asset_reference_count = conn.execute(
            "select count(*) from report_page_slots where control_id = ?",
            (asset["id"],),
        ).fetchone()[0]
        candidates = conn.execute(
            """
            select candidate.*,
                   (
                     select count(*)
                     from report_page_slots slot
                     where slot.control_id = candidate.id
                   ) as reference_count
            from assets candidate
            where candidate.asset_type = 'control'
              and candidate.id <> ?
              and candidate.version_parent_id = ''
              and candidate.semantic_fingerprint = ?
              and candidate.semantic_fingerprint_version = ?
              and coalesce(nullif(candidate.version_group, ''), candidate.id)
                  <> coalesce(nullif(?, ''), ?)
            order by reference_count desc, candidate.created_at, candidate.asset_code, candidate.id
            """,
            (
                asset["id"],
                asset["semantic_fingerprint"],
                PAGE_FINGERPRINT_VERSION,
                asset["version_group"],
                asset["id"],
            ),
        ).fetchall()
        current_thumbnail = thumbnail_path(asset["id"])
        if not current_thumbnail.is_file():
            return {"merged": False, "reason": "current-thumbnail-missing"}
        matches = []
        for candidate in candidates:
            candidate_thumbnail = thumbnail_path(candidate["id"])
            if not candidate_thumbnail.is_file():
                continue
            metrics = thumbnail_difference(
                candidate_thumbnail,
                current_thumbnail,
                image_module=Image,
            )
            if not is_auto_reusable_visual(metrics):
                continue
            matches.append((candidate, metrics))
        match_method = "semantic-visual-v1"
        if not matches and candidates:
            # The semantic fingerprint already requires an identical stable
            # page key and identical normalized visible text. A broken or
            # wrapper-dependent thumbnail must not create another primary
            # card; group it as a preserved version and record that the
            # fallback did not rely on visual equality.
            matches = [(candidate, {"score": 1.0}) for candidate in candidates]
            match_method = "semantic-exact-v1"
        if not matches:
            conn.execute(
                """
                update assets
                set semantic_dedupe_status = ?
                where id = ?
                """,
                ("reviewed" if candidates else "no-match", asset["id"]),
            )
            return {
                "merged": False,
                "reason": "no-visual-match",
                "candidateCount": len(candidates),
            }
        eligible = [
            {
                "id": asset["id"],
                "referenceCount": int(asset_reference_count or 0),
                "createdAt": int(asset["created_at"] or 0),
                "assetCode": asset["asset_code"] or "",
            },
            *[
                {
                    "id": candidate["id"],
                    "referenceCount": int(candidate["reference_count"] or 0),
                    "createdAt": int(candidate["created_at"] or 0),
                    "assetCode": candidate["asset_code"] or "",
                }
                for candidate, _ in matches
            ],
        ]
        eligible.sort(
            key=lambda item: (
                -item["referenceCount"],
                item["createdAt"],
                item["assetCode"],
                item["id"],
            )
        )
        primary_id = eligible[0]["id"]
        metrics_by_id = {
            candidate["id"]: metrics for candidate, metrics in matches
        }
        if primary_id == asset["id"]:
            merge_targets = [candidate["id"] for candidate, _ in matches]
        else:
            merge_targets = [asset["id"]]
            merge_targets.extend(
                candidate["id"]
                for candidate, _ in matches
                if candidate["id"] != primary_id
            )
        merged_ids = []
        for duplicate_id in merge_targets:
            metrics = (
                metrics_by_id.get(duplicate_id)
                or metrics_by_id.get(primary_id)
                or {}
            )
            merged = attach_duplicate_version(
                conn,
                asset_id=duplicate_id,
                primary_id=primary_id,
                similarity_score=metrics.get("score", 1.0),
                timestamp=now_ms(),
                similarity_method=match_method,
            )
            if merged:
                merged_ids.append(duplicate_id)
        if merged_ids:
            placeholders = ",".join("?" for _ in merged_ids)
            conn.execute(
                f"""
                update assets
                set semantic_dedupe_status = 'merged'
                where id in ({placeholders})
                """,
                merged_ids,
            )
        conn.execute(
            """
            update assets
            set semantic_dedupe_status = case
              when id in (
                select id from assets
                where version_group = ? and version_parent_id = ''
              ) then 'primary'
              else semantic_dedupe_status
            end
            where id = ?
            """,
            (primary_id, primary_id),
        )
        if merged_ids:
            invalidate_stats_cache()
        return {
            "merged": bool(merged_ids),
            "assetId": asset["id"],
            "primaryId": primary_id,
            "mergedIds": merged_ids,
            "candidateCount": len(candidates),
        }


def reconcile_pending_page_peers(asset_id):
    with db() as conn:
        row = conn.execute(
            """
            select semantic_fingerprint
            from assets
            where id = ?
              and asset_type = 'control'
              and semantic_fingerprint <> ''
            """,
            (asset_id,),
        ).fetchone()
        if not row:
            return []
        pending_ids = [
            item["id"]
            for item in conn.execute(
                """
                select id
                from assets
                where asset_type = 'control'
                  and version_parent_id = ''
                  and semantic_fingerprint = ?
                  and semantic_fingerprint_version = ?
                  and semantic_dedupe_status = 'pending'
                order by created_at, asset_code, id
                """,
                (row["semantic_fingerprint"], PAGE_FINGERPRINT_VERSION),
            ).fetchall()
        ]
    results = []
    for pending_id in pending_ids:
        result = reconcile_page_duplicate(pending_id)
        results.append(result)
        if result.get("reason") not in {
            "current-thumbnail-missing",
            "candidate-thumbnail-missing",
        }:
            with PAGE_DUPLICATE_RECONCILE_LOCK:
                PAGE_DUPLICATE_RECONCILE_PENDING.discard(pending_id)
    return results


def reclassify_single_page_report_assets():
    """Remove inferred one-page report wrappers without duplicating their page."""
    timestamp = now_ms()
    cleanup_results = []
    converted_ids = []
    with db() as conn:
        candidates = conn.execute(
            """
            select asset.* from assets asset
            where asset.asset_type = 'report' and asset.version_parent_id = ''
            order by asset.created_at, asset.id
            """
        ).fetchall()
        for asset in candidates:
            source = asset_library_path(asset)
            if not source or source.suffix.lower() not in {'.html', '.htm'}:
                continue
            slots = conn.execute(
                """
                select slot.*, control.id control_exists
                from report_page_slots slot
                left join assets control
                  on control.id = slot.control_id and control.asset_type = 'control'
                where slot.report_id = ? and slot.control_id <> ''
                order by slot.page_number
                """,
                (asset["id"],),
            ).fetchall()
            source_path = Path(str(asset["source_path"] or ""))
            source_stem = source_path.stem.lower()
            parent_parts = [part.lower() for part in source_path.parts[:-1]]
            explicit_page_path = (
                any(re.search(r"(?:^|[-_])(page|slide|screen|chapter|section)[-_]?\d+", part) for part in parent_parts)
                or bool(re.match(r"^(?:p|page|slide|screen|chapter|section)[-_]?\d+", source_stem))
            )
            if (
                not slots
                and asset["source_type"] in {"upload", "manual-version-import", "single-page-import"}
                and explicit_page_path
                and (
                    detect_report_page_count(source) <= 1
                    or "input" in parent_parts
                )
            ):
                report_title = clean_report_title(asset["title"])
                asset_code = next_asset_code(conn, "control", "page", "html")
                conn.execute(
                    """
                    update assets
                    set title = ?, category = 'page', usage = ?,
                        asset_type = 'control', asset_code = ?,
                        source_type = 'single-page-import',
                        trusted_entry_ok = 0, trusted_entry_url = '',
                        trusted_page_count = 0, trusted_viewer_page_count = 0,
                        trusted_hash = '', trusted_size = 0, trusted_checked_at = 0,
                        updated_at = ?
                    where id = ?
                    """,
                    (
                        report_title,
                        "单页 HTML 导入，已归类为页面素材。",
                        asset_code,
                        max(timestamp, int(asset["updated_at"] or 0)),
                        asset["id"],
                    ),
                )
                conn.execute(
                    "delete from report_page_arrangements where report_id = ?",
                    (asset["id"],),
                )
                conn.execute(
                    "delete from report_page_candidates where report_id = ?",
                    (asset["id"],),
                )
                if conn.execute(
                    "select 1 from sqlite_master where type = 'table' and name = 'import_tasks'"
                ).fetchone():
                    conn.execute(
                        """
                        update import_tasks
                        set asset_code = ?, asset_title = ?, asset_type = 'control',
                            preview_url = ?, message = '导入完成，已归类为页面素材', updated_at = ?
                        where asset_id = ? or upload_id = ?
                        """,
                        (
                            asset_code,
                            report_title,
                            canonical_preview_url({**dict(asset), "asset_type": "control"}),
                            timestamp,
                            asset["id"],
                            asset["upload_id"],
                        ),
                    )
                converted_ids.append(asset["id"])
                continue
            if asset["source_type"] != "report-material-sync":
                continue
            if len(slots) != 1 or not slots[0]["control_exists"]:
                continue
            if detect_report_page_count(source) != 1:
                continue

            linked_control = conn.execute(
                "select * from assets where id = ? and asset_type = 'control'",
                (slots[0]["control_id"],),
            ).fetchone()
            if not linked_control:
                continue
            report_title = clean_report_title(asset["title"])
            conn.execute(
                """
                update assets
                set title = ?, usage = ?, source_type = 'single-page-import',
                    updated_at = ?
                where id = ?
                """,
                (
                    report_title,
                    "单页 HTML 导入，已归类为页面素材。",
                    max(timestamp, int(asset["updated_at"] or 0)),
                    linked_control["id"],
                ),
            )
            plan = build_asset_deletion_plan(conn, asset["id"])
            result = apply_asset_deletion_plan(conn, plan, timestamp=timestamp)
            cleanup_results.append(result)
            if conn.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'import_tasks'"
            ).fetchone():
                conn.execute(
                    """
                    update import_tasks
                    set asset_id = ?, asset_code = ?, asset_title = ?, asset_type = 'control',
                        preview_url = ?, message = '导入完成，已归类为页面素材', updated_at = ?
                    where upload_id = ?
                    """,
                    (
                        linked_control["id"],
                        linked_control["asset_code"],
                        report_title,
                        canonical_preview_url(linked_control),
                        timestamp,
                        asset["upload_id"],
                    ),
                )
    for result in cleanup_results:
        cleanup_deleted_asset_files(result)
    if cleanup_results or converted_ids:
        invalidate_stats_cache()
    return len(cleanup_results) + len(converted_ids)


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
        tags = merge_tags(
            ["资源素材", MEDIA_KINDS.get(media_kind, media_kind), RESOURCE_KINDS.get(resource_kind, resource_kind), f"源页面:{control['asset_code']}", control["title"]],
            infer_tags_from_text(description),
            suggest_material_tags(" ".join([title, rel, description, control["title"]]), resource_kind),
            image_trait_tags(file_path) if media_kind in {"image", "gif"} else [],
            source_process_tags("control-resource"),
            page_usage_tags(" ".join([title, rel, description, control["title"]])),
        )
        usage = f"从页面素材 {control['asset_code']} 提取"
        if description:
            usage += f"；上传描述：{description}"
        tags = normalize_role_tags(tags, "resource", resource_kind, " ".join([title, rel]))
        title, tag_text = apply_company_logo_metadata(title, ",".join(tags), rel, usage, resource_kind)
        existing = conn.execute(
            "select id, tags, usage from assets where asset_type = 'resource' and source_hash = ? limit 1",
            (source_hash,),
        ).fetchone()
        if existing:
            conn.execute(
                "update assets set usage = ?, updated_at = ? where id = ?",
                (
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
                tag_text,
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


def find_version_match_by_manifest(conn, manifest):
    """Match existing primary assets by manifest code or title."""
    code = manifest.get("code", "").strip()
    if code:
        row = conn.execute(
            "select * from assets where asset_type = 'control' and version_parent_id = '' and asset_code = ? limit 1",
            (code,),
        ).fetchone()
        if row:
            return row
    title = manifest.get("title", "").strip()
    if title:
        row = conn.execute(
            "select * from assets where asset_type = 'control' and version_parent_id = '' and title = ? order by updated_at desc limit 1",
            (title,),
        ).fetchone()
        if row:
            return row
    return None


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
    matched_asset = find_version_match_by_manifest(conn, manifest)
    version_group = ""
    version_no = 1
    version_parent_id = ""
    if matched_asset:
        version_group = matched_asset["version_group"] or matched_asset["id"]
        version_no = next_asset_version_no(conn, version_group)
        version_parent_id = matched_asset["id"]
    deck_id = manifest.get("deck_id") or primary_path.stem
    asset_id = f"{slugify(deck_id)}-{source_hash[:10]}"
    asset_code = next_asset_code(conn, "control", "page", "html")
    title = manifest.get("title") or primary_path.stem.replace("-", " ")
    tags = merge_tags(["页面素材", "基础模板", "feishu-deck-h5-library", "单页模板", "手动导入"], infer_tags_from_text(description))
    snippet = read_text_sample(primary_path)
    usage = "从标准页面模板包导入；导出时保持 feishu-deck-h5-library 包结构"
    if description:
        usage += f"；上传描述：{description}"
    conn.execute(
        """
        insert into assets
        (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, source_type, source_path, preview_url, upload_id, source_hash, version_group, version_no, version_parent_id, created_at, updated_at)
        values (?, ?, 'page', ?, ?, ?, 'control', ?, 'html', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            title,
            usage,
            ",".join(tags),
            snippet,
            asset_code,
            source_type if not matched_asset else "version-update",
            primary,
            f"/extracted/{upload_id}/{primary}",
            upload_id,
            source_hash,
            version_group or asset_id,
            version_no,
            version_parent_id,
            now_ms(),
            now_ms(),
        ),
    )
    if matched_asset:
        promote_asset_version(conn, asset_id)
    resources = insert_control_resource_assets(conn, extract_root, upload_id, {"asset_code": asset_code, "title": title}, description)
    return asset_id, resources








def extract_page_nodes(html):
    return split_page_nodes(html)




def extract_control_page_node(control_html):
    return split_control_page_node(control_html)


def replace_report_page_node(report_html, page_number, page_html):
    return split_replace_report_page_node(report_html, page_number, page_html)


def is_manifest_driven_report(source, report_html):
    return split_manifest_driven_report(source, report_html, read_json_file=read_json_file)




def viewer_pages_array_count(report_html):
    return split_viewer_pages_array_count(report_html)






def sync_manifest_viewer_pages(source):
    return split_sync_manifest_viewer_pages(source, read_json_file=read_json_file, safe_int=safe_int, slugify=slugify)


@lru_cache(maxsize=2048)
def _detect_report_page_count_cached(path_record, size, mtime_ns):
    del size, mtime_ns
    return split_detect_report_page_count(Path(path_record), read_json_file=read_json_file, safe_int=safe_int)


def detect_report_page_count(source):
    source = Path(source)
    try:
        stat = source.stat()
    except OSError:
        return 0
    return _detect_report_page_count_cached(str(source.resolve()), stat.st_size, stat.st_mtime_ns)






def build_control_html(report_html, page_html, title):
    return split_control_html(report_html, page_html, title)


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
        if not asset:
            return None, "素材不存在", ""
        if asset["asset_type"] != "control":
            return None, "只有页面素材支持模板包导出", ""
        source = asset_library_path(asset)
        if not source or not source.exists():
            return None, "找不到页面素材 HTML 文件", ""
        root = (EXTRACTED / asset["upload_id"]).resolve() if asset["upload_id"] else source.parent
        title = asset["title"]
        deck_id = safe_download_name(asset["asset_code"].lower())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            if control_template_manifest(root) and source.relative_to(root).as_posix() == "index.html":
                for path in root.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(root).as_posix())
            else:
                html = source.read_text(encoding="utf-8", errors="ignore")
                archive.writestr("index.html", html)
                archive.writestr("texts.md", build_texts_markdown(title))
                archive.writestr("ingestion-manifest.json", json.dumps(build_export_manifest(asset, deck_id, title), ensure_ascii=False, indent=2))
                archive.writestr("deck.json", json.dumps(build_deck_json(title, html), ensure_ascii=False, indent=2))
                support_files = []
                for path, rel in iter_export_support_files(root):
                    archive.write(path, rel)
                    support_files.append(rel)
                groups = {"framework": [], "deck-local": []}
                for rel in support_files:
                    if rel.startswith("assets/") or rel.startswith("viewer-style"):
                        groups["framework"].append(rel)
                    else:
                        groups["deck-local"].append(rel)
                yaml = "# Generated by MineM.\n# Paths are relative to this zip package.\n"
                for group, values in groups.items():
                    yaml += f"{group}:\n"
                    for rel in sorted(values):
                        yaml += f"  - {rel}\n"
                archive.writestr("assets-manifest.yaml", yaml)
        return buffer.getvalue(), "", f"{deck_id}.zip"


def report_export_page_html(title, source_url):
    """A control-free, fixed canvas wrapper used only for PDF capture."""
    safe_title = html.escape(title or "汇报页面", quote=True)
    safe_src = html.escape(source_url, quote=True)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{safe_title}</title>
    <style>html,body{{margin:0;width:1920px;height:1080px;overflow:hidden;background:#030712}}iframe{{width:1920px;height:1080px;border:0;background:#030712}}</style>
    </head><body><iframe title="{safe_title}" src="{safe_src}"></iframe></body></html>"""


def report_export_source_relative_url(source_url):
    clean = str(source_url or "").split("?", 1)[0]
    if not clean.startswith("/extracted/"):
        return ""
    relative = unquote(clean.removeprefix("/extracted/")).strip("/")
    path = (EXTRACTED / relative).resolve()
    return relative if is_path_within(path, EXTRACTED) and path.exists() and path.is_file() else ""


def report_export_local_references(source_path):
    """Extract static local resource URLs from HTML and CSS without evaluating JS."""
    try:
        text = source_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    raw_values = re.findall(r"(?:src|href|poster)\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.IGNORECASE)
    raw_values.extend(re.findall(r"url\(\s*['\"]?([^'\")\s]+)", text, flags=re.IGNORECASE))
    for srcset in re.findall(r"srcset\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.IGNORECASE):
        raw_values.extend(part.strip().split(" ", 1)[0] for part in srcset.split(","))
    seen = set()
    references = []
    for value in raw_values:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        parsed = urlparse(value)
        if parsed.scheme or parsed.netloc or value.startswith(("#", "data:", "blob:", "javascript:")):
            continue
        references.append(value)
    return references


def report_export_reference_path(reference, source_path, upload_root):
    parsed = urlparse(reference)
    raw_path = unquote(parsed.path or "")
    if not raw_path:
        return None
    if raw_path.startswith("/"):
        # Imported pages occasionally use /assets/... as a server shorthand.
        # In an offline bundle it maps to the same upload's assets directory.
        if not raw_path.startswith("/assets/"):
            return None
        candidate = (upload_root / raw_path.lstrip("/")).resolve()
    else:
        candidate = (source_path.parent / raw_path).resolve()
    if not is_path_within(candidate, upload_root) or not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def report_export_extracted_reference(reference):
    """Resolve platform-local absolute URLs for an offline export bundle."""
    parsed = urlparse(str(reference or ""))
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost"}:
            return None
    raw_path = unquote(parsed.path or "")
    if not raw_path.startswith("/extracted/"):
        return None
    relative = raw_path.removeprefix("/extracted/").strip("/")
    candidate = (EXTRACTED / relative).resolve()
    if not is_path_within(candidate, EXTRACTED) or not candidate.exists() or not candidate.is_file():
        return None
    return candidate, relative


def rewrite_report_export_absolute_references(destination_path, bundle_root, copied):
    """Copy and rewrite MineM absolute resources so the page works offline."""
    try:
        content = destination_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    pattern = re.compile(r"(?P<prefix>(?:src|href|poster)\s*=\s*['\"])(?P<url>[^'\"]+)(?P<suffix>['\"])", re.IGNORECASE)

    def replace(match):
        resolved = report_export_extracted_reference(match.group("url"))
        if not resolved:
            return match.group(0)
        dependency, relative = resolved
        target = (bundle_root / "extracted" / relative).resolve()
        if not is_path_within(target, bundle_root):
            return match.group(0)
        upload_id = relative.split("/", 1)[0]
        copy_report_export_dependency(dependency, target, EXTRACTED / upload_id, bundle_root, copied)
        offline_url = os.path.relpath(target, start=destination_path.parent).replace(os.sep, "/")
        return f'{match.group("prefix")}{offline_url}{match.group("suffix")}'

    rewritten = pattern.sub(replace, content)
    if rewritten != content:
        destination_path.write_text(rewritten, encoding="utf-8")


def report_export_excluded_path(path):
    """AI 演讲、语音模型与运行时只服务平台，不属于汇报交付物。"""
    parts = [part.lower() for part in Path(path).parts]
    name = Path(path).name.lower()
    excluded_parts = {"ai-tts", "ai-presenter", "kokoro-js", "kokoro-voices", "kokoro-zh", "presenter"}
    model_suffixes = {".onnx", ".bin", ".tflite", ".pt", ".pth", ".safetensors"}
    return bool(excluded_parts.intersection(parts)) or name == "ai-presenter.html" or Path(name).suffix in model_suffixes


def copy_report_export_dependency(source_path, destination_path, upload_root, bundle_root, copied, depth=0):
    if depth > 50:
        raise ValueError("导出依赖层级超过限制，请检查 HTML/CSS 是否存在循环引用")
    source_path = source_path.resolve()
    destination_path = destination_path.resolve()
    if report_export_excluded_path(source_path):
        return
    key = (str(source_path), str(destination_path))
    if key in copied:
        return
    copied.add(key)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    if source_path.suffix.lower() not in {".html", ".htm", ".css"}:
        return
    if source_path.suffix.lower() in {".html", ".htm"}:
        try:
            destination_path.write_text(
                inject_embedded_preview_style(destination_path.read_text(encoding="utf-8", errors="ignore")),
                encoding="utf-8",
            )
        except OSError as error:
            raise ValueError(f"无法写入离线预览：{error}") from error
        rewrite_report_export_absolute_references(destination_path, bundle_root, copied)
    for reference in report_export_local_references(source_path):
        dependency = report_export_reference_path(reference, source_path, upload_root)
        if not dependency or report_export_excluded_path(dependency):
            continue
        relative = os.path.relpath(dependency, start=source_path.parent)
        target = (destination_path.parent / relative).resolve()
        if not is_path_within(target, bundle_root):
            continue
        copy_report_export_dependency(dependency, target, upload_root, bundle_root, copied, depth + 1)


def copy_report_export_sources(target_root, page_items, progress=None):
    """Copy only static dependencies needed by each confirmed report page."""
    exported_pages = []
    for index, item in enumerate(page_items, start=1):
        relative = report_export_source_relative_url(item.get("src"))
        if not relative:
            raise ValueError(f"第 {index} 页没有可导出的原始 HTML")
        upload_id = relative.split("/", 1)[0]
        source_root = (EXTRACTED / upload_id).resolve()
        if not is_path_within(source_root, EXTRACTED) or not source_root.exists():
            raise ValueError(f"第 {index} 页的素材目录不存在")
        source_page = (EXTRACTED / relative).resolve()
        if not source_page.exists():
            raise ValueError(f"第 {index} 页的 HTML 文件缺失")
        page_root = (target_root / "pages" / f"page-{index:03d}").resolve()
        destination_page = page_root / source_page.name
        copy_report_export_dependency(source_page, destination_page, source_root, target_root, set())
        exported_pages.append({
            "title": item.get("title") or f"Page {index:02d}",
            "code": item.get("code") or "",
            "src": f"pages/page-{index:03d}/{source_page.name}",
        })
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
    exported_pages = copy_report_export_sources(package_root, page_items, progress=progress)
    (package_root / "index.html").write_text(report_viewer_html(report["title"], exported_pages), encoding="utf-8")
    (package_root / "minem-export-manifest.json").write_text(
        json.dumps(report_export_manifest(report, exported_pages, "html"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    filename = f"{safe_download_name(report['asset_code'] or report['title'])}-html.zip"
    destination = output_dir / filename
    zip_report_export_directory(package_root, destination)
    return destination, filename


def capture_report_export_page(page_url, screenshot_path):
    chrome = preview_chrome_path()
    if not chrome:
        raise RuntimeError("当前运行环境未安装 Chromium，无法生成 PDF")
    with tempfile.TemporaryDirectory(prefix="minem-report-export-chrome-") as profile_dir:
        command = [
            chrome, "--headless=new", "--disable-gpu", "--disable-dev-shm-usage", "--disable-background-networking",
            "--disable-default-apps", "--disable-extensions", "--disable-sync", "--hide-scrollbars",
            "--metrics-recording-only", "--no-first-run", "--no-pings", "--no-sandbox",
            "--allow-file-access-from-files", f"--user-data-dir={profile_dir}",
            "--run-all-compositor-stages-before-draw", "--virtual-time-budget=10000", "--window-size=1920,1080",
            f"--screenshot={screenshot_path}", page_url,
        ]
        process = None
        screenshot_ready = False
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = time.monotonic() + 35
            stable_size = 0
            stable_checks = 0
            while time.monotonic() < deadline:
                size = screenshot_path.stat().st_size if screenshot_path.exists() else 0
                if size >= 1024 and size == stable_size:
                    stable_checks += 1
                    if stable_checks >= 2:
                        screenshot_ready = True
                        break
                else:
                    stable_size = size
                    stable_checks = 0
                if process.poll() is not None:
                    screenshot_ready = size >= 1024
                    break
                time.sleep(0.1)
        except OSError as error:
            raise RuntimeError("PDF 页面渲染失败") from error
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
        if not screenshot_ready:
            raise RuntimeError("PDF 页面渲染超时")
    if not screenshot_path.exists() or screenshot_path.stat().st_size < 1024:
        raise RuntimeError("PDF 页面渲染失败")


def generate_report_pdf_export(task_id, report, page_items, progress):
    if not Image:
        raise RuntimeError("当前运行环境缺少 PDF 图像渲染组件")
    output_dir = REPORT_EXPORTS / task_id
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="minem-report-pdf-") as temp_dir:
        root = Path(temp_dir)
        images = []
        for index, item in enumerate(page_items, start=1):
            source = extracted_url_to_path(item.get("src"))
            if not source or not source.exists():
                raise ValueError(f"第 {index} 页原始 HTML 不存在")
            # Use an absolute file URL so the capture never depends on a
            # browser session or on the report's mutable public entry.
            page_url = f"http://127.0.0.1:{os.environ.get('PORT', '8790')}{item['src']}"
            separator = "&" if "?" in page_url else "?"
            screenshot = root / f"page-{index:03d}.png"
            capture_report_export_page(f"{page_url}{separator}embed=1", screenshot)
            images.append(Image.open(screenshot).convert("RGB"))
            progress(index, len(page_items), f"已完成第 {index}/{len(page_items)} 页渲染")
        filename = f"{safe_download_name(report['asset_code'] or report['title'])}.pdf"
        destination = output_dir / filename
        images[0].save(destination, "PDF", save_all=True, append_images=images[1:], resolution=150.0)
        for image in images:
            image.close()
    return destination, filename


def run_report_export_task(task_id):
    task = REPORT_EXPORT_TASK_STORE.get(task_id, include_private=True)
    if not task:
        return
    REPORT_EXPORT_TASK_STORE.update(task_id, status="running", progress=5, message="正在读取已确认编排", error="")
    try:
        with db() as conn:
            report = conn.execute("select * from assets where id = ? and asset_type = 'report'", (task["reportId"],)).fetchone()
        if not report:
            raise ValueError("汇报素材不存在")
        result, page_items = report_public_page_items(task["reportId"])
        if not result.get("ok") or not page_items:
            raise ValueError(result.get("error") or "该汇报没有可导出的可见页面")
        REPORT_EXPORT_TASK_STORE.update(task_id, pageCount=len(page_items), progress=15, message="正在准备页面素材")
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
        REPORT_EXPORT_TASK_STORE.update(task_id, status="failed", progress=100, message="导出失败", error=str(error) or "导出失败")


def create_report_export_task(report_id, export_format):
    export_format = str(export_format or "").strip().lower()
    if export_format not in {"html", "pdf"}:
        return {"ok": False, "error": "导出格式仅支持 HTML 或 PDF"}
    result, page_items = report_public_page_items(report_id)
    if not result.get("ok") or not page_items:
        return {"ok": False, "error": result.get("error") or "该汇报没有可导出的可见页面"}
    task_id = f"export-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
    task = REPORT_EXPORT_TASK_STORE.create({"id": task_id, "reportId": report_id, "format": export_format, "pageCount": len(page_items)})
    try:
        JOB_RUNTIME.submit("exports", task_id, run_report_export_task, task_id)
    except JobQueueFullError:
        task = REPORT_EXPORT_TASK_STORE.update(
            task_id,
            status="failed",
            progress=100,
            message="导出队列繁忙",
            error="当前导出任务较多，请稍后重试",
        )
        return {"ok": False, "error": "当前导出任务较多，请稍后重试", "task": task}
    return {"ok": True, "task": task}


def normalize_page_numbers(value):
    return normalize_report_page_numbers(value)




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
    old_ids = [row["id"] for row in rows]
    for index, row in enumerate(rows, start=2):
        conn.execute(
            """
            update assets
            set version_group = ?, version_no = ?, version_parent_id = ?, similarity_method = case when similarity_method = '' then 'candidate-history' else similarity_method end
            where id = ?
            """,
            (asset_id, index, asset_id, row["id"]),
        )
    if old_ids and asset["asset_type"] == "control":
        placeholders = ",".join("?" for _ in old_ids)
        timestamp = now_ms()
        conn.execute(
            f"update report_page_slots set control_id = ?, updated_at = ? where control_id in ({placeholders})",
            [asset_id, timestamp, *old_ids],
        )
        conn.execute(
            f"update report_page_candidates set control_id = ?, updated_at = ? where control_id in ({placeholders})",
            [asset_id, timestamp, *old_ids],
        )
        arrangements = conn.execute("select * from report_page_arrangements").fetchall()
        old_id_set = set(old_ids)
        for arrangement in arrangements:
            try:
                page_order = json.loads(arrangement["page_order"] or "[]")
                hidden_ids = json.loads(arrangement["hidden_page_ids"] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not old_id_set.intersection([*page_order, *hidden_ids]):
                continue
            page_order = list(dict.fromkeys(
                asset_id if item in old_id_set else item
                for item in page_order
            ))
            hidden_ids = list(dict.fromkeys(
                asset_id if item in old_id_set else item
                for item in hidden_ids
            ))
            conn.execute(
                """
                update report_page_arrangements
                set page_order = ?, hidden_page_ids = ?, updated_at = ?
                where report_id = ?
                """,
                (
                    json.dumps(page_order, ensure_ascii=False),
                    json.dumps(hidden_ids, ensure_ascii=False),
                    timestamp,
                    arrangement["report_id"],
                ),
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


def get_report_page_slots(report_id):
    def resolve_controls(conn, rows):
        current_rows = current_asset_versions(rows, conn)
        return {
            source_id: row_to_asset(current, conn=conn)
            for source_id, current in current_rows.items()
        }

    return load_report_page_slots(
        report_id,
        connect=db,
        row_to_asset=row_to_asset,
        resolve_controls=resolve_controls,
        asset_library_path=asset_library_path,
        detect_report_page_count=detect_report_page_count,
        validate_report_trusted_entry=validate_report_trusted_entry,
    )


def _build_report_arrangement_payload(report_id):
    slots_result = get_report_page_slots(report_id)
    if not slots_result.get("ok"):
        return slots_result
    slots = [slot for slot in slots_result.get("slots", []) if slot.get("control")]
    if not slots:
        return {"ok": False, "error": "该汇报暂未关联可编排的页面素材", "slots": []}
    with db() as conn:
        row = conn.execute("select * from report_page_arrangements where report_id = ?", (report_id,)).fetchone()
        slots_row = conn.execute(
            "select coalesce(max(updated_at), 0) as updated_at from report_page_slots where report_id = ?",
            (report_id,),
        ).fetchone()
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
    confirmed_order = [item for item in saved_order if item in by_id]
    if not row:
        confirmed_order = list(by_id)
    pending_order = [item for item in by_id if item not in confirmed_order]
    order = [*confirmed_order, *pending_order]
    pages = []
    for index, control_id in enumerate(order, start=1):
        slot = by_id[control_id]
        control = slot["control"]
        pages.append({
            "id": control_id,
            "slotNumber": slot["page_number"],
            "order": index,
            "title": control.get("title") or slot.get("title") or f"第 {index} 页",
            "code": control.get("asset_code") or "",
            "previewUrl": canonical_preview_url(control),
            "thumbnailUrl": control.get("thumbnail_url") or canonical_preview_url(control),
            "hidden": control_id in hidden_ids,
        })
    arrangement_updated_at = int(row["updated_at"] or 0) if row else 0
    slots_updated_at = int(slots_row["updated_at"] or 0) if slots_row else 0
    payload = {
        "ok": True,
        "reportId": report_id,
        "pages": pages,
        "pageOrder": order,
        "confirmedPageIds": confirmed_order,
        "pendingPageIds": pending_order,
        "hiddenPageIds": [item for item in order if item in hidden_ids],
        # Page insertion/replacement changes the editable arrangement even
        # before the user confirms a new order. Include slot mutations so a
        # stale editor cannot overwrite those concurrent changes.
        "updatedAt": max(arrangement_updated_at, slots_updated_at),
        "previewUrl": f"/reports/{quote(report_id, safe='')}/index.html",
    }
    return payload


def report_arrangement_signature(report_id):
    """Cheap revision key that also detects writes made outside HTTP APIs."""
    with db() as conn:
        row = conn.execute(
            """
            select
              coalesce((select updated_at from assets where id = ?), 0) report_updated_at,
              coalesce((select updated_at from report_page_arrangements where report_id = ?), 0) arrangement_updated_at,
              coalesce((select max(updated_at) from report_page_slots where report_id = ?), 0) slots_updated_at,
              (select count(*) from report_page_slots where report_id = ?) slot_count
            """,
            (report_id, report_id, report_id, report_id),
        ).fetchone()
    return tuple(int(value or 0) for value in row) if row else (0, 0, 0, 0)


def report_arrangement_payload(report_id):
    """Return a cached arrangement while coalescing concurrent first reads."""
    now = time.monotonic()
    signature = report_arrangement_signature(report_id)
    with REPORT_ARRANGEMENT_CACHE_LOCK:
        cached = REPORT_ARRANGEMENT_CACHE.get(report_id)
        if cached is not None and cached[0] > now and cached[2] == signature:
            REPORT_ARRANGEMENT_CACHE.move_to_end(report_id)
            return cached[1]
        build_lock = REPORT_ARRANGEMENT_BUILD_LOCKS.setdefault(report_id, threading.Lock())

    with build_lock:
        now = time.monotonic()
        signature = report_arrangement_signature(report_id)
        with REPORT_ARRANGEMENT_CACHE_LOCK:
            cached = REPORT_ARRANGEMENT_CACHE.get(report_id)
            if cached is not None and cached[0] > now and cached[2] == signature:
                REPORT_ARRANGEMENT_CACHE.move_to_end(report_id)
                return cached[1]
            generation = REPORT_ARRANGEMENT_CACHE_GENERATION
        payload = _build_report_arrangement_payload(report_id)
        if not payload.get("ok"):
            return payload
        with REPORT_ARRANGEMENT_CACHE_LOCK:
            if generation == REPORT_ARRANGEMENT_CACHE_GENERATION:
                REPORT_ARRANGEMENT_CACHE[report_id] = (
                    time.monotonic() + REPORT_ARRANGEMENT_CACHE_TTL_SECONDS,
                    payload,
                    signature,
                )
                REPORT_ARRANGEMENT_CACHE.move_to_end(report_id)
                while len(REPORT_ARRANGEMENT_CACHE) > REPORT_ARRANGEMENT_CACHE_LIMIT:
                    evicted_id, _ = REPORT_ARRANGEMENT_CACHE.popitem(last=False)
                    REPORT_ARRANGEMENT_BUILD_LOCKS.pop(evicted_id, None)
        return payload


def _enqueue_normalized_page_thumbnails(result):
    """Refresh derived previews only after their database transaction commits."""
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


def normalize_report_page_canvases(
    report_id,
    *,
    conn=None,
    file_journal=None,
    enqueue_thumbnails=True,
):
    """Ensure a report only references pages sized for its own canvas."""
    owns_connection = conn is None

    def normalize(active_conn):
        result = normalize_report_canvas_versions(
            active_conn,
            report_id,
            extracted_root=EXTRACTED,
            detect_dimensions=detected_html_preview_size,
            now_ms=now_ms,
            next_candidate_asset_code=next_candidate_asset_code,
            next_asset_version_no=next_asset_version_no,
            merge_tags=merge_tags,
            read_text_sample=read_text_sample,
            file_journal=file_journal,
        )
        return result

    if owns_connection:
        with db() as active_conn:
            result = normalize(active_conn)
    else:
        result = normalize(conn)
    if enqueue_thumbnails:
        _enqueue_normalized_page_thumbnails(result)
    if result.get("normalized"):
        invalidate_stats_cache()
    return result


def report_public_url(report_id):
    return f"/reports/{quote(report_id, safe='')}/index.html"


def control_public_url(control_id):
    return f"/pages/{quote(control_id, safe='')}/index.html"


def control_source_doc(control):
    """Return the Feishu source link declared by a page package manifest.

    The page wrapper is the common viewing surface for controls, so resolving
    this once here keeps every Feishu case page consistent without changing
    the authored 16:9 source files.
    """
    candidates = []
    path = local_html_preview_path(control)
    if path:
        for manifest_name in ("manifest.json", "ingestion-manifest.json"):
            manifest_path = path.parent / manifest_name
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
            candidates.extend([
                manifest.get("sourceDoc"),
                manifest.get("sourceUrl"),
                manifest.get("source_document"),
                (manifest.get("ai") or {}).get("sourceUrl"),
            ])
    # CLI-published pages are imported as standalone HTML files, so there is
    # no adjacent case manifest. Preserve the same source-copy affordance by
    # accepting a Feishu/Lark URL embedded in the asset description.
    keys = set(control.keys()) if hasattr(control, "keys") else set()
    if "description" in keys:
        candidates.append(control["description"])
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        urls = re.findall(r"https?://[^\s<>'\"]+", value)
        for url in urls or [value]:
            clean_url = url.rstrip(".,;，。；)")
            if "larkoffice.com/" in clean_url or ".feishu.cn/" in clean_url or "larksuite.com/" in clean_url:
                return clean_url
    return ""


def available_case_groups():
    """Load visible case groups once for both the API and case-only viewer."""
    timestamp = now_ms()
    with CASE_GROUP_CACHE_LOCK:
        cached = CASE_GROUP_CACHE["payload"]
        if cached is not None and timestamp < CASE_GROUP_CACHE["expires_at"]:
            return cached
        roots, _, _ = load_import_sources()
        case_asset_codes = case_group_asset_codes(EXTRACTED, roots)
        with db() as conn:
            rows = []
            for offset in range(0, len(case_asset_codes), 400):
                batch = case_asset_codes[offset:offset + 400]
                placeholders = ",".join("?" for _ in batch)
                rows.extend(conn.execute(
                    f"""
                    select * from assets
                    where asset_code in ({placeholders})
                      and asset_type in ('report', 'control')
                      and version_parent_id = ''
                    order by updated_at desc, created_at desc, asset_code desc
                    """,
                    batch,
                ).fetchall())
            asset_by_code = {}
            for row in rows:
                code = row["asset_code"] or ""
                if code and code not in asset_by_code:
                    asset_data = dict(row)
                    asset_by_code[code] = {
                        "title": row["title"],
                        "previewUrl": canonical_preview_url(row),
                        "thumbnailUrl": asset_thumbnail_url(asset_data, conn=conn),
                        "updatedAt": row["updated_at"],
                    }
            resource_paths = [
                f"{row['source_path']} {row['preview_url']}"
                for row in conn.execute(
                    "select source_path, preview_url from assets where asset_type = 'resource' and version_parent_id = ''"
                ).fetchall()
            ]
        groups = load_case_groups(EXTRACTED, roots, asset_by_code, resource_paths)
        CASE_GROUP_CACHE["payload"] = groups
        CASE_GROUP_CACHE["expires_at"] = now_ms() + 5000
        return groups


def report_public_page_items(report_id):
    """Return the current visible arrangement for the public report entry."""
    result = report_arrangement_payload(report_id)
    if not result.get("ok"):
        return result, []
    confirmed_ids = set(result.get("confirmedPageIds") or [])
    control_ids = [page["id"] for page in result["pages"] if page["id"] in confirmed_ids and not page["hidden"]]
    with db() as conn:
        tagged_controls = {
            row["id"]: row["tags"] or ""
            for row in conn.execute(
                f"select id, tags from assets where id in ({','.join('?' for _ in control_ids)})",
                control_ids,
            ).fetchall()
        } if control_ids else {}
    page_items = []
    for page in result["pages"]:
        if page["id"] not in confirmed_ids or page["hidden"]:
            continue
        page_items.append({
            "id": page["id"],
            "title": page["title"],
            "code": page["code"],
            "src": page["previewUrl"],
            "thumbnailUrl": page.get("thumbnailUrl") or page["previewUrl"],
            "isDirectory": "汇报目录" in tagged_controls.get(page["id"], ""),
        })
    return result, page_items


def update_report_arrangement(report_id, payload):
    current = report_arrangement_payload(report_id)
    if not current.get("ok"):
        return current
    expected_updated_at = payload.get("expectedUpdatedAt")
    if expected_updated_at is None:
        expected_updated_at = payload.get("expected_updated_at")
    if expected_updated_at is not None:
        try:
            expected_updated_at = int(expected_updated_at)
        except (TypeError, ValueError):
            return {"ok": False, "error": "编排版本格式无效"}
        current_updated_at = int(current.get("updatedAt") or 0)
        if expected_updated_at != current_updated_at:
            return {
                "ok": False,
                "conflict": True,
                "error": "该汇报已在其他窗口更新，请重新加载后再编辑",
                "expectedUpdatedAt": expected_updated_at,
                "currentUpdatedAt": current_updated_at,
            }
    known_ids = [page["id"] for page in current["pages"]]
    inserted = payload.get("insertedControlIds") or payload.get("inserted_control_ids") or []
    if not isinstance(inserted, list):
        return {"ok": False, "error": "插入页面格式无效"}
    inserted = list(dict.fromkeys(str(item) for item in inserted if str(item)))
    requested = payload.get("pageOrder") or payload.get("page_order") or []
    if not isinstance(requested, list):
        return {"ok": False, "error": "页面排序格式无效"}
    requested = list(dict.fromkeys(str(item) for item in requested if str(item)))
    removed = payload.get("removedPageIds") or payload.get("removed_page_ids") or []
    if not isinstance(removed, list):
        return {"ok": False, "error": "移出页面格式无效"}
    removed = set(str(item) for item in removed if str(item))
    with db() as conn:
        valid_inserted = {
            row["id"] for row in conn.execute(
                f"select id from assets where asset_type = 'control' and id in ({','.join('?' for _ in inserted)})",
                inserted,
            ).fetchall()
        } if inserted else set()
        removed &= set(known_ids)
        allowed = set(known_ids) | valid_inserted
        order = [item for item in requested if item in allowed and item not in removed]
        order.extend(item for item in known_ids if item not in order and item not in removed)
        order.extend(item for item in inserted if item in valid_inserted and item not in order)
    if not order:
        return {"ok": False, "error": "汇报至少需要保留一页"}
    raw_hidden = payload.get("hiddenPageIds") or payload.get("hidden_page_ids") or []
    if not isinstance(raw_hidden, list):
        return {"ok": False, "error": "隐藏页面格式无效"}
    hidden = [str(item) for item in raw_hidden if str(item) in order]
    timestamp = now_ms()
    file_journal = []
    try:
        with db() as conn:
            existing_rows = conn.execute(
                "select control_id, title, note from report_page_slots where report_id = ? and control_id <> '' order by page_number",
                (report_id,),
            ).fetchall()
            existing_meta = {}
            for row in existing_rows:
                existing_meta.setdefault(row["control_id"], {"title": row["title"], "note": row["note"]})
            controls = {}
            if order:
                placeholders = ",".join("?" for _ in order)
                controls = {
                    row["id"]: row
                    for row in conn.execute(
                        f"select id, title from assets where asset_type = 'control' and id in ({placeholders})",
                        order,
                    ).fetchall()
                }

            # Rebuild the attached rows in one transaction. Updating individual
            # rows fails when old data contains the same control in multiple slots.
            conn.execute(
                "delete from report_page_slots where report_id = ?",
                (report_id,),
            )
            saved_order = []
            for index, control_id in enumerate(order, start=1):
                control = controls.get(control_id)
                if not control:
                    continue
                meta = existing_meta.get(control_id, {})
                note = meta.get("note") or ("人工编排插入页面" if control_id in valid_inserted else "汇报页面编排")
                title = meta.get("title") or control["title"] or f"第 {index} 页"
                conn.execute(
                    """insert into report_page_slots
                    (report_id, page_number, title, status, control_id, task_key, note, created_at, updated_at)
                    values (?, ?, ?, 'attached', ?, '', ?, ?, ?)""",
                    (report_id, index, title, control_id, note, timestamp, timestamp),
                )
                saved_order.append(control_id)
            order = saved_order
            conn.execute(
                """
                insert into report_page_arrangements (report_id, page_order, hidden_page_ids, updated_by, updated_at)
                values (?, ?, ?, 'manual-arrangement', ?)
                on conflict(report_id) do update set
                  page_order = excluded.page_order,
                  hidden_page_ids = excluded.hidden_page_ids,
                  updated_by = excluded.updated_by,
                  updated_at = excluded.updated_at
                """,
                (report_id, json.dumps(order), json.dumps(hidden), timestamp),
            )
            # The public entry composes the committed slots at request time.
            conn.execute(
                "update assets set preview_url = ?, updated_at = ? where id = ? and asset_type = 'report'",
                (report_public_url(report_id), timestamp, report_id),
            )
            normalization = normalize_report_page_canvases(
                report_id,
                conn=conn,
                file_journal=file_journal,
                enqueue_thumbnails=False,
            )
    except Exception:
        restore_report_canvas_files(file_journal)
        raise
    _enqueue_normalized_page_thumbnails(normalization)
    invalidate_stats_cache()
    return report_arrangement_payload(report_id)


def adopt_report_page_candidate(candidate_id):
    with db() as conn:
        candidate = conn.execute(
            "select * from report_page_candidates where id = ?",
            (candidate_id,),
        ).fetchone()
        if not candidate:
            return {"ok": False, "error": "候选页不存在"}
        if candidate["status"] != "candidate":
            return {"ok": False, "error": "候选页状态不可采用"}
        control = conn.execute(
            "select * from assets where id = ? and asset_type = 'control'",
            (candidate["control_id"],),
        ).fetchone()
        if not control:
            return {"ok": False, "error": "候选页面素材不存在"}
        slot = conn.execute(
            "select * from report_page_slots where report_id = ? and page_number = ?",
            (candidate["report_id"], candidate["page_number"]),
        ).fetchone()
        if slot and slot["control_id"] and slot["control_id"] != candidate["control_id"]:
            previous = conn.execute("select * from assets where id = ?", (slot["control_id"],)).fetchone()
            if previous:
                register_report_page_candidate(
                    conn,
                    candidate["report_id"],
                    candidate["page_number"],
                    previous["id"],
                    previous["title"],
                    "采用新候选页前的上一版当前页",
                )
        promote_asset_version(conn, candidate["control_id"])
        attach_report_page_control(
            conn,
            candidate["report_id"],
            candidate["page_number"],
            candidate["control_id"],
            candidate["title"] or control["title"],
            "已手动采用候选页",
            replace=True,
        )
        sync_result = sync_report_index_from_slots(conn, candidate["report_id"], [candidate["page_number"]], "采用候选页后同步最新汇报 index")
        conn.execute(
            "update report_page_candidates set status = 'adopted', updated_at = ? where id = ?",
            (now_ms(), candidate_id),
        )
        report_id = candidate["report_id"]
    result = get_report_page_slots(report_id)
    result["reportSync"] = sync_result
    return result




def copy_page_variant(extract_root, source_rel, variant, source_hash):
    return import_copy_page_variant(extract_root, source_rel, variant, source_hash)


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
    upload_id = report["upload_id"] if "upload_id" in report.keys() else ""
    source_path = report["source_path"] if "source_path" in report.keys() else ""
    if upload_id and source_path:
        return f"/extracted/{upload_id}/{source_path}"
    return report["preview_url"] if "preview_url" in report.keys() else ""


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
        return validate_report_trusted_entry(conn, report_id, refresh=True)


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
            f"/reports/{report['id']}/index.html",
            source_hash,
            timestamp,
            report["id"],
        ),
    )
    try:
        updated_report = conn.execute("select * from assets where id = ?", (report["id"],)).fetchone()
        generate_html_thumbnail(
            report["id"],
            source,
            thumbnail_source_fingerprint(updated_report) if updated_report else source_hash,
        )
    except Exception:
        pass
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
        tags = merge_tags(report["tags"], ["页面素材", "页面片段", "手动导入", f"源汇报:{report['asset_code']}", f"第{page_number}页"])
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


def normalize_filename_for_match(name):
    value = str(name or "").strip()
    value = re.sub(r"\s*\(?\d+\)?\s*$", "", value)
    value = re.sub(r"[_\- ]*(?:v|V)\d+\s*$", "", value)
    value = re.sub(r"[_\- ]*copy\s*\d*$", "", value, flags=re.IGNORECASE)
    value = value.replace("-", " ").replace("_", " ").strip().lower()
    return value


def find_version_match(conn, filename, asset_type, html_title=""):
    if not filename:
        return None
    code_match = re.match(r"^((?:CTL|RES)-[A-Z0-9-]+)", filename, re.IGNORECASE)
    if code_match:
        row = conn.execute(
            "select * from assets where asset_code = ? and version_parent_id = '' limit 1",
            (code_match.group(1).upper(),),
        ).fetchone()
        if row:
            return row
    if filename.lower() in ("index", "page", "slide", "main") and html_title:
        row = conn.execute(
            """select * from assets
               where asset_type = ? and version_parent_id = ''
               and title = ?
               order by updated_at desc limit 1""",
            (asset_type, html_title.strip()),
        ).fetchone()
        if row:
            return row
    normalized = normalize_filename_for_match(filename)
    if not normalized or len(normalized) < 2:
        return None
    row = conn.execute(
        """select * from assets
           where asset_type = ? and version_parent_id = ''
           and lower(replace(replace(title, '-', ' '), '_', ' ')) = ?
           order by updated_at desc limit 1""",
        (asset_type, normalized),
    ).fetchone()
    return row


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
    version_group="",
    version_no=1,
    version_parent_id="",
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
    tags = ""
    resource_kind = resource_kind_for(file_path, media_kind, title, tags) if asset_type == "resource" else ""
    if resource_kind:
        tags = ",".join(normalize_role_tags(
            merge_tags(
                tags,
                [RESOURCE_KINDS.get(resource_kind, resource_kind)],
                suggest_material_tags(" ".join([title, rel, usage]), resource_kind),
                image_trait_tags(file_path) if media_kind in {"image", "gif"} else [],
                source_process_tags(source_type),
                page_usage_tags(" ".join([title, rel, usage])),
            ),
            asset_type,
            resource_kind,
            " ".join([title, rel]),
        ))
    preview_url = ""

    if asset_type in {"report", "page", "control"} and not snippet:
        snippet = read_text_sample(file_path)
    if asset_type in {"report", "page", "resource", "control"}:
        preview_url = f"/extracted/{upload_id}/{rel}"
    if asset_type == "resource":
        title, tags = apply_company_logo_metadata(title, tags, rel, usage, resource_kind)

    effective_version_group = version_group or asset_id
    effective_version_no = version_no
    effective_version_parent = version_parent_id

    conn.execute(
        """
        insert or ignore into assets
        (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, source_path, preview_url, upload_id, source_hash, tag_seeded, version_group, version_no, version_parent_id, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (asset_id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, rel, preview_url, upload_id, source_hash, 0, effective_version_group, effective_version_no, effective_version_parent, now_ms(), now_ms()),
    )
    return asset_id


def insert_scanned_asset(conn, file_path, upload_id, extract_root, *, multi_page_resource_import=False, single_html_import=False):
    rel = file_path.relative_to(extract_root).as_posix()
    source_hash = file_hash(file_path)
    if asset_exists(conn, source_hash):
        return None, None
    page_from_resource_import = (multi_page_resource_import or single_html_import) and file_path.suffix.lower() in {".html", ".htm"}
    target_asset_type = "control" if page_from_resource_import else (asset_type_for(file_path, category_for(file_path), "") or "resource")
    version_kwargs = {}
    matched_asset = None
    if target_asset_type in ("control", "resource"):
        html_title = ""
        if file_path.stem.lower() in ("index", "page", "slide", "main") and file_path.suffix.lower() in (".html", ".htm"):
            snippet = read_text_sample(file_path, limit=2000)
            m = re.search(r"<title[^>]*>([^<]+)</title>", snippet, re.IGNORECASE)
            if m:
                html_title = m.group(1).strip()
        matched_asset = find_version_match(conn, file_path.stem, target_asset_type, html_title=html_title)
        if matched_asset:
            group_id = matched_asset["version_group"] or matched_asset["id"]
            version_kwargs = {
                "version_group": group_id,
                "version_no": next_asset_version_no(conn, group_id),
                "version_parent_id": matched_asset["id"],
            }
    asset_id = insert_asset_record(
        conn,
        file_path=file_path,
        rel=rel,
        upload_id=upload_id,
        source_type="manual-version-import" if matched_asset else ("control-resource-import" if page_from_resource_import else "upload"),
        source_hash=source_hash,
        usage=("从无清单多页面包逐页导入" if multi_page_resource_import else "从单页 HTML 导入") if page_from_resource_import else "从上传文件自动扫描入库",
        asset_type_override="control" if page_from_resource_import else "",
        **version_kwargs,
    )
    if asset_id and matched_asset:
        promote_asset_version(conn, asset_id)
    return asset_id, matched_asset


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
    files = [path for path in extract_root.rglob("*") if path.is_file()]
    if control_template_manifest(extract_root):
        control_id, resource_count = insert_control_template_asset(conn, extract_root, upload_id, "template", description)
        inserted = (1 if control_id else 0) + resource_count
        conn.execute(
            "update uploads set file_count = ?, asset_count = ? where id = ?",
            (len(files), inserted, upload_id),
        )
        return len(files), inserted, []
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
        return file_count, asset_count, []
    assets = [path for path in files if path.suffix.lower() in ALLOWED_SUFFIXES]
    multi_page_resource_import = is_multi_page_resource_import(assets)
    html_assets = [path for path in assets if path.suffix.lower() in {".html", ".htm"}]
    single_html_import = len(html_assets) == 1
    inserted = 0
    version_matches = []
    for path in assets:
        asset_id, matched = insert_scanned_asset(
            conn, path, upload_id, extract_root,
            multi_page_resource_import=multi_page_resource_import,
            single_html_import=single_html_import,
        )
        if asset_id:
            inserted += 1
        if matched:
            version_matches.append({"assetId": asset_id, "matchedTitle": matched["title"], "matchedCode": matched["asset_code"]})
    refresh_report_trusted_entries_for_upload(conn, upload_id)
    conn.execute("update uploads set file_count = ?, asset_count = ? where id = ?", (len(files), inserted, upload_id))
    invalidate_stats_cache()
    return len(files), inserted, version_matches




def report_code_to_control_code(report_code, page_number):
    return import_report_code_to_control_code(report_code, page_number)


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


def safe_int(value, default=0):
    return import_safe_int(value, default)


def load_report_package_manifest(extract_root):
    return import_load_report_package_manifest(extract_root, read_json_file=read_json_file)


def report_package_entry_path(extract_root, manifest, manifest_kind):
    return import_report_package_entry_path(extract_root, manifest, manifest_kind)


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


def external_report_page_base_href(report_html_path, generated_page_path):
    relative = os.path.relpath(report_html_path.parent, generated_page_path.parent)
    return quote(relative.replace(os.sep, "/").rstrip("/") + "/", safe="/._-")


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
    page_spans = split_page_node_spans(report_html)
    if not page_spans:
        return []
    canvas_width, canvas_height = detect_preview_dimensions(report_html_path)
    if not canvas_width or not canvas_height:
        canvas_width, canvas_height = 1920, 1080
    deck_slides, deck_by_key, index_slides, index_by_key = load_deck_slides(extract_root)
    generated_root = Path(extract_root) / "_minem_pages"
    items = []
    for page_number, (_, _, page_node) in enumerate(page_spans, start=1):
        title = external_report_page_title(page_number, page_node, deck_slides, deck_by_key, index_slides, index_by_key)
        rel = f"_minem_pages/page-{page_number:03d}/index.html"
        target = generated_root / f"page-{page_number:03d}" / "index.html"
        base_href = external_report_page_base_href(report_html_path, target)
        page_html = inject_html_base_href(
            split_control_html(report_html, page_node, title, canvas_width, canvas_height),
            base_href,
        )
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
        merge_tags=merge_tags,
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
    # Thumbnail rendering must never run inside the import transaction. The
    # post-commit preview phase renders a representative card; remaining pages
    # are generated lazily when their list is opened.
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
        merge_tags=merge_tags,
        resource_kinds=RESOURCE_KINDS,
        suggest_material_tags=suggest_material_tags,
        normalize_role_tags=normalize_role_tags,
        apply_company_logo_metadata=apply_company_logo_metadata,
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
        merge_tags=merge_tags,
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
    return list_import_task_records(IMPORT_TASK_STORE, limit=8)


def get_import_task(task_id):
    return get_import_task_record(IMPORT_TASK_STORE, task_id)


def cancel_import_task(task_id):
    task = IMPORT_TASK_STORE.get(task_id, include_private=True)
    if not task:
        return {"ok": False, "error": "任务不存在"}, 404
    if task["status"] not in {"queued", "running"}:
        return {"ok": False, "error": "任务已结束，无法取消", "task": get_import_task(task_id)}, 409

    with IMPORT_CANCEL_LOCK:
        if task_id in IMPORT_COMMITTING_TASKS:
            return {"ok": False, "error": "任务正在提交素材，已无法安全取消", "task": get_import_task(task_id)}, 409
        cancel_event = IMPORT_CANCEL_EVENTS.setdefault(task_id, threading.Event())
        cancel_event.set()

    cancelled_before_start = JOB_RUNTIME.cancel("imports", task_id)
    if cancelled_before_start:
        updated = IMPORT_TASK_STORE.mark_cancelled(task_id)
        stored_record = str(task.get("storedPath") or "").strip()
        stored_path = Path(stored_record)
        if stored_record and not stored_path.is_absolute():
            stored_path = RUNTIME_ROOT / stored_path
        if stored_record:
            resolved_stored_path = stored_path.resolve()
            if is_path_within(resolved_stored_path, UPLOADS):
                resolved_stored_path.unlink(missing_ok=True)
        upload_id = str(task.get("uploadId") or "").strip()
        extract_root = (EXTRACTED / upload_id).resolve() if upload_id else None
        if extract_root and is_path_within(extract_root, EXTRACTED):
            shutil.rmtree(extract_root, ignore_errors=True)
        with IMPORT_CANCEL_LOCK:
            IMPORT_CANCEL_EVENTS.pop(task_id, None)
        return {"ok": True, "task": updated, "cancelled": True}, 200

    updated = IMPORT_TASK_STORE.mark_cancelling(task_id)
    return {"ok": True, "task": updated, "cancelled": False}, 202


def retry_import_task(task_id):
    task = IMPORT_TASK_STORE.get(task_id, include_private=True)
    if not task:
        return {"ok": False, "error": "任务不存在"}, 404
    if task["status"] in {"queued", "running"}:
        return {"ok": False, "error": "任务仍在处理中"}, 409
    stored_record = str(task.get("storedPath") or "").strip()
    stored_path = Path(stored_record)
    if not stored_path.is_absolute():
        stored_path = RUNTIME_ROOT / stored_path
    stored_path = stored_path.resolve()
    if not is_path_within(stored_path, UPLOADS) or not stored_path.is_file():
        return {"ok": False, "error": "原始导入文件已失效，请重新选择文件"}, 410
    upload_id = str(task.get("uploadId") or "").strip()
    original = str(task.get("fileName") or stored_path.name).strip() or stored_path.name
    if not upload_id:
        return {"ok": False, "error": "任务缺少导入批次信息，请重新选择文件"}, 409
    updated = update_import_task(
        task_id,
        status="queued",
        progress=4,
        message="等待重新导入",
        error="",
        fileCount=0,
        assetCount=0,
        thumbnailCount=0,
        assetId="",
        assetCode="",
        assetTitle="",
        assetType="",
        previewUrl="",
    )
    with IMPORT_CANCEL_LOCK:
        IMPORT_CANCEL_EVENTS[task_id] = threading.Event()
    try:
        JOB_RUNTIME.submit(
            "imports",
            task_id,
            run_import_task,
            task_id,
            str(stored_path),
            original,
            upload_id,
            "",
            file_hash(stored_path),
        )
    except JobQueueFullError:
        with IMPORT_CANCEL_LOCK:
            IMPORT_CANCEL_EVENTS.pop(task_id, None)
        failed = update_import_task(
            task_id,
            status="failed",
            progress=100,
            message="导入队列繁忙",
            error="当前导入任务较多，请稍后重试",
        )
        return {"ok": False, "error": "当前导入任务较多，请稍后重试", "task": failed}, 503
    return {"ok": True, "task": updated}, 202


def start_tag_analysis_task(task_id):
    try:
        JOB_RUNTIME.submit(
            "tags",
            task_id,
            run_tag_analysis_task_record,
            DB_PATH,
            EXTRACTED,
            task_id,
        )
        return True
    except JobQueueFullError:
        with db() as conn:
            conn.execute(
                """
                update tag_analysis_tasks
                set status = 'failed',
                    message = '标签分析队列繁忙',
                    error = '当前标签任务较多，请稍后重试',
                    updated_at = ?
                where id = ?
                """,
                (now_ms(), task_id),
            )
        return False


def create_tag_analysis_task(asset_ids, trigger_type="manual", scope_type="assets", apply_mode="suggestions"):
    with db() as conn:
        result = create_tag_analysis_task_record(conn, asset_ids, trigger_type, scope_type, apply_mode)
        if result.get("ok"):
            task = conn.execute("select * from tag_analysis_tasks where id = ?", (result["taskId"],)).fetchone()
            result["task"] = public_tag_analysis_task(task)
    if result.get("ok"):
        if not start_tag_analysis_task(result["taskId"]):
            result = get_tag_analysis_task(result["taskId"])
            result["ok"] = False
            result["error"] = "当前标签任务较多，请稍后重试"
    return result


def list_tag_analysis_tasks(limit=20):
    with db() as conn:
        rows = conn.execute("select * from tag_analysis_tasks order by updated_at desc, created_at desc limit ?", (max(1, min(limit, 100)),)).fetchall()
    return {"ok": True, "tasks": [public_tag_analysis_task(row) for row in rows]}


def get_tag_analysis_task(task_id):
    with db() as conn:
        row = conn.execute("select * from tag_analysis_tasks where id = ?", (task_id,)).fetchone()
    return {"ok": bool(row), "task": public_tag_analysis_task(row) if row else None, "error": "标签任务不存在" if not row else ""}


def run_scheduled_tag_analysis():
    with db() as conn:
        ids = tag_changed_asset_ids(conn)
    return create_tag_analysis_task(ids, trigger_type="scheduled", scope_type="changed-assets") if ids else {"ok": True, "skipped": True, "reason": "没有待分析或内容变化的素材"}


def start_tag_scheduler():
    global TAG_SCHEDULER_WORKER
    if TAG_SCHEDULER_WORKER and TAG_SCHEDULER_WORKER.is_alive():
        return
    def loop():
        last_date = ""
        while True:
            local = time.localtime()
            today = time.strftime("%Y-%m-%d", local)
            if local.tm_hour == 0 and local.tm_min == 0 and today != last_date:
                last_date = today
                try:
                    run_scheduled_tag_analysis()
                except Exception as error:
                    print(f"Scheduled tag analysis skipped: {error}")
            time.sleep(20)
    TAG_SCHEDULER_WORKER = threading.Thread(target=loop, name="minem-tag-scheduler", daemon=True)
    TAG_SCHEDULER_WORKER.start()


def reject_oversized_upload(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0") or 0)
    except ValueError:
        length = 0
    try:
        validate_upload_request_size(length)
    except UploadLimitError as error:
        handler.send_json({"ok": False, "error": str(error)}, 413)
        return True
    return False


MAX_JSON_BODY_BYTES = 8 * 1024 * 1024


def reject_oversized_json(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0") or 0)
    except ValueError:
        length = 0
    if length > MAX_JSON_BODY_BYTES:
        handler.send_json({"ok": False, "error": "请求体过大"}, 413)
        return True
    return False


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
    extract_root = Path(extract_root)
    export_manifest = read_json_file(extract_root / "minem-export-manifest.json")
    manifest_report = export_manifest.get("report") if isinstance(export_manifest, dict) else None
    report_id = ""
    report_code = ""
    if isinstance(manifest_report, dict):
        raw_report_id = manifest_report.get("id")
        raw_report_code = manifest_report.get("code")
        report_id = raw_report_id.strip() if isinstance(raw_report_id, str) else ""
        report_code = raw_report_code.strip() if isinstance(raw_report_code, str) else ""

    if report_id or report_code:
        with db() as conn:
            explicit_rows = []
            if report_id:
                row = conn.execute(
                    "select * from assets where id = ? and asset_type in ('report', 'page') limit 1",
                    (report_id,),
                ).fetchone()
                if row:
                    explicit_rows.append(row)
            if report_code:
                row = conn.execute(
                    "select * from assets where asset_code = ? and asset_type in ('report', 'page') limit 1",
                    (report_code,),
                ).fetchone()
                if row and all(candidate["id"] != row["id"] for candidate in explicit_rows):
                    explicit_rows.append(row)
            assets = add_version_counts(conn, explicit_rows)
        entry = next((asset for asset in assets if asset.get("preview_url")), None)
        if entry:
            return {
                "assetId": entry["id"],
                "assetCode": entry["asset_code"],
                "previewUrl": entry["preview_url"],
                "assetTitle": entry["title"],
                "assetType": entry["asset_type"],
                "sourceUploadId": entry["upload_id"],
            }

    hashes = [
        file_hash(path)
        for path in extract_root.rglob("*")
        if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES
    ]
    if not hashes:
        return {}
    BATCH_SIZE = 500
    rows = []
    with db() as conn:
        for i in range(0, len(hashes), BATCH_SIZE):
            batch = hashes[i:i + BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows.extend(conn.execute(
                f"select * from assets where source_hash in ({placeholders})",
                batch,
            ).fetchall())
        type_order = {"report": 1, "control": 2, "resource": 3}
        rows.sort(key=lambda r: (type_order.get(r["asset_type"], 4), -(r["updated_at"] or 0), r["asset_code"] or ""))
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
        "sourceUploadId": entry["upload_id"],
    }


def generate_html_thumbnail(asset_id, html_path, source_fingerprint="", allow_text_fallback=True):
    if not Image:
        sys.stderr.write(f"[thumbnails] PIL/Pillow 未安装，无法为 {asset_id} 生成缩略图\n")
        return False
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
        refresh_upload_page_fingerprints(conn, upload_id)
        representative_rows = conn.execute(
            """
            select id, source_path, preview_url, source_hash, asset_type, upload_id, media_kind
            from assets
            where upload_id = ? and asset_type in ('report', 'control')
            order by case asset_type when 'report' then 0 else 1 end, created_at, id
            limit 1
            """,
            (upload_id,),
        ).fetchall()
        pending_rows = conn.execute(
            """
            select id, source_path, preview_url, source_hash, asset_type, upload_id, media_kind
            from assets
            where upload_id = ?
              and asset_type = 'control'
              and semantic_dedupe_status = 'pending'
            order by created_at, id
            """,
            (upload_id,),
        ).fetchall()
        candidate_rows = []
        for row in pending_rows:
            candidate_rows.extend(
                conn.execute(
                    """
                    select id, source_path, preview_url, source_hash, asset_type, upload_id, media_kind
                    from assets
                    where asset_type = 'control'
                      and id <> ?
                      and version_parent_id = ''
                      and semantic_fingerprint = (
                        select semantic_fingerprint from assets where id = ?
                      )
                      and semantic_fingerprint_version = ?
                    order by created_at, asset_code, id
                    limit 3
                    """,
                    (row["id"], row["id"], PAGE_FINGERPRINT_VERSION),
                ).fetchall()
            )
        rows = []
        seen_ids = set()
        pending_ids = {row["id"] for row in pending_rows}
        representative_only = [
            row for row in representative_rows if row["id"] not in pending_ids
        ]
        for row in [*candidate_rows, *representative_only, *pending_rows]:
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            rows.append(row)
    upload_root = (EXTRACTED / upload_id).resolve()
    for row in rows:
        fingerprint = thumbnail_source_fingerprint(row)
        if thumbnail_url(row["id"], fingerprint):
            reconcile_pending_page_peers(row["id"])
            continue
        html_path = local_html_preview_path(row)
        if not html_path:
            continue
        if generate_html_thumbnail(row["id"], html_path, fingerprint):
            created += 1
            reconcile_pending_page_peers(row["id"])
    return created


def run_import_task(task_id, stored_path, original, upload_id, description, content_hash=""):
    with IMPORT_CANCEL_LOCK:
        cancel_event = IMPORT_CANCEL_EVENTS.setdefault(task_id, threading.Event())

    def begin_commit():
        with IMPORT_CANCEL_LOCK:
            if cancel_event.is_set():
                return False
            IMPORT_COMMITTING_TASKS.add(task_id)
            return True

    try:
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
            is_cancelled=cancel_event.is_set,
            begin_commit=begin_commit,
        )
    finally:
        with IMPORT_CANCEL_LOCK:
            IMPORT_COMMITTING_TASKS.discard(task_id)
            IMPORT_CANCEL_EVENTS.pop(task_id, None)


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


def cleanup_deleted_asset_files(result):
    removed = False
    paths = set()
    for item in result.get("source_files", []):
        paths.add((EXTRACTED / item["upload_id"] / item["source_path"]).resolve())
    for item in result.get("history_rows", []):
        if item.get("snapshot_path"):
            paths.add((EXTRACTED / item["snapshot_path"]).resolve())
        paths.add((THUMBNAILS / f"{item['id']}.png").resolve())
    for target_id in result.get("target_ids", []):
        paths.add((THUMBNAILS / f"{target_id}.png").resolve())
    for item in result.get("export_rows", []):
        if item.get("output_path"):
            export_path = Path(item["output_path"]).resolve()
            if is_path_within(export_path, REPORT_EXPORTS):
                paths.add(export_path)

    for path in paths:
        if not (
            is_path_within(path, EXTRACTED)
            or is_path_within(path, THUMBNAILS)
            or is_path_within(path, REPORT_EXPORTS)
        ):
            continue
        if path.exists() and path.is_file():
            try:
                path.unlink()
                removed = True
            except OSError:
                continue

    for upload_id in result.get("empty_created_uploads", []):
        upload_root = (EXTRACTED / upload_id).resolve()
        if is_path_within(upload_root, EXTRACTED) and upload_root.exists():
            shutil.rmtree(upload_root, ignore_errors=True)
            removed = True

    for upload_id in result.get("upload_ids", []):
        stored_zip = (UPLOADS / f"{upload_id}.zip").resolve()
        if is_path_within(stored_zip, UPLOADS) and stored_zip.exists():
            try:
                stored_zip.unlink()
                removed = True
            except OSError:
                pass
        upload_root = (EXTRACTED / upload_id).resolve()
        if is_path_within(upload_root, EXTRACTED) and upload_root.is_dir():
            remaining = list(upload_root.iterdir())
            if not remaining:
                shutil.rmtree(upload_root, ignore_errors=True)
                removed = True

    return removed


def refresh_upload_count(conn, upload_id):
    if not upload_id:
        return
    count = conn.execute("select count(*) from assets where upload_id = ?", (upload_id,)).fetchone()[0]
    conn.execute("update uploads set asset_count = ? where id = ?", (count, upload_id))


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
    asset_ids = [row["id"] for row in rows]
    storyline_counts = {}
    if asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        for row in conn.execute(
            f"""
            select asset_id, sum(count) count from (
              select source_report_id asset_id, count(*) count
              from report_storyline_collections
              where source_report_id in ({placeholders})
              group by source_report_id
              union all
              select output_report_id asset_id, count(*) count
              from report_storyline_collections
              where output_report_id in ({placeholders})
              group by output_report_id
            )
            group by asset_id
            """,
            asset_ids + asset_ids,
        ).fetchall():
            storyline_counts[row["asset_id"]] = row["count"]
    assets = []
    for row in rows:
        item = row_to_asset(row, conn=conn)
        item["versionCount"] = counts.get(row["version_group"] or row["id"], 1)
        item["storylineCount"] = storyline_counts.get(row["id"], 0)
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
    with STATS_CACHE_LOCK:
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
    with STATS_CACHE_LOCK:
        STATS_CACHE["payload"] = payload
        STATS_CACHE["expires_at"] = now + 30
    return payload


def invalidate_stats_cache():
    global REPORT_ARRANGEMENT_CACHE_GENERATION
    with STATS_CACHE_LOCK:
        STATS_CACHE["payload"] = None
        STATS_CACHE["expires_at"] = 0
    with CASE_GROUP_CACHE_LOCK:
        CASE_GROUP_CACHE["payload"] = None
        CASE_GROUP_CACHE["expires_at"] = 0
    with REPORT_ARRANGEMENT_CACHE_LOCK:
        REPORT_ARRANGEMENT_CACHE.clear()
        REPORT_ARRANGEMENT_BUILD_LOCKS.clear()
        REPORT_ARRANGEMENT_CACHE_GENERATION += 1


def update_asset_tags(asset_id, tags):
    incoming = tags if isinstance(tags, list) else [
        tag.strip().strip("#")
        for tag in re.split(r"[,，、;；\n]+", str(tags or ""))
        if tag.strip()
    ]
    with db() as conn:
        ensure_tag_task_schema(conn)
        definitions = {
            item["tag"]: item
            for item in taxonomy_definitions(conn)["definitions"]
        }
        normalized = []
        invalid = []
        for value in incoming:
            tag = str(value).strip()
            definition = definitions.get(tag)
            if not definition or not definition["active"]:
                invalid.append(tag)
            elif tag not in normalized:
                normalized.append(tag)
        normalized = normalized[:4]
        if invalid:
            return {"ok": False, "error": f"包含未启用或不在受控词表中的标签：{', '.join(invalid[:6])}"}
        asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not asset:
            return {"ok": False, "error": "素材不存在"}
        timestamp = now_ms()
        conn.execute("delete from asset_tags where asset_id=?", (asset_id,))
        for tag in normalized:
            conn.execute("""insert into asset_tags(
              asset_id,tag,dimension,source,confidence,evidence_json,confirmed_at,updated_at
            ) values (?,?,?,'manual',1,'[]',?,?)""",
              (asset_id, tag, definitions[tag]["dimension"], timestamp, timestamp))
        conn.execute("update assets set tags=?, tag_seeded=1 where id=?", (",".join(normalized), asset_id))
        row = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        updated = add_version_counts(conn, [row])[0]
    return {"ok": True, "asset": updated}


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


def update_asset_page_role(asset_id, page_role):
    normalized = str(page_role or "").strip()
    if normalized and normalized not in PAGE_ROLES:
        return {"ok": False, "error": f"无效的页面属性，可选值：{', '.join(PAGE_ROLES.keys())}"}
    with db() as conn:
        asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not asset:
            return {"ok": False, "error": "素材不存在"}
        if asset["asset_type"] != "control":
            return {"ok": False, "error": "仅页面素材支持设置页面属性"}
        conn.execute(
            "update assets set page_role = ?, updated_at = ? where id = ?",
            (normalized, now_ms(), asset_id),
        )
        row = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        updated = add_version_counts(conn, [row])[0]
    return {"ok": True, "asset": updated}


def normalize_storyline_entry(raw, index):
    if not isinstance(raw, dict):
        return None
    directory = raw.get("directory") if isinstance(raw.get("directory"), list) else []
    fixed_blocks = raw.get("fixedBlocks") if isinstance(raw.get("fixedBlocks"), list) else []
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    normalized_directory = []
    for section in directory:
        if not isinstance(section, dict):
            continue
        default_content = section.get("defaultContent") if isinstance(section.get("defaultContent"), list) else []
        normalized_directory.append({
            "title": str(section.get("title") or "").strip(),
            "role": str(section.get("role") or "").strip(),
            "defaultContent": [str(item).strip() for item in default_content if str(item).strip()],
        })
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    code = str(raw.get("code") or f"STL-{index + 1:03d}").strip()
    return {
        "id": str(raw.get("id") or hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]).strip(),
        "code": code,
        "title": title,
        "scenario": str(raw.get("scenario") or "").strip(),
        "tone": str(raw.get("tone") or "").strip(),
        "tags": [str(item).strip() for item in tags if str(item).strip()],
        "fixedBlocks": [str(item).strip() for item in fixed_blocks if str(item).strip()],
        "directory": normalized_directory,
        "createdAt": raw.get("createdAt") or "",
        "updatedAt": raw.get("updatedAt") or "",
    }


def next_storyline_code(conn):
    prefix = f"STL-{date_key()}"
    rows = conn.execute(
        "select code from report_storyline_collections where code like ?",
        (f"{prefix}-%",),
    ).fetchall()
    max_num = 0
    for row in rows:
        try:
            max_num = max(max_num, int((row["code"] or "").rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{prefix}-{max_num + 1:03d}"


def next_storyline_version_no(conn, version_group):
    return safe_int(conn.execute(
        "select coalesce(max(version_no), 0) + 1 from report_storyline_collections where version_group = ?",
        (version_group,),
    ).fetchone()[0], 1)


def compact_storyline_source(data):
    source_id = data.get("source_asset_id") or data.get("source_report_id") or ""
    if not source_id:
        return None
    source = {
        "id": source_id,
        "asset_code": data.get("source_asset_code") or data.get("source_report_code") or "",
        "title": data.get("source_report_title") or data.get("source_report_code") or "来源汇报",
        "media_kind": data.get("source_media_kind") or "html",
        "asset_type": "report",
        "preview_url": canonical_preview_url({
            "preview_url": data.get("source_report_preview_url") or "",
            "upload_id": data.get("source_upload_id") or "",
            "source_path": data.get("source_source_path") or "",
        }),
        "thumbnail_url": "",
        "tags": split_tags(data.get("source_tags") or ""),
        "created_at": data.get("source_created_at") or "",
        "updated_at": data.get("source_updated_at") or "",
    }
    source["thumbnail_url"] = thumbnail_url(source_id, thumbnail_source_fingerprint(source))
    return source


def storyline_version_summary(item):
    return {
        "id": item["id"],
        "code": item["code"],
        "title": item["title"],
        "scenario": item.get("scenario", ""),
        "tone": item.get("tone", ""),
        "tags": item.get("tags", []),
        "fixedBlocks": item.get("fixedBlocks", []),
        "directory": item.get("directory", []),
        "sourceReportId": item.get("sourceReportId", ""),
        "sourceReportCode": item.get("sourceReportCode", ""),
        "sourceReport": item.get("sourceReport"),
        "outputReportId": item.get("outputReportId", ""),
        "outputReportCode": item.get("outputReportCode", ""),
        "targetReportId": item.get("targetReportId", ""),
        "mode": item.get("mode", "collection"),
        "note": item.get("note", ""),
        "versionGroup": item.get("versionGroup", ""),
        "versionNo": item.get("versionNo", 1),
        "versionParentId": item.get("versionParentId", ""),
        "versionLabel": item.get("versionLabel", "V1"),
        "versionCount": item.get("versionCount", 1),
        "createdAt": item.get("createdAt", ""),
        "updatedAt": item.get("updatedAt", ""),
    }


def storyline_from_collection(row):
    data = dict(row)
    tags = [tag.strip() for tag in (data.get("tags") or "").split(",") if tag.strip()]
    mode = data.get("mode") or "collection"
    version_no = safe_int(data.get("version_no"), 1)
    mode_label = f"故事线版本 V{version_no}"
    fixed_blocks = [
        f"来源汇报：{data.get('source_report_code') or ''}",
        f"版本：V{version_no}",
    ]
    if data.get("version_parent_id"):
        fixed_blocks.append("类型：已有故事线的新版本")
    else:
        fixed_blocks.append("类型：新建故事线")
    if data.get("output_report_code"):
        fixed_blocks.append(f"历史产出汇报：{data.get('output_report_code')}")
    if data.get("note"):
        fixed_blocks.append(f"备注：{data.get('note')}")
    return {
        "id": data.get("id"),
        "code": data.get("code"),
        "title": data.get("title"),
        "scenario": f"由 {data.get('source_report_code') or ''} 收藏生成的故事线",
        "tone": mode_label,
        "tags": tags,
        "fixedBlocks": fixed_blocks,
        "directory": [],
        "sourceReportId": data.get("source_report_id"),
        "sourceReportCode": data.get("source_report_code"),
        "sourceReport": compact_storyline_source(data),
        "outputReportId": data.get("output_report_id"),
        "outputReportCode": data.get("output_report_code"),
        "targetReportId": data.get("target_report_id"),
        "mode": mode,
        "note": data.get("note"),
        "versionGroup": data.get("version_group") or data.get("id"),
        "versionNo": version_no,
        "versionParentId": data.get("version_parent_id") or "",
        "versionLabel": f"V{version_no}",
        "versionCount": 1,
        "versions": [],
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
    }


def load_template_storylines(search=""):
    if not STORYLINES_PATH.exists():
        return []
    try:
        payload = json.loads(STORYLINES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ValueError("故事线数据文件格式错误")
    raw_items = payload.get("storylines", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise ValueError("故事线数据必须是数组")
    items = [item for item in (normalize_storyline_entry(raw, index) for index, raw in enumerate(raw_items)) if item]
    return filter_storylines(items, search)


def filter_storylines(items, search=""):
    keyword = (search or "").strip().lower()
    if not keyword:
        return items

    def matched(item):
        text = " ".join([
            str(item.get("id", "")),
            str(item.get("code", "")),
            str(item.get("title", "")),
            str(item.get("scenario", "")),
            str(item.get("tone", "")),
            str(item.get("sourceReportCode", "")),
            str(item.get("outputReportCode", "")),
            str(item.get("versionLabel", "")),
            " ".join(
                " ".join([
                    str(version.get("title", "")),
                    str(version.get("sourceReportCode", "")),
                    str(version.get("versionLabel", "")),
                    str(version.get("note", "")),
                ])
                for version in item.get("versions", [])
            ),
            " ".join(item.get("tags", [])),
            " ".join(item.get("fixedBlocks", [])),
            " ".join(
                " ".join([section.get("title", ""), section.get("role", ""), " ".join(section.get("defaultContent", []))])
                for section in item.get("directory", [])
            ),
        ]).lower()
        return keyword in text
    return [item for item in items if matched(item)]


def load_storyline_collections(conn, search=""):
    rows = conn.execute(
        """
        select
          c.*,
          a.id source_asset_id,
          a.asset_code source_asset_code,
          a.title source_report_title,
          a.preview_url source_report_preview_url,
          a.source_path source_source_path,
          a.upload_id source_upload_id,
          a.media_kind source_media_kind,
          a.tags source_tags,
          a.created_at source_created_at,
          a.updated_at source_updated_at
        from report_storyline_collections c
        left join assets a on a.id = c.source_report_id
        order by c.version_group, c.version_no, c.created_at
        """
    ).fetchall()
    grouped = {}
    for row in rows:
        item = storyline_from_collection(row)
        group_id = item.get("versionGroup") or item.get("id")
        grouped.setdefault(group_id, []).append(item)

    items = []
    for versions in grouped.values():
        ordered = sorted(versions, key=lambda item: (safe_int(item.get("versionNo"), 1), safe_int(item.get("createdAt"), 0)))
        latest = dict(ordered[-1])
        summaries = [storyline_version_summary(item) for item in reversed(ordered)]
        latest["versions"] = summaries
        latest["versionCount"] = len(summaries)
        latest["versionLabel"] = f"V{safe_int(latest.get('versionNo'), 1)}"
        items.append(latest)
    items.sort(key=lambda item: safe_int(item.get("updatedAt") or item.get("createdAt"), 0), reverse=True)
    return filter_storylines(items, search)


def storyline_sort_timestamp(item):
    return safe_int(item.get("updatedAt") or item.get("createdAt"), 0)


def load_storylines(search=""):
    try:
        templates = load_template_storylines(search)
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    with db() as conn:
        collections = load_storyline_collections(conn, search)
    items = collections + templates
    items.sort(key=storyline_sort_timestamp, reverse=True)
    return {
        "ok": True,
        "storylines": items,
        "summary": {
            "count": len(items),
            "directoryCount": sum(len(item.get("directory", [])) for item in items),
            "fixedBlockCount": sum(len(item.get("fixedBlocks", [])) for item in items),
        },
    }


def create_report_storyline_collection(source_report_id, payload):
    title = str(payload.get("title") or "").strip()
    note = str(payload.get("note") or "").strip()
    collect_mode = str(payload.get("storylineMode") or payload.get("mode") or "new").strip()
    target_storyline_id = str(payload.get("target_storyline_id") or payload.get("targetStorylineId") or "").strip()
    if collect_mode not in {"new", "version"}:
        return {"ok": False, "error": "故事线收藏方式不正确"}
    with db() as conn:
        source = conn.execute(
            "select * from assets where id = ? and asset_type = 'report'",
            (source_report_id,),
        ).fetchone()
        if not source:
            return {"ok": False, "error": "来源汇报不存在"}
        timestamp = now_ms()
        target_storyline = None
        if collect_mode == "version":
            if not target_storyline_id:
                return {"ok": False, "error": "请选择要更新版本的故事线"}
            target_storyline = conn.execute(
                "select * from report_storyline_collections where id = ?",
                (target_storyline_id,),
            ).fetchone()
            if not target_storyline:
                return {"ok": False, "error": "目标故事线不存在"}
        if target_storyline:
            version_group = target_storyline["version_group"] or target_storyline["id"]
            version_no = next_storyline_version_no(conn, version_group)
            version_parent_id = target_storyline["id"]
            collection_code = target_storyline["code"]
            collection_title = title or target_storyline["title"] or clean_report_title(source["title"]) or source["title"]
        else:
            version_no = 1
            version_parent_id = ""
            collection_code = next_storyline_code(conn)
            collection_title = title or clean_report_title(source["title"]) or source["title"]
            version_group = ""
        digest = hashlib.sha1(f"{source['id']}:{collection_code}:v{version_no}:{timestamp}".encode("utf-8")).hexdigest()[:10]
        collection_id = f"storyline-{digest}"
        if not version_group:
            version_group = collection_id
        tags = merge_tags(source["tags"], ["故事线收藏", "汇报材料", collection_code, f"V{version_no}"])
        conn.execute(
            """
            insert into report_storyline_collections
            (id, code, title, source_report_id, source_report_code, output_report_id, output_report_code, target_report_id, mode, note, tags, version_group, version_no, version_parent_id, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection_id,
                collection_code,
                collection_title,
                source["id"],
                source["asset_code"],
                "",
                "",
                "",
                "collection",
                note,
                ",".join(tags),
                version_group,
                version_no,
                version_parent_id,
                timestamp,
                timestamp,
            ),
        )
        storyline = next(
            (item for item in load_storyline_collections(conn) if item.get("versionGroup") == version_group),
            None,
        )
    return {"ok": True, "storyline": storyline}


def report_viewer_html(title, page_items, release_url="", arrangement_state=None):
    pages = []
    for index, item in enumerate(page_items, start=1):
        page_title = item.get("title") or f"Page {index:02d}"
        page_id = (
            str(item.get("id") or "").strip()
            or str(item.get("code") or "").strip()
            or f"page-{index:02d}"
        )
        pages.append({
            "id": page_id,
            "label": f"Page {index:02d}",
            "title": page_title,
            "code": item.get("code") or "",
            "src": item.get("src") or "",
            "sourceDoc": item.get("sourceDoc") or "",
            "isDirectory": bool(item.get("isDirectory")),
            "role": "cover" if index == 1 else "content",
        })
    if not pages:
        pages = [{"id": "cover", "label": "Page 01", "title": "首页", "code": "", "src": "", "role": "cover"}]
    pages_json = json_for_html_script(pages, indent=6)
    release_url_json = json_for_html_script(release_url or "")
    arrangement_state_json = json_for_html_script(arrangement_state or {})
    safe_title = html.escape(title or "汇报素材", quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, "PingFang SC", "Microsoft YaHei", Arial, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; overflow: hidden; background: #02050c; color: #fff; }}
    .viewer {{ position: relative; width: 100vw; height: 100vh; display: grid; place-items: center; }}
    .slide-viewport {{ position: relative; width: calc(1920px * var(--deck-scale, 1)); height: calc(1080px * var(--deck-scale, 1)); }}
    .slide-shell {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: hidden; background: #030712; transform: scale(var(--deck-scale, 1)); transform-origin: left top; }}
    .frame-stack {{ position: absolute; inset: 0; overflow: hidden; background: #030712; }}
    iframe {{ position: absolute; inset: 0; width: 1920px; height: 1080px; border: 0; background: #030712; visibility: hidden; opacity: 0; pointer-events: none; }}
    iframe.is-active {{ visibility: visible; opacity: 1; pointer-events: none; }}
    .viewer.is-interactive iframe.is-active {{ pointer-events: auto; }}
    .page-pill {{ position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); display: inline-flex; gap: 12px; align-items: center; border: 1px solid rgba(153,180,209,.34); border-radius: 999px; padding: 10px 18px; background: rgba(2,5,12,.62); font-size: 14px; }}
    .page-pill[hidden] {{ display: none; }}
    .nav-btn {{ width: 30px; height: 30px; border: 1px solid rgba(153,180,209,.34); border-radius: 999px; color: #fff; background: rgba(255,255,255,.08); cursor: pointer; }}
    .nav-btn:disabled {{ opacity: .35; cursor: default; }}
    .page-tools {{ position: fixed; top: 24px; right: 24px; display: inline-flex; gap: 8px; padding: 6px; border: 1px solid rgba(153,180,209,.34); border-radius: 10px; background: rgba(2,5,12,.72); }}
    .tool-btn {{ width: 36px; height: 36px; border: 0; border-radius: 7px; color: #fff; background: transparent; font-size: 19px; line-height: 1; cursor: pointer; }}
    .tool-btn:hover {{ background: rgba(255,255,255,.12); }}
    .tool-btn svg {{ display: block; width: 20px; height: 20px; margin: auto; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }}
    .toc-page {{ color: #8cecff; }}
    .toc-page[hidden] {{ display: none; }}
    .copy-page, .copy-source {{ position: relative; font-size: 0; }}
    .copy-page::before, .copy-page::after {{ content: ""; position: absolute; width: 11px; height: 12px; border: 1.5px solid currentColor; border-radius: 2px; }}
    .copy-page::before {{ left: 10px; top: 9px; opacity: .72; }}
    .copy-page::after {{ left: 14px; top: 13px; background: #02050c; }}
    .copy-source::before {{ content: "↗"; position: absolute; inset: 0; display: grid; place-items: center; font-size: 21px; font-weight: 800; }}
    .copy-source[hidden] {{ display: none; }}
    .copy-tip {{ position: fixed; top: 78px; right: 24px; z-index: 4; padding: 8px 12px; border: 1px solid rgba(114,213,255,.55); border-radius: 8px; background: rgba(12,38,65,.96); color: #b8ebff; font-size: 13px; font-weight: 800; opacity: 0; transform: translateY(-6px); pointer-events: none; transition: opacity .16s ease,transform .16s ease; }}
    .copy-tip.is-visible {{ opacity: 1; transform: translateY(0); }}
	    .page-state {{ position: absolute; z-index: 3; inset: 0; display: grid; place-items: center; align-content: center; gap: 12px; padding: 32px; color: #b8c8d8; background: radial-gradient(circle at 50% 34%, rgba(57,112,165,.18), transparent 48%), #030712; text-align: center; }}
	    .page-state[hidden] {{ display: none; }}
	    .page-state strong {{ color: #fff; font-size: 18px; }}
	    .page-state span {{ max-width: 480px; font-size: 13px; line-height: 1.6; }}
	    .page-state button {{ min-height: 36px; border: 1px solid rgba(153,180,209,.38); border-radius: 8px; padding: 0 14px; color: #fff; background: rgba(255,255,255,.08); cursor: pointer; }}
	    .page-state.is-loading::before {{ width: 24px; height: 24px; border: 2px solid rgba(184,207,229,.28); border-top-color: #8cecff; border-radius: 50%; content: ""; animation: page-spin .8s linear infinite; }}
	    @keyframes page-spin {{ to {{ transform: rotate(360deg); }} }}
    html[data-embed="1"] .page-tools {{ display: none; }}
    @media (max-width: 720px) {{ .page-tools {{ top: 12px; right: 12px; }} .page-pill {{ bottom: 12px; }} }}
  </style>
</head>
	<body>
	  <script id="minem-arrangement-state" type="application/json">{arrangement_state_json}</script>
	  <main class="viewer" aria-label="{safe_title}">
	    <div class="slide-viewport"><section class="slide-shell"><div class="frame-stack"></div><div class="page-state is-loading" role="status"><strong>正在加载当前页面</strong><span>页面素材正在准备，请稍候。</span><button class="retry-page" type="button" hidden>重新加载当前页</button></div></section></div>
    <div class="page-tools" aria-label="页面工具"><button class="tool-btn toc-page" type="button" title="返回目录" aria-label="返回目录" hidden><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"></path></svg></button><button class="tool-btn copy-page" type="button" title="复制当前页链接" aria-label="复制当前页链接"></button><button class="tool-btn copy-source" type="button" title="复制原始飞书文档链接" aria-label="复制原始飞书文档链接" hidden></button><button class="tool-btn refresh-page" type="button" title="刷新当前页" aria-label="刷新当前页">↻</button><button class="tool-btn fullscreen-page" type="button" title="全屏" aria-label="全屏">⛶</button></div>
    <div class="copy-tip" role="status">复制成功</div>
    <div class="page-pill"><button class="nav-btn prev" type="button" aria-label="上一页">‹</button><span class="page-count">1 / 1</span><span>·</span><span class="page-title">Page 01</span><button class="nav-btn next" type="button" aria-label="下一页">›</button></div>
  </main>
  <script>
	    const pages = {pages_json};
	    const embedded = new URLSearchParams(window.location.search).get("embed") === "1";
	    if (embedded) document.documentElement.dataset.embed = "1";
	    if (pages.length <= 1) document.querySelector(".page-pill").hidden = true;
	    const releaseUrl = {release_url_json};
	    const heartbeatUrl = releaseUrl ? releaseUrl.replace(new RegExp("/release$"), "/heartbeat") : "";
	    let currentIndex = 0;
	    let released = false;
	    let heartbeatTimer = 0;
    const frameStack = document.querySelector(".frame-stack");
    const frames = pages.map(() => null);
    const pageLoadStates = pages.map(() => "pending");
    const pageLoadTimers = [];
    const pageLoadSequences = pages.map(() => 0);
    const pageCount = document.querySelector(".page-count");
    const pageTitle = document.querySelector(".page-title");
    const prevButton = document.querySelector(".prev");
    const nextButton = document.querySelector(".next");
    const tocButton = document.querySelector(".toc-page");
    const copyButton = document.querySelector(".copy-page");
    const copySourceButton = document.querySelector(".copy-source");
    const copyTip = document.querySelector(".copy-tip");
	    const pageState = document.querySelector(".page-state");
	    const pageStateTitle = pageState.querySelector("strong");
	    const pageStateMessage = pageState.querySelector("span");
	    const retryPageButton = document.querySelector(".retry-page");
    let copyTipTimer = 0;
    function flashCopyTip() {{
      copyTip.classList.add("is-visible");
      if (copyTipTimer) window.clearTimeout(copyTipTimer);
      copyTipTimer = window.setTimeout(() => copyTip.classList.remove("is-visible"), 1000);
    }}
    const refreshButton = document.querySelector(".refresh-page");
    const fullscreenButton = document.querySelector(".fullscreen-page");
    const directoryPage = pages.find(page => page.isDirectory) || null;
    function updateDeckScale() {{
      const scale = Math.min((window.innerWidth - 96) / 1920, (window.innerHeight - 72) / 1080, 1);
      document.documentElement.style.setProperty("--deck-scale", String(scale));
    }}
    function resolvePageIndex(target, fallback = 0) {{
      if (target == null || target === "") return fallback;
      if (/^\\d+$/.test(String(target))) {{
        const index = Number(target);
        return index >= 0 && index < pages.length ? index : fallback;
      }}
      const normalized = decodeURIComponent(String(target)).replace(/^page=/, "");
      const index = pages.findIndex(page => page.id === normalized || page.code === normalized || page.src === normalized || page.title === normalized);
      return index >= 0 ? index : fallback;
    }}
    function locationPageTarget() {{
      const queryTarget = new URLSearchParams(window.location.search).get("page");
      const hashValue = window.location.hash.replace(/^#/, "");
      const hashTarget = new URLSearchParams(hashValue).get("page");
      return queryTarget || hashTarget || "";
    }}
    function syncPageUrl(page) {{
      if (!page || !window.history?.replaceState) return;
      const url = new URL(window.location.href);
      url.hash = `page=${{encodeURIComponent(page.id || page.code)}}`;
      window.history.replaceState(null, "", url);
    }}
    function setPageState(state, title = "", message = "") {{
      pageState.classList.toggle("is-loading", state === "loading");
      pageState.hidden = state === "ready";
      pageStateTitle.textContent = title;
      pageStateMessage.textContent = message;
      retryPageButton.hidden = state !== "error";
    }}
    function pageSource(page, refresh = false) {{
      if (!page?.src) return "";
      const url = new URL(page.src, window.location.href);
      url.searchParams.set("embed", "1");
      if (refresh) url.searchParams.set("v", String(Date.now()));
      return url.toString();
    }}
    function pageHasSettled(index) {{
      return pageLoadStates[index] === "ready" || pageLoadStates[index] === "error";
    }}
    function updateNavigationState() {{
      prevButton.disabled = currentIndex === 0;
      nextButton.disabled = currentIndex >= pages.length - 1;
    }}
    function renderCurrentPageState() {{
      const page = pages[currentIndex] || pages[0];
      const state = pageLoadStates[currentIndex];
      frameStack.dataset.currentLoadState = state;
      frameStack.dataset.liveFrameCount = String(frames.filter(Boolean).length);
      updateNavigationState();
      if (state === "pending" || state === "loading") {{
        setPageState("loading", "正在加载当前页面", `${{page.label}} · ${{page.title}}`);
        return;
      }}
      if (state === "error") {{
        setPageState("error", "当前页面加载失败", `${{page.label}} · ${{page.title}}。可以重新加载当前页。`);
        return;
      }}
      setPageState("ready");
    }}
    function inspectLoadedFrame(frame) {{
      try {{
        const documentTitle = frame.contentDocument?.title || "";
        return !(
          frame.contentDocument?.querySelector("[data-minem-preview-error]")
          || documentTitle === "Error response"
          || /^(?:404(?:\\s+Not Found)?|410(?:\\s+Gone)?)$/i.test(documentTitle.trim())
        );
      }} catch (_) {{
        // Sandboxed or cross-origin pages cannot be inspected. A completed load
        // remains the strongest signal available without weakening isolation.
        return true;
      }}
    }}
    function destroyFrame(index) {{
      const frame = frames[index];
      if (pageLoadTimers[index]) window.clearTimeout(pageLoadTimers[index]);
      pageLoadTimers[index] = 0;
      pageLoadSequences[index] += 1;
      pageLoadStates[index] = "pending";
      if (!frame) return;
      frame.onload = null;
      frame.onerror = null;
      frame.removeAttribute("src");
      frame.remove();
      frames[index] = null;
    }}
    function trimFramesAround(index) {{
      frames.forEach((frame, frameIndex) => {{
        if (frame && Math.abs(frameIndex - index) > 1) destroyFrame(frameIndex);
      }});
    }}
    function warmAdjacentFrames(index) {{
      if (index !== currentIndex || !pageHasSettled(index)) return;
      [index - 1, index + 1].forEach(neighborIndex => {{
        if (neighborIndex >= 0 && neighborIndex < pages.length) loadFrame(neighborIndex);
      }});
      renderCurrentPageState();
    }}
    function completePageLoad(index, frame, sequence, state) {{
      if (frames[index] !== frame || pageLoadSequences[index] !== sequence) return;
      if (pageLoadTimers[index]) window.clearTimeout(pageLoadTimers[index]);
      pageLoadTimers[index] = 0;
      pageLoadStates[index] = state;
      frame.dataset.loadState = state;
      if (index === currentIndex) {{
        renderCurrentPageState();
        warmAdjacentFrames(index);
      }}
    }}
    function loadFrame(index, refresh = false) {{
      const page = pages[index];
      if (!page) return null;
      if (refresh) destroyFrame(index);
      if (frames[index]) return frames[index];
      const frame = document.createElement("iframe");
      frame.className = "deck-frame";
      frame.title = `${{page.label}} - ${{page.title}}`;
      frame.setAttribute("sandbox", "allow-scripts");
      frames[index] = frame;
      pageLoadStates[index] = "loading";
      frame.dataset.loadState = "loading";
      const sequence = pageLoadSequences[index] + 1;
      pageLoadSequences[index] = sequence;
      const source = pageSource(page, refresh);
      if (!source) {{
        frameStack.appendChild(frame);
        completePageLoad(index, frame, sequence, "error");
        return frame;
      }}
      frame.onload = () => completePageLoad(index, frame, sequence, inspectLoadedFrame(frame) ? "ready" : "error");
      frame.onerror = () => completePageLoad(index, frame, sequence, "error");
      pageLoadTimers[index] = window.setTimeout(
        () => completePageLoad(index, frame, sequence, "error"),
        30000,
      );
      frame.src = source;
      frameStack.appendChild(frame);
      if (index === currentIndex) renderCurrentPageState();
      return frame;
    }}
    let interactiveMode = false;
    const viewerEl = document.querySelector(".viewer");
    function setInteractive(active) {{
      interactiveMode = active;
      viewerEl.classList.toggle("is-interactive", active);
    }}
    function showPage(index, options = {{}}) {{
      currentIndex = Math.max(0, Math.min(index, pages.length - 1));
      const page = pages[currentIndex] || pages[0];
      trimFramesAround(currentIndex);
      loadFrame(currentIndex);
      frames.forEach((frame, frameIndex) => {{
        if (frame) frame.classList.toggle("is-active", frameIndex === currentIndex);
      }});
      setInteractive(false);
      pageCount.textContent = `${{currentIndex + 1}} / ${{pages.length}}`;
      pageTitle.textContent = page.label;
      copySourceButton.hidden = !page.sourceDoc;
      tocButton.hidden = !directoryPage || page === directoryPage;
      renderCurrentPageState();
      if (pageHasSettled(currentIndex)) warmAdjacentFrames(currentIndex);
      if (options.syncUrl !== false) syncPageUrl(page);
    }}
    function refreshCurrentPage() {{
      loadFrame(currentIndex, true);
      frames[currentIndex]?.classList.add("is-active");
      setInteractive(false);
      renderCurrentPageState();
    }}
    retryPageButton.addEventListener("click", refreshCurrentPage);
    updateDeckScale();
    currentIndex = resolvePageIndex(locationPageTarget());
    showPage(currentIndex);
    window.addEventListener("resize", updateDeckScale);
    prevButton.addEventListener("click", () => showPage(currentIndex - 1));
    nextButton.addEventListener("click", () => showPage(currentIndex + 1));
	    tocButton.addEventListener("click", () => {{
	      if (directoryPage) showPage(pages.indexOf(directoryPage));
	    }});
    window.addEventListener("message", event => {{
      const sourceIndex = frames.findIndex(frame => frame && event.source === frame.contentWindow);
      if (sourceIndex !== currentIndex || event.data?.type !== "report:navigate") return;
      const targetIndex = resolvePageIndex(event.data.target, -1);
      if (targetIndex < 0) return;
      showPage(targetIndex);
    }});
	    window.addEventListener("hashchange", () => {{
      const target = locationPageTarget();
      if (!target) {{
        syncPageUrl(pages[currentIndex]);
        return;
      }}
      const targetIndex = resolvePageIndex(target, -1);
      if (targetIndex < 0) {{
        syncPageUrl(pages[currentIndex]);
        return;
      }}
      showPage(targetIndex, {{ syncUrl: false }});
    }});
	    copyButton.addEventListener("click", async () => {{
	      const page = pages[currentIndex] || pages[0];
	      if (!page) return;
	      const url = new URL(window.location.href);
	      url.hash = `page=${{encodeURIComponent(page.id || page.code)}}`;
	      try {{
	        await navigator.clipboard.writeText(url.toString());
	        copyButton.setAttribute("data-copied", "true");
	        flashCopyTip();
	        window.setTimeout(() => {{ copyButton.removeAttribute("data-copied"); }}, 1000);
	      }} catch (_) {{
	        window.prompt("复制当前页链接", url.toString());
	      }}
	    }});
	    copySourceButton.addEventListener("click", async () => {{
	      const page = pages[currentIndex] || pages[0];
	      if (!page || !page.sourceDoc) return;
	      try {{
	        await navigator.clipboard.writeText(page.sourceDoc);
	        copySourceButton.setAttribute("data-copied", "true");
	        flashCopyTip();
	        window.setTimeout(() => {{ copySourceButton.removeAttribute("data-copied"); }}, 1000);
	      }} catch (_) {{
	        window.prompt("复制原始飞书文档链接", page.sourceDoc);
	      }}
	    }});
	    refreshButton.addEventListener("click", refreshCurrentPage);
	    fullscreenButton.addEventListener("click", async () => {{
	      try {{
	        if (document.fullscreenElement) {{
	          await document.exitFullscreen();
	        }} else {{
	          await document.documentElement.requestFullscreen();
	        }}
	      }} catch (_) {{
	        // The browser can deny fullscreen until a direct user gesture.
	      }}
	    }});
	    document.addEventListener("fullscreenchange", () => {{
	      const active = Boolean(document.fullscreenElement);
	      fullscreenButton.setAttribute("aria-label", active ? "退出全屏" : "全屏");
	      fullscreenButton.setAttribute("title", active ? "退出全屏" : "全屏");
	      fullscreenButton.textContent = active ? "⛶" : "⛶";
	    }});
	    function releaseTempReport() {{
	      if (!releaseUrl || released) return;
	      released = true;
	      if (heartbeatTimer) window.clearInterval(heartbeatTimer);
	      const payload = new Blob(["{{}}"], {{ type: "application/json" }});
	      if (navigator.sendBeacon) {{
	        navigator.sendBeacon(releaseUrl, payload);
	        return;
	      }}
	      fetch(releaseUrl, {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: "{{}}", keepalive: true }}).catch(() => {{}});
	    }}
	    function heartbeatTempReport() {{
	      if (!heartbeatUrl || released) return;
	      fetch(heartbeatUrl, {{ method: "POST", keepalive: true }}).catch(() => {{}});
	    }}
	    heartbeatTempReport();
	    if (heartbeatUrl) heartbeatTimer = window.setInterval(heartbeatTempReport, 5000);
	    window.addEventListener("pagehide", releaseTempReport);
	    window.addEventListener("keydown", (event) => {{
      if (event.key === "ArrowLeft") showPage(currentIndex - 1);
      if (event.key === "ArrowRight") showPage(currentIndex + 1);
      if (event.key === "Escape" && interactiveMode) setInteractive(false);
    }});
    document.querySelector(".slide-shell").addEventListener("dblclick", () => {{
      if (!interactiveMode) setInteractive(true);
    }});
  </script>
</body>
	</html>
	"""


def preview_error_html(title, message):
    safe_title = html.escape(str(title or "预览不可用"), quote=True)
    safe_message = html.escape(str(message or "当前素材暂时无法预览"), quote=True)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title><style>
:root{{color-scheme:dark;font-family:Inter,"PingFang SC","Microsoft YaHei",Arial,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;color:#d6e3ef;background:radial-gradient(circle at 50% 24%,rgba(57,112,165,.2),transparent 42%),#030712}}
main{{width:min(520px,100%);display:grid;justify-items:center;gap:12px;text-align:center}}
i{{width:44px;height:44px;display:grid;place-items:center;border:1px solid rgba(151,191,225,.3);border-radius:50%;color:#8cecff;background:rgba(140,236,255,.08);font-size:22px;font-style:normal}}
h1{{margin:0;color:white;font-size:20px}}p{{margin:0;color:#9fb3c6;font-size:13px;line-height:1.7}}
button{{min-height:36px;margin-top:4px;border:1px solid rgba(151,191,225,.34);border-radius:8px;padding:0 14px;color:white;background:rgba(255,255,255,.08);cursor:pointer}}
</style></head><body><main data-minem-preview-error="true"><i>!</i><h1>{safe_title}</h1><p>{safe_message}</p><button type="button" onclick="location.reload()">重新加载</button></main></body></html>"""


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


def copy_control_as_report_page(control, target_root, page_number=1):
    source = asset_library_path(control)
    if not source or not source.exists():
        raise ValueError("页面素材文件不存在")
    target_dir = target_root / "pages" / f"page-{int(page_number):02d}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if source.name == "index.html":
        shutil.copytree(source.parent, target_dir, dirs_exist_ok=True)
    else:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_dir / "index.html")
    return f"pages/page-{int(page_number):02d}/index.html"


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
        source_control_id = str(item.get("source_control_id") or "").strip()
        source_control = None
        if source_control_id:
            source_control = conn.execute(
                "select * from assets where id = ? and asset_type = 'control' limit 1",
                (source_control_id,),
            ).fetchone()
        if source_control:
            attach_report_page_control(
                conn,
                report_id,
                page_number,
                source_control["id"],
                str(item.get("title") or source_control["title"] or "").strip() or f"第{page_number}页",
                "创建汇报引用已有页面素材",
                replace=True,
            )
            continue
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
            tags = merge_tags(
                ["页面素材", "汇报页面", "创建汇报", report_code, f"第{page_number}页"],
                [source_code] if source_code else [],
                item.get("tags") or [],
            )
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


def control_codes_from_conversation(text):
    codes = []
    seen = set()
    for match in re.findall(r"CTRL-[A-Z0-9-]+", text or "", flags=re.I):
        code = match.upper()
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def title_from_conversation(text):
    match = re.search(r"标题(?:是|为)\s*[「《“\"]([^」》”\"\n。]+)[」》”\"]?", text or "")
    return match.group(1).strip() if match else ""


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


def create_storyline_report(payload):
    conversation = str(payload.get("conversation") or payload.get("prompt") or payload.get("message") or "").strip()
    mode = str(payload.get("mode") or ("chat" if conversation else "manual")).strip()
    title = str(payload.get("title") or "").strip() or title_from_conversation(conversation) or f"新建汇报素材 {time.strftime('%Y%m%d-%H%M')}"
    note = str(payload.get("note") or "").strip()
    timestamp = now_ms()
    digest = hashlib.sha1(f"{title}:{mode}:{timestamp}".encode("utf-8")).hexdigest()[:10]
    upload_id = f"created-report-{time.strftime('%Y%m%d-%H%M%S')}-{digest}"
    report_id = f"created-report-{time.strftime('%Y%m%d-%H%M%S')}-{digest}"
    target_root = EXTRACTED / upload_id
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    def fail(message):
        if target_root.exists():
            shutil.rmtree(target_root, ignore_errors=True)
        return {"ok": False, "error": message}

    with db() as conn:
      asset_code = next_asset_code(conn, "report", "report", "html")
      source_type = "storyline-report-manual"
      source_hash = f"created-report:{mode}:{digest}"
      tags = merge_tags(["汇报素材", "故事线新增", "独立汇报", asset_code])
      source_path = "index.html"
      manifest_pages = []

      if mode in ("manual", "chat"):
          raw_control_ids = payload.get("controlIds") or payload.get("control_ids") or []
          if isinstance(raw_control_ids, str):
              raw_control_ids = [raw_control_ids]
          control_ids = [str(item).strip() for item in raw_control_ids if str(item).strip()]
          first_control_id = str(payload.get("firstControlId") or payload.get("first_control_id") or "").strip()
          if not control_ids and first_control_id:
              control_ids = [first_control_id]
          if not control_ids and conversation:
              control_codes = control_codes_from_conversation(conversation)
              if control_codes:
                  placeholders = ",".join("?" for _ in control_codes)
                  code_rows = conn.execute(f"select id, asset_code from assets where asset_type = 'control' and upper(asset_code) in ({placeholders})", control_codes).fetchall()
                  ids_by_code = {row["asset_code"].upper(): row["id"] for row in code_rows}
                  missing_codes = [code for code in control_codes if code not in ids_by_code]
                  if missing_codes:
                      return fail(f"页面素材编号不存在：{'、'.join(missing_codes[:3])}")
                  control_ids = [ids_by_code[code] for code in control_codes]
          if not control_ids:
              return fail("请在快捷公式里填写页面素材编号")
          placeholders = ",".join("?" for _ in control_ids)
          rows = conn.execute(f"select * from assets where asset_type = 'control' and id in ({placeholders})", control_ids).fetchall()
          controls_by_id = {row["id"]: row for row in rows}
          missing_control_ids = [control_id for control_id in control_ids if control_id not in controls_by_id]
          if missing_control_ids:
              return fail(f"页面素材不存在：{'、'.join(missing_control_ids[:3])}")
          controls = [controls_by_id.get(control_id) for control_id in control_ids if control_id in controls_by_id]
          if not controls:
              return fail("没有找到可用的页面素材")
          page_items = []
          for index, control in enumerate(controls, start=1):
              try:
                  page_src = copy_control_as_report_page(control, target_root, index)
              except (OSError, ValueError) as error:
                  return fail(str(error) or "页面素材复制失败")
              page_items.append({
                  "title": control["title"],
                  "code": control["asset_code"],
                  "src": page_src,
              })
              manifest_pages.append({
                  "sequence": index - 1,
                  "display_page": index,
                  "role": "cover" if index == 1 else "content",
                  "title": control["title"],
                  "control_asset_code": control["asset_code"],
                  "source_control_id": control["id"],
                  "control_path": page_src,
              })
          (target_root / "index.html").write_text(report_viewer_html(title, page_items), encoding="utf-8")
          manifest = {
              "asset_type": "report",
              "asset_code": asset_code,
              "title": title,
              "entry": "index.html",
              "preview_url": "",
              "pages": manifest_pages,
              "created_by": "MineM",
              "created_at": timestamp,
          }
          (target_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
          if mode == "chat":
              source_type = "storyline-report-chat"
              tags = merge_tags(tags, ["AI对话创建"])
              control_codes = "、".join(control["asset_code"] for control in controls)
              usage = f"从故事线模块通过快捷公式新增；页面素材：{control_codes}。"
              if conversation:
                  usage += f" 对话公式：{conversation[:500]}"
          else:
              usage = f"从故事线模块人工新增；首页页面素材：{controls[0]['asset_code']}。"
          if note:
              usage += f" 备注：{note}"
      elif mode == "copy":
          version_id = str(payload.get("storylineVersionId") or payload.get("storyline_version_id") or "").strip()
          if not version_id:
              return fail("请选择要复制的故事线版本")
          version = conn.execute("select * from report_storyline_collections where id = ?", (version_id,)).fetchone()
          if not version:
              return fail("故事线版本不存在")
          source_report_id = version["output_report_id"] or version["source_report_id"]
          source_report = conn.execute("select * from assets where id = ? and asset_type = 'report'", (source_report_id,)).fetchone()
          if not source_report:
              return fail("故事线版本没有可复制的来源汇报")
          source_root = EXTRACTED / source_report["upload_id"]
          if not source_root.exists():
              return fail("来源汇报目录不存在")
          try:
              shutil.copytree(source_root, target_root, dirs_exist_ok=True)
          except OSError as error:
              return fail(str(error) or "故事线版本复制失败")
          source_path = source_report["source_path"] or "index.html"
          source_type = "storyline-report-copy"
          tags = merge_tags(tags, [version["code"], f"复制自:{source_report['asset_code']}"])
          usage = f"从故事线 {version['code']} 的 V{version['version_no']} 复制为独立汇报素材。"
          if note:
              usage += f" 备注：{note}"
      else:
          return fail("创建方式不正确")

      report_file = target_root / source_path
      if not report_file.exists():
          return fail("汇报入口生成失败")
      preview_url = f"/reports/{report_id}/index.html"
      conn.execute(
          "insert or replace into uploads (id, filename, stored_path, extract_path, file_count, asset_count, created_at) values (?, ?, ?, ?, ?, ?, ?)",
          (
              upload_id,
              title,
              runtime_record_path(target_root, RUNTIME_ROOT),
              runtime_record_path(target_root, RUNTIME_ROOT),
              sum(1 for path in target_root.rglob("*") if path.is_file()),
              1,
              timestamp,
          ),
      )
      insert_created_report_asset(
          conn,
          report_id=report_id,
          title=report_material_title(title),
          usage=usage,
          tags=tags,
          asset_code=asset_code,
          source_type=source_type,
          source_path=source_path,
          preview_url=preview_url,
          upload_id=upload_id,
          source_hash=source_hash,
          timestamp=timestamp,
      )
      if mode in ("manual", "chat"):
          created_page_ids = register_created_report_pages(
              conn,
              report_id=report_id,
              report_code=asset_code,
              report_title=title,
              target_root=target_root,
              manifest_pages=manifest_pages,
              timestamp=timestamp,
          )
      else:
          created_page_ids = []

      report_row = conn.execute("select * from assets where id = ?", (report_id,)).fetchone()
      cover_path = None
      for index, page_id in enumerate(created_page_ids):
          page_row = conn.execute("select * from assets where id = ?", (page_id,)).fetchone()
          page_path = asset_library_path(page_row) if page_row else None
          if not page_path or not page_path.exists():
              continue
          page_fingerprint = thumbnail_source_fingerprint(page_row)
          if index == 0:
              generate_html_thumbnail(page_id, page_path, page_fingerprint)
              cover_path = page_path
          else:
              enqueue_thumbnail_refresh(page_id, page_path, page_fingerprint)

      if cover_path is None:
          manifest_file = target_root / "manifest.json"
          try:
              copied_manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
          except (OSError, json.JSONDecodeError):
              copied_manifest = {}
          first_page = next(iter(copied_manifest.get("pages") or []), {})
          first_rel = str(first_page.get("control_path") or first_page.get("path") or first_page.get("src") or "").strip()
          candidate = (target_root / first_rel).resolve() if first_rel else None
          if candidate and is_path_within(candidate, target_root.resolve()) and candidate.exists():
              cover_path = candidate

      try:
          generate_html_thumbnail(
              report_id,
              cover_path or report_file,
              thumbnail_source_fingerprint(report_row) if report_row else source_hash,
          )
      except Exception:
          pass
      trusted_entry = validate_report_trusted_entry(conn, report_id, refresh=True)
      row = conn.execute("select * from assets where id = ?", (report_id,)).fetchone()
      asset = add_version_counts(conn, [row])[0]
      asset["trustedEntry"] = trusted_entry
      invalidate_stats_cache()
    return {"ok": True, "asset": asset, "url": preview_url}


def js_value_span(text, const_name, opener, closer):
    markers = [f"const {const_name}", f"let {const_name}", f"var {const_name}"]
    start = -1
    for marker in markers:
        start = text.find(marker)
        if start >= 0:
            break
    if start < 0:
        return None
    equal_at = text.find("=", start)
    if equal_at < 0:
        return None
    value_start = text.find(opener, equal_at)
    if value_start < 0:
        return None
    depth = 0
    quote = ""
    escaped = False
    for index in range(value_start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in ("'", '"', "`"):
            quote = char
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return value_start, index + 1
    return None


def js_const_json_value(text, const_name, opener, closer, default):
    span = js_value_span(text, const_name, opener, closer)
    if not span:
        return default
    try:
        return json.loads(text[span[0]:span[1]])
    except json.JSONDecodeError:
        return default


def replace_js_const_json(text, const_name, value, opener, closer):
    span = js_value_span(text, const_name, opener, closer)
    dumped = json_for_html_script(value, indent=6)
    if span:
        return f"{text[:span[0]]}{dumped}{text[span[1]:]}"
    insert_at = text.find("let currentIndex")
    if insert_at < 0:
        return f"{text}\nconst {const_name} = {dumped};\n"
    return f"{text[:insert_at]}const {const_name} = {dumped};\n    {text[insert_at:]}"


def load_report_asset(report_id):
    with db() as conn:
        row = conn.execute("select * from assets where id = ?", (report_id,)).fetchone()
    if not row:
        return None, {"ok": False, "error": "汇报素材不存在"}
    asset = dict(row)
    if asset.get("asset_type") not in ("report", "page"):
        return None, {"ok": False, "error": "只有汇报素材支持 AI 演讲台"}
    asset["preview_url"] = canonical_preview_url(asset)
    return asset, None


def extracted_url_to_path(url):
    clean_url = str(url or "").split("?", 1)[0]
    if not clean_url.startswith("/extracted/"):
        return None
    rel = unquote(clean_url.removeprefix("/extracted/")).replace("\\", "/")
    path = (EXTRACTED / rel).resolve()
    if not is_path_within(path, EXTRACTED):
        return None
    return path


def presenter_url_for_path(path):
    try:
        rel = path.resolve().relative_to(EXTRACTED.resolve())
    except ValueError:
        return ""
    return f"/extracted/{rel.as_posix()}?v={AI_PRESENTER_VERSION}"


def report_preview_path(asset):
    return extracted_url_to_path(asset.get("preview_url") or "")


def report_presenter_candidates(asset):
    candidates = []
    preview_path = report_preview_path(asset)
    if preview_path:
        candidates.append(preview_path.with_name("ai-presenter.html"))
        try:
            rel = preview_path.relative_to(EXTRACTED.resolve())
            if rel.parts:
                candidates.append(EXTRACTED / rel.parts[0] / "ai-presenter.html")
        except ValueError:
            pass
    upload_id = asset.get("upload_id") or ""
    if upload_id:
        candidates.append(EXTRACTED / upload_id / "ai-presenter.html")
    unique = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if is_path_within(resolved, EXTRACTED) and resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def existing_report_presenter_path(asset):
    for candidate in report_presenter_candidates(asset):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def report_presenter_trash_dir(asset):
    upload_id = str(asset.get("upload_id") or "").strip()
    if not upload_id:
        return None
    path = (EXTRACTED / upload_id / "_presenter_trash").resolve()
    return path if is_path_within(path, EXTRACTED) else None


def report_presenter_deleted_paths(asset):
    trash_dir = report_presenter_trash_dir(asset)
    if not trash_dir or not trash_dir.exists():
        return []
    return sorted(
        (path for path in trash_dir.glob("*.html") if path.is_file()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )


def report_presenter_restore_target(asset):
    candidates = report_presenter_candidates(asset)
    return candidates[0] if candidates else None


def presenter_metadata_path(presenter_path):
    return presenter_path.with_suffix(".meta.json") if presenter_path else None


def read_presenter_metadata(presenter_path):
    path = presenter_metadata_path(presenter_path)
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_presenter_metadata(presenter_path, source_type, minutes_url):
    path = presenter_metadata_path(presenter_path)
    if not path:
        return
    payload = {
        "sourceType": source_type,
        "minutesUrl": minutes_url,
        "updatedAt": now_ms(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize_presenter_pages(raw_pages, asset, preview_path=None):
    pages = []
    if isinstance(raw_pages, list):
        for index, page in enumerate(raw_pages, start=1):
            if not isinstance(page, dict):
                continue
            page_id = str(page.get("id") or f"page-{index:02d}").strip()
            src = str(page.get("src") or "").strip()
            item = {
                "id": page_id,
                "label": str(page.get("label") or f"Page {index:02d}").strip(),
                "title": str(page.get("title") or page.get("label") or asset.get("title") or f"Page {index:02d}").strip(),
                "code": str(page.get("code") or "").strip(),
                "src": src,
            }
            for optional_key in ("chapter", "role"):
                if page.get(optional_key):
                    item[optional_key] = str(page.get(optional_key)).strip()
            pages.append(item)
    if pages:
        return pages
    fallback_src = preview_path.name if preview_path else "index.html"
    return [{
        "id": "report-page-01",
        "label": "Page 01",
        "title": asset.get("title") or "汇报素材",
        "code": asset.get("asset_code") or "",
        "src": fallback_src,
        "role": "page",
    }]


def read_presenter_pages_from_path(path, asset):
    if not path or not path.exists() or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return sanitize_presenter_pages(js_const_json_value(text, "pages", "[", "]", []), asset, path)


def read_pages_from_report_preview(asset):
    preview_path = report_preview_path(asset)
    if not preview_path or not preview_path.exists() or not preview_path.is_file():
        return sanitize_presenter_pages([], asset, preview_path)
    try:
        text = preview_path.read_text(encoding="utf-8")
    except OSError:
        return sanitize_presenter_pages([], asset, preview_path)
    return sanitize_presenter_pages(js_const_json_value(text, "pages", "[", "]", []), asset, preview_path)


def strip_html_text(text):
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def page_expression_base_path(asset, presenter_path=None):
    if presenter_path:
        return presenter_path.parent
    preview_path = report_preview_path(asset)
    return preview_path.parent if preview_path else None


def page_expression_text(page_path):
    if not page_path or not page_path.exists() or not page_path.is_file():
        return ""
    try:
        text = page_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return strip_html_text(text)[:5000]


def attach_page_expression(asset, pages, presenter_path=None):
    base_path = page_expression_base_path(asset, presenter_path)
    enriched = []
    for page in pages or []:
        item = dict(page)
        src = str(page.get("src") or "").strip()
        page_text = ""
        if base_path and src and not re.match(r"^https?://", src, flags=re.I):
            candidate = (base_path / src).resolve()
            if is_path_within(candidate, EXTRACTED):
                page_text = page_expression_text(candidate)
        item["expressionText"] = " ".join(
            str(value or "")
            for value in (
                item.get("label"),
                item.get("title"),
                item.get("chapter"),
                item.get("role"),
                page_text,
            )
            if str(value or "").strip()
        )
        enriched.append(item)
    return enriched


def read_presenter_notes(path):
    if not path or not path.exists() or not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    notes = js_const_json_value(text, "defaultSpeakerNotes", "{", "}", {})
    return notes if isinstance(notes, dict) else {}


def presenter_note_count(notes):
    return sum(1 for value in (notes or {}).values() if str(value or "").strip())


def presenter_script_text(notes, pages):
    chunks = []
    for index, page in enumerate(pages or [], start=1):
        note = str((notes or {}).get(page.get("id") or "") or "").strip()
        if note:
            chunks.append(f"Page {index:02d}: {note}")
    if chunks:
        return "\n\n".join(chunks)
    return "\n\n".join(str(value or "").strip() for value in (notes or {}).values() if str(value or "").strip())


def report_presenter_status(report_id):
    asset, error = load_report_asset(report_id)
    if error:
        return error
    presenter_path = existing_report_presenter_path(asset)
    deleted_paths = report_presenter_deleted_paths(asset)
    pages = read_presenter_pages_from_path(presenter_path, asset) if presenter_path else read_pages_from_report_preview(asset)
    notes = read_presenter_notes(presenter_path)
    metadata = read_presenter_metadata(presenter_path or (deleted_paths[0] if deleted_paths else None))
    count = presenter_note_count(notes)
    candidate_paths = report_presenter_candidates(asset)
    target_path = presenter_path or (candidate_paths[0] if candidate_paths else None)
    return {
        "ok": True,
        "hasScript": count > 0,
        "scriptCount": count,
        "pageCount": len(pages),
        "missingPresenter": presenter_path is None,
        "presenterUrl": presenter_url_for_path(target_path) if target_path else "",
        "presenterModeUrl": presenter_mode_url(report_id),
        "scriptText": presenter_script_text(notes, pages),
        "canRestore": bool(deleted_paths) and presenter_path is None,
        "deletedAt": int(deleted_paths[0].stat().st_mtime * 1000) if deleted_paths and presenter_path is None else 0,
        "sourceType": str(metadata.get("sourceType") or ""),
        "minutesUrl": str(metadata.get("minutesUrl") or ""),
        "updatedAt": int(metadata.get("updatedAt") or (presenter_path.stat().st_mtime * 1000 if presenter_path else 0)),
    }


def report_presenter_mode_payload(report_id):
    """Build the shared, confirmed presenter/audience page model."""
    result, page_items = report_public_page_items(report_id)
    if not result.get("ok"):
        return result
    asset, error = load_report_asset(report_id)
    if error:
        return error
    presenter_path = existing_report_presenter_path(asset)
    presenter_pages = read_presenter_pages_from_path(presenter_path, asset) if presenter_path else []
    notes = read_presenter_notes(presenter_path)
    return {
        "ok": True,
        "reportId": report_id,
        "title": asset.get("title") or f"汇报 · {report_id}",
        "pages": attach_presenter_notes(page_items, presenter_pages, notes),
        "presenterModeUrl": presenter_mode_url(report_id),
        "audienceModeUrl": audience_mode_url(report_id),
    }


def ensure_report_presenter_file(asset):
    existing = existing_report_presenter_path(asset)
    if existing:
        return existing, read_presenter_pages_from_path(existing, asset), ""
    candidates = report_presenter_candidates(asset)
    if not candidates:
        return None, [], "当前汇报没有可写入的本地预览路径"
    if not AI_PRESENTER_TEMPLATE.exists():
        return None, [], "缺少 AI 演讲台模板"
    target = candidates[0]
    try:
        template = AI_PRESENTER_TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return None, [], "AI 演讲台模板读取失败"
    pages = read_pages_from_report_preview(asset)
    html_text = replace_js_const_json(template, "pages", pages, "[", "]")
    html_text = replace_js_const_json(html_text, "defaultSpeakerNotes", {}, "{", "}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(html_text, encoding="utf-8")
    except OSError:
        return None, [], "AI 演讲台页面写入失败"
    return target, pages, ""


def parse_marked_script_chunks(script):
    marker = re.compile(r"^\s*(?:#{1,4}\s*)?(?:page|p|第)\s*0*(\d{1,3})(?:\s*页)?\s*[：:.\-、]?\s*(.*)$", re.I)
    chunks = []
    current = None
    for raw_line in script.splitlines():
        match = marker.match(raw_line)
        if match:
            if current is not None:
                chunks.append("\n".join(current).strip())
            current = []
            rest = match.group(2).strip()
            if rest:
                current.append(rest)
            continue
        if current is not None:
            current.append(raw_line.rstrip())
    if current is not None:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def parse_marked_script_notes(script, pages):
    marker = re.compile(r"^\s*(?:#{1,4}\s*)?(?:page|p|第)\s*0*(\d{1,3})(?:\s*页)?\s*[：:.\-、]?\s*(.*)$", re.I)
    notes = {}
    current_page = None
    current_lines = []

    def flush():
        if current_page is None:
            return
        if current_page < 1 or current_page > len(pages or []):
            return
        chunk = "\n".join(current_lines).strip()
        if not chunk:
            return
        page = pages[current_page - 1]
        page_id = str(page.get("id") or f"page-{current_page:02d}").strip()
        if page_id:
            notes[page_id] = chunk

    for raw_line in script.splitlines():
        match = marker.match(raw_line)
        if match:
            flush()
            current_page = int(match.group(1))
            current_lines = []
            rest = match.group(2).strip()
            if rest:
                current_lines.append(rest)
            continue
        if current_page is not None:
            current_lines.append(raw_line.rstrip())
    flush()
    return notes


def text_keyword_tokens(text):
    tokens = set()
    lowered = str(text or "").lower()
    for seq in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9_-]{1,}", lowered):
        if re.search(r"[\u4e00-\u9fff]", seq):
            max_size = 4 if len(seq) >= 4 else len(seq)
            for size in range(2, max_size + 1):
                for index in range(0, len(seq) - size + 1):
                    tokens.add(seq[index:index + size])
        else:
            tokens.add(seq.strip("_-"))
    return {token for token in tokens if token}


def script_auto_units(script, page_count):
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", script) if part.strip()]
    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", script) if part.strip()]
    if len(sentences) > len(paragraphs) and (len(paragraphs) <= 1 or len(paragraphs) < max(3, page_count // 3)):
        return sentences
    if paragraphs:
        return paragraphs
    lines = [line.strip() for line in script.splitlines() if line.strip()]
    return lines or ([script.strip()] if script.strip() else [])


def distribute_units_by_order(units, pages):
    page_count = max(1, len(pages or []))
    if not units:
        return {}
    notes = {}
    if len(units) <= page_count:
        for index, unit in enumerate(units):
            page = pages[index] if index < len(pages) else {}
            page_id = str(page.get("id") or f"page-{index + 1:02d}").strip()
            if page_id:
                notes[page_id] = unit.strip()
        return notes
    group_size = max(1, (len(units) + page_count - 1) // page_count)
    for index in range(page_count):
        chunk = "\n".join(units[index * group_size:(index + 1) * group_size]).strip()
        if not chunk:
            continue
        page = pages[index] if index < len(pages) else {}
        page_id = str(page.get("id") or f"page-{index + 1:02d}").strip()
        if page_id:
            notes[page_id] = chunk
    return notes


def auto_paginate_script_notes(script, pages):
    page_list = pages or []
    page_count = max(1, len(page_list))
    units = script_auto_units(script, page_count)
    if not units:
        return {}
    if not page_list:
        return {"page-01": "\n".join(units).strip()}

    page_contexts = []
    for page in page_list:
        expression = " ".join(str(page.get(key) or "") for key in ("label", "title", "chapter", "role", "expressionText"))
        page_contexts.append(text_keyword_tokens(expression))

    notes_by_page = [[] for _ in page_list]
    matched_count = 0
    for unit_index, unit in enumerate(units):
        unit_tokens = text_keyword_tokens(unit)
        base_index = min(page_count - 1, int(unit_index * page_count / max(1, len(units))))
        best_index = base_index
        best_score = 0.0
        if unit_tokens:
            for page_index, page_tokens in enumerate(page_contexts):
                overlap = len(unit_tokens & page_tokens)
                if not overlap:
                    continue
                order_penalty = abs(page_index - base_index) * 0.18
                score = overlap - order_penalty
                if score > best_score:
                    best_score = score
                    best_index = page_index
        if best_score >= 1.5:
            matched_count += 1
            notes_by_page[best_index].append(unit)
        else:
            notes_by_page[base_index].append(unit)

    notes = {}
    for index, chunks in enumerate(notes_by_page):
        if not chunks:
            continue
        page = page_list[index]
        page_id = str(page.get("id") or f"page-{index + 1:02d}").strip()
        if page_id:
            notes[page_id] = "\n".join(chunks).strip()

    if len(units) >= page_count and matched_count < max(2, len(units) // 8):
        return distribute_units_by_order(units, page_list)
    return notes or distribute_units_by_order(units, page_list)


def clean_expression_snippet(part):
    part = re.sub(r"\b(?:cover|toc|contents|chapter-divider|page|role|html[_-]?preview)\b", " ", str(part), flags=re.I)
    part = re.sub(r"\b(?:CTRL|RPT|RES)-[A-Z0-9-]+\b", " ", part, flags=re.I)
    part = re.sub(r"\bPage\s*\d+[A-Z]?\b", " ", part, flags=re.I)
    part = re.sub(r"\s+", " ", part).strip(" -_·•｜|:：")
    return part


def expression_snippets(text, limit=3):
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    parts = [
        clean_expression_snippet(part)
        for part in re.split(r"[。！？!?；;\n\r]+", cleaned)
    ]
    seen = set()
    snippets = []
    for part in parts:
        if not (8 <= len(part) <= 120):
            continue
        compact = re.sub(r"\s+", "", part.lower())
        if compact in seen:
            continue
        if re.fullmatch(r"(page|ctrl|rpt|html|preview|slide)[\w\s:-]*", part, flags=re.I):
            continue
        seen.add(compact)
        snippets.append(part)
        if len(snippets) >= limit:
            break
    return snippets


TIME_NODE_PATTERN = re.compile(
    r"("
    r"\d{4}\s*[年/-]\s*\d{1,2}\s*(?:[月/-]\s*\d{1,2}\s*日?)?"
    r"|\d{4}\s*年"
    r"|\d{4}\s*[-–—]\s*\d{2,4}"
    r"|(?:19|20)\d{2}"
    r"|Q[1-4]"
    r"|[一二三四五六七八九十]+季度"
    r"|第[一二三四五六七八九十\d]+阶段"
    r"|过去[一二三四五六七八九十\d]+年"
    r"|未来[一二三四五六七八九十\d]+年"
    r"|近[一二三四五六七八九十\d]+年"
    r"|下一阶段"
    r")",
    re.I,
)


TRANSCRIPT_TIMESTAMP_PATTERN = re.compile(
    r"(?:[\[【(（]\s*)?"
    r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
    r"(?:\s*[\]】)）])?"
)


def strip_transcript_timestamps(text):
    return TRANSCRIPT_TIMESTAMP_PATTERN.sub("\n", str(text or ""))


def extract_time_nodes(text, limit=4):
    seen = set()
    nodes = []
    for match in TIME_NODE_PATTERN.findall(str(text or "")):
        value = re.sub(r"\s+", "", str(match)).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        nodes.append(value)
        if len(nodes) >= limit:
            break
    return nodes


def time_nodes_sentence(nodes):
    if not nodes:
        return ""
    if len(nodes) == 1:
        return f"时间节点上，这里要特别留意「{nodes[0]}」。"
    return "时间线上，可以按照" + "、".join(f"「{node}」" for node in nodes[:4]) + "来理解这页内容。"


def generated_note_for_page(page, index, total):
    title = str(page.get("title") or page.get("label") or f"第{index}页").strip()
    role = str(page.get("role") or "").strip().lower()
    chapter = str(page.get("chapter") or "").strip()
    expression_text = page.get("expressionText") or title
    snippets = expression_snippets(expression_text, 3)
    time_nodes = extract_time_nodes(" ".join([title, str(expression_text)]), 4)
    useful = [item for item in snippets if item and item not in {title, page.get("label", "")}]
    lead = f"这一页我们看「{title}」。"
    if index == 1 or role == "cover":
        lead = f"各位好，今天我们围绕「{title}」展开。"
    elif role in {"toc", "contents"} or "目录" in title:
        lead = "这一页先建立今天的汇报结构。"
    elif "chapter" in role or chapter:
        lead = f"接下来进入{chapter or '下一部分'}，主题是「{title}」。"
    elif role == "ending" or index == total:
        lead = f"最后回到「{title}」做一个收束。"

    if useful:
        body = "重点可以从" + "、".join(f"「{item[:52]}」" for item in useful[:2]) + "切入。"
    else:
        body = "讲解时先点出页面核心观点，再结合业务场景说明它为什么重要。"
    time_body = time_nodes_sentence(time_nodes)
    if time_body:
        body = f"{body}{time_body}"

    if index == 1 or role == "cover":
        close = "我会先交代背景和目标，再带大家进入后面的具体内容。"
    elif role in {"toc", "contents"} or "目录" in title:
        close = "接下来我会按照这个顺序，逐步展开关键观点。"
    elif role == "ending" or index == total:
        close = "以上就是这一部分的核心结论，也作为今天汇报的最终落点。"
    else:
        close = "这一页的目的，是让大家先形成共同理解，再进入下一页。"
    return f"{lead}{body}{close}"


def generate_presenter_script_from_pages(pages):
    chunks = []
    total = len(pages or [])
    for index, page in enumerate(pages or [], start=1):
        chunks.append(f"Page {index:02d}: {generated_note_for_page(page, index, total)}")
    return "\n\n".join(chunks).strip()


def optimize_imported_speech_text(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = strip_transcript_timestamps(text)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}\d+[.)、]\s+", "", text, flags=re.M)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\n(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(data):
    try:
        from pypdf import PdfReader
    except Exception:
        return "", "PDF 解析依赖不可用"
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for index, page in enumerate(reader.pages[:80], start=1):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(f"第{index}页\n{text.strip()}")
        return "\n\n".join(parts).strip(), ""
    except Exception as error:
        return "", f"PDF 解析失败：{error}"


def extract_presenter_script_file(file_item, filename):
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".pdf", ".md", ".markdown", ".txt"}:
        return {"ok": False, "error": "仅支持 PDF、MD、Markdown 或 TXT"}
    data = file_item.file.read()
    if suffix == ".pdf":
        text, error = extract_pdf_text(data)
        if error:
            return {"ok": False, "error": error}
    else:
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                text = ""
        if not text:
            return {"ok": False, "error": "文本编码无法识别"}
    optimized = optimize_imported_speech_text(text)
    if not optimized:
        return {"ok": False, "error": "没有提取到可用文本"}
    return {"ok": True, "scriptText": optimized, "sourceType": "script", "fileName": Path(filename).name}


def report_presenter_pages_with_expression(asset, presenter_path=None):
    pages = read_presenter_pages_from_path(presenter_path, asset) if presenter_path else read_pages_from_report_preview(asset)
    if not pages:
        pages = read_pages_from_report_preview(asset)
    return attach_page_expression(asset, pages, presenter_path)


def generate_report_presenter_script(report_id):
    asset, error = load_report_asset(report_id)
    if error:
        return error
    presenter_path = existing_report_presenter_path(asset)
    pages = report_presenter_pages_with_expression(asset, presenter_path)
    script_text = generate_presenter_script_from_pages(pages)
    if not script_text:
        return {"ok": False, "error": "没有可用于生成演讲稿的页面信息"}
    return {"ok": True, "scriptText": script_text, "pageCount": len(pages), "sourceType": "script"}


def split_plain_script_chunks(script, page_count):
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", script) if part.strip()]
    if len(paragraphs) <= 1:
        lines = [line.strip() for line in script.splitlines() if line.strip()]
        if len(lines) > 1:
            paragraphs = lines
    if len(paragraphs) <= 1:
        sentences = [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", script) if part.strip()]
        paragraphs = sentences if len(sentences) > 1 else [script.strip()]
    if len(paragraphs) <= page_count:
        return paragraphs
    group_size = max(1, (len(paragraphs) + page_count - 1) // page_count)
    return ["\n".join(paragraphs[index:index + group_size]).strip() for index in range(0, len(paragraphs), group_size)]


def normalize_sentence_end(text):
    text = str(text or "").strip()
    if not text:
        return ""
    return text if re.search(r"[。！？!?]$", text) else f"{text}。"


def clean_presenter_note_text(text):
    text = optimize_imported_speech_text(text)
    text = re.sub(r"^\s*(?:Page|P|第)\s*\d+(?:\s*页)?\s*[：:.\-、]?\s*", "", text, flags=re.I)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    parts = [part.strip() for part in re.split(r"\n+", text) if part.strip()]
    cleaned = " ".join(parts)
    cleaned = re.sub(r"\s*([，。！？；：、])\s*", r"\1", cleaned)
    cleaned = re.sub(r"([。！？]){2,}", r"\1", cleaned)
    return normalize_sentence_end(cleaned)


def page_transition_title(page):
    title = clean_expression_snippet(page.get("title") or page.get("label") or "")
    if len(title) > 34:
        title = f"{title[:34]}..."
    return title or "下一页"


def has_transition_tail(text):
    tail = str(text or "")[-80:]
    return bool(re.search(r"(下一页|接下来|下面|再进入|继续看|转向|最后)", tail))


def refine_presenter_notes(notes, pages):
    if not notes:
        return {}
    page_list = pages or []
    next_title_by_id = {}
    ordered_ids = []
    for page in page_list:
        page_id = str(page.get("id") or "").strip()
        if page_id and str(notes.get(page_id) or "").strip():
            ordered_ids.append(page_id)
    for index, page_id in enumerate(ordered_ids[:-1]):
        next_page_id = ordered_ids[index + 1]
        next_page = next((page for page in page_list if page.get("id") == next_page_id), {})
        next_title_by_id[page_id] = page_transition_title(next_page)

    refined = {}
    for page in page_list:
        page_id = str(page.get("id") or "").strip()
        raw = str(notes.get(page_id) or "").strip()
        if not page_id or not raw:
            continue
        text = clean_presenter_note_text(raw)
        time_nodes = extract_time_nodes(" ".join([
            str(page.get("title") or ""),
            str(page.get("chapter") or ""),
            str(page.get("expressionText") or ""),
            raw,
        ]), 4)
        missing_time_nodes = [node for node in time_nodes if node not in text]
        if missing_time_nodes:
            text = f"{text} {time_nodes_sentence(missing_time_nodes)}"
        next_title = next_title_by_id.get(page_id, "")
        if next_title and next_title not in text and not has_transition_tail(text):
            text = f"{text} 讲完这一点，我们再进入「{next_title}」。"
        refined[page_id] = text
    for page_id, raw in notes.items():
        if page_id not in refined and str(raw or "").strip():
            refined[page_id] = clean_presenter_note_text(raw)
    return refined


def presenter_notes_from_script(script, pages):
    page_list = pages or []
    page_count = max(1, len(page_list))
    marked_notes = parse_marked_script_notes(script, page_list)
    if marked_notes:
        return marked_notes
    auto_notes = auto_paginate_script_notes(script, page_list)
    if auto_notes:
        return auto_notes
    chunks = parse_marked_script_chunks(script) or split_plain_script_chunks(script, page_count)
    notes = {}
    for index, chunk in enumerate(chunks[:page_count]):
        page = page_list[index] if index < len(page_list) else {}
        page_id = str(page.get("id") or f"page-{index + 1:02d}").strip()
        if page_id and chunk.strip():
            notes[page_id] = chunk.strip()
    return notes


def save_report_presenter_script(report_id, payload):
    asset, error = load_report_asset(report_id)
    if error:
        return error
    script = str(payload.get("script") or payload.get("content") or "").strip()
    source_type = str(payload.get("sourceType") or payload.get("source_type") or "script").strip()
    minutes_url = str(payload.get("minutesUrl") or payload.get("minutes_url") or "").strip()
    if source_type == "minutes" and not minutes_url:
        return {"ok": False, "error": "请先填写飞书妙记链接"}
    if not script:
        return {"ok": False, "error": "请粘贴飞书妙记整理后的内容或演讲稿正文"}
    script = optimize_imported_speech_text(script)
    if not script:
        return {"ok": False, "error": "清洗后没有可写入的演讲稿内容"}
    presenter_path, pages, ensure_error = ensure_report_presenter_file(asset)
    if ensure_error:
        return {"ok": False, "error": ensure_error}
    if not pages:
        pages = read_presenter_pages_from_path(presenter_path, asset) or read_pages_from_report_preview(asset)
    pages = attach_page_expression(asset, pages, presenter_path)
    notes = presenter_notes_from_script(script, pages)
    notes = refine_presenter_notes(notes, pages)
    if not notes:
        return {"ok": False, "error": "没有解析到可写入的演讲稿内容"}
    try:
        html_text = presenter_path.read_text(encoding="utf-8")
        html_text = replace_js_const_json(html_text, "defaultSpeakerNotes", notes, "{", "}")
        presenter_path.write_text(html_text, encoding="utf-8")
        write_presenter_metadata(presenter_path, source_type, minutes_url)
    except OSError:
        return {"ok": False, "error": "演讲稿写入失败"}
    trash_dir = report_presenter_trash_dir(asset)
    if trash_dir:
        shutil.rmtree(trash_dir, ignore_errors=True)
    status = report_presenter_status(report_id)
    status.update({
        "sourceType": source_type,
        "minutesUrl": minutes_url,
    })
    return status


def save_report_presenter_page_note(report_id, payload):
    """Persist one arranged page note without rewriting the report script."""
    asset, error = load_report_asset(report_id)
    if error:
        return error
    page_id = str(payload.get("pageId") or payload.get("page_id") or "").strip()
    if not page_id:
        return {"ok": False, "error": "缺少页面编号"}
    result, page_items = report_public_page_items(report_id)
    if not result.get("ok"):
        return result
    page = next((
        item for item in page_items
        if page_id in {str(item.get("id") or ""), str(item.get("code") or "")}
    ), None)
    if not page:
        return {"ok": False, "error": "当前汇报中不存在该页面"}
    stable_page_id = str(page.get("id") or page_id).strip()
    note = str(payload.get("note") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(note) > 20000:
        return {"ok": False, "error": "单页提示词不能超过 20000 个字符"}
    presenter_path, _pages, ensure_error = ensure_report_presenter_file(asset)
    if ensure_error:
        return {"ok": False, "error": ensure_error}
    notes = read_presenter_notes(presenter_path)
    if note:
        notes[stable_page_id] = note
    else:
        notes.pop(stable_page_id, None)
    metadata = read_presenter_metadata(presenter_path)
    try:
        html_text = presenter_path.read_text(encoding="utf-8")
        html_text = replace_js_const_json(html_text, "defaultSpeakerNotes", notes, "{", "}")
        presenter_path.write_text(html_text, encoding="utf-8")
        write_presenter_metadata(
            presenter_path,
            str(metadata.get("sourceType") or "manual"),
            str(metadata.get("minutesUrl") or ""),
        )
    except OSError:
        return {"ok": False, "error": "当前页提示词保存失败"}
    return {
        "ok": True,
        "pageId": stable_page_id,
        "note": note,
        "updatedAt": now_ms(),
    }


def delete_report_presenter_script(report_id):
    asset, error = load_report_asset(report_id)
    if error:
        return error
    presenter_path = existing_report_presenter_path(asset)
    if not presenter_path:
        status = report_presenter_status(report_id)
        status["deleted"] = False
        return status
    trash_dir = report_presenter_trash_dir(asset)
    if not trash_dir:
        return {"ok": False, "error": "当前汇报没有可恢复的本地演讲稿路径"}
    trash_dir.mkdir(parents=True, exist_ok=True)
    destination = trash_dir / f"{now_ms()}-{presenter_path.name}"
    try:
        os.replace(presenter_path, destination)
        os.utime(destination, None)
    except OSError:
        return {"ok": False, "error": "演讲稿删除失败"}
    metadata_path = presenter_metadata_path(presenter_path)
    if metadata_path and metadata_path.exists():
        try:
            os.replace(metadata_path, presenter_metadata_path(destination))
        except OSError:
            pass
    status = report_presenter_status(report_id)
    status["deleted"] = True
    return status


def restore_report_presenter_script(report_id):
    asset, error = load_report_asset(report_id)
    if error:
        return error
    if existing_report_presenter_path(asset):
        return {"ok": False, "error": "当前汇报已有演讲稿，不能覆盖恢复"}
    deleted_paths = report_presenter_deleted_paths(asset)
    if not deleted_paths:
        return {"ok": False, "error": "没有可恢复的演讲稿"}
    target = report_presenter_restore_target(asset)
    if not target:
        return {"ok": False, "error": "当前汇报没有可恢复的本地演讲稿路径"}
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(deleted_paths[0], target)
    except OSError:
        return {"ok": False, "error": "演讲稿恢复失败"}
    deleted_metadata = presenter_metadata_path(deleted_paths[0])
    if deleted_metadata and deleted_metadata.exists():
        try:
            os.replace(deleted_metadata, presenter_metadata_path(target))
        except OSError:
            pass
    trash_dir = report_presenter_trash_dir(asset)
    if trash_dir and not any(trash_dir.iterdir()):
        trash_dir.rmdir()
    status = report_presenter_status(report_id)
    status["restored"] = True
    return status












def restore_upload_extract(upload_id):
    """Rebuild a missing extraction directory from its retained upload package."""
    upload_id = str(upload_id or "").strip()
    if not upload_id or not re.fullmatch(r"[A-Za-z0-9._-]+", upload_id):
        return False

    with EXTRACT_RESTORE_LOCK:
        restore_lock = EXTRACT_RESTORE_LOCKS.setdefault(upload_id, threading.Lock())

    with restore_lock:
        target_root = (EXTRACTED / upload_id).resolve()
        if not is_path_within(target_root, EXTRACTED):
            return False
        with db() as conn:
            upload = conn.execute(
                "select filename, stored_path from uploads where id = ?",
                (upload_id,),
            ).fetchone()
            existing_timestamps = {
                row["id"]: row["updated_at"]
                for row in conn.execute(
                    "select id, updated_at from assets where upload_id = ?",
                    (upload_id,),
                ).fetchall()
            }
            has_report_asset = bool(conn.execute(
                "select 1 from assets where upload_id = ? and asset_type = 'report' limit 1",
                (upload_id,),
            ).fetchone())
        if not upload:
            return False

        stored_record = str(upload["stored_path"] or "").strip()
        stored_path = Path(stored_record)
        if not stored_path.is_absolute():
            stored_path = RUNTIME_ROOT / stored_path
        stored_path = stored_path.resolve()
        if not is_path_within(stored_path, UPLOADS) or not stored_path.is_file():
            return False

        try:
            suffix = stored_path.suffix.lower()
            if suffix in ZIP_SUFFIXES:
                safe_extract(stored_path, target_root)
            elif suffix in {".html", ".htm"}:
                target_root.mkdir(parents=True, exist_ok=True)
                copy_html_dependency_bundle(stored_path, target_root, "upload-html")
            else:
                target_root.mkdir(parents=True, exist_ok=True)
                filename = Path(str(upload["filename"] or stored_path.name)).name
                shutil.copy2(stored_path, target_root / filename)
            normalize_ephemeral_runtime_references(target_root)
            dependency_audit = audit_dependency_closure(target_root)
            write_dependency_audit(target_root, dependency_audit)
            if dependency_audit.get("blockingMissing"):
                shutil.rmtree(target_root, ignore_errors=True)
                return False
            if has_report_asset:
                try:
                    with db() as conn:
                        manifest, manifest_kind = load_report_package_manifest(target_root)
                        if manifest_kind:
                            sync_report_material_package(conn, upload_id, target_root)
                            for asset_id, updated_at in existing_timestamps.items():
                                conn.execute(
                                    "update assets set updated_at = ? where id = ?",
                                    (updated_at, asset_id),
                                )
                            refresh_report_trusted_entries_for_upload(conn, upload_id)
                except Exception:
                    shutil.rmtree(target_root, ignore_errors=True)
                    return False
            return any(path.is_file() for path in target_root.rglob("*"))
        except (OSError, ValueError, zipfile.BadZipFile, UploadLimitError):
            return False


class Handler(BaseHTTPRequestHandler):
    server_version = f"MineM/{PRODUCT_VERSION['version']}"
    _response_started = False

    def log_message(self, fmt, *args):
        message = fmt % args
        message = re.sub(
            rf"([?&]{SOURCE_PREVIEW_CAPABILITY_QUERY}=)[^&\s\"]+",
            r"\1[redacted]",
            message,
        )
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), message))

    def send_response(self, code, message=None):
        # Track that the status line was emitted so the request guard never
        # tries to send a second response on top of a partial one.
        self._response_started = True
        super().send_response(code, message)

    def _guarded_dispatch(self, handler):
        self._response_started = False
        try:
            if not self.authorize_host():
                return
            handler()
        except (BrokenPipeError, ConnectionResetError):
            # Client went away mid-response; nothing useful to send back.
            pass
        except json.JSONDecodeError:
            if not self._response_started:
                try:
                    self.send_json({"ok": False, "error": "请求参数格式无效，请检查 JSON"}, 400)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        except Exception:
            sys.stderr.write(traceback.format_exc())
            if not self._response_started:
                try:
                    self.send_json({"ok": False, "error": "服务器内部错误，请重试"}, 500)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

    def do_GET(self):
        self._guarded_dispatch(self._dispatch_get)

    def do_POST(self):
        self._guarded_dispatch(self._dispatch_post)

    def do_DELETE(self):
        self._guarded_dispatch(self._dispatch_delete)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_binary(self, data, filename, content_type="application/zip"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.write_response_body(data)

    def write_response_body(self, body):
        try:
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def stream_response_file(self, path):
        try:
            with Path(path).open("rb") as source:
                shutil.copyfileobj(source, self.wfile, length=1024 * 1024)
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
        self.send_header("Content-Disposition", f'attachment; filename="{safe_download_name(filename)}"')
        self.end_headers()
        self.stream_response_file(path)

    def send_html(self, html_text, status=200, cache_control="", content_security_policy=""):
        body = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        if content_security_policy:
            self.send_header("Content-Security-Policy", content_security_policy)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.write_response_body(body)

    def authorize_host(self):
        host = str(self.headers.get("Host") or "").strip()
        try:
            parsed = urlparse(f"//{host}")
        except ValueError:
            parsed = None
        if parsed and str(parsed.hostname or "").lower() in self.allowed_request_hosts():
            return True
        if self.path.startswith("/api/"):
            self.send_json({"ok": False, "error": "请求主机不受信任"}, 421)
        else:
            self.send_error(421, "Misdirected Request")
        return False

    def allowed_request_hosts(self):
        allowed = {"127.0.0.1", "localhost", "::1"}
        allowed.update(
            item.strip().lower()
            for item in os.environ.get("MINEM_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        )
        return allowed

    def request_origin(self):
        host = str(self.headers.get("Host") or "").strip()
        if not host:
            return ""
        try:
            parsed = urlparse(f"//{host}")
        except ValueError:
            return ""
        if str(parsed.hostname or "").lower() not in self.allowed_request_hosts():
            return ""
        return f"http://{host}"

    def client_is_loopback(self):
        address = str(self.client_address[0] if self.client_address else "")
        return address in {"127.0.0.1", "::1"} or address.startswith("127.")

    def browser_session_token(self):
        if self.client_is_loopback() and self.request_origin():
            return SESSION_TOKEN
        if truthy_env("MINEM_ALLOW_REMOTE_SESSION") and self.request_origin():
            return SESSION_TOKEN
        return ""

    def requires_session_token(self, path):
        if path == "/api/version":
            return False
        if path.startswith("/api/internal/agent/"):
            return False
        if path.startswith("/api/temp-reports/") and path.endswith(("/heartbeat", "/release")):
            return False
        return path.startswith("/api/")

    def authorize_session_write(self, path):
        if not self.requires_session_token(path):
            return True
        provided = request_token(self.headers)
        if not token_matches(provided, SESSION_TOKEN):
            self.send_json({"ok": False, "error": "MineM 会话已失效，请刷新页面或重新连接 CLI"}, 401)
            return False
        browser_context = bool(
            str(self.headers.get("Origin") or "").strip()
            or str(self.headers.get("Sec-Fetch-Site") or "").strip()
        )
        if browser_context:
            origin = self.request_origin()
            if not origin or not browser_write_origin_allowed(self.headers, origin):
                self.send_json({"ok": False, "error": "请求来源不受信任"}, 403)
                return False
        return True

    def serve_file(self, path, embedded_preview=False, source_preview_capability=""):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        allow_opaque_source = (
            str(self.headers.get("Origin") or "").strip() == "null"
            and source_preview_capability_allows(source_preview_capability, path)
        )
        is_immutable_asset = (
            not embedded_preview
            and not allow_opaque_source
            and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".css", ".js", ".woff2", ".woff", ".ttf"}
        )
        if embedded_preview and path.suffix.lower() in {".html", ".htm"}:
            try:
                html_text = path.read_text(encoding="utf-8")
                if embedded_preview:
                    html_text = inject_embedded_preview_style(
                        html_text,
                        create_source_preview_capability(path),
                    )
                body = html_text.encode("utf-8")
            except (OSError, UnicodeDecodeError):
                body = None
            if body is not None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header(
                    "Content-Security-Policy",
                    "sandbox allow-scripts",
                )
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Referrer-Policy", "no-referrer")
                if allow_opaque_source:
                    self.send_header("Access-Control-Allow-Origin", "null")
                    self.send_header("Vary", "Origin")
                self.end_headers()
                self.write_response_body(body)
                return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("X-Content-Type-Options", "nosniff")
        if allow_opaque_source:
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Cache-Control", "private, no-store, max-age=0")
            self.send_header("Vary", "Origin")
        elif is_immutable_asset:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.stream_response_file(path)

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

        upload_id = rel.split("/", 1)[0]
        original_source_path = rel.split("/", 1)[1] if "/" in rel else ""
        with db() as conn:
            original_asset = conn.execute(
                """select id from assets
                   where upload_id = ? and source_path = ?
                   order by case when version_parent_id = '' then 0 else 1 end
                   limit 1""",
                (upload_id, original_source_path),
            ).fetchone()
        if restore_upload_extract(upload_id):
            path = (EXTRACTED / rel).resolve()
            if is_path_within(path, EXTRACTED) and path.exists() and path.is_file():
                return path
            if original_asset:
                with db() as conn:
                    repaired = conn.execute(
                        "select upload_id, source_path from assets where id = ?",
                        (original_asset["id"],),
                    ).fetchone()
                if repaired and repaired["upload_id"] and repaired["source_path"]:
                    repaired_path = (
                        EXTRACTED / repaired["upload_id"] / repaired["source_path"]
                    ).resolve()
                    if (
                        is_path_within(repaired_path, EXTRACTED)
                        and repaired_path.exists()
                        and repaired_path.is_file()
                    ):
                        return repaired_path

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

    def _dispatch_get(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and self.requires_session_token(parsed.path):
            provided = request_token(self.headers)
            if not token_matches(provided, SESSION_TOKEN):
                self.send_json({"ok": False, "error": "MineM 会话已失效，请刷新页面或重新连接 CLI"}, 401)
                return
        if parsed.path == "/api/version":
            self.send_json({
                "ok": True,
                "release": PRODUCT_VERSION,
                "database": DATABASE_MIGRATION_STATE,
                "jobs": JOB_RUNTIME.snapshot(),
            })
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
        case_preview_match = re.fullmatch(r"/case-groups/([^/]+)/index\.html", parsed.path)
        if case_preview_match:
            case_code = unquote(case_preview_match.group(1))
            group = next((item for item in available_case_groups() if item["code"] == case_code), None)
            if not group:
                self.send_html(
                    preview_error_html("案例预览不可用", "案例组不存在或来源页面尚未完成入库"),
                    404,
                    cache_control="no-store, max-age=0",
                )
                return
            page_items = [
                {
                    "title": control["title"],
                    "code": control["code"],
                    "src": control["controlUrl"],
                    "sourceDoc": control.get("sourceUrl") or group.get("sourceDoc") or "",
                }
                for control in group["controls"]
            ]
            self.send_html(
                report_viewer_html(group["title"], page_items),
                cache_control="no-store, max-age=0",
            )
            return
        if parsed.path.startswith("/pages/") and parsed.path.endswith("/index.html"):
            control_id = unquote(parsed.path.removeprefix("/pages/").removesuffix("/index.html").strip("/"))
            if not control_id or "/" in control_id:
                self.send_html(preview_error_html("页面预览不可用", "页面素材地址无效"), 404, cache_control="no-store, max-age=0")
                return
            with db() as conn:
                control = conn.execute(
                    "select * from assets where id = ? and asset_type = 'control'",
                    (control_id,),
                ).fetchone()
                if control:
                    control = current_asset_version(control, conn=conn)
            if not control:
                self.send_html(preview_error_html("页面预览不可用", "页面素材不存在或已被移出"), 404, cache_control="no-store, max-age=0")
                return
            source_url = canonical_preview_url(control)
            self.send_html(
                report_viewer_html(control["title"] or f"页面 · {control_id}", [{
                    "title": control["title"],
                    "code": control["asset_code"],
                    "src": source_url,
                    "sourceDoc": control_source_doc(control),
                }]),
                cache_control="no-store, max-age=0",
            )
            return

        presenter_match = re.fullmatch(r"/reports/([^/]+)/(presenter|audience)\.html", parsed.path)
        if presenter_match:
            report_id = unquote(presenter_match.group(1))
            payload = report_presenter_mode_payload(report_id)
            if not payload.get("ok"):
                self.send_html(
                    preview_error_html("汇报模式不可用", payload.get("error") or "无法加载汇报"),
                    404,
                    cache_control="no-store, max-age=0",
                )
                return
            is_presenter = presenter_match.group(2) == "presenter"
            self.send_html(
                render_presenter_console(
                    report_id,
                    payload["title"],
                    payload["pages"],
                    self.browser_session_token(),
                    API_TOKEN_HEADER,
                ) if is_presenter else render_audience_view(report_id, payload["title"], payload["pages"]),
                cache_control="no-store, max-age=0",
            )
            return

        if parsed.path.startswith("/reports/") and parsed.path.endswith("/index.html"):
            report_id = unquote(parsed.path.removeprefix("/reports/").removesuffix("/index.html").strip("/"))
            if not report_id or "/" in report_id:
                self.send_html(preview_error_html("汇报预览不可用", "汇报素材地址无效"), 404, cache_control="no-store, max-age=0")
                return
            result, page_items = report_public_page_items(report_id)
            if not result.get("ok"):
                self.send_html(
                    preview_error_html("汇报预览不可用", result.get("error") or "无法加载汇报"),
                    404,
                    cache_control="no-store, max-age=0",
                )
                return
            with db() as conn:
                report = conn.execute("select title from assets where id = ? and asset_type = 'report'", (report_id,)).fetchone()
            title = report["title"] if report else f"汇报 · {report_id}"
            self.send_html(
                report_viewer_html(
                    title,
                    page_items,
                    arrangement_state={
                        "reportId": report_id,
                        "updatedAt": result.get("updatedAt", 0),
                        "pageOrder": result.get("confirmedPageIds", []),
                        "hiddenPageIds": result.get("hiddenPageIds", []),
                    },
                ),
                cache_control="no-store, max-age=0",
            )
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/arrangement/viewer"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/arrangement/viewer").strip("/")
            result, page_items = report_public_page_items(unquote(report_id))
            if not result.get("ok"):
                self.send_html(
                    preview_error_html("汇报编排预览不可用", result.get("error") or "无法加载汇报编排"),
                    404,
                    cache_control="no-store, max-age=0",
                )
                return
            self.send_html(report_viewer_html(f"汇报编排 · {result['reportId']}", page_items), cache_control="no-store, max-age=0")
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
                    """
                    select * from assets
                    where id = ? or version_group = ?
                    order by version_no desc, created_at desc, asset_code desc
                    """,
                    (group_id, group_id),
                ).fetchall()
                assets = add_version_counts(conn, rows)
            self.send_json({"ok": True, "groupId": group_id, "versions": assets})
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/duplicates"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").removesuffix("/duplicates").strip("/"))
            with db() as conn:
                asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
                if not asset:
                    self.send_json({"ok": False, "error": "素材不存在"}, 404)
                    return
                rows = conn.execute(
                    """select * from assets
                       where title = ? and asset_type = ? and version_parent_id = '' and id != ?
                       order by updated_at desc""",
                    (asset["title"], asset["asset_type"], asset_id),
                ).fetchall()
                duplicates = add_version_counts(conn, rows)
            self.send_json({"ok": True, "duplicates": duplicates})
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
            if not self.authorize_session_write(parsed.path):
                return
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/trusted-entry").strip("/")
            result = validate_report_trusted_entry_by_id(unquote(report_id))
            self.send_json(result, 200 if result.get("ok") else 404)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/presenter-script"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/presenter-script").strip("/")
            result = report_presenter_status(unquote(report_id))
            self.send_json(result, 200 if result.get("ok") else 404)
            return

        if parsed.path == "/api/storylines":
            query = parse_qs(parsed.query)
            search = query.get("q", [""])[0].strip()
            self.send_json(load_storylines(search))
            return

        if parsed.path == "/api/case-groups":
            groups = available_case_groups()
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
                    if asset.get("asset_type") == "report":
                        asset["trustedEntry"] = validate_report_trusted_entry(conn, asset["id"])
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
                    page_roles=PAGE_ROLES,
                    tag_taxonomy=taxonomy_payload(),
                )
            self.send_json(payload)
            return
        if parsed.path == "/api/tag-taxonomy":
            with db() as conn:
                self.send_json({"ok": True, "taxonomy": taxonomy_definitions(conn), "status": "active"})
            return
        if parsed.path == "/api/tag-analysis/tasks":
            query = parse_qs(parsed.query)
            limit = int(query.get("limit", ["20"])[0] or 20)
            self.send_json(list_tag_analysis_tasks(limit))
            return
        if parsed.path.startswith("/api/tag-analysis/tasks/"):
            task_id = unquote(parsed.path.removeprefix("/api/tag-analysis/tasks/").strip("/"))
            result = get_tag_analysis_task(task_id)
            self.send_json(result, 200 if result.get("ok") else 404)
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
            embedded = parse_qs(parsed.query).get("embed", [""])[0] == "1"
            # Old copied links should follow the current public report entry
            # after an arrangement is confirmed.  Only exact report source
            # entries redirect; linked page assets remain untouched. Embedded
            # viewer requests always serve the raw source and skip redirects.
            decoded_rel = unquote(rel).strip("/")
            parts = decoded_rel.split("/", 1)
            source_preview_url = f"/extracted/{decoded_rel}"
            if not embedded and len(parts) == 2:
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
            if not embedded and len(parts) == 2:
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
                if (
                    not embedded
                    and path.exists()
                    and path.suffix.lower() in {".html", ".htm"}
                ):
                    self.send_html(
                        report_viewer_html(
                            path.stem or "HTML 素材",
                            [{
                                "title": path.stem or "HTML 素材",
                                "code": "",
                                "src": f"/extracted/{quote(decoded_rel, safe='/._-')}",
                            }],
                        ),
                        cache_control="no-store, max-age=0",
                    )
                    return
                # Platform Preview Shell owns copy/refresh/fullscreen controls.
                # Never inject a second toolbar into source HTML.
                self.serve_file(
                    path,
                    embedded_preview=embedded,
                    source_preview_capability=parse_qs(parsed.query).get(
                        SOURCE_PREVIEW_CAPABILITY_QUERY,
                        [""],
                    )[0],
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

        rel = parsed.path.lstrip("/") or "index.html"
        path = (PUBLIC / rel).resolve()
        if is_path_within(path, PUBLIC):
            if rel == "index.html" and path.is_file():
                self.send_html(
                    management_index_html(path, self.browser_session_token()),
                    cache_control="no-store, max-age=0",
                    content_security_policy=(
                        "default-src 'self'; "
                        "script-src 'self'; "
                        "style-src 'self' 'unsafe-inline'; "
                        "img-src 'self' data: blob:; "
                        "media-src 'self' blob:; "
                        "font-src 'self' data:; "
                        "connect-src 'self'; "
                        "frame-src 'self' blob:; "
                        "object-src 'none'; "
                        "base-uri 'none'; "
                        "form-action 'self'; "
                        "frame-ancestors 'self'"
                    ),
                )
                return
            self.serve_file(path)
            return
        self.send_error(403)

    def _dispatch_post(self):
        parsed = urlparse(self.path)
        if not self.authorize_session_write(parsed.path):
            return
        if parsed.path != "/api/import-tasks" and not parsed.path.endswith("/presenter-script/extract"):
            if reject_oversized_json(self):
                return
        if parsed.path == "/api/desktop/creator-assistant":
            executable = Path(os.environ.get(
                "MINEM_DESKTOP_EXECUTABLE",
                "/Applications/MineM.app/Contents/MacOS/minem-desktop",
            )).expanduser()
            if not executable.is_file():
                self.send_json({
                    "ok": False,
                    "error": "未检测到 MineM 客户端，请先安装 macOS 客户端",
                }, 409)
                return
            try:
                subprocess.Popen(
                    [str(executable), "--assistant"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as error:
                self.send_json({"ok": False, "error": f"无法打开创作助手：{error}"}, 500)
                return
            self.send_json({"ok": True})
            return
        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/exports"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/exports").strip("/"))
            if not report_id or "/" in report_id:
                self.send_json({"ok": False, "error": "汇报地址无效"}, 400)
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "导出参数格式无效"}, 400)
                return
            result = create_report_export_task(report_id, payload.get("format"))
            self.send_json(
                result,
                202 if result.get("ok") else 503 if result.get("task", {}).get("message") == "导出队列繁忙" else 400,
            )
            return
        if parsed.path == "/api/temp-reports":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = create_temp_report(payload)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/tag-taxonomy":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            with db() as conn:
                ensure_tag_task_schema(conn)
                result = update_taxonomy_definitions(conn, payload)
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
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            asset_id = payload.get("id") or f"{slugify(payload.get('title', 'asset'))}-{now_ms()}"
            asset_type = payload.get("asset_type", "control")
            category = payload.get("category", "code")
            media_kind = payload.get("media_kind", "none")
            with db() as conn:
                existing = conn.execute("select asset_code from assets where id = ?", (asset_id,)).fetchone()
                asset_code = existing["asset_code"] if existing and existing["asset_code"] else next_asset_code(conn, asset_type, category, media_kind)
                conn.execute(
                    """
                    insert or replace into assets
                    (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, source_type, source_path, preview_url, upload_id, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', '', '', null, coalesce((select created_at from assets where id = ?), ?), ?)
                    """,
                    (
                        asset_id,
                        payload.get("title", "未命名素材"),
                        category,
                        payload.get("usage", ""),
                        "",
                        payload.get("snippet", ""),
                        asset_type,
                        asset_code,
                        media_kind,
                        asset_id,
                        now_ms(),
                        now_ms(),
                    ),
                )
            self.send_json({"ok": True, "id": asset_id, "assetCode": asset_code})
            return

        if parsed.path == "/api/auto-import":
            self.send_json(auto_import_sources())
            return

        if parsed.path == "/api/sync-report-materials":
            changed = sync_report_materials_from_extracted()
            self.send_json({"ok": True, "changed": changed})
            return

        if parsed.path == "/api/ai-tag":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self.send_json(ai_tag_assets(payload.get("asset_type", "control")))
            return

        if parsed.path == "/api/tag-analysis/tasks":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "标签任务参数格式无效"}, 400)
                return
            asset_ids = payload.get("assetIds") or []
            if not isinstance(asset_ids, list):
                self.send_json({"ok": False, "error": "assetIds 必须是数组"}, 400)
                return
            scope_type = str(payload.get("scopeType") or "assets")
            if not asset_ids and scope_type in {"all", "control", "report", "resource"}:
                with db() as conn:
                    if scope_type == "all":
                        rows = conn.execute("select id from assets order by updated_at desc, created_at desc").fetchall()
                    else:
                        rows = conn.execute(
                            "select id from assets where asset_type=? order by updated_at desc, created_at desc",
                            (scope_type,),
                        ).fetchall()
                asset_ids = [row["id"] for row in rows]
            apply_mode = "confirmed" if payload.get("apply") is True else "suggestions"
            result = create_tag_analysis_task(
                [str(item) for item in asset_ids if str(item).strip()],
                trigger_type="manual",
                scope_type=scope_type,
                apply_mode=apply_mode,
            )
            self.send_json(
                result,
                202 if result.get("ok") else 503 if result.get("error") == "当前标签任务较多，请稍后重试" else 400,
            )
            return
        if parsed.path == "/api/tag-analysis/scheduled-run":
            self.send_json(run_scheduled_tag_analysis())
            return

        if parsed.path == "/api/merge-similar":
            self.send_json(merge_similar_resource_versions())
            return

        if parsed.path == "/api/assets/manual-merge":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = manual_merge_asset_versions(payload)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/internal/agent/analyze":
            if not self.authorize_agent_api():
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            task = str(payload.get("task") or "").strip()
            if not task:
                self.send_json({"ok": False, "error": "缺少 task"}, 400)
                return
            self.send_json(AGENT_RUNTIME.analyze(task, focus=str(payload.get("focus") or "")))
            return

        if parsed.path == "/api/internal/agent/checkpoint":
            if not self.authorize_agent_api():
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self.send_json(AGENT_RUNTIME.checkpoint(
                label=str(payload.get("label") or ""),
                task=str(payload.get("task") or ""),
            ))
            return

        if parsed.path == "/api/internal/agent/validate":
            if not self.authorize_agent_api():
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
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

        if parsed.path == "/api/storyline-reports":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = create_storyline_report(payload)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/assets/") and "/versions/" in parsed.path and parsed.path.endswith("/promote"):
            parts = parsed.path.removeprefix("/api/assets/").removesuffix("/promote").split("/versions/")
            if len(parts) == 2:
                asset_id = unquote(parts[0].strip("/"))
                version_id = unquote(parts[1].strip("/"))
                with db() as conn:
                    asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
                    version_asset = conn.execute("select * from assets where id = ?", (version_id,)).fetchone()
                    if not asset or not version_asset:
                        self.send_json({"ok": False, "error": "素材不存在"}, 404)
                        return
                    group_id = asset["version_group"] or asset["id"]
                    version_group = version_asset["version_group"] or version_asset["id"]
                    if group_id != version_group:
                        self.send_json({"ok": False, "error": "目标版本不属于同一版本组"}, 400)
                        return
                    promote_asset_version(conn, version_id)
                    rows = conn.execute(
                        "select * from assets where id = ? or version_group = ? order by version_no, created_at desc",
                        (version_id, version_id),
                    ).fetchall()
                    versions = add_version_counts(conn, rows)
                self.send_json({"ok": True, "groupId": version_id, "versions": versions})
                return

        if parsed.path == "/api/assets/merge-versions":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            asset_ids = payload.get("assetIds")
            if not isinstance(asset_ids, list) or len(asset_ids) < 2:
                self.send_json({"ok": False, "error": "至少需要两个素材 ID"}, 400)
                return
            with db() as conn:
                placeholders = ",".join("?" for _ in asset_ids)
                rows = conn.execute(
                    f"select id, updated_at from assets where id in ({placeholders})",
                    asset_ids,
                ).fetchall()
            if len(rows) != len(set(asset_ids)):
                self.send_json({"ok": False, "error": "部分素材不存在"}, 404)
                return
            primary_id = max(rows, key=lambda row: row["updated_at"])["id"]
            result = manual_merge_asset_versions({
                "assetIds": asset_ids,
                "primaryAssetId": primary_id,
                "mode": "version",
            })
            if result.get("ok"):
                result["primaryId"] = result["primary"]["id"]
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/versions"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").removesuffix("/versions").strip("/"))
            if reject_oversized_upload(self):
                return
            with db() as conn:
                target = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
                if not target:
                    self.send_json({"ok": False, "error": "素材不存在"}, 404)
                    return
                if target["asset_type"] not in ("control", "resource"):
                    self.send_json({"ok": False, "error": "仅页面和资源素材支持上传新版本"}, 400)
                    return
                if target["version_parent_id"]:
                    self.send_json({"ok": False, "error": "请从主版本上传新版本"}, 400)
                    return
            form = parse_multipart(self.rfile, self.headers.get("Content-Type"), self.headers.get("Content-Length", "0"))
            file_item = form.get("file")
            if file_item is None or not getattr(file_item, "filename", None):
                self.send_json({"ok": False, "error": "没有收到上传文件"}, 400)
                return
            original = Path(file_item.filename).name
            suffix = Path(original).suffix.lower()
            if suffix not in IMPORT_SUFFIXES:
                self.send_json({"ok": False, "error": "仅支持 HTML、ZIP、图片、SVG、GIF 或视频文件"}, 400)
                return
            upload_id = f"version-{uuid.uuid4().hex[:12]}"
            stored_path = UPLOADS / f"{upload_id}{suffix}"
            stored_path.parent.mkdir(parents=True, exist_ok=True)
            with open(stored_path, "wb") as fp:
                shutil.copyfileobj(file_item.file, fp)
            extract_root = EXTRACTED / upload_id
            extract_root.mkdir(parents=True, exist_ok=True)
            if suffix == ".zip":
                safe_extract(stored_path, extract_root)
            else:
                shutil.copy2(stored_path, extract_root / original)
            group_id = target["version_group"] or target["id"]
            with db() as conn:
                version_no = next_asset_version_no(conn, group_id)
                files = [p for p in extract_root.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES]
                if not files:
                    self.send_json({"ok": False, "error": "上传文件中未找到可识别的素材"}, 400)
                    return
                new_asset_id = None
                for file_path in files[:1]:
                    rel = file_path.relative_to(extract_root).as_posix()
                    source_hash = file_hash(file_path)
                    new_asset_id = insert_asset_record(
                        conn,
                        file_path=file_path,
                        rel=rel,
                        upload_id=upload_id,
                        source_type="version-upload",
                        source_hash=source_hash,
                        usage="手动上传新版本",
                        asset_type_override=target["asset_type"],
                        version_group=group_id,
                        version_no=version_no,
                        version_parent_id=target["id"],
                    )
                if not new_asset_id:
                    self.send_json({"ok": False, "error": "版本创建失败"}, 500)
                    return
                promote_asset_version(conn, new_asset_id)
                conn.execute(
                    "insert or replace into uploads (id, filename, stored_path, extract_path, created_at) values (?, ?, ?, ?, ?)",
                    (upload_id, original, str(stored_path), str(extract_root), now_ms()),
                )
                rows = conn.execute(
                    "select * from assets where id = ? or version_group = ? order by version_no, created_at desc",
                    (new_asset_id, new_asset_id),
                ).fetchall()
                versions = add_version_counts(conn, rows)
            generate_upload_thumbnails(upload_id)
            invalidate_stats_cache()
            self.send_json({"ok": True, "groupId": new_asset_id, "versions": versions, "newAssetId": new_asset_id})
            return

        if parsed.path == "/api/import-tasks":
            if reject_oversized_upload(self):
                return
            form = parse_multipart(self.rfile, self.headers.get("Content-Type"), self.headers.get("Content-Length", "0"))
            file_item = form.get("file")
            if file_item is None or not getattr(file_item, "filename", None):
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
            description = str(form.get("description", "") or "").strip()
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
            with IMPORT_CANCEL_LOCK:
                IMPORT_CANCEL_EVENTS[task_id] = threading.Event()
            try:
                JOB_RUNTIME.submit(
                    "imports",
                    task_id,
                    run_import_task,
                    task_id,
                    str(stored),
                    original,
                    upload_id,
                    description,
                    content_hash,
                )
            except JobQueueFullError:
                with IMPORT_CANCEL_LOCK:
                    IMPORT_CANCEL_EVENTS.pop(task_id, None)
                failed_task = update_import_task(
                    task_id,
                    status="failed",
                    progress=100,
                    message="导入队列繁忙",
                    error="当前导入任务较多，请稍后重试",
                )
                self.send_json(
                    {
                        "ok": False,
                        "error": "当前导入任务较多，请稍后重试",
                        "task": failed_task,
                    },
                    503,
                )
                return
            self.send_json({"ok": True, "task": created_task}, 202)
            return

        if parsed.path.startswith("/api/import-tasks/") and parsed.path.endswith("/retry"):
            task_id = unquote(
                parsed.path.removeprefix("/api/import-tasks/").removesuffix("/retry").strip("/")
            )
            if not task_id or "/" in task_id:
                self.send_json({"ok": False, "error": "任务地址无效"}, 400)
                return
            result, status = retry_import_task(task_id)
            self.send_json(result, status)
            return

        if parsed.path.startswith("/api/import-tasks/") and parsed.path.endswith("/cancel"):
            task_id = unquote(
                parsed.path.removeprefix("/api/import-tasks/").removesuffix("/cancel").strip("/")
            )
            if not task_id or "/" in task_id:
                self.send_json({"ok": False, "error": "任务地址无效"}, 400)
                return
            result, status = cancel_import_task(task_id)
            self.send_json(result, status)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/arrangement"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/arrangement").strip("/")
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = update_report_arrangement(unquote(report_id), payload)
            self.send_json(result, 200 if result.get("ok") else 409 if result.get("conflict") else 400)
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/tags"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").removesuffix("/tags").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = update_asset_tags(asset_id, payload.get("tags", []))
            self.send_json(result, 200 if result.get("ok") else 404)
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/title"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").removesuffix("/title").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = update_asset_title(asset_id, payload.get("title", ""))
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/assets/") and parsed.path.endswith("/page-role"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").removesuffix("/page-role").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = update_asset_page_role(asset_id, payload.get("page_role", ""))
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/pages"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/pages").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            pages = payload.get("pages") or payload.get("page_numbers") or payload.get("page_number")
            result = upsert_report_page_slots(
                report_id,
                pages,
                payload.get("title_prefix", ""),
                payload.get("note", ""),
            )
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/presenter-script/generate"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/presenter-script/generate").strip("/"))
            result = generate_report_presenter_script(report_id)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/presenter-script/extract"):
            if reject_oversized_upload(self):
                return
            form = parse_multipart(self.rfile, self.headers.get("Content-Type"), self.headers.get("Content-Length", "0"))
            file_item = form.get("file")
            if file_item is None or not getattr(file_item, "filename", None):
                self.send_json({"ok": False, "error": "没有收到文件"}, 400)
                return
            result = extract_presenter_script_file(file_item, file_item.filename)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/presenter-notes"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/presenter-notes").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = save_report_presenter_page_note(report_id, payload)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/presenter-script"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/presenter-script").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = save_report_presenter_script(report_id, payload)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/presenter-script/restore"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/presenter-script/restore").strip("/"))
            result = restore_report_presenter_script(report_id)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/controls"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/controls").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
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

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/storyline-collections"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/storyline-collections").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = create_report_storyline_collection(report_id, payload)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/report-page-candidates/") and parsed.path.endswith("/adopt"):
            candidate_id = unquote(parsed.path.removeprefix("/api/report-page-candidates/").removesuffix("/adopt").strip("/"))
            result = adopt_report_page_candidate(candidate_id)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/uploads":
            # Legacy synchronous ZIP import bypassed dependency validation and
            # could publish partial assets. Keep it closed so every new import
            # uses the guarded asynchronous task pipeline.
            self.send_json({"ok": False, "error": "该旧导入入口已停用，请使用 /api/import-tasks"}, 410)
            return

        self.send_error(404)

    def _dispatch_delete(self):
        parsed = urlparse(self.path)
        if not self.authorize_session_write(parsed.path):
            return
        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/presenter-script"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/presenter-script").strip("/"))
            result = delete_report_presenter_script(report_id)
            self.send_json(result, 200 if result.get("ok") else 400)
            return
        if parsed.path.startswith("/api/temp-reports/"):
            token = unquote(parsed.path.removeprefix("/api/temp-reports/").strip("/"))
            self.send_json(release_temp_report(token))
            return

        if parsed.path.startswith("/api/case-groups/"):
            case_code = unquote(parsed.path.removeprefix("/api/case-groups/").strip("/"))
            if not case_code:
                self.send_json({"ok": False, "error": "缺少案例组编号"}, 400)
                return
            groups = available_case_groups()
            group = next((item for item in groups if item["code"] == case_code), None)
            if not group:
                self.send_json({"ok": False, "error": "案例组不存在"}, 404)
                return
            roots, _, _ = load_import_sources()
            manifests = case_group_manifest_paths(EXTRACTED, roots, case_code)
            control_codes = case_group_control_codes(EXTRACTED, roots, case_code)
            if not control_codes:
                control_codes = [control["code"] for control in group["controls"]]
            try:
                with db() as conn:
                    plan = build_case_group_deletion_plan(conn, case_code, control_codes)
                    result = apply_case_group_deletion_plan(conn, plan, timestamp=now_ms())
            except AssetDeletionError as error:
                self.send_json(
                    {"ok": False, "error": str(error), **error.details},
                    error.status,
                )
                return

            removed_files = False
            for page_result in result["results"]:
                removed_files = cleanup_deleted_asset_files(page_result) or removed_files
            removed_manifest_count = 0
            for manifest_path in manifests:
                if not is_path_within(manifest_path, EXTRACTED):
                    continue
                try:
                    if manifest_path.exists():
                        manifest_path.unlink()
                        removed_manifest_count += 1
                except OSError:
                    continue
            invalidate_stats_cache()
            self.send_json({
                "ok": True,
                "code": case_code,
                "deletedCount": result["deleted_asset_count"],
                "deletedPageCount": result["deleted_page_count"],
                "deletedAssetCount": result["deleted_asset_count"],
                "missingPageCodes": result["missing_page_codes"],
                "removedFiles": removed_files,
                "removedManifestCount": removed_manifest_count,
                "resourcesRetained": True,
            })
            return

        if parsed.path.startswith("/api/assets/"):
            asset_id = unquote(parsed.path.removeprefix("/api/assets/").strip("/"))
            if not asset_id:
                self.send_json({"ok": False, "error": "缺少素材 ID"}, 400)
                return
            try:
                with db() as conn:
                    row = conn.execute("select id from assets where id = ?", (asset_id,)).fetchone()
                    if not row:
                        row = conn.execute(
                            "select id from assets where asset_code = ? and version_parent_id = '' limit 1",
                            (asset_id,),
                        ).fetchone()
                    resolved_id = row["id"] if row else asset_id
                    plan = build_asset_deletion_plan(conn, resolved_id)
                    result = apply_asset_deletion_plan(conn, plan, timestamp=now_ms())
            except AssetDeletionError as error:
                self.send_json(
                    {"ok": False, "error": str(error), **error.details},
                    error.status,
                )
                return
            removed_file = cleanup_deleted_asset_files(result)
            invalidate_stats_cache()
            self.send_json({
                "ok": True,
                "id": asset_id,
                "assetCode": result["asset"]["asset_code"],
                "removedFile": removed_file,
                "deletedCount": result["deleted_count"],
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


def start_parent_watchdog(server):
    """Stop a desktop-managed sidecar when its Tauri parent disappears."""
    try:
        parent_pid = int(os.environ.get("MINEM_PARENT_PID", "0"))
    except ValueError:
        parent_pid = 0
    if parent_pid <= 1:
        return

    def watch():
        while True:
            try:
                os.kill(parent_pid, 0)
            except ProcessLookupError:
                server.shutdown()
                return
            except PermissionError:
                pass
            time.sleep(1)

    threading.Thread(target=watch, name="minem-parent-watchdog", daemon=True).start()


def main():
    port = int(os.environ.get("PORT", "8790"))
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        assert_service_port_available(host, port)
        acquire_instance_lock(host, port)
    except RuntimeError as error:
        print(f"MineM 启动失败：{error}", file=sys.stderr)
        raise SystemExit(2) from error
    initialize_session_security(host, port)
    init_db()
    start_tag_scheduler()
    with db() as conn:
        stats_payload(conn)
    if os.environ.get("AUTO_IMPORT_ON_START", "0") != "0":
        result = auto_import_sources()
        print(f"Auto import: scanned {result['scanned']} files, added {result['assetCount']} assets")
    server = ThreadingHTTPServer((host, port), Handler)
    start_parent_watchdog(server)
    print(f"Material Library: http://{host}:{port}/")
    print(f"Database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        clear_session_manifest()


def is_cli_invocation():
    executable = Path(sys.argv[0]).name.lower()
    return executable in {"minem", "minem-cli"} or sys.argv[1:2] == ["--cli"]


def run_cli():
    if sys.argv[1:2] == ["--cli"]:
        del sys.argv[1]
    cli_script = RESOURCE_ROOT / "scripts" / "minem_cli.py"
    if not cli_script.is_file():
        print("MineM CLI 组件缺失，请重新安装客户端", file=sys.stderr)
        raise SystemExit(2)
    runpy.run_path(str(cli_script), run_name="__main__")


if __name__ == "__main__":
    if is_cli_invocation():
        run_cli()
    else:
        main()
