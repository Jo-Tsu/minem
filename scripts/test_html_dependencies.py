#!/usr/bin/env python3
"""Small, isolated regression checks for HTML import dependency closure."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minem.html_dependencies import audit_dependency_closure, normalize_ephemeral_runtime_references
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

        (script_case / "index.html").write_text(
            '<script>URL.createObjectURL(new Blob([], { type: entry.mime }));</script>'
            '<style>.hero { background: url("assets/missing.png") }</style>',
            encoding="utf-8",
        )
        missing = audit_dependency_closure(script_case)["missing"]
        assert len(missing) == 1 and missing[0]["resolved"] == "assets/missing.png", missing

        runtime_case = root / "runtime-case"
        (runtime_case / "assets" / "gsap").mkdir(parents=True)
        (runtime_case / "assets" / "gsap" / "gsap.min.js").write_text("window.gsap = {};", encoding="utf-8")
        signed_base = "/decks/example/.runtime/signed-token/assets"
        (runtime_case / "index.html").write_text(
            f'<link rel="stylesheet" href="{signed_base}/framework/extra-layouts.css">'
            f'<script src="{signed_base}/gsap/gsap.min.js"></script>'
            f'<script src="{signed_base}/gsap/CustomEase.min.js"></script>'
            f'<img src="{signed_base}/images/required.png">',
            encoding="utf-8",
        )
        report = normalize_ephemeral_runtime_references(runtime_case)
        normalized = (runtime_case / "index.html").read_text(encoding="utf-8")
        assert report["changeCount"] == 3, report
        assert 'src="assets/gsap/gsap.min.js"' in normalized, normalized
        assert "extra-layouts.css" not in normalized and "CustomEase.min.js" not in normalized, normalized
        assert f'{signed_base}/images/required.png' in normalized, normalized
        missing = audit_dependency_closure(runtime_case)["missing"]
        assert len(missing) == 1 and missing[0]["resolved"].endswith("images/required.png"), missing
    print("html dependency checks passed")


if __name__ == "__main__":
    main()
