import hashlib
import re


def normalize_page_numbers(value):
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = re.split(r"[,，、\s]+", str(value or ""))
    pages = []
    seen = set()
    for item in raw_items:
        try:
            page = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if page < 1 or page in seen:
            continue
        pages.append(page)
        seen.add(page)
    return pages


def report_page_candidate_id(report_id, page_number, control_id, *, slugify):
    digest = hashlib.sha1(f"{report_id}:{page_number}:{control_id}".encode("utf-8")).hexdigest()[:12]
    return f"cand-{slugify(report_id)}-p{page_number:02d}-{digest}"


def register_report_page_candidate(conn, report_id, page_number, control_id, title="", note="", *, slugify, now_ms):
    control = conn.execute("select * from assets where id = ? and asset_type = 'control'", (control_id,)).fetchone()
    if not control:
        return None
    timestamp = now_ms()
    candidate_id = report_page_candidate_id(report_id, page_number, control_id, slugify=slugify)
    conn.execute(
        """
        insert into report_page_candidates
        (id, report_id, page_number, control_id, title, status, note, created_at, updated_at)
        values (?, ?, ?, ?, ?, 'candidate', ?, ?, ?)
        on conflict(report_id, page_number, control_id) do update set
          title = case when excluded.title <> '' then excluded.title else report_page_candidates.title end,
          status = 'candidate',
          note = case when excluded.note <> '' then excluded.note else report_page_candidates.note end,
          updated_at = excluded.updated_at
        """,
        (candidate_id, report_id, page_number, control_id, title.strip() or control["title"], note.strip(), timestamp, timestamp),
    )
    return candidate_id


def attach_report_page_control(
    conn,
    report_id,
    page_number,
    control_id,
    title="",
    note="",
    replace=False,
    *,
    register_candidate,
    now_ms,
):
    slot = conn.execute(
        "select * from report_page_slots where report_id = ? and page_number = ?",
        (report_id, page_number),
    ).fetchone()
    if slot and slot["control_id"] and slot["control_id"] != control_id and not replace:
        candidate_id = register_candidate(conn, report_id, page_number, control_id, title, note or "并行生成候选页，未覆盖当前页")
        return {"attached": False, "candidate": True, "candidateId": candidate_id}

    timestamp = now_ms()
    conn.execute(
        """
        insert into report_page_slots
        (report_id, page_number, title, status, control_id, task_key, note, created_at, updated_at)
        values (?, ?, ?, 'attached', ?, '', ?, ?, ?)
        on conflict(report_id, page_number) do update set
          title = case when excluded.title <> '' then excluded.title else report_page_slots.title end,
          status = 'attached',
          control_id = excluded.control_id,
          note = case when excluded.note <> '' then excluded.note else report_page_slots.note end,
          updated_at = excluded.updated_at
        """,
        (report_id, page_number, title.strip(), control_id, note.strip(), timestamp, timestamp),
    )
    return {"attached": True, "candidate": False, "candidateId": ""}


def upsert_report_page_slots(report_id, pages, title_prefix="", note="", *, connect, now_ms, get_slots):
    pages = normalize_page_numbers(pages)
    if not pages:
        return {"ok": False, "error": "请输入要并行生成的页码，例如 2,3,4,6"}
    with connect() as conn:
        report = conn.execute("select * from assets where id = ?", (report_id,)).fetchone()
        if not report or report["asset_type"] not in {"report", "page"}:
            return {"ok": False, "error": "汇报素材不存在"}
        timestamp = now_ms()
        for page in pages:
            title = f"{title_prefix.strip()} 第 {page} 页" if title_prefix.strip() else f"{report['title']} 第 {page} 页"
            conn.execute(
                """
                insert into report_page_slots
                (report_id, page_number, title, status, control_id, task_key, note, created_at, updated_at)
                values (?, ?, ?, 'planned', '', ?, ?, ?, ?)
                on conflict(report_id, page_number) do update set
                  title = case when excluded.title <> '' then excluded.title else report_page_slots.title end,
                  status = case when report_page_slots.status = 'attached' then report_page_slots.status else excluded.status end,
                  note = case when excluded.note <> '' then excluded.note else report_page_slots.note end,
                  updated_at = excluded.updated_at
                """,
                (report_id, page, title, f"parallel:{report_id}:{page}", note.strip(), timestamp, timestamp),
            )
    return get_slots(report_id)


def get_report_page_slots(
    report_id,
    *,
    connect,
    row_to_asset,
    asset_library_path,
    detect_report_page_count,
    validate_report_trusted_entry,
):
    with connect() as conn:
        report = conn.execute("select * from assets where id = ?", (report_id,)).fetchone()
        if not report or report["asset_type"] not in {"report", "page"}:
            return {"ok": False, "error": "汇报素材不存在"}
        rows = conn.execute(
            "select * from report_page_slots where report_id = ? order by page_number",
            (report_id,),
        ).fetchall()
        candidate_rows = conn.execute(
            """
            select * from report_page_candidates
            where report_id = ? and status = 'candidate'
            order by page_number, updated_at desc
            """,
            (report_id,),
        ).fetchall()
        controls = {}
        control_ids = [row["control_id"] for row in rows if row["control_id"]]
        control_ids.extend(row["control_id"] for row in candidate_rows if row["control_id"])
        control_ids = list(dict.fromkeys(control_ids))
        if control_ids:
            placeholders = ",".join("?" for _ in control_ids)
            control_rows = conn.execute(f"select * from assets where id in ({placeholders})", control_ids).fetchall()
            controls = {row["id"]: row_to_asset(row) for row in control_rows}
        candidates_by_page = {}
        for candidate in candidate_rows:
            item = dict(candidate)
            item["control"] = controls.get(candidate["control_id"])
            item["statusLabel"] = "候选页"
            candidates_by_page.setdefault(candidate["page_number"], []).append(item)
        detected_page_count = 0
        source = asset_library_path(report)
        if source and source.exists():
            detected_page_count = detect_report_page_count(source)
        slots = []
        for row in rows:
            item = dict(row)
            item["control"] = controls.get(row["control_id"])
            item["candidates"] = candidates_by_page.get(row["page_number"], [])
            item["candidateCount"] = len(item["candidates"])
            item["statusLabel"] = "已挂载" if item["control"] else ("生成中" if item["status"] == "generating" else "待生成")
            slots.append(item)
        return {
            "ok": True,
            "reportId": report_id,
            "detectedPageCount": detected_page_count,
            "trustedEntry": validate_report_trusted_entry(conn, report_id),
            "slots": slots,
        }
