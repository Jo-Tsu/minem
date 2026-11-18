#!/usr/bin/env python3
"""Small, isolated regression checks for HTML import dependency closure."""

from __future__ import annotations

import tempfile
from http.client import HTTPException
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minem.html_dependencies import audit_dependency_closure
from minem.drive_fonts import localize_drive_fonts
from minem.hosted_deck_media import check_mp4, localize_hosted_deck_media
from minem.imports import copy_html_dependency_bundle


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "assets").mkdir()
        (root / "assets" / "ok.png").write_bytes(b"png")
        (root / "nested.html").write_text('<img data-fs-src="assets/ok.png">', encoding="utf-8")
        (root / "index.html").write_text('<iframe src="nested.html"></iframe>', encoding="utf-8")
        assert not audit_dependency_closure(root)["missing"]

        (root / "nested.html").write_text('<img data-fs-src="assets/missing.png">', encoding="utf-8")
        missing = audit_dependency_closure(root)["missing"]
        assert len(missing) == 1 and missing[0]["resolved"] == "assets/missing.png", missing

        source = root / "source"
        (source / "assets").mkdir(parents=True)
        (source / "assets" / "ok.png").write_bytes(b"png")
        (source / "nested.html").write_text('<img data-fs-src="assets/ok.png">', encoding="utf-8")
        (source / "index.html").write_text('<iframe src="nested.html"></iframe>', encoding="utf-8")
        target = root / "target"
        copied, _ = copy_html_dependency_bundle(source / "index.html", target, "sample")
        assert (copied.parent / "nested.html").exists()
        assert (copied.parent / "assets" / "ok.png").exists()

        (source / "index.html").write_text(
            '<svg><image href="assets/ok.png"/><use xlink:href="assets/symbols.svg#tick"/>'
            '<use href="#inline"/></svg><a href="other.html">链接</a>',
            encoding="utf-8",
        )
        missing = audit_dependency_closure(source)["missing"]
        assert [item["resolved"] for item in missing] == ["assets/symbols.svg"], missing
        (source / "assets" / "symbols.svg").write_text('<svg><symbol id="tick"/></svg>', encoding="utf-8")
        svg_page, _ = copy_html_dependency_bundle(source / "index.html", target, "svg")
        assert (svg_page.parent / "assets" / "ok.png").is_file()
        assert (svg_page.parent / "assets" / "symbols.svg").is_file()
        assert not audit_dependency_closure(svg_page.parent)["missing"]

        (root / "nested.html").write_text('<iframe src="/extracted/demo/nested.html"></iframe>', encoding="utf-8")
        # Platform URLs pointing at another package are intentionally ignored by this package audit.
        assert not audit_dependency_closure(root)["missing"]

        script_case = root / "script-case"
        (script_case / "assets").mkdir(parents=True)
        (script_case / "assets" / "ok.png").write_bytes(b"png")
        (script_case / "index.html").write_text(
            """
            <script>
              function url(t) { return t; }
              const image = URL.createObjectURL(new Blob([finalBytes], { type: entry.mime }));
            </script>
            <style>.hero { background-image: url("assets/ok.png"); }</style>
            <div style="mask-image: url('assets/ok.png')"></div>
            """,
            encoding="utf-8",
        )
        assert not audit_dependency_closure(script_case)["missing"]

        # CSS in HTML style attributes commonly quotes data URLs using entities.
        embedded_image = "data:image/jpeg;base64," + "A" * 4096
        (source / "index.html").write_text(
            f'<section style="--cover: url(&quot;{embedded_image}&quot;); '
            'background-image: url(&quot;assets/ok.png&quot;)"></section>',
            encoding="utf-8",
        )
        encoded_page, _ = copy_html_dependency_bundle(source / "index.html", target, "encoded")
        assert embedded_image in encoded_page.read_text(encoding="utf-8")
        assert (encoded_page.parent / "assets" / "ok.png").is_file()
        assert not audit_dependency_closure(encoded_page.parent)["missing"]

        (script_case / "index.html").write_text(
            '<script>URL.createObjectURL(new Blob([], { type: entry.mime }));</script>'
            '<style>.hero { background: url("assets/missing.png") }</style>',
            encoding="utf-8",
        )
        missing = audit_dependency_closure(script_case)["missing"]
        assert len(missing) == 1 and missing[0]["resolved"] == "assets/missing.png", missing

        hosted = root / "hosted"
        hosted.mkdir()
        entry = hosted / "index.html"
        original = (
            '<base href="https://example.feishuapp.cn/app/demo/deck/">'
            '<img src="cover.png"><video poster="poster.jpg">'
            '<source src="clips/movie.mp4"><source src="clips/movie.mp4#t=2">'
            '</video>'
        )
        entry.write_text(original)
        def save_media(url, target, base):
            assert url.startswith(base.geturl())
            target.write_bytes(b"local media")
            return target.stat().st_size

        with patch("minem.hosted_deck_media.download_media", side_effect=save_media) as fetch:
            assert localize_hosted_deck_media(entry)
            assert fetch.call_count == 2
        localized = entry.read_text()
        assert '<base href="./">' in localized
        assert 'https://example.feishuapp.cn/app/demo/deck/cover.png' in localized
        assert '-movie.mp4#t=2' in localized
        assert not audit_dependency_closure(hosted)["missing"]

        movie = hosted / "checks.mp4"
        movie.write_bytes(b"\0\0\0\x08moov\0\0\0\x0cmdatdata")
        check_mp4(movie, movie.stat().st_size)
        try:
            check_mp4(movie, movie.stat().st_size - 1)
        except HTTPException:
            pass
        else:
            raise AssertionError("A cut-off MP4 must be rejected")

        page = root / "drive-page"
        prototype = page / "assets" / "prototype"
        prototype.mkdir(parents=True)
        (page / "index.html").write_text('<iframe src="assets/prototype/index.html"></iframe>')
        stylesheet = "https://miaoda.feishu.cn/fonts/css2?family=Noto+Sans+SC"
        font_url = "https://sf3-scmcdn-cn.feishucdn.com/obj/feishu-static/lark-miaoda-fonts/fonts/noto-sans-sc/test.woff2"
        prototype_html = prototype / "index.html"
        prototype_html.write_text(f'<link rel="stylesheet" href="{stylesheet}"><p>演示</p>')
        before = audit_dependency_closure(page, require_local=True)
        assert before["remote"] == {"source": "assets/prototype/index.html", "host": "miaoda.feishu.cn"}
        sample_font = b"wOF2" + bytes(4) + (48).to_bytes(4, "big") + bytes(36)
        css = f"@font-face {{ font-family: 'Noto Sans SC'; src: url({font_url}); }}".encode()
        with patch("minem.drive_fonts.read_font_resource", side_effect=lambda url, _: {stylesheet: css, font_url: sample_font}[url]):
            localize_drive_fonts(page, root / "font-cache")
        assets = list(prototype.rglob("*.woff2"))
        assert len(assets) == 1 and assets[0].read_bytes() == sample_font
        after = audit_dependency_closure(page, require_local=True)
        assert not after["remote"] and not after["missing"]
    print("html dependency checks passed")


if __name__ == "__main__":
    main()
