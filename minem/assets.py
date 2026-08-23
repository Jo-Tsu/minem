from urllib.parse import parse_qs, unquote, urlparse


DEFAULT_ASSET_PAGE_SIZE = 30
MAX_ASSET_PAGE_SIZE = 200


def asset_search_terms(search):
    """Expand a pasted asset URL into the identifiers stored by MineM."""
    raw = str(search or "").strip()
    if not raw:
        return []
    parsed = urlparse(raw)
    candidates = [raw]
    if parsed.path:
        candidates.append(unquote(parsed.path))
    for values in (parse_qs(parsed.query), parse_qs(parsed.fragment)):
        for key, entries in values.items():
            if key.lower() in {"page", "id", "code", "asset", "asset_id", "q"}:
                candidates.extend(unquote(value).strip() for value in entries)
    if parsed.fragment and "=" not in parsed.fragment:
        candidates.append(unquote(parsed.fragment).strip())
    return list(dict.fromkeys(item for item in candidates if item))


ASSET_ACTIVITY_CTE = """
with version_activity as (
  select coalesce(nullif(version_group, ''), id) as version_group,
         max(updated_at) as updated_at
  from assets
  group by coalesce(nullif(version_group, ''), id)
), slot_activity as (
  select coalesce(nullif(control.version_group, ''), control.id) as version_group,
         max(slot.updated_at) as updated_at
  from report_page_slots slot
  join assets control on control.id = slot.control_id
  group by coalesce(nullif(control.version_group, ''), control.id)
), candidate_activity as (
  select coalesce(nullif(control.version_group, ''), control.id) as version_group,
         max(candidate.updated_at) as updated_at
  from report_page_candidates candidate
  join assets control on control.id = candidate.control_id
  group by coalesce(nullif(control.version_group, ''), control.id)
)
"""


ASSET_ACTIVITY_SQL = """
max(
  assets.updated_at,
  assets.created_at,
  coalesce(version_activity.updated_at, 0),
  case when assets.asset_type = 'control' then coalesce(slot_activity.updated_at, 0) else 0 end,
  case when assets.asset_type = 'control' then coalesce(candidate_activity.updated_at, 0) else 0 end
)
"""


def parse_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def parse_pagination(query):
    requested = "page" in query or "page_size" in query or "limit" in query
    if not requested:
        return None
    page = parse_int(query.get("page", ["1"])[0], 1, minimum=1)
    page_size_raw = query.get("page_size", query.get("limit", [str(DEFAULT_ASSET_PAGE_SIZE)]))[0]
    page_size = parse_int(page_size_raw, DEFAULT_ASSET_PAGE_SIZE, minimum=1, maximum=MAX_ASSET_PAGE_SIZE)
    return page, page_size


def list_assets_response(
    conn,
    query,
    *,
    add_version_counts,
    pipeline_summary,
    categories,
    asset_types,
    resource_kinds,
    page_roles=None,
    tag_taxonomy,
):
    category = query.get("category", ["all"])[0]
    asset_type = query.get("type", ["all"])[0]
    resource_kind = query.get("resource_kind", ["all"])[0]
    search = query.get("q", [""])[0].strip()
    include_versions = query.get("include_versions", ["0"])[0] == "1"
    view = query.get("view", ["full"])[0]
    list_view = view == "list"
    params = []
    where = []

    if asset_type != "all":
        where.append("asset_type = ?")
        params.append(asset_type)
    if category != "all":
        where.append("category = ?")
        params.append(category)
    if resource_kind != "all":
        where.append("asset_type = 'resource' and resource_kind = ?")
        params.append(resource_kind)
    page_role = query.get("page_role", ["all"])[0]
    if page_role != "all":
        where.append("asset_type = 'control' and page_role = ?")
        params.append(page_role)
    if search:
        search_terms = asset_search_terms(search)
        match_fields = "asset_code like ? or title like ? or usage like ? or tags like ? or source_path like ? or preview_url like ? or upload_id like ?"
        match_clause = " or ".join(f"({match_fields})" for _ in search_terms)
        match_params = []
        for term in search_terms:
            like = f"%{term}%"
            match_params.extend([like, like, like, like, like, like, like])
        if include_versions:
            where.append(f"({match_clause})")
            params.extend(match_params)
        else:
            sub_match_fields = "matched.asset_code like ? or matched.title like ? or matched.usage like ? or matched.tags like ? or matched.source_path like ? or matched.preview_url like ? or matched.upload_id like ?"
            sub_match_clause = " or ".join(f"({sub_match_fields})" for _ in search_terms)
            where.append(
                f"""
                coalesce(nullif(assets.version_group, ''), assets.id) in (
                  select coalesce(nullif(matched.version_group, ''), matched.id)
                  from assets matched
                  where ({sub_match_clause})
                )
                """
            )
            params.extend(match_params)
    if not include_versions:
        where.append("version_parent_id = ''")

    sql = f"""{ASSET_ACTIVITY_CTE}
        select assets.*, {ASSET_ACTIVITY_SQL} as activity_at
        from assets
        left join version_activity
          on version_activity.version_group = coalesce(nullif(assets.version_group, ''), assets.id)
        left join slot_activity
          on slot_activity.version_group = coalesce(nullif(assets.version_group, ''), assets.id)
        left join candidate_activity
          on candidate_activity.version_group = coalesce(nullif(assets.version_group, ''), assets.id)
    """
    count_sql = "select count(*) from assets"
    if where:
        where_sql = " where " + " and ".join(where)
        sql += where_sql
        count_sql += where_sql
    sql += " order by activity_at desc, assets.created_at desc, assets.asset_code desc, assets.id desc"

    pagination_request = parse_pagination(query)
    total = conn.execute(count_sql, params).fetchone()[0]
    if pagination_request:
        page, page_size = pagination_request
        offset = (page - 1) * page_size
        rows = conn.execute(f"{sql} limit ? offset ?", params + [page_size, offset]).fetchall()
        total_pages = max(1, (total + page_size - 1) // page_size)
        pagination = {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
            "hasPrev": page > 1,
            "hasNext": page < total_pages,
        }
    else:
        rows = conn.execute(sql, params).fetchall()
        pagination = {
            "page": 1,
            "pageSize": len(rows),
            "total": total,
            "totalPages": 1,
            "hasPrev": False,
            "hasNext": False,
        }

    return {
        "assets": add_version_counts(
            conn,
            rows,
            include_source_batches=not list_view,
            include_report_trusted=not list_view,
        ),
        "pagination": pagination,
        "categories": categories,
        "types": asset_types,
        "resourceKinds": resource_kinds,
        "pageRoles": page_roles or {},
        "tagTaxonomy": {} if list_view else tag_taxonomy,
        "pipeline": None if list_view else pipeline_summary(conn),
    }
