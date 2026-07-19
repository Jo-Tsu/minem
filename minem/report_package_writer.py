import hashlib
from pathlib import Path


def sync_report_material_package(
    conn,
    upload_id,
    extract_root,
    *,
    load_report_package_manifest,
    report_package_entry_path,
    find_existing_asset_by_code,
    next_report_revision_code,
    next_asset_code,
    clean_report_title,
    report_material_title,
    merge_tags,
    read_text_sample,
    file_hash,
    copy_package_preview_thumbnail,
    report_manifest_page_items,
    report_code_to_control_code,
    find_existing_asset,
    control_display_title,
    asset_library_path,
    next_candidate_asset_code,
    copy_page_variant,
    insert_control_asset,
    next_asset_version_no,
    attach_report_page_control,
    sync_report_index_from_slots,
    sync_report_package_resources,
    now_ms,
):
    extract_root = Path(extract_root)
    manifest, manifest_kind = load_report_package_manifest(extract_root)
    if not manifest_kind:
        return 0
    timestamp = now_ms()
    changed = 0
    manifest_report_code = str(manifest.get("asset_code") or "").strip()
    report_html, report_rel = report_package_entry_path(extract_root, manifest, manifest_kind)
    report_content_hash = file_hash(report_html) if report_html and report_html.exists() else ""
    existing_report = conn.execute(
        """
        select * from assets
        where upload_id = ? and source_path = ? and asset_type = 'report'
        order by created_at, asset_code
        limit 1
        """,
        (upload_id, report_rel),
    ).fetchone()
    if not existing_report:
        existing_report = conn.execute(
            "select * from assets where upload_id = ? and asset_type = 'report' order by created_at, asset_code limit 1",
            (upload_id,),
        ).fetchone()
    if not existing_report and manifest_report_code:
        code_match = find_existing_asset_by_code(conn, manifest_report_code, "report")
        if code_match and code_match["upload_id"] == upload_id and code_match["source_path"] == report_rel:
            existing_report = code_match
    if not existing_report and report_content_hash:
        # The same complete HTML package may be uploaded again under a new
        # batch id. Reuse its report record instead of creating a duplicate
        # card; pages and resources are synchronized onto that report.
        existing_report = conn.execute(
            """
            select * from assets
            where asset_type = 'report' and source_hash like ?
            order by created_at, asset_code
            limit 1
            """,
            (f"%:{report_content_hash}",),
        ).fetchone()
    report_asset_id = existing_report["id"] if existing_report else f"{upload_id}-report"
    report_code = existing_report["asset_code"] if existing_report else next_report_revision_code(conn, manifest_report_code)
    raw_report_title = manifest.get("title") or (existing_report["title"] if existing_report else upload_id)
    if manifest_report_code and str(raw_report_title).strip().startswith(manifest_report_code) and existing_report:
        raw_report_title = existing_report["title"]
    report_title = clean_report_title(raw_report_title)

    if report_html and report_html.exists():
        if not report_code:
            report_code = next_asset_code(conn, "report", "page", "html")
        conn.execute(
            """
            insert into assets
            (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, source_path, preview_url, upload_id, source_hash, version_group, version_no, version_parent_id, similarity_score, similarity_method, tag_seeded, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, 'report', ?, 'html', '', 'report-material-sync', ?, ?, ?, ?, ?, 1, '', 1.0, '', 1, ?, ?)
            on conflict(id) do update set
              title=excluded.title,
              usage=excluded.usage,
              tags=excluded.tags,
              snippet=excluded.snippet,
              source_type=excluded.source_type,
              source_path=excluded.source_path,
              preview_url=excluded.preview_url,
              upload_id=excluded.upload_id,
              source_hash=excluded.source_hash,
              updated_at=excluded.updated_at
            """,
            (
                report_asset_id,
                report_material_title(report_title),
                existing_report["category"] if existing_report else "report",
                f"由素材包内 {report_rel} 与页面素材自动同步的完整汇报素材。",
                ",".join(merge_tags(existing_report["tags"] if existing_report else "", ["汇报素材", "完整汇报", "HTML 汇报", "自动同步"])),
                read_text_sample(report_html),
                report_code,
                report_rel,
                f"/extracted/{upload_id}/{report_rel}",
                upload_id,
                f"sync-report:{upload_id}:{report_content_hash}",
                existing_report["version_group"] if existing_report else report_asset_id,
                existing_report["created_at"] if existing_report else timestamp,
                timestamp,
            ),
        )
        copy_package_preview_thumbnail(
            report_asset_id,
            extract_root,
            manifest.get("preview_url") or "",
            report_html,
            f"sync-report:{upload_id}:{report_content_hash}",
        )
        changed += 1

    existing_controls_by_content_hash = {}
    for control_row in conn.execute(
        """
        select * from assets
        where asset_type = 'control'
          and source_path <> ''
        order by
          case when version_parent_id = '' then 0 else 1 end,
          created_at,
          asset_code
        """
    ).fetchall():
        control_path = asset_library_path(control_row)
        if control_path and control_path.exists():
            existing_controls_by_content_hash.setdefault(file_hash(control_path), control_row)

    pages_to_sync_index = []
    for page_item in report_manifest_page_items(extract_root, manifest, manifest_kind):
        control_html = page_item["path"]
        rel = page_item["rel"]
        page_number = page_item["page"]
        asset_code = report_code_to_control_code(report_code, page_number)
        existing = find_existing_asset(conn, upload_id, rel, "control") or find_existing_asset_by_code(conn, asset_code, "control")
        title = str(page_item.get("title") or (existing["title"] if existing else "") or f"{page_number:02d} 汇报页面").strip()
        display_title = control_display_title(title, page_number)
        asset_id = existing["id"] if existing else f"{upload_id}-control-{page_number:02d}"
        if not asset_code:
            asset_code = next_asset_code(conn, "control", "page", "html")
        tags = merge_tags(
            existing["tags"] if existing else "",
            page_item.get("tags") or [],
            ["页面素材", "汇报页面", "单页素材", f"页码:{page_number:02d}", "自动同步"],
            [f"原页面:{page_item.get('source_code')}"] if page_item.get("source_code") else [],
            [page_item.get("role")] if page_item.get("role") else [],
        )
        control_content_hash = file_hash(control_html)
        control_source_hash = f"sync-control:{control_content_hash}"
        slot = conn.execute(
            "select * from report_page_slots where report_id = ? and page_number = ?",
            (report_asset_id, page_number),
        ).fetchone()
        current_asset = None
        if slot and slot["control_id"]:
            current_asset = conn.execute(
                "select * from assets where id = ? and asset_type = 'control'",
                (slot["control_id"],),
            ).fetchone()
        same_hash_asset = conn.execute(
            "select * from assets where source_hash = ? and asset_type = 'control' limit 1",
            (control_source_hash,),
        ).fetchone()
        if not same_hash_asset:
            same_hash_asset = existing_controls_by_content_hash.get(control_content_hash)

        incoming_asset_id = ""
        incoming_asset_code = ""
        incoming_path = None
        existing_path = asset_library_path(existing) if existing else None
        existing_content_matches = bool(existing_path and existing_path.exists() and file_hash(existing_path) == control_content_hash)
        can_update_existing = existing and (existing["source_hash"] == control_source_hash or existing_content_matches)
        if same_hash_asset:
            incoming_asset_id = same_hash_asset["id"]
            incoming_asset_code = same_hash_asset["asset_code"]
            incoming_path = asset_library_path(same_hash_asset)
        elif can_update_existing:
            incoming_asset_id = existing["id"]
            incoming_asset_code = existing["asset_code"]
            incoming_path = asset_library_path(existing)
            conn.execute(
                """
                update assets
                set title = ?, category = ?, usage = ?, tags = ?, snippet = ?, source_hash = ?, source_path = ?, preview_url = ?, updated_at = ?
                where id = ?
                """,
                (
                    display_title,
                    existing["category"] if existing else "page",
                    f"从汇报素材 {report_code or upload_id} 自动同步的第 {page_number} 页页面素材。",
                    ",".join(tags),
                    read_text_sample(control_html),
                    control_source_hash,
                    rel,
                    f"/extracted/{upload_id}/{rel}",
                    timestamp,
                    incoming_asset_id,
                ),
            )
        else:
            parent_asset = current_asset or existing
            hash_digest = hashlib.sha1(control_source_hash.encode("utf-8")).hexdigest()[:10]
            incoming_asset_id = asset_id if not existing and not current_asset else f"{upload_id}-control-{page_number:02d}-{hash_digest}"
            if conn.execute("select 1 from assets where id = ? limit 1", (incoming_asset_id,)).fetchone():
                incoming_asset_id = f"{incoming_asset_id}-{hashlib.sha1(str(now_ms()).encode()).hexdigest()[:6]}"
            if existing or current_asset:
                incoming_asset_code = next_candidate_asset_code(conn, (current_asset or existing)["asset_code"] or asset_code)
            else:
                incoming_asset_code = asset_code or next_asset_code(conn, "control", "page", "html")
            variant = "candidate" if current_asset else "current"
            variant_path, variant_rel = copy_page_variant(extract_root, rel, variant, control_source_hash)
            if not variant_path:
                variant_path, variant_rel = control_html, rel
            version_group = (parent_asset["version_group"] or parent_asset["id"]) if parent_asset else incoming_asset_id
            insert_control_asset(
                conn,
                asset_id=incoming_asset_id,
                title=display_title,
                usage=f"从汇报素材 {report_code or upload_id} 自动同步的第 {page_number} 页页面素材。",
                tags=tags,
                snippet=read_text_sample(control_html),
                asset_code=incoming_asset_code,
                source_type="report-material-candidate" if current_asset else "report-material-sync",
                source_path=variant_rel,
                preview_url=f"/extracted/{upload_id}/{variant_rel}",
                upload_id=upload_id,
                source_hash=control_source_hash,
                version_group=version_group,
                version_no=next_asset_version_no(conn, version_group) if parent_asset else 1,
                version_parent_id=parent_asset["id"] if parent_asset else "",
                created_at=timestamp,
            )
            incoming_path = variant_path
        copy_package_preview_thumbnail(
            incoming_asset_id,
            extract_root,
            page_item.get("preview") or "",
            incoming_path or control_html,
            control_source_hash,
        )
        if (report_html and report_html.exists()) or existing_report:
            attach_result = attach_report_page_control(conn, report_asset_id, page_number, incoming_asset_id, display_title, page_item.get("note") or "自动同步页面素材")
            if attach_result.get("attached"):
                pages_to_sync_index.append(page_number)
        changed += 1

    if pages_to_sync_index:
        sync_report_index_from_slots(conn, report_asset_id, pages_to_sync_index, "自动同步页面素材后更新最新汇报 index")

    changed += sync_report_package_resources(conn, upload_id, extract_root, report_code, report_title)

    file_count = sum(1 for path in extract_root.rglob("*") if path.is_file())
    asset_count = conn.execute("select count(*) from assets where upload_id = ?", (upload_id,)).fetchone()[0]
    conn.execute(
        "update uploads set file_count = ?, asset_count = ? where id = ?",
        (file_count, asset_count, upload_id),
    )
    return changed
