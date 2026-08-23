"""Asynchronous evidence collection and controlled business tagging."""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

from minem.tag_taxonomy import (
    CONTROLLED_TAGS,
    MAX_CONFIRMED_TAGS,
    MIN_CONFIRM_CONFIDENCE,
    MODEL_VERSION,
    TAXONOMY,
    TAXONOMY_VERSION,
    classify_evidence,
    confirmed_candidates,
)


SCHEMA = """
create table if not exists tag_analysis_tasks (
  id text primary key, status text not null default 'queued', trigger_type text not null,
  scope_type text not null default 'assets', scope_json text not null default '[]',
  total_count integer not null default 0, processed_count integer not null default 0,
  error_count integer not null default 0, message text not null default '', error text not null default '',
  model_version text not null default 'rules-v1', taxonomy_version text not null default 'taxonomy-v1',
  apply_mode text not null default 'suggestions',
  created_at integer not null, updated_at integer not null
);
create table if not exists asset_tag_evidence (
  asset_id text primary key, source_fingerprint text not null default '', evidence_json text not null default '{}',
  status text not null default 'collected', collected_at integer not null, updated_at integer not null
);
create table if not exists tag_definitions (
  tag text primary key, dimension text not null, aliases_json text not null default '[]',
  active integer not null default 1, sort_order integer not null default 0, updated_at integer not null
);
create table if not exists asset_tag_suggestions (
  asset_id text not null, tag text not null, dimension text not null,
  confidence real not null default 0, evidence_json text not null default '[]',
  status text not null default 'suggested', conflict_status text not null default 'none',
  source_fingerprint text not null default '', model_version text not null, taxonomy_version text not null,
  created_at integer not null, updated_at integer not null, primary key(asset_id, tag)
);
create table if not exists asset_tags (
  asset_id text not null, tag text not null, dimension text not null,
  source text not null default 'rule_confirmed', confidence real not null default 1,
  evidence_json text not null default '[]', confirmed_at integer not null, updated_at integer not null,
  primary key(asset_id, tag)
);
create index if not exists idx_tag_analysis_tasks_status on tag_analysis_tasks(status, updated_at desc);
create index if not exists idx_asset_tag_evidence_fingerprint on asset_tag_evidence(source_fingerprint);
create index if not exists idx_asset_tag_suggestions_asset on asset_tag_suggestions(asset_id, confidence desc);
create index if not exists idx_asset_tags_asset on asset_tags(asset_id);
create index if not exists idx_asset_tags_tag on asset_tags(tag, asset_id);
"""


def now_ms(): return int(time.time() * 1000)


def _ensure_column(conn, table, column, declaration):
    columns = {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in conn.execute(f"pragma table_info({table})")}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {declaration}")


def ensure_schema(conn):
    conn.executescript(SCHEMA)
    _ensure_column(conn, "tag_analysis_tasks", "apply_mode", "text not null default 'suggestions'")
    now = now_ms()
    order = 0
    for dimension, tags in TAXONOMY.items():
        for tag in tags:
            order += 1
            conn.execute(
                """insert into tag_definitions(tag,dimension,aliases_json,active,sort_order,updated_at)
                values (?,?,'[]',1,?,?)
                on conflict(tag) do nothing""",
                (tag, dimension, order, now),
            )


def taxonomy_definitions(conn):
    ensure_schema(conn)
    rows = conn.execute(
        """
        select tag, dimension, aliases_json, active, sort_order, updated_at
        from tag_definitions
        order by sort_order, tag
        """
    ).fetchall()
    definitions = []
    for row in rows:
        try:
            aliases = json.loads(row["aliases_json"] or "[]")
        except json.JSONDecodeError:
            aliases = []
        definitions.append({
            "tag": row["tag"],
            "dimension": row["dimension"],
            "aliases": aliases if isinstance(aliases, list) else [],
            "active": bool(row["active"]),
            "sortOrder": row["sort_order"],
            "updatedAt": row["updated_at"],
        })
    dimensions = list(TAXONOMY)
    for definition in definitions:
        if definition["dimension"] not in dimensions:
            dimensions.append(definition["dimension"])
    return {
        "version": TAXONOMY_VERSION,
        "dimensions": dimensions,
        "definitions": definitions,
        "minimumConfirmConfidence": MIN_CONFIRM_CONFIDENCE,
        "maximumConfirmedTags": MAX_CONFIRMED_TAGS,
    }


def update_taxonomy_definitions(conn, payload):
    definitions = payload.get("definitions") if isinstance(payload, dict) else None
    if not isinstance(definitions, list) or not definitions:
        return {"ok": False, "error": "缺少标签定义"}
    allowed_dimensions = set(TAXONOMY)
    existing = {
        row["tag"]
        for row in conn.execute("select tag from tag_definitions").fetchall()
    }
    updates = []
    seen = set()
    for index, item in enumerate(definitions, start=1):
        if not isinstance(item, dict):
            return {"ok": False, "error": "标签定义格式无效"}
        tag = str(item.get("tag") or "").strip()
        dimension = str(item.get("dimension") or "").strip()
        if tag not in existing or tag in seen:
            return {"ok": False, "error": f"标签不存在或重复：{tag or '空标签'}"}
        if dimension not in allowed_dimensions:
            return {"ok": False, "error": f"标签维度不受支持：{dimension or '空维度'}"}
        seen.add(tag)
        updates.append((dimension, 1 if item.get("active", True) else 0, index, now_ms(), tag))

    with conn:
        conn.executemany(
            """
            update tag_definitions
            set dimension = ?, active = ?, sort_order = ?, updated_at = ?
            where tag = ?
            """,
            updates,
        )
        for dimension, _, _, _, tag in updates:
            conn.execute("update asset_tags set dimension=? where tag=?", (dimension, tag))
            conn.execute("update asset_tag_suggestions set dimension=? where tag=?", (dimension, tag))
        asset_ids = [
            row["asset_id"]
            for row in conn.execute("select distinct asset_id from asset_tags").fetchall()
        ]
        for asset_id in asset_ids:
            _sync_asset_tag_cache(conn, asset_id)
    return {"ok": True, "taxonomy": taxonomy_definitions(conn)}


def apply_taxonomy_definitions(conn, candidates):
    rows = conn.execute(
        "select tag, dimension, active from tag_definitions"
    ).fetchall()
    definitions = {row["tag"]: row for row in rows}
    governed = []
    for candidate in candidates:
        definition = definitions.get(candidate["tag"])
        if not definition or not definition["active"]:
            continue
        governed.append({**candidate, "dimension": definition["dimension"]})
    return governed


def recover_interrupted(conn):
    ensure_schema(conn)
    timestamp = now_ms()
    cursor = conn.execute(
        """
        update tag_analysis_tasks
        set status = 'failed',
            message = '标签分析已中断',
            error = 'MineM 服务已重新启动，原标签分析无法继续；请重新创建任务',
            updated_at = ?
        where status in ('queued', 'running')
        """,
        (timestamp,),
    )
    return max(0, cursor.rowcount)


def public_task(row):
    item = dict(row)
    item["scope"] = json.loads(item.pop("scope_json") or "[]")
    return {"id": item["id"], "status": item["status"], "triggerType": item["trigger_type"],
            "scopeType": item["scope_type"], "scope": item["scope"], "totalCount": item["total_count"],
            "processedCount": item["processed_count"], "errorCount": item["error_count"], "message": item["message"],
            "error": item["error"], "modelVersion": item["model_version"], "taxonomyVersion": item["taxonomy_version"],
            "applyMode": item.get("apply_mode") or "suggestions",
            "createdAt": item["created_at"], "updatedAt": item["updated_at"]}


def fingerprint(asset):
    raw = "|".join(str(asset.get(key) or "") for key in ("source_hash", "preview_url", "source_path", "updated_at", "title"))
    return hashlib.sha256(raw.encode()).hexdigest()


def create_task(conn, asset_ids, trigger_type="manual", scope_type="assets", apply_mode="suggestions"):
    ensure_schema(conn)
    valid = [row["id"] for row in conn.execute(
        f"select id from assets where id in ({','.join('?' for _ in asset_ids)})", asset_ids).fetchall()] if asset_ids else []
    if not valid:
        return {"ok": False, "error": "没有可分析的素材"}
    now = now_ms(); task_id = f"tag-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    mode = "confirmed" if apply_mode == "confirmed" else "suggestions"
    conn.execute("""insert into tag_analysis_tasks(
      id,status,trigger_type,scope_type,scope_json,total_count,processed_count,error_count,
      message,error,model_version,taxonomy_version,apply_mode,created_at,updated_at
    ) values (?, 'queued', ?, ?, ?, ?, 0, 0, ?, '', ?, ?, ?, ?, ?)""",
                 (task_id, trigger_type, scope_type, json.dumps(valid),
                  len(valid), "等待标签分析", MODEL_VERSION, TAXONOMY_VERSION, mode, now, now))
    return {"ok": True, "taskId": task_id}


def changed_asset_ids(conn, limit=500):
    # SQLite has no portable sha256 function; compare fingerprints in Python.
    result = []
    for row in conn.execute("select a.*, e.source_fingerprint from assets a left join asset_tag_evidence e on e.asset_id=a.id order by a.updated_at desc limit ?", (limit,)).fetchall():
        if not row["source_fingerprint"] or row["source_fingerprint"] != fingerprint(dict(row)):
            result.append(row["id"])
    return result


def _visible_text(raw):
    raw = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html_lib.unescape(raw)).strip()[:12000]


def _metadata_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value or "")


def collect_evidence(conn, asset, extracted_root: Path):
    item = dict(asset); sources = []
    path = None; preview = item.get("preview_url") or ""
    if preview.startswith("/extracted/"):
        path = extracted_root / preview.removeprefix("/extracted/")
    elif str(item.get("source_path") or "").endswith((".html", ".htm")):
        candidate = Path(item["source_path"])
        if candidate.is_file(): path = candidate
    if path and path.is_file() and path.stat().st_size <= 8 * 1024 * 1024:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        headings = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", raw, re.I | re.S)
        alts = re.findall(r"\balt=[\"']([^\"']+)", raw, re.I)
        sources.append({"priority": "P1", "type": "page_html", "title": _visible_text(title.group(1)) if title else "", "headings": [_visible_text(x)[:240] for x in headings[:20]], "text": _visible_text(raw)})
        if alts: sources.append({"priority": "P1", "type": "image_alt", "text": " | ".join(alts[:30])})
    if item.get("title") or item.get("usage") or item.get("snippet"):
        sources.append({
            "priority": "P1",
            "type": "page_metadata",
            "title": _metadata_text(item.get("title")),
            "text": " ".join(filter(None, [
                _metadata_text(item.get("usage")),
                _metadata_text(item.get("snippet")),
            ]))[:3000],
        })
    contexts = conn.execute("""
      select r.asset_code, r.title, s.page_number from report_page_slots s join assets r on r.id=s.report_id
      where s.control_id=? order by s.updated_at desc limit 12
    """, (item["id"],)).fetchall()
    if contexts:
        sources.append({"priority": "P2", "type": "report_context", "items": [dict(row) for row in contexts]})
    if item.get("asset_type") == "report":
        pages = conn.execute("""
          select p.asset_code, p.title, p.usage, p.snippet from report_page_slots s
          join assets p on p.id=s.control_id where s.report_id=?
          order by s.page_number limit 30
        """, (item["id"],)).fetchall()
        if pages:
            sources.append({"priority": "P2", "type": "report_pages", "items": [dict(row) for row in pages]})
    if item.get("asset_type") == "resource" and item.get("upload_id"):
        related = conn.execute("""
          select asset_code,title,usage,snippet from assets
          where upload_id=? and asset_type in ('control','report') and id<>?
          order by case asset_type when 'control' then 0 else 1 end, updated_at desc limit 24
        """, (item["upload_id"], item["id"])).fetchall()
        if related:
            sources.append({"priority": "P2", "type": "parent_material_context", "items": [dict(row) for row in related]})
    sources.append({"priority": "P4", "type": "structured_source", "sourceType": item.get("source_type") or "", "mediaKind": item.get("media_kind") or "", "resourceKind": item.get("resource_kind") or ""})
    evidence = {"assetId": item["id"], "assetCode": item.get("asset_code") or "", "fingerprint": fingerprint(item), "status": "classified", "mode": MODEL_VERSION, "sources": sources}
    evidence["candidates"] = classify_evidence(evidence)
    return evidence


def _sync_asset_tag_cache(conn, asset_id):
    rows = conn.execute("""
      select at.tag from asset_tags at
      join tag_definitions td on td.tag=at.tag and td.active=1
      where at.asset_id=? order by td.sort_order, at.tag limit ?
    """, (asset_id, MAX_CONFIRMED_TAGS)).fetchall()
    tags = [row["tag"] for row in rows]
    conn.execute("update assets set tags=?, tag_seeded=1 where id=?", (",".join(tags), asset_id))
    return tags


def _store_candidates(conn, asset_id, evidence, apply_mode):
    now = now_ms()
    candidates = apply_taxonomy_definitions(conn, evidence["candidates"])
    candidate_tags = {candidate["tag"] for candidate in candidates}
    for candidate in candidates:
        conn.execute("""insert into asset_tag_suggestions(
          asset_id,tag,dimension,confidence,evidence_json,status,conflict_status,
          source_fingerprint,model_version,taxonomy_version,created_at,updated_at
        ) values (?,?,?,?,?,'suggested',?,?,?,?,?,?)
        on conflict(asset_id,tag) do update set dimension=excluded.dimension,
          confidence=excluded.confidence,evidence_json=excluded.evidence_json,
          status=excluded.status,conflict_status=excluded.conflict_status,
          source_fingerprint=excluded.source_fingerprint,model_version=excluded.model_version,
          taxonomy_version=excluded.taxonomy_version,updated_at=excluded.updated_at""",
          (asset_id, candidate["tag"], candidate["dimension"], candidate["confidence"],
           json.dumps(candidate["evidence"], ensure_ascii=False), candidate["conflictStatus"],
           evidence["fingerprint"], MODEL_VERSION, TAXONOMY_VERSION, now, now))
    if candidate_tags:
        placeholders = ",".join("?" for _ in candidate_tags)
        conn.execute(
            f"delete from asset_tag_suggestions where asset_id=? and tag not in ({placeholders})",
            (asset_id, *candidate_tags),
        )
    else:
        conn.execute("delete from asset_tag_suggestions where asset_id=?", (asset_id,))

    if apply_mode != "confirmed":
        return 0
    selected = confirmed_candidates(candidates)
    conn.execute("delete from asset_tags where asset_id=? and source<>'manual'", (asset_id,))
    manual_count = conn.execute(
        "select count(*) count from asset_tags where asset_id=? and source='manual'",
        (asset_id,),
    ).fetchone()["count"]
    applied = 0
    for candidate in selected:
        if manual_count + applied >= MAX_CONFIRMED_TAGS:
            break
        manual_dimension = conn.execute(
            "select 1 from asset_tags where asset_id=? and dimension=? and source='manual' limit 1",
            (asset_id, candidate["dimension"]),
        ).fetchone()
        if manual_dimension:
            continue
        conn.execute("""insert into asset_tags(
          asset_id,tag,dimension,source,confidence,evidence_json,confirmed_at,updated_at
        ) values (?,?,?,'rule_confirmed',?,?,?,?)
        on conflict(asset_id,tag) do update set dimension=excluded.dimension,
          source=case when asset_tags.source='manual' then asset_tags.source else excluded.source end,
          confidence=case when asset_tags.source='manual' then asset_tags.confidence else excluded.confidence end,
          evidence_json=case when asset_tags.source='manual' then asset_tags.evidence_json else excluded.evidence_json end,
          updated_at=excluded.updated_at""",
          (asset_id, candidate["tag"], candidate["dimension"], candidate["confidence"],
           json.dumps(candidate["evidence"], ensure_ascii=False), now, now))
        applied += 1
    _sync_asset_tag_cache(conn, asset_id)
    return applied


def run_task(db_path, extracted_root, task_id):
    conn = sqlite3.connect(db_path, timeout=30); conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        with conn:
            task = conn.execute("select * from tag_analysis_tasks where id=?", (task_id,)).fetchone()
            if not task or task["status"] == "cancelled": return
            conn.execute("update tag_analysis_tasks set status='running', message='正在分析素材标签', updated_at=? where id=?", (now_ms(), task_id))
        ids = json.loads(task["scope_json"])
        errors = 0; applied = 0
        for index, asset_id in enumerate(ids, 1):
            with conn:
                current = conn.execute("select status from tag_analysis_tasks where id=?", (task_id,)).fetchone()
                if not current or current["status"] == "cancelled": return
                asset = conn.execute("select * from assets where id=?", (asset_id,)).fetchone()
            if not asset:
                errors += 1
                with conn:
                    conn.execute(
                        "update tag_analysis_tasks set processed_count=?, error_count=?, updated_at=? where id=?",
                        (index, errors, now_ms(), task_id),
                    )
                continue
            try:
                asset_applied = 0
                with conn:
                    evidence = collect_evidence(conn, asset, Path(extracted_root))
                    conn.execute("""insert into asset_tag_evidence values (?, ?, ?, 'classified', ?, ?)
                      on conflict(asset_id) do update set source_fingerprint=excluded.source_fingerprint,evidence_json=excluded.evidence_json,status='classified',updated_at=excluded.updated_at""",
                      (asset_id, evidence["fingerprint"], json.dumps(evidence, ensure_ascii=False), now_ms(), now_ms()))
                    asset_applied = _store_candidates(conn, asset_id, evidence, task["apply_mode"])
                    action = "确认" if task["apply_mode"] == "confirmed" else "分析"
                    conn.execute("update tag_analysis_tasks set processed_count=?, error_count=?, message=?, updated_at=? where id=?", (index, errors, f'已{action} {index}/{len(ids)} 个素材', now_ms(), task_id))
                applied += asset_applied
            except Exception:
                errors += 1
                with conn:
                    conn.execute("update tag_analysis_tasks set processed_count=?, error_count=?, updated_at=? where id=?", (index, errors, now_ms(), task_id))
        with conn:
            if task["apply_mode"] == "confirmed":
                message = f"标签分析完成；已确认 {applied} 条正式标签"
            else:
                message = "标签候选与证据已生成"
            if errors:
                message += f"；{errors} 个素材分析失败"
            conn.execute("update tag_analysis_tasks set status='completed', message=?, updated_at=? where id=?", (message, now_ms(), task_id))
    except Exception as error:
        with conn: conn.execute("update tag_analysis_tasks set status='failed', error=?, message='标签分析失败', updated_at=? where id=?", (str(error)[:1000], now_ms(), task_id))
    finally: conn.close()
