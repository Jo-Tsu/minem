#!/usr/bin/env python3
"""Read-only MineM core data and preview-link regression checks.

Usage:
  python3 scripts/run_core_tests.py --suite data
  python3 scripts/run_core_tests.py --suite click
  python3 scripts/run_core_tests.py --suite all

The script never imports files, regenerates thumbnails, merges versions, or
modifies the production SQLite database. It returns non-zero for blockers.
"""

from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPException
import json
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "materials.db"
DEFAULT_BASE_URL = "http://127.0.0.1:8790"


class Reporter:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, case: str, status: str, message: str, **details: object) -> None:
        self.items.append({"case": case, "status": status, "message": message, "details": details})

    def fail(self, case: str, message: str, **details: object) -> None:
        self.add(case, "failed", message, **details)

    def passed(self, case: str, message: str, **details: object) -> None:
        self.add(case, "passed", message, **details)

    def warning(self, case: str, message: str, **details: object) -> None:
        self.add(case, "warning", message, **details)

    def summary(self) -> dict:
        counts = defaultdict(int)
        for item in self.items:
            counts[item["status"]] += 1
        return {"passed": counts["passed"], "failed": counts["failed"], "warning": counts["warning"], "total": len(self.items)}


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def preview_file(root: Path, preview_url: str) -> Path | None:
    path = urlparse(preview_url or "").path
    if not path.startswith("/extracted/"):
        return None
    candidate = (root / path.lstrip("/")).resolve()
    extracted = (root / "extracted").resolve()
    return candidate if candidate.is_relative_to(extracted) else None


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_data_checks(conn: sqlite3.Connection, reporter: Reporter) -> None:
    rows = conn.execute("select * from assets order by id").fetchall()
    reports = [row for row in rows if row["asset_type"] == "report"]
    controls = [row for row in rows if row["asset_type"] == "control"]
    resources = [row for row in rows if row["asset_type"] == "resource"]
    reporter.passed("DATA-000", "资产表可读取", assets=len(rows), reports=len(reports), controls=len(controls), resources=len(resources))

    prefix_issues = []
    misplaced_controls = []
    missing_previews = []
    blank_previews = []
    by_hash: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    by_file_hash: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        code = row["asset_code"] or ""
        asset_type = row["asset_type"]
        if code.startswith("RPT-") and asset_type != "report":
            prefix_issues.append((code, asset_type))
        if code.startswith("CTRL-") and asset_type != "control":
            prefix_issues.append((code, asset_type))
        if code.startswith("RES-") and asset_type != "resource":
            prefix_issues.append((code, asset_type))
        if asset_type == "report" and (code.startswith("CTRL-") or "_minem_pages/" in (row["source_path"] or "")):
            misplaced_controls.append((code, row["source_path"]))
        if asset_type in {"report", "control", "resource"}:
            if not row["preview_url"]:
                blank_previews.append(code)
            else:
                target = preview_file(ROOT, row["preview_url"])
                public_report_entry = asset_type == "report" and (row["preview_url"] or "").startswith("/reports/")
                if not public_report_entry and (not target or not target.is_file() or target.stat().st_size == 0):
                    missing_previews.append((code, row["preview_url"]))
                elif target:
                    by_file_hash[(asset_type, file_sha1(target))].append(row)
        if row["source_hash"]:
            by_hash[(asset_type, row["source_hash"])].append(row)

    if prefix_issues:
        reporter.fail("DATA-001", "编号与资产类型不匹配", issues=prefix_issues[:30], total=len(prefix_issues))
    else:
        reporter.passed("DATA-001", "编号与资产类型匹配")
    if misplaced_controls:
        reporter.fail("DATA-001A", "页面素材混入汇报列表", issues=misplaced_controls[:30], total=len(misplaced_controls))
    else:
        reporter.passed("DATA-001A", "汇报列表未发现页面素材")
    if blank_previews or missing_previews:
        reporter.fail("DATA-002", "存在空白或缺失预览", blank=blank_previews[:30], missing=missing_previews[:30], total=len(blank_previews) + len(missing_previews))
    else:
        reporter.passed("DATA-002", "所有活跃素材预览文件存在且非空")

    governance = ROOT / "scripts" / "govern_material_data.py"
    governance_result = subprocess.run(
        [sys.executable, str(governance)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        governance_payload = json.loads(governance_result.stdout)
    except json.JSONDecodeError:
        governance_payload = {}
    governance_issues = {
        key: governance_payload.get(key)
        for key in ("prefixBad", "missingFiles", "htmlRefIssues")
        if governance_payload.get(key)
    }
    if governance_result.returncode or governance_payload.get("apply") is not False or governance_issues:
        reporter.fail(
            "DATA-002A",
            "只读素材依赖审计失败或检测到断链",
            returnCode=governance_result.returncode,
            issues=governance_issues,
            output=(governance_result.stdout + governance_result.stderr)[-2000:],
        )
    else:
        reporter.passed("DATA-002A", "素材依赖审计为只读模式，且无本地断链或分类异常")

    no_slots = []
    slot_duplicates = []
    for report in reports:
        slots = conn.execute("select page_number, control_id from report_page_slots where report_id = ? order by page_number", (report["id"],)).fetchall()
        if not slots:
            no_slots.append(report["asset_code"])
            continue
        pages = [slot["page_number"] for slot in slots]
        control_ids = [slot["control_id"] for slot in slots]
        if len(pages) != len(set(pages)) or len(control_ids) != len(set(control_ids)) or any(not control_id for control_id in control_ids):
            slot_duplicates.append(report["asset_code"])
    if no_slots or slot_duplicates:
        reporter.fail("DATA-004", "汇报页面槽不完整", missingSlots=no_slots, invalidSlots=slot_duplicates)
    else:
        reporter.passed("DATA-004", "所有汇报具备完整且唯一的页面槽")

    orphan_slots = conn.execute(
        """
        select s.report_id, s.page_number, s.control_id from report_page_slots s
        left join assets r on r.id = s.report_id and r.asset_type = 'report'
        left join assets c on c.id = s.control_id and c.asset_type = 'control'
        where r.id is null or c.id is null
        """
    ).fetchall()
    if orphan_slots:
        reporter.fail("DATA-005", "存在孤儿汇报页面引用", issues=[dict(row) for row in orphan_slots[:30]], total=len(orphan_slots))
    else:
        reporter.passed("DATA-005", "汇报页面引用完整")

    exact_duplicates = [items for items in by_hash.values() if len(items) > 1]
    ungrouped_file_duplicates = [
        items for items in by_file_hash.values()
        if len(items) > 1 and len({item["version_group"] or item["id"] for item in items}) > 1
    ]
    if ungrouped_file_duplicates:
        reporter.fail(
            "DATA-006",
            "存在未归入同一版本组的完全相同素材",
            groups=[[(item["asset_code"], item["upload_id"], item["version_group"]) for item in group] for group in ungrouped_file_duplicates[:20]],
            total=len(ungrouped_file_duplicates),
        )
    elif exact_duplicates:
        reporter.warning("DATA-006", "数据库来源哈希存在重复，但文件版本关系已正确归并", total=len(exact_duplicates))
    else:
        reporter.passed("DATA-006", "完全相同素材均已归入同一版本组")

    canvas_test = ROOT / "scripts" / "test_report_canvas_normalization.py"
    result = subprocess.run([sys.executable, str(canvas_test)], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode:
        reporter.fail("DATA-014", "汇报尺寸适配版本回归测试失败", output=(result.stdout + result.stderr)[-2000:])
    else:
        reporter.passed("DATA-014", "汇报尺寸适配版本可创建、复用且保留原页面素材")

    export_columns = {row["name"] for row in conn.execute("pragma table_info(report_export_tasks)").fetchall()}
    required_export_columns = {"id", "report_id", "format", "status", "progress", "page_count", "output_path", "error", "updated_at"}
    if not required_export_columns.issubset(export_columns):
        reporter.fail("DATA-016", "完整汇报导出任务表不完整", missing=sorted(required_export_columns - export_columns))
    else:
        invalid_exports = conn.execute(
            "select id, format, status from report_export_tasks where format not in ('html', 'pdf') or status not in ('queued', 'running', 'completed', 'failed')"
        ).fetchall()
        if invalid_exports:
            reporter.fail("DATA-016", "存在无效的完整汇报导出任务", tasks=[dict(row) for row in invalid_exports[:20]])
        else:
            reporter.passed("DATA-016", "完整汇报导出任务结构与状态合法")

    legacy_asset_tags = conn.execute(
        "select asset_code, tags from assets where trim(coalesce(tags, '')) <> '' limit 30"
    ).fetchall()
    legacy_history_tags = conn.execute(
        "select asset_code, tags from asset_history where trim(coalesce(tags, '')) <> '' limit 30"
    ).fetchall()
    legacy_storyline_tags = conn.execute(
        "select code, tags from report_storyline_collections where trim(coalesce(tags, '')) <> '' limit 30"
    ).fetchall()
    if legacy_asset_tags or legacy_history_tags or legacy_storyline_tags:
        reporter.fail(
            "DATA-017",
            "旧标签重置期仍存在标签数据",
            assets=[dict(row) for row in legacy_asset_tags],
            history=[dict(row) for row in legacy_history_tags],
            storylines=[dict(row) for row in legacy_storyline_tags],
        )
    else:
        reporter.passed("DATA-017", "旧标签已清空，未发现自动回填")

    legacy_upload_paths = conn.execute(
        """
        select id, stored_path, extract_path from uploads
        where stored_path like '%material-library%'
           or extract_path like '%material-library%'
           or extract_path like '/%'
        """
    ).fetchall()
    zero_asset_uploads = conn.execute(
        """
        select u.id from uploads u
        left join assets a on a.upload_id = u.id
        group by u.id
        having count(a.id) = 0 and coalesce(u.asset_count, 0) = 0
        """
    ).fetchall()
    duplicate_upload_hashes = conn.execute(
        """
        select content_hash, count(*) count from uploads
        where content_hash <> ''
        group by content_hash
        having count(*) > 1
        """
    ).fetchall()
    if legacy_upload_paths or zero_asset_uploads or duplicate_upload_hashes:
        reporter.fail(
            "DATA-020",
            "导入批次仍含旧绝对路径、零产物记录或重复上传指纹",
            legacyPaths=[dict(row) for row in legacy_upload_paths[:30]],
            zeroAssetUploads=[row["id"] for row in zero_asset_uploads[:30]],
            duplicateContentHashes=[dict(row) for row in duplicate_upload_hashes[:30]],
        )
    else:
        reporter.passed("DATA-020", "导入批次路径可迁移，且不存在零产物垃圾记录")

    backup_files = sorted((ROOT / "data").glob("materials.db.before-*"))
    if backup_files:
        reporter.fail("DATA-021", "项目运行目录仍含历史数据库副本", files=[path.name for path in backup_files[:30]])
    else:
        reporter.passed("DATA-021", "项目运行目录未保留历史数据库副本")

    visible_assets = conn.execute("select count(*) from assets where version_parent_id = ''").fetchone()[0]
    version_assets = conn.execute("select count(*) from assets where version_parent_id <> ''").fetchone()[0]
    if visible_assets + version_assets != len(rows):
        reporter.fail("DATA-022", "可见素材与版本素材统计不能还原原始记录数")
    else:
        reporter.passed("DATA-022", "可见素材、版本素材与原始记录数口径一致", visible=visible_assets, versions=version_assets, raw=len(rows))


def request_status(url: str, timeout: float) -> tuple[int, str]:
    try:
        with urlopen(Request(url, headers={"User-Agent": "MineM-Core-Test/1.0"}), timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            response.read(1024)
            return response.status, content_type
    except HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "")
    except (URLError, OSError, HTTPException):
        return 0, ""


def request_json(url: str, timeout: float) -> tuple[int, dict]:
    try:
        with urlopen(Request(url, headers={"User-Agent": "MineM-Core-Test/1.0"}), timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, HTTPException, json.JSONDecodeError):
        return 0, {}


def request_text(url: str, timeout: float) -> tuple[int, str]:
    try:
        with urlopen(Request(url, headers={"User-Agent": "MineM-Core-Test/1.0"}), timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "ignore")
    except (HTTPError, URLError, OSError, HTTPException):
        return 0, ""


def encode_url_path(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%:@"), parts.query, parts.fragment))


def run_click_checks(conn: sqlite3.Connection, reporter: Reporter, base_url: str, timeout: float) -> None:
    release_manifest = json.loads((ROOT / "product-version.json").read_text(encoding="utf-8"))
    version_status, release_payload = request_json(urljoin(base_url, "/api/version"), timeout)
    release = release_payload.get("release") or {}
    if version_status != 200 or release.get("version") != release_manifest.get("version"):
        reporter.fail(
            "DATA-015",
            "服务发布版本与产品版本清单不一致",
            expected=release_manifest.get("version"),
            actual=release.get("version"),
            httpStatus=version_status,
        )
    else:
        reporter.passed("DATA-015", "服务发布版本与产品版本清单一致", version=release.get("version"), channel=release.get("channel"))

    source_status, source_payload = request_json(urljoin(base_url, "/api/import-sources"), timeout)
    import_roots = source_payload.get("roots") or []
    if source_status != 200 or not isinstance(source_payload.get("roots"), list):
        reporter.fail("CLICK-016", "导入来源接口结构无效", httpStatus=source_status, payload=source_payload)
    elif import_roots:
        reporter.passed("CLICK-016", "服务使用用户显式配置的素材来源", roots=import_roots)
    else:
        reporter.passed("CLICK-016", "公开默认配置未扫描任何外部素材来源")

    graph_status, _ = request_status(urljoin(base_url, "/api/graph"), timeout)
    if graph_status != 404:
        reporter.fail("CLICK-018", "已删除的图谱接口仍可访问", httpStatus=graph_status)
    else:
        reporter.passed("CLICK-018", "图谱接口已下线且返回 404")

    case_status, case_payload = request_json(urljoin(base_url, "/api/case-groups"), timeout)
    case_groups = case_payload.get("caseGroups") or []
    known_controls = {
        row["asset_code"]
        for row in conn.execute(
            "select asset_code from assets where asset_type = 'control' and version_parent_id = ''"
        ).fetchall()
    }
    case_codes = [str(group.get("code") or "") for group in case_groups]
    case_issues = []
    case_links = []
    for group in case_groups:
        controls = group.get("controls") or []
        if not group.get("reportUrl") or not controls:
            case_issues.append({"group": group.get("code"), "reason": "缺少组预览或页面素材"})
        else:
            case_links.append((str(group.get("code") or ""), str(group.get("reportUrl") or "")))
        for control in controls:
            if control.get("code") not in known_controls or not control.get("controlUrl"):
                case_issues.append({"group": group.get("code"), "control": control.get("code"), "reason": "页面未入库或无预览"})
    link_issues = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(case_links)))) as executor:
        future_map = {
            executor.submit(request_status, encode_url_path(urljoin(base_url, url)), timeout): (code, url)
            for code, url in case_links
        }
        for future in as_completed(future_map):
            code, url = future_map[future]
            status, content_type = future.result()
            if status != 200 or "text/html" not in content_type:
                link_issues.append({"group": code, "url": url, "status": status, "contentType": content_type})
    if case_status != 200 or not case_groups or len(case_codes) != len(set(case_codes)) or case_issues or link_issues:
        reporter.fail(
            "CLICK-017",
            "案例清单含重复、未入库页面或不可访问入口",
            httpStatus=case_status,
            groups=len(case_groups),
            issues=(case_issues + link_issues)[:30],
        )
    else:
        reporter.passed("CLICK-017", "案例清单来自真实入库页面，组入口均可访问", groups=len(case_groups))

    rows = conn.execute(
        "select * from assets where asset_type in ('report','control','resource') and preview_url <> '' order by updated_at desc"
    ).fetchall()
    selected: list[sqlite3.Row] = []
    seen = set()
    for row in rows:
        if row["asset_type"] not in seen:
            selected.append(row)
            seen.add(row["asset_type"])
    if len(seen) < 3:
        reporter.fail("CLICK-001", "缺少可用于点击回归的素材类型", found=sorted(seen))
        return

    checks: list[tuple[str, str, str, str]] = []
    for row in selected:
        asset_url = urljoin(base_url, f"/api/assets/{quote(row['id'])}")
        preview_url = encode_url_path(urljoin(base_url, row["preview_url"]))
        checks.extend([
            ("CLICK-001", row["asset_code"], asset_url, "json"),
            ("CLICK-002", row["asset_code"], preview_url, "html" if row["media_kind"] == "html" else "media"),
        ])
        if row["asset_type"] == "report":
            checks.append(("CLICK-004", row["asset_code"], urljoin(base_url, f"/api/reports/{quote(row['id'])}/arrangement/viewer"), "html"))
            checks.append(("CLICK-005", row["asset_code"], urljoin(base_url, f"/api/reports/{quote(row['id'])}/arrangement"), "json"))

    failures = []
    with ThreadPoolExecutor(max_workers=min(8, len(checks))) as executor:
        future_map = {executor.submit(request_status, url, timeout): (case, code, url, expected) for case, code, url, expected in checks}
        for future in as_completed(future_map):
            case, code, url, expected = future_map[future]
            status, content_type = future.result()
            if status != 200:
                failures.append({"case": case, "assetCode": code, "url": url, "status": status})
            elif expected == "html" and "text/html" not in content_type:
                failures.append({"case": case, "assetCode": code, "url": url, "status": status, "contentType": content_type})
            elif expected == "json" and "application/json" not in content_type:
                failures.append({"case": case, "assetCode": code, "url": url, "status": status, "contentType": content_type})
    if failures:
        reporter.fail("CLICK", "存在无法打开的详情、当前链接或汇报查看器", failures=failures)
    else:
        reporter.passed("CLICK", "详情、当前链接、汇报查看器与编排接口均可点击访问", checked=len(checks))

    ordering_issues = []
    for asset_type in ("report", "control", "resource"):
        url = urljoin(base_url, f"/api/assets?view=list&type={asset_type}&page=1&page_size=30")
        status, payload = request_json(url, timeout)
        assets = payload.get("assets") or []
        pagination = payload.get("pagination") or {}
        activities = [int(item.get("activity_at") or item.get("updated_at") or 0) for item in assets]
        if status != 200 or pagination.get("pageSize") != 30 or len(assets) > 30 or any(left < right for left, right in zip(activities, activities[1:])):
            ordering_issues.append({"type": asset_type, "status": status, "pageSize": pagination.get("pageSize"), "count": len(assets), "activity": activities[:8]})
    if ordering_issues:
        reporter.fail("DATA-012", "素材列表未按最近活动倒序或默认分页不是 30 条", issues=ordering_issues)
    else:
        reporter.passed("DATA-012", "汇报、页面、资源均按最近活动倒序，默认每批 30 条")

    page_count_issues = []
    for report_row in conn.execute("select id, asset_code from assets where asset_type = 'report' and version_parent_id = '' order by asset_code").fetchall():
        asset_status, asset_payload = request_json(urljoin(base_url, f"/api/assets/{quote(report_row['id'])}"), timeout)
        arrangement_status, arrangement_payload = request_json(urljoin(base_url, f"/api/reports/{quote(report_row['id'])}/arrangement"), timeout)
        visible_count = len([page for page in arrangement_payload.get("pages", []) if not page.get("hidden")])
        actual_count = (asset_payload.get("asset") or {}).get("displayPageCount")
        if asset_status != 200 or arrangement_status != 200 or actual_count != visible_count:
            page_count_issues.append({
                "assetCode": report_row["asset_code"],
                "assetStatus": asset_status,
                "arrangementStatus": arrangement_status,
                "displayPageCount": actual_count,
                "visiblePageCount": visible_count,
            })
    if page_count_issues:
        reporter.fail("DATA-004A", "汇报卡片页数与已确认编排的可见页面数不一致", issues=page_count_issues)
    else:
        reporter.passed("DATA-004A", "汇报卡片页数与已确认编排的可见页面数一致")

    layout_issues = []
    report = next((row for row in selected if row["asset_type"] == "report"), None)
    control = next((row for row in selected if row["asset_type"] == "control" and row["media_kind"] == "html"), None)
    if report:
        status, body = request_text(urljoin(base_url, report["preview_url"]), timeout)
        if (
            status != 200
            or "updateDeckScale" not in body
            or "width: 1920px" not in body
            or "height: 1080px" not in body
            or "fullscreen-page" not in body
            or "requestFullscreen" not in body
        ):
            layout_issues.append({"assetCode": report["asset_code"], "surface": "public-report", "status": status})
    if control:
        separator = "&" if "?" in control["preview_url"] else "?"
        status, body = request_text(urljoin(base_url, f"{control['preview_url']}{separator}embed=1"), timeout)
        if status != 200 or "minem-embedded-preview-style" not in body or "--fs-scale: 1" not in body:
            layout_issues.append({"assetCode": control["asset_code"], "surface": "embedded-page", "status": status})
        status, body = request_text(urljoin(base_url, control["preview_url"]), timeout)
        if status != 200 or "updateDeckScale" not in body or "width: 1920px" not in body or "fullscreen-page" not in body or "requestFullscreen" not in body:
            layout_issues.append({"assetCode": control["asset_code"], "surface": "direct-page", "status": status})
    if layout_issues:
        reporter.fail("CLICK-011", "预览画布未应用统一等比适配", issues=layout_issues)
    else:
        reporter.passed("CLICK-011", "公开汇报与嵌入页面均应用统一 1920×1080 等比画布，并提供全屏入口")

    versioned = conn.execute(
        """
        select primary_asset.*
        from assets primary_asset
        where primary_asset.version_parent_id = ''
          and (select count(*) from assets version where version.version_group = primary_asset.version_group) > 1
        order by primary_asset.updated_at desc
        limit 1
        """
    ).fetchone()
    if versioned:
        status, payload = request_json(urljoin(base_url, f"/api/assets/{quote(versioned['id'])}/versions"), timeout)
        versions = payload.get("versions") or []
        ids = {item.get("id") for item in versions}
        ordered = [int(item.get("version_no") or 0) for item in versions]
        if status != 200 or len(versions) < 2 or versioned["id"] not in ids or ordered != sorted(ordered, reverse=True):
            reporter.fail("CLICK-015", "详情版本侧栏接口未返回完整且有序的历史版本", assetCode=versioned["asset_code"], httpStatus=status, versions=versions[:5])
        else:
            reporter.passed("CLICK-015", "详情版本侧栏可读取全部历史版本并按最新版本优先展示", assetCode=versioned["asset_code"], versions=len(versions))
    else:
        reporter.warning("CLICK-015", "当前数据没有可用于版本侧栏回归的多版本素材")

    search_control = conn.execute(
        """
        select * from assets
        where asset_type = 'control' and version_parent_id = '' and source_path <> ''
        order by updated_at desc
        limit 1
        """
    ).fetchone()
    search_issues = []
    if search_control:
        source_link = urljoin(base_url, search_control["preview_url"])
        for query, label in ((search_control["asset_code"], "编号"), (source_link, "链接")):
            status, payload = request_json(
                urljoin(base_url, f"/api/assets?view=list&type=control&page=1&page_size=30&q={quote(query, safe='')}"),
                timeout,
            )
            result_ids = {item.get("id") for item in payload.get("assets") or []}
            if status != 200 or search_control["id"] not in result_ids:
                search_issues.append({"queryType": label, "assetCode": search_control["asset_code"], "status": status})
    if search_issues:
        reporter.fail("DATA-013", "页面编号或链接搜索未命中对应素材", issues=search_issues)
    else:
        reporter.passed("DATA-013", "页面素材可通过编号和来源链接搜索定位")

    export_status, export_type = request_status(urljoin(base_url, "/api/report-exports/not-a-real-task"), timeout)
    if export_status != 404 or "application/json" not in export_type:
        reporter.fail("CLICK-013", "完整汇报导出任务查询接口不可用", task_status=export_status, contentType=export_type)
    else:
        reporter.passed("CLICK-013", "完整汇报导出任务查询接口可访问并返回标准错误")


def run_full_link_checks(conn: sqlite3.Connection, reporter: Reporter, base_url: str, timeout: float) -> None:
    rows = conn.execute(
        """
        select id, asset_code, asset_type, media_kind, preview_url
        from assets
        where version_parent_id = '' and preview_url <> ''
        order by asset_type, asset_code, id
        """
    ).fetchall()
    checks: list[tuple[str, str, str]] = []
    for row in rows:
        code = row["asset_code"] or row["id"]
        checks.append((code, "detail", f"{base_url}/api/assets/{quote(row['id'])}"))
        checks.append((code, "preview", encode_url_path(urljoin(base_url, row["preview_url"]))))
        if row["asset_type"] == "report":
            checks.append((code, "viewer", f"{base_url}/api/reports/{quote(row['id'])}/arrangement/viewer"))
            checks.append((code, "arrangement", f"{base_url}/api/reports/{quote(row['id'])}/arrangement"))

    failures = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(request_status, url, timeout): (code, surface) for code, surface, url in checks}
        for future in as_completed(future_map):
            code, surface = future_map[future]
            status, content_type = future.result()
            expected_json = surface in {"detail", "arrangement"}
            if status != 200 or (expected_json and "application/json" not in content_type):
                failures.append({"assetCode": code, "surface": surface, "status": status, "contentType": content_type})
    if failures:
        reporter.fail("CLICK-014", "全量素材详情、预览或汇报编排链接不可访问", failures=failures[:100], total=len(failures))
    else:
        reporter.passed("CLICK-014", "全量主素材详情、预览与汇报编排链接均可访问", assets=len(rows), checked=len(checks))


def write_report(payload: dict, output: Path | None) -> Path:
    target = output or ROOT / "artifacts" / "test-reports" / f"core-{int(time.time())}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only MineM core data and click-link tests.")
    parser.add_argument("--suite", choices=["data", "click", "all"], default="all")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    parser.add_argument("--full", action="store_true", help="Check every primary material detail and preview link, not only representative samples.")
    args = parser.parse_args()

    reporter = Reporter()
    started = time.time()
    try:
        with connect(args.db) as conn:
            if args.suite in {"data", "all"}:
                run_data_checks(conn, reporter)
            if args.suite in {"click", "all"}:
                run_click_checks(conn, reporter, args.base_url.rstrip("/"), args.timeout)
                if args.full:
                    run_full_link_checks(conn, reporter, args.base_url.rstrip("/"), args.timeout)
    except Exception as exc:  # Keep a report for test harness failures too.
        reporter.fail("HARNESS", str(exc))
    payload = {"suite": args.suite, "startedAt": int(started * 1000), "durationMs": int((time.time() - started) * 1000), "summary": reporter.summary(), "results": reporter.items}
    output = write_report(payload, args.json_out)
    print(json.dumps({"summary": payload["summary"], "report": str(output)}, ensure_ascii=False))
    has_failure = payload["summary"]["failed"] > 0 or (args.strict and payload["summary"]["warning"] > 0)
    return 1 if has_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
