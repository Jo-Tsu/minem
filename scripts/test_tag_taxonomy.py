#!/usr/bin/env python3
"""Regression checks for the controlled MineM tag taxonomy."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minem.tag_tasks import collect_evidence, create_task, ensure_schema, run_task
from minem.tag_taxonomy import CONTROLLED_TAGS, FORBIDDEN_TAGS, classify_evidence, confirmed_candidates


def sample_evidence():
    evidence = {
        "sources": [
            {
                "priority": "P1",
                "type": "page_html",
                "title": "制造企业 AI 质量管理解决方案",
                "headings": ["质量问题与解决方案", "下一步行动计划"],
                "text": "面向管理层，通过人工智能质检提升生产效率并降低风险。",
            }
        ]
    }
    candidates = classify_evidence(evidence)
    confirmed = confirmed_candidates(candidates)
    tags = {item["tag"] for item in confirmed}
    assert tags <= CONTROLLED_TAGS
    assert not tags & FORBIDDEN_TAGS
    assert "制造" in tags
    assert "质量管理" in tags


def task_round_trip():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        db_path = root / "materials.db"
        page = root / "page.html"
        page.write_text(
            "<html><title>客户增长解决方案</title><body><h1>零售客户增长</h1>"
            "<p>为销售和门店提供客户增长方案。</p></body></html>",
            encoding="utf-8",
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
        create table assets (
          id text primary key,title text,usage text default '',snippet text default '',
          asset_type text,asset_code text,source_type text default '',source_path text default '',
          preview_url text default '',upload_id text,created_at integer,updated_at integer,
          source_hash text default '',media_kind text default '',resource_kind text default '',
          tags text default '',tag_seeded integer default 0
        );
        create table report_page_slots (
          report_id text,control_id text,page_number integer,updated_at integer
        );
        """)
        conn.execute(
            """insert into assets(id,title,asset_type,asset_code,source_path,created_at,updated_at)
            values ('a1','客户增长解决方案','control','CTRL-TEST-001',?,1,2)""",
            (str(page),),
        )
        ensure_schema(conn)
        result = create_task(conn, ["a1"], apply_mode="confirmed")
        conn.commit()
        conn.close()
        assert result["ok"]
        run_task(db_path, root, result["taskId"])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("select tags,updated_at from assets where id='a1'").fetchone()
        relations = {
            item["tag"] for item in conn.execute("select tag from asset_tags where asset_id='a1'")
        }
        assert set(filter(None, row["tags"].split(","))) == relations
        assert relations <= CONTROLLED_TAGS
        assert row["updated_at"] == 2
        conn.close()


if __name__ == "__main__":
    sample_evidence()
    task_round_trip()
    print("tag-taxonomy-ok")
