"""Asynchronous evidence collection for MineM's future tag system.

This module deliberately stores evidence only.  It never writes assets.tags or
creates business labels; a governed model/lexicon stage will consume evidence
later.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path


SCHEMA = """
create table if not exists tag_analysis_tasks (
  id text primary key, status text not null default 'queued', trigger_type text not null,
  scope_type text not null default 'assets', scope_json text not null default '[]',
  total_count integer not null default 0, processed_count integer not null default 0,
  error_count integer not null default 0, message text not null default '', error text not null default '',
  model_version text not null default 'evidence-v1', taxonomy_version text not null default 'pending',
  created_at integer not null, updated_at integer not null
);
create table if not exists asset_tag_evidence (
  asset_id text primary key, source_fingerprint text not null default '', evidence_json text not null default '{}',
  status text not null default 'collected', collected_at integer not null, updated_at integer not null
);
create index if not exists idx_tag_analysis_tasks_status on tag_analysis_tasks(status, updated_at desc);
create index if not exists idx_asset_tag_evidence_fingerprint on asset_tag_evidence(source_fingerprint);
"""


def now_ms(): return int(time.time() * 1000)


def ensure_schema(conn): conn.executescript(SCHEMA)


def public_task(row):
    item = dict(row)
    item["scope"] = json.loads(item.pop("scope_json") or "[]")
    return {"id": item["id"], "status": item["status"], "triggerType": item["trigger_type"],
            "scopeType": item["scope_type"], "scope": item["scope"], "totalCount": item["total_count"],
            "processedCount": item["processed_count"], "errorCount": item["error_count"], "message": item["message"],
            "error": item["error"], "modelVersion": item["model_version"], "taxonomyVersion": item["taxonomy_version"],
            "createdAt": item["created_at"], "updatedAt": item["updated_at"]}


def fingerprint(asset):
    raw = "|".join(str(asset.get(key) or "") for key in ("source_hash", "preview_url", "source_path", "updated_at", "title"))
    return hashlib.sha256(raw.encode()).hexdigest()


def create_task(conn, asset_ids, trigger_type="manual", scope_type="assets"):
    valid = [row["id"] for row in conn.execute(
        f"select id from assets where id in ({','.join('?' for _ in asset_ids)})", asset_ids).fetchall()] if asset_ids else []
    if not valid:
        return {"ok": False, "error": "没有可分析的素材"}
    now = now_ms(); task_id = f"tag-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    conn.execute("insert into tag_analysis_tasks values (?, 'queued', ?, ?, ?, ?, 0, 0, '等待页面证据采集', '', 'evidence-v1', 'pending', ?, ?)",
                 (task_id, trigger_type, scope_type, json.dumps(valid), len(valid), now, now))
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
        sources.append({"priority": "P1", "type": "page_metadata", "title": item.get("title") or "", "text": " ".join(filter(None, [item.get("usage"), item.get("snippet")]))[:3000]})
    contexts = conn.execute("""
      select r.asset_code, r.title, s.page_number from report_page_slots s join assets r on r.id=s.report_id
      where s.control_id=? order by s.updated_at desc limit 12
    """, (item["id"],)).fetchall()
    if contexts:
        sources.append({"priority": "P2", "type": "report_context", "items": [dict(row) for row in contexts]})
    sources.append({"priority": "P4", "type": "structured_source", "sourceType": item.get("source_type") or "", "mediaKind": item.get("media_kind") or "", "resourceKind": item.get("resource_kind") or ""})
    return {"assetId": item["id"], "assetCode": item.get("asset_code") or "", "fingerprint": fingerprint(item), "status": "collected", "mode": "evidence-only", "sources": sources, "candidates": []}


def run_task(db_path, extracted_root, task_id):
    conn = sqlite3.connect(db_path, timeout=30); conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        with conn:
            task = conn.execute("select * from tag_analysis_tasks where id=?", (task_id,)).fetchone()
            if not task or task["status"] == "cancelled": return
            conn.execute("update tag_analysis_tasks set status='running', message='正在采集页面证据', updated_at=? where id=?", (now_ms(), task_id))
        ids = json.loads(task["scope_json"])
        errors = 0
        for index, asset_id in enumerate(ids, 1):
            with conn:
                current = conn.execute("select status from tag_analysis_tasks where id=?", (task_id,)).fetchone()
                if not current or current["status"] == "cancelled": return
                asset = conn.execute("select * from assets where id=?", (asset_id,)).fetchone()
                if not asset: errors += 1; continue
                evidence = collect_evidence(conn, asset, Path(extracted_root))
                conn.execute("""insert into asset_tag_evidence values (?, ?, ?, 'collected', ?, ?)
                  on conflict(asset_id) do update set source_fingerprint=excluded.source_fingerprint,evidence_json=excluded.evidence_json,status='collected',updated_at=excluded.updated_at""",
                  (asset_id, evidence["fingerprint"], json.dumps(evidence, ensure_ascii=False), now_ms(), now_ms()))
                conn.execute("update tag_analysis_tasks set processed_count=?, error_count=?, message=?, updated_at=? where id=?", (index, errors, f'已采集 {index}/{len(ids)} 页证据', now_ms(), task_id))
        with conn:
            conn.execute("update tag_analysis_tasks set status='completed', message='页面证据已采集；等待词表与模型启用后生成候选标签', updated_at=? where id=?", (now_ms(), task_id))
    except Exception as error:
        with conn: conn.execute("update tag_analysis_tasks set status='failed', error=?, message='页面证据采集失败', updated_at=? where id=?", (str(error)[:1000], now_ms(), task_id))
    finally: conn.close()
