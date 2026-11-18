#!/usr/bin/env python3
"""Verify Miaoda assets preserve ownership and pass the normal ZIP audit."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minem.html_dependencies import audit_dependency_closure
from minem.native_deck import read_native_deck, render_native_deck
from minem.spark_package import has_online_spark_storage, prepare_spark_zip


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        package = root / "document"
        (package / ".spark").mkdir(parents=True)
        (package / ".spark/meta.json").write_text(json.dumps({"stack": "design-html", "app_id": "app_test"}))
        local = "/spark/app/app_test/runtime/api/v1/storage/object/bucket/banner.png"
        remote_path = "/spark/app/app_test/runtime/api/v1/storage/object/bucket/video.mp4"
        online = "https://example.feishuapp.cn" + remote_path
        (package / local.lstrip("/")).parent.mkdir(parents=True)
        (package / local.lstrip("/")).write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        (package / "assets").mkdir()
        (package / "assets/feishu-deck.js").write_text("// runtime")
        path = package / "index.html"
        path.write_text(f"""<!doctype html><head><meta name="fs-deck-generator" content="render-deck"></head>
<body><a href="https://example.larkoffice.com/docx/abc">source</a><div class="deck">
<div class="slide-frame"><div class="slide"><img src="{local}"></div></div>
<div class="slide-frame"><div class="slide"><video src="{online}"></video></div></div>
</div><script defer src="assets/feishu-deck.js"></script></body>""")
        saved = path.read_bytes()
        assert has_online_spark_storage(path)
        for invalid in (None, b"<!doctype html><html>Login</html>"):
            if invalid:
                (package / remote_path.lstrip("/")).write_bytes(invalid)
            try:
                prepare_spark_zip(root)
            except ValueError as error:
                assert "缺少 1 个原始媒体文件" in str(error)
            else:
                raise AssertionError("Incomplete media package accepted")
            assert path.read_bytes() == saved
        (package / remote_path.lstrip("/")).write_bytes(b"\x00\x00\x00\x18ftypmp42")
        assert prepare_spark_zip(root)
        text = path.read_text()
        assert f'src=".{local}"' in text and f'src=".{remote_path}"' in text
        assert not has_online_spark_storage(path)
        assert not audit_dependency_closure(package)["missing"]
        deck = read_native_deck(path)
        assert deck and deck.external_runtime and len(deck.frames) == 2
        only_second = render_native_deck(deck, [2], "/document/", single_page=True)
        assert local not in only_second and remote_path in only_second and "minemReplaceState" in only_second
        path.write_text(text.replace("src=\"assets/feishu-deck.js\"", "src=\"assets/missing.js\""))
        assert {i["resolved"] for i in audit_dependency_closure(package)["missing"]} == {"assets/missing.js"}
    print("Miaoda ZIP resource, strict dependency and native playback checks passed")


if __name__ == "__main__":
    main()
