def upload_batch_summaries(conn, upload_ids, *, pipeline_stages, validate_report_trusted_entry):
    ids = sorted({upload_id for upload_id in upload_ids if upload_id})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    uploads = conn.execute(
        f"select * from uploads where id in ({placeholders})",
        ids,
    ).fetchall()
    type_counts = {}
    for row in conn.execute(
        f"""
        select upload_id, asset_type, count(*) count
        from assets
        where upload_id in ({placeholders})
        group by upload_id, asset_type
        """,
        ids,
    ).fetchall():
        type_counts.setdefault(row["upload_id"], {})[row["asset_type"]] = row["count"]
    resource_counts = {}
    for row in conn.execute(
        f"""
        select upload_id, resource_kind, count(*) count
        from assets
        where upload_id in ({placeholders}) and asset_type = 'resource'
        group by upload_id, resource_kind
        """,
        ids,
    ).fetchall():
        key = row["resource_kind"] or "other"
        resource_counts.setdefault(row["upload_id"], {})[key] = row["count"]
    entry_assets = {}
    for row in conn.execute(
        f"""
        select upload_id, id, asset_code, title
        from assets
        where upload_id in ({placeholders}) and asset_type = 'report'
        order by created_at, asset_code
        """,
        ids,
    ).fetchall():
        trusted_entry = validate_report_trusted_entry(conn, row["id"])
        entry_assets.setdefault(
            row["upload_id"],
            {
                "assetId": row["id"],
                "assetCode": row["asset_code"],
                "title": row["title"],
                "pageCount": trusted_entry.get("pageCount", 0) if trusted_entry.get("ok") else 0,
                "url": trusted_entry.get("url", ""),
            },
        )
    summaries = {}
    for upload in uploads:
        counts = type_counts.get(upload["id"], {})
        entry_asset = entry_assets.get(upload["id"])
        summaries[upload["id"]] = {
            "id": upload["id"],
            "filename": upload["filename"],
            "storedPath": upload["stored_path"],
            "extractPath": upload["extract_path"],
            "fileCount": upload["file_count"],
            "assetCount": upload["asset_count"],
            "createdAt": upload["created_at"],
            "pageCount": entry_asset.get("pageCount", 0) if entry_asset else 0,
            "typeCounts": {stage["key"]: counts.get(stage["key"], 0) for stage in pipeline_stages},
            "resourceCounts": resource_counts.get(upload["id"], {}),
            "entryAsset": entry_asset,
        }
    return summaries


def attach_source_batches(conn, assets, *, upload_batch_summaries_fn):
    summaries = upload_batch_summaries_fn(conn, [asset.get("upload_id") for asset in assets])
    for asset in assets:
        asset["sourceBatch"] = summaries.get(asset.get("upload_id"))


def lineage_asset_summary(asset, *, asset_types, categories, resource_kinds, canonical_preview_url):
    asset = dict(asset)
    return {
        "id": asset["id"],
        "assetCode": asset["asset_code"],
        "title": asset["title"],
        "assetType": asset["asset_type"],
        "typeLabel": asset_types.get(asset["asset_type"], asset["asset_type"]),
        "categoryLabel": categories.get(asset["category"], asset["category"]),
        "resourceKind": asset["resource_kind"] or "",
        "resourceKindLabel": resource_kinds.get(asset["resource_kind"] or "", asset["resource_kind"] or ""),
        "sourceType": asset["source_type"],
        "sourcePath": asset["source_path"],
        "previewUrl": canonical_preview_url(asset),
        "createdAt": asset["created_at"],
        "updatedAt": asset["updated_at"],
    }


def asset_lineage_details(
    asset_id,
    *,
    connect,
    row_to_asset,
    upload_batch_summaries_fn,
    validate_report_trusted_entry,
    asset_types,
    categories,
    resource_kinds,
    source_types,
    canonical_preview_url,
):
    with connect() as conn:
        row = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "素材不存在"}
        asset = row_to_asset(row)
        source_batch = upload_batch_summaries_fn(conn, [asset.get("upload_id")]).get(asset.get("upload_id"))
        upload_id = asset.get("upload_id")
        rows = conn.execute(
            """
            select *
            from assets
            where upload_id = ?
            order by
              case asset_type when 'report' then 1 when 'control' then 2 when 'resource' then 3 else 9 end,
              asset_code
            """,
            (upload_id,),
        ).fetchall() if upload_id else []
        summarize = lambda item: lineage_asset_summary(
            item,
            asset_types=asset_types,
            categories=categories,
            resource_kinds=resource_kinds,
            canonical_preview_url=canonical_preview_url,
        )
        assets = [summarize(item) for item in rows]
        by_type = {}
        for item in assets:
            by_type.setdefault(item["assetType"], []).append(item)
        by_resource_kind = {}
        for item in assets:
            if item["assetType"] != "resource":
                continue
            by_resource_kind.setdefault(item["resourceKind"] or "other", []).append(item)
        trusted_entry = validate_report_trusted_entry(conn, asset_id) if asset.get("asset_type") == "report" else {}
        current_item = summarize(row)
        sections = [
            {
                "key": "current-stage",
                "label": "当前层级",
                "value": asset.get("typeLabel") or asset_types.get(asset.get("asset_type"), asset.get("asset_type")),
                "summary": "当前素材在素材生产链路中的层级。",
                "items": [current_item],
            },
            {
                "key": "source-action",
                "label": "生成动作",
                "value": source_types.get(asset.get("source_type"), asset.get("source_type") or "未记录"),
                "summary": "这条素材记录进入素材库时使用的导入或同步动作。",
                "items": [current_item],
            },
            {
                "key": "source-batch",
                "label": "原数据批次",
                "value": source_batch.get("filename") if source_batch else (upload_id or "未记录批次"),
                "summary": "同一批次表示这些素材来自同一次导入、抽取或同步。",
                "items": assets,
            },
            {
                "key": "batch-output",
                "label": "批次产物",
                "value": "",
                "summary": "同一批次在素材库中实际生成的汇报、页面素材和资源素材数量。",
                "groups": [
                    {"key": "report", "label": "汇报素材", "count": len(by_type.get("report", [])), "items": by_type.get("report", [])},
                    {"key": "page", "label": "页面", "count": source_batch.get("pageCount", 0) if source_batch else 0, "items": []},
                    {"key": "control", "label": "页面素材", "count": len(by_type.get("control", [])), "items": by_type.get("control", [])},
                    {"key": "resource", "label": "资源素材", "count": len(by_type.get("resource", [])), "items": by_type.get("resource", [])},
                ],
            },
            {
                "key": "created-at",
                "label": "入库时间",
                "value": source_batch.get("createdAt") if source_batch else asset.get("created_at"),
                "summary": "原数据批次写入素材库的时间。",
                "items": assets,
            },
            {
                "key": "resource-breakdown",
                "label": "资源细分",
                "value": "",
                "summary": "资源素材按图片、Logo、图标、GIF、视频等类型继续拆分。",
                "groups": [
                    {
                        "key": key,
                        "label": resource_kinds.get(key, key),
                        "count": len(items),
                        "items": items,
                    }
                    for key, items in sorted(by_resource_kind.items())
                ],
            },
            {
                "key": "source-path",
                "label": "入口文件",
                "value": asset.get("source_path") or "未记录",
                "summary": "当前素材在原始批次中的相对路径。",
                "items": [current_item],
            },
        ]
        return {
            "ok": True,
            "assetId": asset_id,
            "sourceBatch": source_batch,
            "trustedEntry": trusted_entry,
            "sections": sections,
        }


def pipeline_summary(conn, *, pipeline_stages, upload_batch_summaries_fn):
    type_counts = {
        row["asset_type"]: row["count"]
        for row in conn.execute(
            "select asset_type, count(*) count from assets where version_parent_id = '' group by asset_type"
        ).fetchall()
    }
    resource_counts = {
        (row["resource_kind"] or "other"): row["count"]
        for row in conn.execute(
            """
            select resource_kind, count(*) count
            from assets
            where asset_type = 'resource' and version_parent_id = ''
            group by resource_kind
            """
        ).fetchall()
    }
    latest_upload_rows = conn.execute(
        "select id from uploads order by created_at desc limit 6"
    ).fetchall()
    latest_batches = upload_batch_summaries_fn(conn, [row["id"] for row in latest_upload_rows])
    stages = []
    for index, stage in enumerate(pipeline_stages, start=1):
        item = dict(stage)
        item["index"] = index
        item["count"] = type_counts.get(stage["key"], 0)
        stages.append(item)
    return {
        "stages": stages,
        "resourceCounts": resource_counts,
        "latestBatches": [latest_batches[row["id"]] for row in latest_upload_rows if row["id"] in latest_batches],
    }
