"""Transactional asset deletion planning and database cleanup."""
from __future__ import annotations


class AssetDeletionError(Exception):
    def __init__(self, message, *, status=400, details=None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


def _table_exists(conn, table):
    return bool(conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone())


def _placeholders(values):
    return ",".join("?" for _ in values)


def _rows_as_dicts(rows):
    return [dict(row) for row in rows]


def _control_references(conn, target_ids):
    placeholders = _placeholders(target_ids)
    report_ids = set()
    for table in ("report_page_slots", "report_page_candidates"):
        if not _table_exists(conn, table):
            continue
        report_ids.update(
            row["report_id"]
            for row in conn.execute(
                f"select distinct report_id from {table} where control_id in ({placeholders})",
                target_ids,
            ).fetchall()
        )
    if _table_exists(conn, "report_page_normalizations"):
        report_ids.update(
            row["report_id"]
            for row in conn.execute(
                f"""
                select distinct report_id
                from report_page_normalizations
                where source_control_id in ({placeholders})
                   or normalized_control_id in ({placeholders})
                """,
                [*target_ids, *target_ids],
            ).fetchall()
        )
    if not report_ids:
        return []
    report_placeholders = _placeholders(report_ids)
    rows = conn.execute(
        f"""
        select id, asset_code, title
        from assets
        where id in ({report_placeholders})
        order by updated_at desc, asset_code
        """,
        list(report_ids),
    ).fetchall()
    known = {row["id"] for row in rows}
    result = _rows_as_dicts(rows)
    result.extend(
        {"id": report_id, "asset_code": "", "title": "已失效的汇报引用"}
        for report_id in sorted(report_ids - known)
    )
    return result


def build_asset_deletion_plan(conn, asset_id):
    asset = conn.execute("select * from assets where id = ?", (asset_id,)).fetchone()
    if not asset:
        raise AssetDeletionError("素材不存在", status=404)

    asset_type = asset["asset_type"]
    group_id = asset["version_group"] or asset["id"]
    delete_group = not asset["version_parent_id"] and group_id == asset["id"]
    if delete_group:
        targets = conn.execute(
            """
            select *
            from assets
            where asset_type = ? and (version_group = ? or id = ?)
            order by version_no, created_at, id
            """,
            (asset_type, group_id, asset["id"]),
        ).fetchall()
    else:
        targets = [asset]
    target_rows = _rows_as_dicts(targets)
    target_ids = [row["id"] for row in target_rows]

    if asset_type == "control":
        references = _control_references(conn, target_ids)
        if references:
            codes = [row["asset_code"] or row["id"] for row in references]
            raise AssetDeletionError(
                f"页面仍被 {len(references)} 个汇报引用，请先从对应汇报中移出该页面",
                status=409,
                details={"references": references, "referenceCodes": codes},
            )

    placeholders = _placeholders(target_ids)
    source_files = []
    for target in target_rows:
        upload_id = target.get("upload_id") or ""
        source_path = target.get("source_path") or ""
        if not upload_id or not source_path:
            continue
        remaining = conn.execute(
            f"""
            select count(*)
            from assets
            where upload_id = ? and source_path = ?
              and id not in ({placeholders})
            """,
            [upload_id, source_path, *target_ids],
        ).fetchone()[0]
        if not remaining:
            source_files.append({"upload_id": upload_id, "source_path": source_path})

    history_rows = []
    if _table_exists(conn, "asset_history"):
        history_rows = _rows_as_dicts(conn.execute(
            f"select id, snapshot_path from asset_history where asset_id in ({placeholders})",
            target_ids,
        ).fetchall())

    report_ids = [row["id"] for row in target_rows if row["asset_type"] == "report"]
    retained_control_ids = []
    if report_ids and _table_exists(conn, "report_page_slots"):
        report_placeholders = _placeholders(report_ids)
        retained_control_ids = [
            row["control_id"]
            for row in conn.execute(
                f"""
                select distinct slot.control_id
                from report_page_slots slot
                join assets control on control.id = slot.control_id
                where slot.report_id in ({report_placeholders})
                  and slot.control_id <> ''
                  and control.asset_type = 'control'
                """,
                report_ids,
            ).fetchall()
        ]
    export_rows = []
    if report_ids and _table_exists(conn, "report_export_tasks"):
        report_placeholders = _placeholders(report_ids)
        export_rows = _rows_as_dicts(conn.execute(
            f"select id, output_path from report_export_tasks where report_id in ({report_placeholders})",
            report_ids,
        ).fetchall())

    return {
        "asset": dict(asset),
        "targets": target_rows,
        "target_ids": target_ids,
        "report_ids": report_ids,
        "retained_control_ids": retained_control_ids,
        "upload_ids": sorted({row.get("upload_id") for row in target_rows if row.get("upload_id")}),
        "source_files": source_files,
        "history_rows": history_rows,
        "export_rows": export_rows,
    }


def _delete_by_asset_ids(conn, table, target_ids):
    if not _table_exists(conn, table):
        return
    conn.execute(
        f"delete from {table} where asset_id in ({_placeholders(target_ids)})",
        target_ids,
    )


def apply_asset_deletion_plan(conn, plan, *, timestamp):
    target_ids = plan["target_ids"]
    report_ids = plan["report_ids"]
    retained_control_ids = plan.get("retained_control_ids") or []
    target_placeholders = _placeholders(target_ids)

    for table in ("asset_tags", "asset_tag_suggestions", "asset_tag_evidence"):
        _delete_by_asset_ids(conn, table, target_ids)
    if _table_exists(conn, "asset_history"):
        conn.execute(
            f"delete from asset_history where asset_id in ({target_placeholders})",
            target_ids,
        )
    if _table_exists(conn, "import_tasks"):
        conn.execute(
            f"""
            update import_tasks
            set asset_id = '', asset_code = '', asset_title = '', asset_type = '',
                preview_url = '', message = '导入产物已删除', updated_at = ?
            where asset_id in ({target_placeholders})
            """,
            [timestamp, *target_ids],
        )

    if report_ids:
        report_placeholders = _placeholders(report_ids)
        if retained_control_ids:
            control_placeholders = _placeholders(retained_control_ids)
            conn.execute(
                f"""
                update assets
                set usage = '从已删除汇报保留的页面素材。',
                    source_type = 'retained-report-page',
                    updated_at = ?
                where id in ({control_placeholders})
                """,
                [timestamp, *retained_control_ids],
            )
        for table in (
            "report_page_arrangements",
            "report_page_slots",
            "report_page_candidates",
            "report_page_normalizations",
            "report_export_tasks",
        ):
            if _table_exists(conn, table):
                conn.execute(
                    f"delete from {table} where report_id in ({report_placeholders})",
                    report_ids,
                )
        if _table_exists(conn, "report_storyline_collections"):
            conn.execute(
                f"""
                delete from report_storyline_collections
                where source_report_id in ({report_placeholders})
                   or output_report_id in ({report_placeholders})
                   or target_report_id in ({report_placeholders})
                """,
                [*report_ids, *report_ids, *report_ids],
            )

    conn.execute(
        f"delete from assets where id in ({target_placeholders})",
        target_ids,
    )

    empty_created_uploads = []
    for upload_id in plan["upload_ids"]:
        count = conn.execute(
            "select count(*) from assets where upload_id = ?",
            (upload_id,),
        ).fetchone()[0]
        conn.execute(
            "update uploads set asset_count = ? where id = ?",
            (count, upload_id),
        )
        if not count and str(upload_id).startswith("created-report-"):
            conn.execute("delete from uploads where id = ?", (upload_id,))
            empty_created_uploads.append(upload_id)

    return {
        **plan,
        "empty_created_uploads": empty_created_uploads,
        "retained_control_count": len(retained_control_ids),
        "deleted_count": len(target_ids),
    }
