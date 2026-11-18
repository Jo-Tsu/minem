#!/usr/bin/env python3
"""Exercise ownership and asset integrity for image deck imports."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minem.image_deck import prepare_image_deck
from minem.html_dependencies import audit_dependency_closure


def main():
    with TemporaryDirectory() as path:
        root = Path(path)
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAgUBAO+XWxkAAAAASUVORK5CYII="
        original = """<!doctype html><html><head><title>A &amp; B</title></head><body>
<script>(()=>{const images=%s,media=%s,videoBase="";function source(video,item) {video.dataset.src=videoBase+item.file}})()</script>
</body></html>""" % (json.dumps([png, png]), json.dumps({"1":[{"file":"clip.mp4"}], "2":[{"file":"clip.mp4"}]}))
        (root / "clip.mp4").write_bytes(b"video fixture")
        (root / "source.html").write_text(original, encoding="utf-8")
        report = prepare_image_deck(root, lambda title, pages: f"<title>{title}</title>")
        assert report["title"] == "A & B"
        assert len(report["pages"]) == 2
        for pos, page in enumerate(report["pages"], 1):
            index = root / page["path"]
            document = index.read_text(encoding="utf-8")
            owned = json.loads((index.parent / "manifest.json").read_text(encoding="utf-8"))
            assert owned["sourcePage"] == pos and "data:image" not in document
            assert len(owned["resources"]) == 2
            assert (index.parent / owned["resources"][1]).read_bytes() == b"video fixture"
            assert not audit_dependency_closure(index.parent)["missing"]
        (root / "owned-pages/page-001/assets/video-01/clip.mp4").unlink()
        assert (root / "owned-pages/page-002/assets/video-01/clip.mp4").is_file()
        assert (root / "source.html").read_text(encoding="utf-8") == original
    print("Image deck page isolation and media package checks passed")


if __name__ == "__main__":
    main()
