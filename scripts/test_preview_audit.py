#!/usr/bin/env python3
"""Ensure the preview audit recognizes the current supported viewers."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
import run_core_tests as audit
from minem.native_deck import read_native_deck, render_native_deck


class PreviewAuditChecks(unittest.TestCase):
    def test_current_shared_player_has_supported_scaling(self):
        document = server.report_viewer_html("Report", [{"src": "page.html", "canvas": {"width": 1920, "height": 1080}}])
        self.assertTrue(audit.has_scaled_viewer(document))

    def test_native_player_keeps_its_scaling_and_fullscreen(self):
        with tempfile.TemporaryDirectory() as runtime:
            path = Path(runtime) / "index.html"
            path.write_text('<html><head><meta name="fs-deck-generator" content="render-deck"><style>.slide{width:1920px;height:1080px}</style></head><body><div class="deck"><div class="slide-frame"><div class="slide">Page</div></div></div><script>function goTo(deck, frames, idx){const scale=Math.min(innerWidth/1920,innerHeight/1080);}function fullscreen(){document.documentElement.requestFullscreen();}</script></body></html>')
            deck = read_native_deck(path)
            self.assertIsNotNone(deck)
            self.assertTrue(audit.has_scaled_viewer(render_native_deck(deck, [1], "./")))

    def test_plain_html_does_not_pass_the_viewer_audit(self):
        self.assertFalse(audit.has_scaled_viewer("<html><body>Plain page</body></html>"))


if __name__ == "__main__":
    unittest.main()
