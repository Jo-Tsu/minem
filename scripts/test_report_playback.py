#!/usr/bin/env python3
"""Regression checks for the shared player, conflict protection, and offline media."""

import json
import re
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
from minem.db import create_core_schema
from minem.offline_bundle import OfflineBundle


def check_player():
    document = server.report_viewer_html("A < B", [{"title": "</script>", "code": "CTRL-01", "src": "page.html", "canvas": {"width": 800, "height": 1200}}])
    assert "A &lt; B" in document
    raw = re.search(r'<script type="application/json" id="player-data">(.*?)</script>', document)[1]
    payload = json.loads(raw)
    assert payload["pages"][0]["title"] == "</script>"
    assert payload["pages"][0]["height"] == 1200 and payload["pages"][0]["id"] == "CTRL-01"
    assert "width:800px;height:1200px" in server.report_export_page_html("Page", "test.html", {"width": 800, "height": 1200})


def check_offline_bundle():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        extracted = root / "extracted"
        bundle = OfflineBundle(extracted, root / "export", excluded=lambda _: False)
        for upload in ("a", "b"):
            assets = extracted / upload / "assets"
            assets.mkdir(parents=True)
            (assets / "cover.svg").write_text(f"<svg id='{upload}'/>", encoding="utf-8")
            (assets / "layout.css").write_text('.slide{background:url("/assets/cover.svg?x=1&y=2")}', encoding="utf-8")
            nested = assets.parent / "nested"
            nested.mkdir()
            (nested / "index.html").write_text(
                '<head><base href="../assets/"><link href="layout.css" rel="stylesheet"></head>'
                '<img src="/assets/cover.svg"><a href="#local">Jump</a>'
                '<script>const snippet=\'<img src="/do-not-rewrite">\';</script>',
                encoding="utf-8",
            )
        output = bundle.add(extracted / "a/nested/index.html")
        other = bundle.add(extracted / "b/nested/index.html")
        for upload, page in (("a", output), ("b", other)):
            content = page.read_text(encoding="utf-8")
            assert '<base href="./">' in content
            assert 'src="../assets/cover.svg"' in content and 'href="#local"' in content
            assert '/do-not-rewrite' in content
            assert (page.parent / "../assets/cover.svg").read_text() == f"<svg id='{upload}'/>"
            assert 'url("cover.svg?x=1&y=2")' in (page.parent / "../assets/layout.css").read_text()


def check_arrangement():
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        create_core_schema(conn)
        conn.executemany("insert into assets (id, title, asset_type, created_at, updated_at) values (?, ?, ?, 1, 1)", [("report","Report","report"),("a","A","control"),("b","B","control")])
        conn.executemany("insert into report_page_slots (report_id,page_number,status,control_id,created_at,updated_at) values ('report',?,'attached',?,1,1)", [(1,"a"), (2,"b")])
        conn.commit()
        with patch.object(server,"db",return_value=conn), patch.object(server,"report_arrangement_payload",return_value={"ok":True}):
            assert server.update_report_arrangement("report",{"expectedUpdatedAt":0, "pageOrder":["b","a"]})["ok"]
            stale = server.update_report_arrangement("report",{"expectedUpdatedAt":0, "pageOrder":["a","b"]})
            assert stale["code"] == "ARRANGEMENT_CONFLICT"
            hidden = server.update_report_arrangement("report",{"hiddenPageIds":["a","b"]})
            assert not hidden["ok"]
        assert [row[0] for row in conn.execute("select control_id from report_page_slots order by page_number")] == ["b","a"]


if __name__ == "__main__":
    check_player()
    check_offline_bundle()
    check_arrangement()
    print("Shared playback, offline resources and arrangement safety passed")
