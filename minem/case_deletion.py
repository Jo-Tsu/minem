"""Atomic deletion for manifest-backed case groups."""
from __future__ import annotations

from minem.asset_deletion import (
    AssetDeletionError,
    apply_asset_deletion_plan,
    build_asset_deletion_plan,
)


def _control_codes(controls):
    codes = []
    seen = set()
    for control in controls or []:
        code = str(control.get("code") if isinstance(control, dict) else control or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def build_case_group_deletion_plan(conn, case_code, controls):
    """Preflight every case page before any record is changed."""
    code = str(case_code or "").strip()
    if not code:
        raise AssetDeletionError("缺少案例组编号", status=400)

    page_codes = _control_codes(controls)
    if not page_codes:
        raise AssetDeletionError("案例组没有可删除的页面素材", status=409)

    page_plans = []
    missing_page_codes = []
    blocked_pages = []
    planned_target_ids = set()

    for page_code in page_codes:
        row = conn.execute(
            """
            select id
            from assets
            where asset_code = ? and asset_type = 'control' and version_parent_id = ''
            order by updated_at desc, created_at desc, id
            limit 1
            """,
            (page_code,),
        ).fetchone()
        if not row:
            missing_page_codes.append(page_code)
            continue
        try:
            plan = build_asset_deletion_plan(conn, row["id"])
        except AssetDeletionError as error:
            if error.status != 409:
                raise
            blocked_pages.append({
                "code": page_code,
                "references": error.details.get("references", []),
                "referenceCodes": error.details.get("referenceCodes", []),
            })
            continue

        target_ids = set(plan["target_ids"])
        overlap = target_ids & planned_target_ids
        if overlap:
            if target_ids <= planned_target_ids:
                continue
            raise AssetDeletionError(
                "案例页面版本关系异常，请先完成数据走查后再删除",
                status=409,
                details={"caseCode": code, "overlappingAssetIds": sorted(overlap)},
            )
        planned_target_ids.update(target_ids)
        page_plans.append(plan)

    if blocked_pages:
        referenced_reports = {
            reference.get("id"): reference
            for page in blocked_pages
            for reference in page["references"]
            if reference.get("id")
        }
        raise AssetDeletionError(
            f"案例中有 {len(blocked_pages)} 个页面仍被汇报引用，请先从对应汇报中移出",
            status=409,
            details={
                "caseCode": code,
                "blockedPages": blocked_pages,
                "references": list(referenced_reports.values()),
                "referenceCodes": sorted({
                    reference_code
                    for page in blocked_pages
                    for reference_code in page["referenceCodes"]
                }),
            },
        )

    if not page_plans:
        raise AssetDeletionError(
            "案例页面已经不存在，请刷新案例列表",
            status=409,
            details={"caseCode": code, "missingPageCodes": missing_page_codes},
        )

    return {
        "case_code": code,
        "page_codes": page_codes,
        "page_plans": page_plans,
        "missing_page_codes": missing_page_codes,
        "target_ids": sorted(planned_target_ids),
    }


def apply_case_group_deletion_plan(conn, plan, *, timestamp):
    """Delete all planned page/version records in the caller's transaction."""
    results = [
        apply_asset_deletion_plan(conn, page_plan, timestamp=timestamp)
        for page_plan in plan["page_plans"]
    ]
    return {
        **plan,
        "results": results,
        "deleted_page_count": len(plan["page_plans"]),
        "deleted_asset_count": sum(result["deleted_count"] for result in results),
    }
