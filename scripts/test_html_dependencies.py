#!/usr/bin/env python3
"""Small, isolated regression checks for HTML import dependency closure."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minem.html_dependencies import audit_dependency_closure
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
    print("html dependency checks passed")


if __name__ == "__main__":
    main()
