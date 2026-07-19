#!/usr/bin/env python3
from pathlib import Path
import json
import re
import sqlite3
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minem.paths import is_path_within

DB_PATH = ROOT / "data" / "materials.db"
EXTRACTED = ROOT / "extracted"
SECOND_TS_LIMIT = 100_000_000_000
LEGACY_MOCK_TAG = "界面 " + "Mock"
LEGACY_MOCK_CODE_PREFIX = "CTRL-" + "MOCK"

LOGO_TITLE_BY_IMAGE_NO = {
    "136": ("长鑫存储（CXMT）", "客户logo"),
    "137": ("摩尔精英", "客户logo"),
    "138": ("四维图新", "客户logo"),
    "139": ("地平线", "客户logo"),
    "141": ("华米", "客户logo"),
    "150": ("华润微电子", "客户logo"),
    "167": ("惠伦晶体", "客户logo"),
    "169": ("云脉芯联", "客户logo"),
    "236": ("华峰", "客户logo"),
}

LOGO_KEYWORD_RULES = [
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


def now_ms():
    return int(time.time() * 1000)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma busy_timeout = 5000")
    return conn


def table_exists(conn, table):
    return bool(conn.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone())


def table_columns(conn, table):
    return {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()} if table_exists(conn, table) else set()


def split_tags(value):
    return [tag.strip() for tag in str(value or "").split(",") if tag.strip()]


def merge_tags(*groups):
    seen = set()
    merged = []
    for group in groups:
        tags = split_tags(group) if isinstance(group, str) else [tag for tag in group if tag]
        for tag in tags:
            tag = str(tag).strip()
            if tag and tag not in seen:
                seen.add(tag)
                merged.append(tag)
    return merged


def clean_tags(value):
    replacements = {
        LEGACY_MOCK_TAG: "界面参考",
        "HTML 汇报": "HTML汇报",
    }
    tags = []
    for tag in split_tags(value):
        tag = replacements.get(tag, tag)
        if tag.lower() == "mock":
            continue
        tags.append(tag)
    return ",".join(merge_tags(tags))


def clean_report_title(value):
    title = str(value or "").strip()
    if "｜完整汇报材料" not in title:
        return title
    base = re.sub(r"(?:｜完整汇报材料)+$", "", title).strip()
    return f"{base or '未命名汇报'}｜完整汇报材料"


def normalize_timestamps(conn):
    changed = {}
    for table in ["assets", "uploads", "asset_history", "report_page_slots"]:
        columns = table_columns(conn, table)
        for column in ["created_at", "updated_at", "captured_at"]:
            if column not in columns:
                continue
            count = conn.execute(
                f"select count(*) from {table} where {column} > 0 and {column} < ?",
                (SECOND_TS_LIMIT,),
            ).fetchone()[0]
            if count:
                conn.execute(
                    f"update {table} set {column} = {column} * 1000 where {column} > 0 and {column} < ?",
                    (SECOND_TS_LIMIT,),
                )
            changed[f"{table}.{column}"] = count
    return changed


def normalize_categories_and_tags(conn):
    changed = 0
    rows = conn.execute("select id, asset_type, category, tags, title from assets").fetchall()
    for row in rows:
        category = row["category"]
        if row["asset_type"] == "report" and category != "report":
            category = "report"
        elif row["asset_type"] == "control" and category in {"mock", "storytelling"}:
            category = "page"
        tags = clean_tags(row["tags"])
        title = clean_report_title(row["title"]) if row["asset_type"] == "report" else row["title"]
        if category != row["category"] or tags != row["tags"] or title != row["title"]:
            conn.execute(
                "update assets set category = ?, tags = ?, title = ?, updated_at = ? where id = ?",
                (category, tags, title, now_ms(), row["id"]),
            )
            changed += 1

    if table_exists(conn, "asset_history"):
        rows = conn.execute("select id, asset_type, category, tags from asset_history").fetchall()
        for row in rows:
            category = row["category"]
            if row["asset_type"] == "report" and category != "report":
                category = "report"
            elif row["asset_type"] == "control" and category in {"mock", "storytelling"}:
                category = "page"
            tags = clean_tags(row["tags"])
            if category != row["category"] or tags != row["tags"]:
                conn.execute("update asset_history set category = ?, tags = ? where id = ?", (category, tags, row["id"]))
                changed += 1
    return changed


def logo_image_number(source_path):
    source = (source_path or "").replace("\\", "/")
    match = re.search(r"(?:^|/)(?:s\d+[-_])?logo[-_ ]?(\d+)\.(?:png|jpe?g|webp|svg)$", source, re.I)
    return match.group(1) if match else ""


def is_generic_logo_title(title):
    probe = str(title or "").strip().lower()
    if not probe:
        return True
    if re.fullmatch(r"image\d+", probe):
        return True
    if re.fullmatch(r"[a-f0-9]{8,12}[-_ ].*", probe):
        return True
    if re.fullmatch(r"s\d+[\s_-]+logo[\s_-]+\d+", probe):
        return True
    return any(word in probe for word in [" logo", "logo ", "mark", "品牌标识"])


def generic_logo_title(title, source_path, tags="", usage=""):
    text = " ".join([str(title or ""), str(source_path or ""), str(tags or ""), str(usage or "")]).lower()
    source = (source_path or "").replace("\\", "/")
    match = re.search(r"(?:^|/)s(\d+)[-_]logo[-_ ]?(\d+)\.(?:png|jpe?g|webp|svg)$", source, re.I)
    if match:
        page_no, logo_no = match.groups()
        if page_no == "6":
            return f"先进制造企业标识 {logo_no}"
        if page_no == "9":
            return f"制造业场景标识 {logo_no}"
        return f"企业标识 {logo_no}"
    if "feishu" in text or "飞书" in text or "lark" in text:
        return "飞书"
    return "品牌标识"


def logo_title_for(row):
    source = row["source_path"] or ""
    title = row["title"] or ""
    image_no = logo_image_number(source)
    if image_no in LOGO_TITLE_BY_IMAGE_NO:
        return LOGO_TITLE_BY_IMAGE_NO[image_no]
    text = " ".join([title, source]).lower()
    for keywords, company_name, subtag in LOGO_KEYWORD_RULES:
        if any(keyword.lower() in text for keyword in keywords):
            return company_name, subtag
    if is_generic_logo_title(title):
        return generic_logo_title(title, source, row["tags"], row["usage"]), "品牌标识"
    return title, ""


def normalize_logo_titles(conn):
    changed = 0
    rows = conn.execute(
        "select id, title, tags, usage, source_path from assets where asset_type = 'resource' and resource_kind = 'logo'"
    ).fetchall()
    for row in rows:
        new_title, subtag = logo_title_for(row)
        tags = [tag for tag in split_tags(clean_tags(row["tags"])) if tag != LEGACY_MOCK_TAG]
        seeded = ["企业logo"]
        if subtag:
            seeded.append(subtag)
        if subtag != "飞书logo":
            tags = [tag for tag in tags if tag != "飞书logo"]
        new_tags = ",".join(merge_tags(tags, seeded, ["可直接使用"]))
        if new_title != row["title"] or new_tags != row["tags"]:
            conn.execute(
                "update assets set title = ?, tags = ?, updated_at = ? where id = ?",
                (new_title, new_tags, now_ms(), row["id"]),
            )
            changed += 1
    return changed


def report_code_to_control_code(report_code, page_number):
    if report_code and report_code.startswith("RPT-"):
        stem = report_code.removeprefix("RPT-").rsplit("-", 1)[0]
        return f"CTRL-{stem}-{page_number:03d}"
    return f"CTRL-PAGE-{page_number:03d}"


def page_number_from_asset(row):
    values = " ".join([row["asset_code"] or "", row["title"] or "", row["source_path"] or "", row["tags"] or ""])
    legacy_pattern = rf"{re.escape(LEGACY_MOCK_CODE_PREFIX)}-(\d+)"
    for pattern in [legacy_pattern, r"slide[-_]?(\d+)", r"页码[:：]\s*0*(\d+)"]:
        match = re.search(pattern, values, re.I)
        if match:
            return int(match.group(1))
    return 0


def replace_references(conn, mapping):
    changed = 0
    text_tables = {
        "assets": ["usage", "tags", "snippet"],
        "asset_history": ["asset_code", "usage", "tags", "change_note"],
        "report_page_slots": ["task_key", "note"],
    }
    for table, columns in text_tables.items():
        existing = table_columns(conn, table)
        for column in columns:
            if column not in existing:
                continue
            for old, new in mapping.items():
                count = conn.execute(f"select count(*) from {table} where {column} like ?", (f"%{old}%",)).fetchone()[0]
                if count:
                    conn.execute(f"update {table} set {column} = replace({column}, ?, ?)", (old, new))
                    changed += count
    return changed


def migrate_legacy_control_codes(conn):
    rows = conn.execute(
        "select * from assets where asset_type = 'control' and asset_code like ? order by asset_code",
        (f"{LEGACY_MOCK_CODE_PREFIX}-%",),
    ).fetchall()
    mapping = {}
    for row in rows:
        page_no = page_number_from_asset(row)
        report = conn.execute(
            "select asset_code from assets where asset_type = 'report' and upload_id = ? order by created_at limit 1",
            (row["upload_id"],),
        ).fetchone()
        new_code = report_code_to_control_code(report["asset_code"] if report else "", page_no or len(mapping) + 1)
        exists = conn.execute("select 1 from assets where asset_code = ? and id <> ?", (new_code, row["id"])).fetchone()
        if exists:
            new_code = f"CTRL-PAGE-{len(mapping) + 1:03d}"
        mapping[row["asset_code"]] = new_code
        conn.execute("update assets set asset_code = ?, category = 'page', updated_at = ? where id = ?", (new_code, now_ms(), row["id"]))
    refs = replace_references(conn, mapping) if mapping else 0
    return {"controls": len(mapping), "references": refs, "mapping": mapping}


def normalize_report_titles(conn):
    changed = 0
    rows = conn.execute("select id, title from assets where asset_type = 'report'").fetchall()
    for row in rows:
        cleaned = clean_report_title(row["title"])
        if cleaned != row["title"]:
            conn.execute("update assets set title = ?, updated_at = ? where id = ?", (cleaned, now_ms(), row["id"]))
            changed += 1
    return changed


def normalize_control_versions(conn):
    rows = conn.execute(
        """
        select id
        from assets
        where asset_type = 'control'
          and source_type in ('report-material-sync', 'report-page')
          and (version_group <> id or version_no <> 1 or version_parent_id <> '')
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "update assets set version_group = id, version_no = 1, version_parent_id = '' where id = ?",
            (row["id"],),
        )
    return len(rows)


def repair_bad_version_parents(conn):
    rows = conn.execute(
        """
        select id
        from assets a
        where version_parent_id <> ''
          and not exists(select 1 from assets p where p.id = a.version_parent_id)
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "update assets set version_group = id, version_no = 1, version_parent_id = '' where id = ?",
            (row["id"],),
        )
    return len(rows)


def cleanup_orphan_relations(conn):
    orphan_slots = conn.execute(
        """
        select s.report_id, s.page_number
        from report_page_slots s
        left join assets r on r.id = s.report_id
        where r.id is null
        """
    ).fetchall()
    for row in orphan_slots:
        conn.execute("delete from report_page_slots where report_id = ? and page_number = ?", (row["report_id"], row["page_number"]))

    orphan_slot_controls = conn.execute(
        """
        select report_id, page_number
        from report_page_slots s
        where control_id <> ''
          and not exists(select 1 from assets a where a.id = s.control_id)
        """
    ).fetchall()
    for row in orphan_slot_controls:
        conn.execute(
            "update report_page_slots set control_id = '', status = 'planned' where report_id = ? and page_number = ?",
            (row["report_id"], row["page_number"]),
        )

    orphan_history = conn.execute(
        """
        select id, snapshot_path
        from asset_history h
        where not exists(select 1 from assets a where a.id = h.asset_id)
        """
    ).fetchall()
    for row in orphan_history:
        if row["snapshot_path"]:
            path = (EXTRACTED / row["snapshot_path"]).resolve()
            if is_path_within(path, EXTRACTED) and path.exists() and path.is_file():
                path.unlink()
        conn.execute("delete from asset_history where id = ?", (row["id"],))

    return {
        "orphanSlots": len(orphan_slots),
        "orphanSlotControls": len(orphan_slot_controls),
        "orphanHistory": len(orphan_history),
    }


def normalize_history_asset_codes(conn):
    rows = conn.execute(
        """
        select h.id, h.asset_code old_code, a.asset_code new_code
        from asset_history h
        join assets a on a.id = h.asset_id
        where h.asset_code <> a.asset_code
        """
    ).fetchall()
    for row in rows:
        conn.execute("update asset_history set asset_code = ? where id = ?", (row["new_code"], row["id"]))
    return len(rows)


def refresh_upload_counts(conn):
    changed = 0
    uploads = conn.execute("select id from uploads").fetchall()
    for row in uploads:
        upload_id = row["id"]
        extract_root = EXTRACTED / upload_id
        file_count = sum(1 for path in extract_root.rglob("*") if path.is_file()) if extract_root.exists() else 0
        asset_count = conn.execute("select count(*) from assets where upload_id = ?", (upload_id,)).fetchone()[0]
        conn.execute("update uploads set file_count = ?, asset_count = ? where id = ?", (file_count, asset_count, upload_id))
        changed += 1
    return changed


def normalize_preview_urls(conn):
    changed = 0
    stale = 0
    rows = conn.execute("select id, upload_id, source_path, preview_url from assets where upload_id <> '' and source_path <> ''").fetchall()
    for row in rows:
        expected = f"/extracted/{row['upload_id']}/{row['source_path']}"
        path = EXTRACTED / row["upload_id"] / row["source_path"]
        if not path.exists():
            stale += 1
            continue
        if row["preview_url"] != expected:
            conn.execute("update assets set preview_url = ?, updated_at = ? where id = ?", (expected, now_ms(), row["id"]))
            changed += 1
    return {"updated": changed, "staleFiles": stale}


def audit(conn):
    result = {}
    result["assets"] = conn.execute("select count(*) from assets").fetchone()[0]
    result["uploads"] = conn.execute("select count(*) from uploads").fetchone()[0]
    result["history"] = conn.execute("select count(*) from asset_history").fetchone()[0]
    result["duplicateCodes"] = [dict(row) for row in conn.execute(
        "select asset_code, count(*) count from assets where asset_code <> '' group by asset_code having count(*) > 1"
    ).fetchall()]
    result["rawLogoTitles"] = conn.execute(
        """
        select count(*)
        from assets
        where asset_type = 'resource'
          and resource_kind = 'logo'
          and (
            lower(title) glob 's[0-9]* logo *'
            or lower(title) like 's%-logo-%'
            or lower(title) like 'slide%logo%'
          )
        """
    ).fetchone()[0]
    result["legacyMockCodes"] = conn.execute(
        "select count(*) from assets where asset_code like ? or category = 'mock' or tags like ?",
        (f"{LEGACY_MOCK_CODE_PREFIX}-%", f"%{LEGACY_MOCK_TAG}%"),
    ).fetchone()[0]
    result["badVersionParents"] = conn.execute(
        """
        select count(*)
        from assets a
        where version_parent_id <> ''
          and not exists(select 1 from assets p where p.id = a.version_parent_id)
        """
    ).fetchone()[0]
    result["orphanHistory"] = conn.execute(
        "select count(*) from asset_history h where not exists(select 1 from assets a where a.id = h.asset_id)"
    ).fetchone()[0]
    return result


def govern():
    with connect() as conn:
        before = audit(conn)
        changes = {
            "timestamps": normalize_timestamps(conn),
            "categoriesAndTags": normalize_categories_and_tags(conn),
            "reportTitles": normalize_report_titles(conn),
            "legacyControlCodes": migrate_legacy_control_codes(conn),
            "logoTitles": normalize_logo_titles(conn),
            "previewUrls": normalize_preview_urls(conn),
            "controlVersions": normalize_control_versions(conn),
            "badVersionParents": repair_bad_version_parents(conn),
            "orphans": cleanup_orphan_relations(conn),
            "historyAssetCodes": normalize_history_asset_codes(conn),
            "uploadCounts": refresh_upload_counts(conn),
        }
        after = audit(conn)
    return {"before": before, "changes": changes, "after": after}


if __name__ == "__main__":
    print(json.dumps(govern(), ensure_ascii=False, indent=2))
