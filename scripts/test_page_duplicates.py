#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minem.db import SCHEMA_MIGRATIONS, create_core_schema, ensure_asset_schema
from minem.migrations import run_migrations
from minem.page_duplicates import (
    attach_duplicate_version,
    fingerprint_html,
    is_auto_reusable_visual,
    refresh_asset_fingerprint,
    thumbnail_difference,
)


def page_html(key: str, text: str, *, wrapper: str = "") -> str:
    return f"""<!doctype html><html><head><title>{text}</title>
    <style>body{{margin:0}}.slide{{width:1920px;height:1080px}}</style></head>
    <body>{wrapper}<main class="slide-frame"><section class="slide" data-slide-key="{key}">
    <h1>{text}</h1><script>window.runtimePath="/different/package";</script>
    </section></main></body></html>"""


def fingerprint_checks() -> None:
    first = fingerprint_html(page_html("stable-page", "这是同一张需要复用的业务页面正文"))
    second = fingerprint_html(
        page_html(
            "stable-page",
            "这是同一张需要复用的业务页面正文",
            wrapper="<script>window.packageId='other-upload'</script>",
        )
    )
    changed = fingerprint_html(page_html("stable-page", "这是另一张正文已经发生变化的页面"))
    ambiguous = fingerprint_html(
        """<main><section data-slide-key="one">A</section>
        <section data-slide-key="two">A</section></main>"""
    )
    assert first.fingerprint
    assert first.fingerprint == second.fingerprint
    assert first.text_hash == second.text_hash
    assert changed.fingerprint != first.fingerprint
    assert ambiguous.fingerprint == ""


def visual_checks(root: Path) -> None:
    first = root / "first.png"
    same = root / "same.png"
    changed = root / "changed.png"
    Image.new("RGB", (320, 180), "#0b1f33").save(first)
    Image.new("RGB", (640, 360), "#0b1f33").save(same)
    modified = Image.new("RGB", (320, 180), "#0b1f33")
    modified.paste(Image.new("RGB", (160, 90), "#ffffff"), (0, 0))
    modified.save(changed)

    same_metrics = thumbnail_difference(first, same, image_module=Image)
    changed_metrics = thumbnail_difference(first, changed, image_module=Image)
    assert is_auto_reusable_visual(same_metrics)
    assert not is_auto_reusable_visual(changed_metrics)


def version_checks(root: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_core_schema(conn)
    ensure_asset_schema(conn)
    run_migrations(conn, SCHEMA_MIGRATIONS)
    primary_path = root / "primary.html"
    duplicate_path = root / "duplicate.html"
    primary_path.write_text(
        page_html("same-page", "这是可复用的同一张业务页面正文"),
        encoding="utf-8",
    )
    duplicate_path.write_text(
        page_html(
            "same-page",
            "这是可复用的同一张业务页面正文",
            wrapper="<script>window.upload='next'</script>",
        ),
        encoding="utf-8",
    )
    conn.execute(
        """
        insert into assets
        (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
         preview_url,upload_id,source_hash,version_group,version_no,version_parent_id,
         created_at,updated_at)
        values
        ('primary','Primary','page','control','CTRL-PRIMARY','html','test','primary.html',
         '/extracted/test/primary.html','test','primary-hash','primary',1,'',1,1),
        ('duplicate','Duplicate','page','control','CTRL-DUPLICATE','html','test','duplicate.html',
         '/extracted/test/duplicate.html','test','duplicate-hash','duplicate',1,'',2,2),
        ('report','Report','report','report','RPT-TEST','html','test','report.html',
         '/reports/report/index.html','test','report-hash','report',1,'',1,1)
        """
    )
    conn.execute(
        """
        insert into report_page_slots
        (report_id,page_number,title,status,control_id,task_key,note,created_at,updated_at)
        values ('report',1,'Duplicate','completed','duplicate','','',2,2)
        """
    )
    primary_identity = refresh_asset_fingerprint(conn, "primary", primary_path)
    duplicate_identity = refresh_asset_fingerprint(conn, "duplicate", duplicate_path)
    assert primary_identity.fingerprint == duplicate_identity.fingerprint
    assert attach_duplicate_version(
        conn,
        asset_id="duplicate",
        primary_id="primary",
        similarity_score=1.0,
        timestamp=3,
    )
    duplicate = conn.execute(
        "select version_group,version_no,version_parent_id,similarity_method from assets where id='duplicate'"
    ).fetchone()
    assert dict(duplicate) == {
        "version_group": "primary",
        "version_no": 2,
        "version_parent_id": "primary",
        "similarity_method": "semantic-visual-v1",
    }
    slot = conn.execute(
        "select control_id from report_page_slots where report_id='report' and page_number=1"
    ).fetchone()
    assert slot["control_id"] == "duplicate"
    conn.close()


def main() -> None:
    fingerprint_checks()
    with tempfile.TemporaryDirectory(prefix="minem-page-duplicates-") as temp_dir:
        root = Path(temp_dir)
        visual_checks(root)
        version_checks(root)
    print("page duplicate checks passed")


if __name__ == "__main__":
    main()
