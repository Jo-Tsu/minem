import time
from urllib.parse import urlparse
from .paths import is_safe_filename_stem


def save_asset_metadata(conn, payload, *, timestamp, make_id, next_asset_code, asset_types, media_kinds):
    text_fields = ("title", "category", "usage", "snippet", "asset_type", "media_kind")
    if any(key in payload and not isinstance(payload[key], str) for key in text_fields):
        raise ValueError("素材文本字段格式无效")
    if payload.get("id") is not None and not isinstance(payload["id"], str):
        raise ValueError("素材 ID 格式无效")
    tags = payload.get("tags", [])
    if not isinstance(tags, (str, list)) or (isinstance(tags, list) and any(not isinstance(tag, str) for tag in tags)):
        raise ValueError("标签必须是文本或文本数组")
    tags = ",".join(tags) if isinstance(tags, list) else tags
    try:
        for value in [tags, *(payload[key] for key in text_fields if key in payload)]:
            value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("素材文本编码无效") from error
    asset_id = payload.get("id") or make_id(payload.get("title", "asset"))
    if not is_safe_filename_stem(asset_id):
        raise ValueError("素材 ID 不可包含路径或控制字符")
    if not conn.in_transaction:
        conn.execute("begin immediate")
    existing = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
    defaults = {"title": "未命名素材", "category": "code", "usage": "", "snippet": "", "asset_type": "control", "media_kind": "none"}
    values = {key: payload.get(key, existing[key] if existing else default) for key, default in defaults.items()}
    if values["asset_type"] not in asset_types or values["media_kind"] not in media_kinds:
        raise ValueError("素材类型或媒体类型无效")
    if existing and values["asset_type"] != existing["asset_type"]:
        raise ValueError("已有素材的类型不能通过元数据更新改变")
    if existing and existing["source_path"] and values["media_kind"] != existing["media_kind"]:
        raise ValueError("已有文件的媒体类型不能通过元数据更新改变")
    if "tags" not in payload and existing:
        tags = existing["tags"]
    asset_code = existing["asset_code"] if existing and existing["asset_code"] else next_asset_code(conn, values["asset_type"], values["category"], values["media_kind"])
    conn.execute(
        """insert into assets
        (id,title,category,usage,tags,snippet,asset_type,asset_code,media_kind,source_type,source_path,preview_url,upload_id,created_at,updated_at,version_group)
        values (?,?,?,?,?,?,?,?,?,'manual','','',null,?,?,?)
        on conflict(id) do update set title=excluded.title, category=excluded.category,
            usage=excluded.usage, tags=excluded.tags, snippet=excluded.snippet,
            asset_type=excluded.asset_type, asset_code=excluded.asset_code,
            media_kind=excluded.media_kind, updated_at=excluded.updated_at""",
        (asset_id, values["title"], values["category"], values["usage"], tags, values["snippet"],
         values["asset_type"], asset_code, values["media_kind"], timestamp, timestamp, asset_id),
    )
    return {"ok": True, "id": asset_id, "assetCode": asset_code}


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
):
    category = query.get("category", ["all"])[0]
    asset_type = query.get("type", ["all"])[0]
    resource_kind = query.get("resource_kind", ["all"])[0]
    control_role = query.get("control_role", ["全部"])[0]
    search = query.get("q", [""])[0].strip()
    sort = query.get("sort", ["updated"])[0]
    days = {"7": 7, "30": 30, "90": 90}.get(query.get("days", [""])[0])
    include_versions = query.get("include_versions", ["0"])[0] == "1"
    view = query.get("view", ["full"])[0]
    list_view = view == "list"
    params = []
    where = []
    if days:
        where.append(f"{ASSET_ACTIVITY_SQL} >= ?")
        params.append(int(time.time() * 1000) - days * 86400000)

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
    ordering = {"code": "assets.asset_code asc", "title": "assets.title collate nocase asc"}.get(sort, "activity_at desc, assets.created_at desc, assets.asset_code desc")
    sql += f" order by {ordering}, assets.id desc"

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
        "pipeline": None if list_view else pipeline_summary(conn),
    }
