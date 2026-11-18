#!/usr/bin/env python3
"""Check native frame selection, preserved layout, and portable deck resources."""

import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
from minem.html_dependencies import audit_dependency_closure
from minem.native_deck import read_native_deck, render_native_deck
from minem.report_package_importer import load_report_package_manifest


def main():
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        extracted = root / "extracted"
        source = extracted / "upload" / "nested" / "deck.html"
        styles = source.parent / "theme"
        styles.mkdir(parents=True)
        (styles / "layout.css").write_text(".slide{background:url(cover.svg)}", encoding="utf-8")
        (styles / "cover.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        document = """<!doctype html><html lang="zh-CN"><head>
<meta name="fs-deck-generator" content="render-deck">
<title>Feishu &amp; Deck</title>
<base href="theme/" target="_self"><link rel="stylesheet" href="layout.css">
</head><body><div class="deck" data-mode="present">
<div class="slide-frame is-current"><div class="slide" data-slide-key="opening">Opening</div></div>
<div class="slide-frame"><div class="slide" data-slide-key="closing">Closing</div></div>
</div><div class="deck-controls">Native navigation</div>
<script>function goTo(deck, frames, idx) { const newHash = "#" + (idx + 1); history.replaceState(null, '', newHash); }</script>
</body></html>"""
        source.write_text(document, encoding="utf-8")
        deck = read_native_deck(source)
        assert deck and len(deck.frames) == 2
        reordered = render_native_deck(deck, [2, 1], "/extracted/upload/nested/theme/")
        assert reordered.index('data-slide-key="closing"') < reordered.index('data-slide-key="opening"')
        assert reordered.count('class="slide-frame is-current"') == 1
        assert 'target="_self"' in reordered and "Native navigation" in reordered
        assert "new URL(newHash, location.href)" in reordered
        one_page = render_native_deck(deck, [2], "/extracted/upload/nested/theme/", single_page=True)
        assert "Opening</div>" not in one_page and 'data-slide-key="closing"' in one_page
        cover = render_native_deck(deck, [2], "/extracted/upload/nested/theme/", single_page=True, cover_title='Feishu & "Deck"')
        assert 'name="minem-cover-title" content="Feishu &amp; &quot;Deck&quot;"' in cover
        assert 'data-slide-key="opening"' not in cover
        manifest, kind = load_report_package_manifest(source.parent, read_json_file=lambda _: {})
        assert kind == "html-report" and manifest["title"] == "Feishu & Deck"

        package = root / "export"
        with patch.object(server, "EXTRACTED", extracted):
            server.write_native_deck_export(source, [2, 1], package / "index.html", package)
        exported = (package / "index.html").read_text(encoding="utf-8")
        assert re.search(r'<base href="deck-resources/upload/nested/theme/"', exported)
        assert (package / "deck-resources/upload/nested/theme/cover.svg").is_file()
        assert not audit_dependency_closure(package)["missing"]
        assert source.read_text(encoding="utf-8") == document
    print("native deck rendering and offline resource checks passed")


if __name__ == "__main__":
    main()
