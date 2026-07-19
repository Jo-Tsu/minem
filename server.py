#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import cgi
from collections import defaultdict
from contextlib import contextmanager
import fcntl
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
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

from minem.assets import list_assets_response
from minem.agent import AgentRuntime
from minem.case_groups import load_case_groups
from minem.db import connect_database, ensure_asset_schema, initialize_database
from minem.html_splitter import (
    build_control_html as split_control_html,
    build_viewer_pages_from_manifest as split_viewer_pages_from_manifest,
    detect_report_page_count as split_detect_report_page_count,
    extract_body_scripts as split_body_scripts,
    extract_control_page_node as split_control_page_node,
    extract_head as split_head,
    extract_page_node_spans as split_page_node_spans,
    extract_page_nodes as split_page_nodes,
    find_balanced_element as split_balanced_element,
    find_balanced_element_span as split_balanced_element_span,
    is_manifest_driven_report as split_manifest_driven_report,
    manifest_page_id as split_manifest_page_id,
    replace_report_page_node as split_replace_report_page_node,
    strip_outer_element as split_outer_element,
    sync_manifest_viewer_pages as split_sync_manifest_viewer_pages,
    viewer_pages_array_count as split_viewer_pages_array_count,
    viewer_pages_array_span as split_viewer_pages_array_span,
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
from minem.tag_tasks import (
    changed_asset_ids as tag_changed_asset_ids,
    create_task as create_tag_analysis_task_record,
    ensure_schema as ensure_tag_task_schema,
    public_task as public_tag_analysis_task,
    run_task as run_tag_analysis_task_record,
)
from minem.report_exports import ReportExportTaskStore
from minem.lineage import (
    asset_lineage_details as build_asset_lineage_details,
    attach_source_batches as hydrate_source_batches,
    lineage_asset_summary as summarize_lineage_asset,
    pipeline_summary as build_pipeline_summary,
    upload_batch_summaries as summarize_upload_batches,
)
from minem.paths import is_path_within
from minem.reports import (
    attach_report_page_control as attach_slot_control,
    get_report_page_slots as load_report_page_slots,
    normalize_page_numbers as normalize_report_page_numbers,
    register_report_page_candidate as register_slot_candidate,
    report_page_candidate_id as make_report_page_candidate_id,
    upsert_report_page_slots as save_report_page_slots,
)
from minem.report_package_importer import (
    copy_page_variant as import_copy_page_variant,
    discover_report_package_roots as import_discover_report_package_roots,
    load_report_package_manifest as import_load_report_package_manifest,
    page_number_from_slide_path as import_page_number_from_slide_path,
    report_code_to_control_code as import_report_code_to_control_code,
    report_manifest_page_items as import_report_manifest_page_items,
    report_package_entry_path as import_report_package_entry_path,
    safe_int as import_safe_int,
    variant_page_rel as import_variant_page_rel,
)
from minem.report_package_writer import sync_report_material_package as write_report_material_package
from minem.report_canvas import normalize_report_page_canvases as normalize_report_canvas_versions
from minem.resource_importer import sync_report_package_resources as write_report_package_resources
from minem.similarity import (
    apply_similarity_versions as similarity_apply_versions,
    collect_similarity_features as similarity_collect_features,
    dhash_image as similarity_dhash_image,
    hamming_distance as similarity_hamming_distance,
    merge_similar_resource_versions as run_merge_similar_resource_versions,
    normalized_svg_hash as similarity_normalized_svg_hash,
    same_shape as similarity_same_shape,
    similarity_for as similarity_similarity_for,
)
from minem.tagging import (
    allowed_icon_subtags as tagging_allowed_icon_subtags,
    allowed_logo_subtags as tagging_allowed_logo_subtags,
    apply_company_logo_metadata as tagging_apply_company_logo_metadata,
    asset_value as tagging_asset_value,
    extract_company_logo_name as tagging_extract_company_logo_name,
    generic_logo_title as tagging_generic_logo_title,
    image_trait_tags as tagging_image_trait_tags,
    image_traits as tagging_image_traits,
    infer_tags as tagging_infer_tags,
    infer_tags_from_text as tagging_infer_tags_from_text,
    is_generic_logo_title as tagging_is_generic_logo_title,
    merge_tags as tagging_merge_tags,
    normalize_role_tags as tagging_normalize_role_tags,
    page_usage_tags as tagging_page_usage_tags,
    resource_kind_for as tagging_resource_kind_for,
    source_process_tags as tagging_source_process_tags,
    split_tags as tagging_split_tags,
    suggest_material_tags as tagging_suggest_material_tags,
)
from minem.thumbnails import (
    chrome_path as preview_chrome_path,
    detect_html_dimensions as detect_preview_dimensions,
    generate_html_thumbnail as render_html_thumbnail,
    save_contained_thumbnail as render_contained_thumbnail,
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
AI_PRESENTER_VERSION = "edgetts5"
AI_PRESENTER_TEMPLATE = ROOT / "templates" / "ai-presenter.html"
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
TAG_SCHEDULER_WORKER = None

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

TAG_RULES = [
    ("证据与指标", ["kpi", "metric", "指标", "数据", "roi", "percent", "%", "占比", "证明", "quote", "原话", "证据"]),
    ("流程与路径", ["flow", "pipeline", "timeline", "step", "流程", "路径", "步骤", "节点", "演进", "journey"]),
    ("界面参考", ["screen", "console", "phone", "chat", "iframe", "demo", "界面", "控制台", "手机", "对话", "弹窗"]),
    ("叙事表达", ["story", "persona", "经验", "故事", "专家", "判断", "推理", "叙事", "角色", "场景"]),
    ("视觉素材", ["image", "logo", "icon", "background", "visual", "图片", "图标", "背景", "截图", "svg", "png", "jpg", "gif"]),
    ("代码片段", ["css", "javascript", "function", "const ", "class=", "style", "json", "markdown", "代码", "片段"]),
    ("汇报页面", ["deck", "slide", "report", "汇报", "材料", "封面", "页面"]),
    ("可拼接页面", ["card", "panel", "component", "widget", "卡片", "面板", "页面", "组件"]),
    ("资源依赖", ["assets/", "src=", "url(", "logo", "icon", "资源", "素材"]),
    ("制造业", ["制造", "工厂", "车间", "设备", "生产", "质检", "巡检", "供应商", "qms", "andon", "plc"]),
    ("客户案例", ["客户", "案例", "顺达", "蔚来", "继峰", "海亮", "宝龙达", "customer", "case"]),
    ("生产巡检", ["生产", "巡检", "点检", "plc", "气体", "摄像头", "inspection"]),
    ("质量管理", ["质量", "质检", "qms", "mqc", "异常", "quality"]),
    ("安全巡检", ["安全", "风险", "预警", "安防", "safety", "warning"]),
    ("供应商管理", ["供应商", "采购", "supplier", "vendor"]),
]

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
    "storyline-collection": "故事线收藏",
}

MATERIAL_TAG_TAXONOMY = {
    "汇报素材": ["完整汇报", "HTML汇报", "可导出", "汇报母版"],
    "页面素材": ["单页素材", "可拼接页面", "页面片段", "页面模板"],
    "基础资源": ["图片素材", "视频素材", "GIF素材", "SVG素材", "资源依赖"],
    "图片素材": ["产品截图", "页面截图", "实景照片", "装饰插画"],
    "企业logo": ["客户logo", "飞书logo", "合作伙伴logo", "品牌标识"],
    "方案素材": ["AI方案", "效率工程", "组织管理", "业务提效", "办公协同"],
    "产品icon": ["飞书产品", "协作工具", "管理工具", "AI产品", "第三方产品"],
    "页面背景": ["封面背景", "内容页背景", "深色科技风"],
    "人物/头像": ["客户人物", "员工头像", "数字人"],
    "数据图表": ["地图", "柱状图", "时间轴", "矩阵图"],
    "页面用途": ["封面", "内容页", "案例页", "数据页", "过渡页", "结尾页"],
    "视觉风格": ["浅色简洁", "深色科技风", "品牌色", "透明底", "横版", "竖版", "方形", "高清大图", "小尺寸图"],
    "业务场景": ["制造业", "客户案例", "生产巡检", "质量管理", "安全巡检", "供应商管理"],
    "参考截图": ["产品截图", "页面截图", "设计参考", "不可直接使用"],
    "复用状态": ["可直接使用", "需二次编辑", "仅作参考"],
    "来源过程": ["完整汇报导入", "单页拆分", "页面抽取", "手动导入", "自动扫描"],
}

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

COMPANY_NAME_RULES = [
    (("feishu", "lark", "飞书"), "飞书", "飞书logo"),
    (("nio", "蔚来"), "蔚来", "客户logo"),
    (("jifeng", "继峰"), "继峰座椅", "客户logo"),
    (("hailiang", "海亮"), "海亮股份", "客户logo"),
    (("pengfei", "鹏飞"), "鹏飞集团", "客户logo"),
    (("bge",), "BGE", "客户logo"),
    (("efficiency", "效率工程"), "效率工程标识", "品牌标识"),
    (("cxmt", "长鑫", "长鑫存储"), "长鑫存储（CXMT）", "客户logo"),
    (("mooreelite", "摩尔精英"), "摩尔精英", "客户logo"),
    (("navinfo", "四维图新"), "四维图新", "客户logo"),
    (("horizon", "地平线", "horizon robotics"), "地平线", "客户logo"),
    (("huami", "华米"), "华米", "客户logo"),
    (("cr micro", "crmicro", "华润微"), "华润微电子", "客户logo"),
    (("faith long", "惠伦晶体"), "惠伦晶体", "客户logo"),
    (("yunstilicon", "云脉芯联"), "云脉芯联", "客户logo"),
    (("huafon", "华峰"), "华峰", "客户logo"),
]

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


# The former flat tag field mixed system metadata, import state, and business
# semantics. Keep it disabled until the governed taxonomy migration lands.
LEGACY_TAGS_ENABLED = False


def merge_tags(*tag_groups):
    if not LEGACY_TAGS_ENABLED:
        return []
    return tagging_merge_tags(*tag_groups)






def normalize_role_tags(tags, asset_type, resource_kind="", identity_text=""):
    if not LEGACY_TAGS_ENABLED:
        return []
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
    if not LEGACY_TAGS_ENABLED:
        return []
    return tagging_infer_tags(
        asset,
        categories=CATEGORIES,
        tag_rules=TAG_RULES,
        asset_library_path=asset_library_path,
        image_trait_tags_fn=image_trait_tags,
    )


def infer_tags_from_text(text):
    if not LEGACY_TAGS_ENABLED:
        return []
    return tagging_infer_tags_from_text(text, tag_rules=TAG_RULES)


def ai_tag_assets(asset_type="control"):
    if not LEGACY_TAGS_ENABLED:
        return {
            "ok": False,
            "error": "旧标签体系已停用，等待新标签体系启用后再执行自动标注",
            "updated": 0,
            "scanned": 0,
            "assetType": asset_type,
        }
    where = ""
    params = []
    if asset_type != "all":
        where = " where asset_type = ?"
        params.append(asset_type)
    updated = 0
    with db() as conn:
        rows = conn.execute(f"select * from assets{where}", params).fetchall()
        for row in rows:
            item = dict(row)
            new_title = row["title"]
            new_kind = row["resource_kind"] or ""
            if row["asset_type"] == "resource":
                path = asset_library_path(row) or Path(row["source_path"] or row["title"] or "")
                new_kind = resource_kind_for(path, row["media_kind"], row["title"], row["tags"])
                item["resource_kind"] = new_kind
                new_title, seeded_tags = apply_company_logo_metadata(
                    row["title"],
                    ",".join(merge_tags(row["tags"], [RESOURCE_KINDS.get(new_kind, new_kind)])),
                    row["source_path"],
                    row["usage"],
                    new_kind,
                )
                item["title"] = new_title
                item["tags"] = seeded_tags
            inferred = infer_tags(item)
            suggested = suggest_material_tags(item) if row["asset_type"] == "resource" else []
            merged = normalize_role_tags(
                merge_tags(item.get("tags") or row["tags"], inferred, suggested),
                row["asset_type"],
                new_kind,
                " ".join([new_title or "", row["source_path"] or ""]),
            )
            tag_text = ",".join(merged)
            if tag_text != (row["tags"] or "") or new_kind != (row["resource_kind"] or "") or new_title != row["title"]:
                conn.execute(
                    "update assets set title = ?, resource_kind = ?, tags = ?, tag_seeded = 1, updated_at = ? where id = ?",
                    (new_title, new_kind, tag_text, now_ms(), row["id"]),
                )
                updated += 1
    return {"ok": True, "updated": updated, "scanned": len(rows), "assetType": asset_type}


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
    if not LEGACY_TAGS_ENABLED:
        return title, ""
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
    with db() as conn:
        ensure_tag_task_schema(conn)
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
  #minem-page-tools, .page-pill, .slide-controls, .slide-navigation,
  .slide-nav, .deck-controls, .deck-navigation, .presentation-controls,
  [data-minem-page-tools], [data-slide-navigation], [data-deck-navigation] {
    display: none !important;
  }
  /* Split page exports use a 1280x720 staging wrapper inside a 1920x1080
     iframe. Let the platform canvas own the sizing so the page is not
     letterboxed a second time inside the report viewer. */
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


def inject_embedded_preview_style(html_text):
    if "minem-embedded-preview-style" in html_text:
        return html_text
    marker = re.search(r"</head\s*>", html_text, flags=re.IGNORECASE)
    if marker:
        return f"{html_text[:marker.start()]}{PREVIEW_EMBED_STYLE}{html_text[marker.start():]}"
    return f"{PREVIEW_EMBED_STYLE}{html_text}"


def thumbnail_path(asset_id):
    return THUMBNAILS / f"{asset_id}.png"


def thumbnail_meta_path(asset_id):
    return THUMBNAILS / f"{asset_id}.json"


def local_html_preview_path(data):
    preview_url = canonical_preview_url(data)
    if not preview_url.startswith("/"):
        return None
    preview_path = urlparse(preview_url).path
    html_path = (ROOT / preview_path.lstrip("/")).resolve()
    if (
        is_path_within(html_path, ROOT)
        and html_path.exists()
        and html_path.is_file()
        and html_path.suffix.lower() in {".html", ".htm"}
    ):
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
    html_path = local_html_preview_path({**dict(data), "preview_url": preview_url})
    if html_path:
        try:
            stat = html_path.stat()
            relative = html_path.relative_to(ROOT).as_posix()
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
            if thumb.stat().st_mtime_ns >= html_path.stat().st_mtime_ns:
                write_thumbnail_meta(data["id"], fingerprint)
                return thumbnail_url(data["id"], fingerprint)
        except OSError:
            pass
    if html_path and data.get("media_kind") == "html":
        enqueue_thumbnail_refresh(data["id"], html_path, fingerprint)
    return ""


def detected_html_preview_size(html_path):
    return detect_preview_dimensions(html_path)




def preview_meta_for_asset(data):
    preview_url = data.get("preview_url") or ""
    media_kind = data.get("media_kind") or ""
    if media_kind != "html" or not preview_url.startswith("/"):
        return {"width": 0, "height": 0, "aspectRatio": 0, "longPage": False}
    html_path = (ROOT / preview_url.lstrip("/")).resolve()
    if not is_path_within(html_path, ROOT) or not html_path.exists() or html_path.suffix.lower() not in {".html", ".htm"}:
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
        tags = normalize_role_tags(
            merge_tags(row["tags"], [RESOURCE_KINDS.get(kind, kind)]),
            row["asset_type"],
            kind,
            " ".join([row["title"] or "", row["source_path"] or ""]),
        )
        title, tag_text = apply_company_logo_metadata(row["title"], ",".join(tags), row["source_path"], row["usage"], kind)
        conn.execute(
            "update assets set title = ?, resource_kind = ?, tags = ?, updated_at = ? where id = ?",
            (title, kind, tag_text, now_ms(), row["id"]),
        )
    seed_material_tags(conn)
    backfill_company_logo_titles(conn)


def seed_material_tags(conn):
    if not LEGACY_TAGS_ENABLED:
        return
    rows = conn.execute(
        "select * from assets where asset_type = 'resource' and tag_seeded = 0"
    ).fetchall()
    for row in rows:
        suggested = merge_tags(suggest_material_tags(row), infer_tags(row))
        if suggested:
            tags = normalize_role_tags(
                merge_tags(row["tags"], suggested),
                row["asset_type"],
                row["resource_kind"],
                " ".join([row["title"] or "", row["source_path"] or ""]),
            )
            conn.execute(
                "update assets set tags = ?, tag_seeded = 1, updated_at = ? where id = ?",
                (",".join(tags), now_ms(), row["id"]),
            )
        else:
            conn.execute("update assets set tag_seeded = 1 where id = ?", (row["id"],))


def backfill_company_logo_titles(conn):
    rows = conn.execute(
        "select * from assets where asset_type = 'resource' and (resource_kind = 'logo' or instr(','||tags||',', ',企业logo,')>0)"
    ).fetchall()
    for row in rows:
        title, tags = apply_company_logo_metadata(row["title"], row["tags"], row["source_path"], row["usage"], row["resource_kind"])
        if title != row["title"] or tags != row["tags"]:
            conn.execute(
                "update assets set title = ?, tags = ?, updated_at = ? where id = ?",
                (title, tags, now_ms(), row["id"]),
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
            tags = merge_tags(
                asset["tags"],
                ["页面素材", "单页素材", "导入分类修复"],
            )
            tags = [tag for tag in tags if tag not in {"汇报素材", "完整汇报", "HTML 汇报"}]
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
                "update assets set tags = ?, usage = ?, updated_at = ? where id = ?",
                (
                    ",".join(merge_tags(existing["tags"], tag_text, ["复用资源"])),
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
    tags = merge_tags(["页面素材", "基础模板", "feishu-deck-h5-library", "单页模板", "手动导入"], infer_tags_from_text(description))
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


def detect_report_page_count(source):
    return split_detect_report_page_count(source, read_json_file=read_json_file, safe_int=safe_int)






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


def report_export_excluded_path(path):
    """AI 演讲、语音模型与运行时只服务平台，不属于汇报交付物。"""
    parts = [part.lower() for part in Path(path).parts]
    name = Path(path).name.lower()
    excluded_parts = {"ai-tts", "ai-presenter", "kokoro-js", "kokoro-voices", "kokoro-zh", "presenter"}
    model_suffixes = {".onnx", ".bin", ".tflite", ".pt", ".pth", ".safetensors"}
    return bool(excluded_parts.intersection(parts)) or name == "ai-presenter.html" or Path(name).suffix in model_suffixes


def copy_report_export_dependency(source_path, destination_path, upload_root, bundle_root, copied):
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
    for reference in report_export_local_references(source_path):
        dependency = report_export_reference_path(reference, source_path, upload_root)
        if not dependency or report_export_excluded_path(dependency):
            continue
        relative = os.path.relpath(dependency, start=source_path.parent)
        target = (destination_path.parent / relative).resolve()
        if not is_path_within(target, bundle_root):
            continue
        copy_report_export_dependency(dependency, target, upload_root, bundle_root, copied)


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


def capture_report_export_page(wrapper_path, screenshot_path):
    chrome = preview_chrome_path()
    if not chrome:
        raise RuntimeError("当前运行环境未安装 Chromium，无法生成 PDF")
    command = [
        chrome, "--headless=new", "--disable-gpu", "--disable-dev-shm-usage", "--disable-background-networking",
        "--disable-extensions", "--hide-scrollbars", "--no-first-run", "--no-sandbox",
        "--allow-file-access-from-files",
        "--run-all-compositor-stages-before-draw", "--virtual-time-budget=10000", "--window-size=1920,1080",
        f"--screenshot={screenshot_path}", wrapper_path.resolve().as_uri(),
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=35, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("PDF 页面渲染超时") from error
    if result.returncode != 0 or not screenshot_path.exists() or screenshot_path.stat().st_size < 1024:
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
            wrapper = root / f"page-{index:03d}.html"
            page_url = f"http://127.0.0.1:{os.environ.get('PORT', '8790')}{item['src']}"
            separator = "&" if "?" in page_url else "?"
            wrapper.write_text(report_export_page_html(item.get("title") or f"Page {index:02d}", f"{page_url}{separator}embed=1"), encoding="utf-8")
            screenshot = root / f"page-{index:03d}.png"
            capture_report_export_page(wrapper, screenshot)
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
    threading.Thread(target=run_report_export_task, args=(task_id,), name=f"report-export-{task_id}", daemon=True).start()
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


def get_report_page_slots(report_id):
    return load_report_page_slots(
        report_id,
        connect=db,
        row_to_asset=row_to_asset,
        asset_library_path=asset_library_path,
        detect_report_page_count=detect_report_page_count,
        validate_report_trusted_entry=validate_report_trusted_entry,
    )


def report_arrangement_payload(report_id):
    normalize_report_page_canvases(report_id)
    slots_result = get_report_page_slots(report_id)
    if not slots_result.get("ok"):
        return slots_result
    slots = [slot for slot in slots_result.get("slots", []) if slot.get("control")]
    if not slots:
        return {"ok": False, "error": "该汇报暂未关联可编排的页面素材", "slots": []}
    with db() as conn:
        row = conn.execute("select * from report_page_arrangements where report_id = ?", (report_id,)).fetchone()
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
        result = normalize_report_canvas_versions(
            conn,
            report_id,
            extracted_root=EXTRACTED,
            detect_dimensions=detected_html_preview_size,
            now_ms=now_ms,
            next_candidate_asset_code=next_candidate_asset_code,
            next_asset_version_no=next_asset_version_no,
            merge_tags=merge_tags,
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


def report_public_page_items(report_id):
    """Return the current visible arrangement for the public report entry."""
    result = report_arrangement_payload(report_id)
    if not result.get("ok"):
        return result, []
    page_items = [
        {"title": page["title"], "code": page["code"], "src": page["previewUrl"]}
        for page in result["pages"] if not page["hidden"]
    ]
    return result, page_items


def update_report_arrangement(report_id, payload):
    current = report_arrangement_payload(report_id)
    if not current.get("ok"):
        return current
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

        # Rebuild the attached rows in one transaction.  Updating individual
        # rows fails when old data contains the same control in multiple slots:
        # both rows would be assigned the same new page number.  Rebuilding
        # also normalizes those legacy duplicates without copying page assets.
        conn.execute("delete from report_page_slots where report_id = ?", (report_id,))
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
        # The public report entry composes the saved page slots at request
        # time.  This keeps the imported source package intact while making
        # both the UI link and an old raw entry URL show the confirmed order.
        conn.execute(
            "update assets set preview_url = ?, updated_at = ? where id = ? and asset_type = 'report'",
            (report_public_url(report_id), timestamp, report_id),
        )
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
    try:
        generate_html_thumbnail(report["id"], source, source_hash)
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
            sync_report_material_package(conn, upload_id, extract_root)
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
    deck_slides, deck_by_key, index_slides, index_by_key = load_deck_slides(extract_root)
    generated_root = Path(extract_root) / "_minem_pages"
    items = []
    for page_number, (_, _, page_node) in enumerate(page_spans, start=1):
        title = external_report_page_title(page_number, page_node, deck_slides, deck_by_key, index_slides, index_by_key)
        rel = f"_minem_pages/page-{page_number:03d}/index.html"
        target = generated_root / f"page-{page_number:03d}" / "index.html"
        page_html = inject_html_base_href(split_control_html(report_html, page_node, title), "../../")
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
    return generate_html_thumbnail(asset_id, html_path, source_fingerprint)


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


def start_tag_analysis_task(task_id):
    threading.Thread(
        target=run_tag_analysis_task_record,
        args=(DB_PATH, EXTRACTED, task_id),
        name=f"minem-tag-analysis-{task_id}",
        daemon=True,
    ).start()


def create_tag_analysis_task(asset_ids, trigger_type="manual", scope_type="assets"):
    with db() as conn:
        result = create_tag_analysis_task_record(conn, asset_ids, trigger_type, scope_type)
        if result.get("ok"):
            task = conn.execute("select * from tag_analysis_tasks where id = ?", (result["taskId"],)).fetchone()
            result["task"] = public_tag_analysis_task(task)
    if result.get("ok"):
        start_tag_analysis_task(result["taskId"])
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


def delete_asset_history_files(conn, asset_ids):
    if not asset_ids:
        return
    placeholders = ",".join("?" for _ in asset_ids)
    rows = conn.execute(f"select id, snapshot_path from asset_history where asset_id in ({placeholders})", asset_ids).fetchall()
    for row in rows:
        if row["snapshot_path"]:
            path = (EXTRACTED / row["snapshot_path"]).resolve()
            if is_path_within(path, EXTRACTED) and path.exists() and path.is_file():
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
    thumb = THUMBNAILS / f"{asset_id}.png"
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
        item = row_to_asset(row)
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


def normalize_tag_payload(value):
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,，、;；\n]+", str(value or ""))
    cleaned = []
    for tag in raw:
        tag = str(tag).strip().strip("#")
        if 1 <= len(tag) <= 24 and not re.search(r"[<>={}()]", tag):
            cleaned.append(tag)
    return merge_tags(cleaned)[:40]


def update_asset_tags(asset_id, tags):
    if not LEGACY_TAGS_ENABLED:
        return {"ok": False, "error": "旧标签体系已停用，暂不支持编辑标签"}
    normalized = normalize_tag_payload(tags)
    with db() as conn:
        asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not asset:
            return {"ok": False, "error": "素材不存在"}
        conn.execute(
            "update assets set tags = ?, tag_seeded = 1, updated_at = ? where id = ?",
            (",".join(normalized), now_ms(), asset_id),
        )
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


def report_viewer_html(title, page_items, release_url=""):
    pages = []
    for index, item in enumerate(page_items, start=1):
        page_title = item.get("title") or f"Page {index:02d}"
        pages.append({
            "id": slugify(page_title) or f"page-{index:02d}",
            "label": f"Page {index:02d}",
            "title": page_title,
            "code": item.get("code") or "",
            "src": item.get("src") or "",
            "role": "cover" if index == 1 else "content",
        })
    if not pages:
        pages = [{"id": "cover", "label": "Page 01", "title": "首页", "code": "", "src": "", "role": "cover"}]
    pages_json = json.dumps(pages, ensure_ascii=False, indent=6)
    release_url_json = json.dumps(release_url or "", ensure_ascii=False)
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
    iframe {{ position: absolute; inset: 0; width: 1920px; height: 1080px; border: 0; background: #030712; }}
    .page-pill {{ position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); display: inline-flex; gap: 12px; align-items: center; border: 1px solid rgba(153,180,209,.34); border-radius: 999px; padding: 10px 18px; background: rgba(2,5,12,.62); font-size: 14px; }}
    .nav-btn {{ width: 30px; height: 30px; border: 1px solid rgba(153,180,209,.34); border-radius: 999px; color: #fff; background: rgba(255,255,255,.08); cursor: pointer; }}
    .nav-btn:disabled {{ opacity: .35; cursor: default; }}
    .page-tools {{ position: fixed; top: 24px; right: 24px; display: inline-flex; gap: 8px; padding: 6px; border: 1px solid rgba(153,180,209,.34); border-radius: 10px; background: rgba(2,5,12,.72); }}
    .tool-btn {{ width: 36px; height: 36px; border: 0; border-radius: 7px; color: #fff; background: transparent; font-size: 19px; line-height: 1; cursor: pointer; }}
    .tool-btn:hover {{ background: rgba(255,255,255,.12); }}
    .copy-page {{ position: relative; font-size: 0; }}
    .copy-page::before, .copy-page::after {{ content: ""; position: absolute; width: 11px; height: 12px; border: 1.5px solid currentColor; border-radius: 2px; }}
    .copy-page::before {{ left: 10px; top: 9px; opacity: .72; }}
    .copy-page::after {{ left: 14px; top: 13px; background: #02050c; }}
    html[data-embed="1"] .page-tools {{ display: none; }}
    @media (max-width: 720px) {{ .page-tools {{ top: 12px; right: 12px; }} .page-pill {{ bottom: 12px; }} }}
  </style>
</head>
<body>
  <main class="viewer" aria-label="{safe_title}">
    <div class="slide-viewport"><section class="slide-shell"><iframe class="deck-frame" title="Page 01" src=""></iframe></section></div>
    <div class="page-tools" aria-label="页面工具"><button class="tool-btn copy-page" type="button" title="复制当前页链接" aria-label="复制当前页链接"></button><button class="tool-btn refresh-page" type="button" title="刷新当前页" aria-label="刷新当前页">↻</button><button class="tool-btn fullscreen-page" type="button" title="全屏" aria-label="全屏">⛶</button></div>
    <div class="page-pill"><button class="nav-btn prev" type="button" aria-label="上一页">‹</button><span class="page-count">1 / 1</span><span>·</span><span class="page-title">Page 01</span><button class="nav-btn next" type="button" aria-label="下一页">›</button></div>
  </main>
  <script>
	    const pages = {pages_json};
	    const embedded = new URLSearchParams(window.location.search).get("embed") === "1";
	    if (embedded) document.documentElement.dataset.embed = "1";
	    const releaseUrl = {release_url_json};
	    const heartbeatUrl = releaseUrl ? releaseUrl.replace(new RegExp("/release$"), "/heartbeat") : "";
	    let currentIndex = 0;
	    let released = false;
	    let heartbeatTimer = 0;
	    const frame = document.querySelector(".deck-frame");
    const pageCount = document.querySelector(".page-count");
    const pageTitle = document.querySelector(".page-title");
    const prevButton = document.querySelector(".prev");
    const nextButton = document.querySelector(".next");
    const copyButton = document.querySelector(".copy-page");
    const refreshButton = document.querySelector(".refresh-page");
    const fullscreenButton = document.querySelector(".fullscreen-page");
    function updateDeckScale() {{
      const scale = Math.min((window.innerWidth - 96) / 1920, (window.innerHeight - 72) / 1080, 1);
      document.documentElement.style.setProperty("--deck-scale", String(scale));
    }}
    function showPage(index) {{
      currentIndex = Math.max(0, Math.min(index, pages.length - 1));
      const page = pages[currentIndex] || pages[0];
      frame.src = page.src ? `${{page.src}}${{page.src.includes("?") ? "&" : "?"}}embed=1&v=${{Date.now()}}` : "";
      frame.title = `${{page.label}} - ${{page.title}}`;
      pageCount.textContent = `${{currentIndex + 1}} / ${{pages.length}}`;
      pageTitle.textContent = page.label;
      prevButton.disabled = currentIndex === 0;
      nextButton.disabled = currentIndex >= pages.length - 1;
    }}
    updateDeckScale();
    showPage(0);
    window.addEventListener("resize", updateDeckScale);
	    prevButton.addEventListener("click", () => showPage(currentIndex - 1));
	    nextButton.addEventListener("click", () => showPage(currentIndex + 1));
	    copyButton.addEventListener("click", async () => {{
	      const page = pages[currentIndex] || pages[0];
	      if (!page || !page.src) return;
	      const url = new URL(page.src, window.location.origin).toString();
	      try {{
	        await navigator.clipboard.writeText(url);
	        copyButton.setAttribute("data-copied", "true");
	        window.setTimeout(() => {{ copyButton.removeAttribute("data-copied"); }}, 1200);
	      }} catch (_) {{
	        window.prompt("复制当前页链接", url);
	      }}
	    }});
	    refreshButton.addEventListener("click", () => showPage(currentIndex));
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
    }});
  </script>
</body>
	</html>
	"""


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


def copy_report_thumbnail(source_id, target_id, source_fingerprint=""):
    source_thumb = THUMBNAILS / f"{source_id}.png"
    target_thumb = THUMBNAILS / f"{target_id}.png"
    if source_thumb.exists():
        target_thumb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_thumb, target_thumb)
        write_thumbnail_meta(target_id, source_fingerprint)


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
      copied_thumbnail_from = ""
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
          copied_thumbnail_from = controls[0]["id"]
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
          copied_thumbnail_from = source_report["id"]
          tags = merge_tags(tags, [version["code"], f"复制自:{source_report['asset_code']}"])
          usage = f"从故事线 {version['code']} 的 V{version['version_no']} 复制为独立汇报素材。"
          if note:
              usage += f" 备注：{note}"
      else:
          return fail("创建方式不正确")

      report_file = target_root / source_path
      if not report_file.exists():
          return fail("汇报入口生成失败")
      preview_url = f"/extracted/{upload_id}/{source_path}"
      conn.execute(
          "insert or replace into uploads (id, filename, stored_path, extract_path, file_count, asset_count, created_at) values (?, ?, ?, ?, ?, ?, ?)",
          (upload_id, title, str(target_root), str(target_root), sum(1 for path in target_root.rglob("*") if path.is_file()), 1, timestamp),
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
          for page_id, control in zip(created_page_ids, controls):
              copy_report_thumbnail(control["id"], page_id, source_hash)
      copy_report_thumbnail(copied_thumbnail_from, report_id, source_hash)
      try:
          if not (THUMBNAILS / f"{report_id}.png").exists():
              generate_html_thumbnail(report_id, report_file, source_hash)
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
    dumped = json.dumps(value, ensure_ascii=False, indent=6)
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
    pages = read_presenter_pages_from_path(presenter_path, asset) if presenter_path else read_pages_from_report_preview(asset)
    notes = read_presenter_notes(presenter_path)
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
        "scriptText": presenter_script_text(notes, pages),
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
    except OSError:
        return {"ok": False, "error": "演讲稿写入失败"}
    status = report_presenter_status(report_id)
    status.update({
        "sourceType": source_type,
        "minutesUrl": minutes_url,
    })
    return status












class Handler(BaseHTTPRequestHandler):
    server_version = f"MineM/{PRODUCT_VERSION['version']}"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

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

    def send_html(self, html_text, status=200, cache_control=""):
        body = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.write_response_body(body)

    def serve_file(self, path, embedded_preview=False):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if embedded_preview and path.suffix.lower() in {".html", ".htm"}:
            try:
                html_text = path.read_text(encoding="utf-8")
                if embedded_preview:
                    html_text = inject_embedded_preview_style(html_text)
                body = html_text.encode("utf-8")
            except (OSError, UnicodeDecodeError):
                body = None
            if body is not None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.write_response_body(body)
                return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("X-Content-Type-Options", "nosniff")
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
            if not control:
                self.send_error(404)
                return
            source_url = canonical_preview_url(control)
            self.send_html(
                report_viewer_html(control["title"] or f"页面 · {control_id}", [{
                    "title": control["title"],
                    "code": control["asset_code"],
                    "src": source_url,
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
            self.send_html(report_viewer_html(title, page_items), cache_control="no-store, max-age=0")
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/arrangement/viewer"):
            report_id = parsed.path.removeprefix("/api/reports/").removesuffix("/arrangement/viewer").strip("/")
            result, page_items = report_public_page_items(unquote(report_id))
            if not result.get("ok"):
                self.send_html(f"<!doctype html><meta charset='utf-8'><body>{html.escape(result.get('error') or '无法加载汇报编排')}</body>", 404)
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
                    tag_taxonomy={},
                )
            self.send_json(payload)
            return
        if parsed.path == "/api/tag-taxonomy":
            self.send_json({"taxonomy": {}, "status": "legacy-tags-disabled"})
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
            # Old copied links should follow the current public report entry
            # after an arrangement is confirmed.  Only exact report source
            # entries redirect; linked page assets remain untouched.
            decoded_rel = unquote(rel).strip("/")
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

        rel = parsed.path.lstrip("/") or "index.html"
        path = (PUBLIC / rel).resolve()
        if is_path_within(path, PUBLIC):
            self.serve_file(path)
            return
        self.send_error(403)

    def do_POST(self):
        parsed = urlparse(self.path)
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
            self.send_json(result, 202 if result.get("ok") else 400)
            return
        if parsed.path == "/api/temp-reports":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
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
                        ",".join(payload.get("tags", [])) if isinstance(payload.get("tags"), list) else payload.get("tags", ""),
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
            result = create_tag_analysis_task([str(item) for item in asset_ids if str(item).strip()])
            self.send_json(result, 202 if result.get("ok") else 400)
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

        if parsed.path == "/api/import-tasks":
            if reject_oversized_upload(self):
                return
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
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = update_report_arrangement(unquote(report_id), payload)
            self.send_json(result, 200 if result.get("ok") else 400)
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
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            })
            file_item = form["file"] if "file" in form else None
            if file_item is None or not file_item.filename:
                self.send_json({"ok": False, "error": "没有收到文件"}, 400)
                return
            result = extract_presenter_script_file(file_item, file_item.filename)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path.startswith("/api/reports/") and parsed.path.endswith("/presenter-script"):
            report_id = unquote(parsed.path.removeprefix("/api/reports/").removesuffix("/presenter-script").strip("/"))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = save_report_presenter_script(report_id, payload)
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
                targets = conn.execute("select * from assets where version_group = ?", (group_id,)).fetchall() if not asset["version_parent_id"] else [asset]
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
                conn.executemany("delete from report_storyline_collections where source_report_id = ? or output_report_id = ? or target_report_id = ?", [(target["id"], target["id"], target["id"]) for target in targets])
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
    start_tag_scheduler()
    if os.environ.get("AUTO_IMPORT_ON_START", "0") != "0":
        result = auto_import_sources()
        print(f"Auto import: scanned {result['scanned']} files, added {result['assetCount']} assets")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Material Library: http://{host}:{port}/")
    print(f"Database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
