from urllib.parse import urlparse


DEFAULT_ASSET_PAGE_SIZE = 30
MAX_ASSET_PAGE_SIZE = 200


ASSET_ACTIVITY_SQL = """
max(
  assets.updated_at,
  assets.created_at,
  coalesce((
    select max(version.updated_at)
    from assets version
    where version.version_group = coalesce(nullif(assets.version_group, ''), assets.id)
  ), 0),
  case when assets.asset_type = 'control' then coalesce((
    select max(slot.updated_at)
    from report_page_slots slot
    join assets referenced_control on referenced_control.id = slot.control_id
    where referenced_control.version_group = coalesce(nullif(assets.version_group, ''), assets.id)
  ), 0) else 0 end,
  case when assets.asset_type = 'control' then coalesce((
    select max(candidate.updated_at)
    from report_page_candidates candidate
    join assets referenced_control on referenced_control.id = candidate.control_id
    where referenced_control.version_group = coalesce(nullif(assets.version_group, ''), assets.id)
  ), 0) else 0 end
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
    tag_taxonomy,
):
    category = query.get("category", ["all"])[0]
    asset_type = query.get("type", ["all"])[0]
    resource_kind = query.get("resource_kind", ["all"])[0]
    control_role = query.get("control_role", ["全部"])[0]
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
    if asset_type == "control" and control_role and control_role != "全部":
        where.append("instr(',' || tags || ',', ?) > 0")
        params.append(f",{control_role},")
    if search:
        search_terms = [search]
        link_path = urlparse(search).path.strip()
        if link_path and link_path not in search_terms:
            search_terms.append(link_path)
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
            where.append(
                f"""
                exists (
                  select 1 from assets matched
                  where matched.version_group = assets.version_group
                    and ({match_clause.replace('asset_', 'matched.asset_').replace(' title', ' matched.title').replace(' usage', ' matched.usage').replace(' tags', ' matched.tags').replace(' source_path', ' matched.source_path').replace(' preview_url', ' matched.preview_url').replace(' upload_id', ' matched.upload_id')})
                )
                """
            )
            params.extend(match_params)
    if not include_versions:
        where.append("version_parent_id = ''")

    sql = f"select assets.*, {ASSET_ACTIVITY_SQL} as activity_at from assets"
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
        "tagTaxonomy": {} if list_view else tag_taxonomy,
        "pipeline": None if list_view else pipeline_summary(conn),
    }
