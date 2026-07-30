#!/usr/bin/env python3
"""Regression checks for deterministic MineM HTML page generation."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from minem.html_page_builder import HtmlPageBuildError, build_page_file, render_page_html


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="minem-html-page-") as temp:
        root = Path(temp)
        image = root / "proof.png"
        image.write_bytes(PNG_1X1)
        spec = root / "page.json"
        spec.write_text(
            json.dumps(
                {
                    "title": "AI <落地> 价值",
                    "eyebrow": "经营汇报",
                    "subtitle": "从试点走向规模化",
                    "body": ["用统一方法管理页面素材。"],
                    "bullets": ["生成", "校验", "导入"],
                    "metrics": [{"value": "42%", "label": "效率提升"}],
                    "image": "proof.png",
                    "layout": "split",
                    "theme": "light",
                    "accent": "#1687FF",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        output, normalized = build_page_file(spec)
        document = output.read_text(encoding="utf-8")
        assert normalized["title"] == "AI <落地> 价值"
        assert 'content="1920x1080"' in document
        assert "width: 1920px" in document and "height: 1080px" in document
        assert "AI &lt;落地&gt; 价值" in document
        assert "data:image/png;base64," in document
        assert 'src="http' not in document and 'src="https' not in document
        assert "requestFullscreen" not in document

        try:
            render_page_html({"title": "远程图片", "image": "https://example.com/image.png"}, base_dir=root)
        except HtmlPageBuildError:
            pass
        else:
            raise AssertionError("remote image dependencies must be rejected")

        try:
            render_page_html({"title": "内联图片", "image": "data:image/png;base64,AAAA"}, base_dir=root)
        except HtmlPageBuildError:
            pass
        else:
            raise AssertionError("input data URIs must be rejected")

    print("html page builder checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
