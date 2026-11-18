"""Describe the files actually included in a portable HTML delivery."""

import hashlib
import json
import re
from pathlib import Path


def download_name(value):
    name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "-", str(value or "")).strip(" .")
    return name.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .") or "汇报素材"


def write_delivery_inventory(root, manifest, manifest_name="minem-export-manifest.json"):
    root = Path(root)
    excluded = {manifest_name, "assets-manifest.yaml", "README.md", ".minem-dependency-audit.json"}
    resources = []
    groups = {"framework": [], "deck-local": [], "shared": []}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or relative in excluded:
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        resources.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest.hexdigest()})
        group = "framework" if path.suffix.lower() in {".js", ".css"} else "deck-local"
        groups[group].append(relative)
    manifest.update(standardVersion=1, entry="index.html", canvas={"width": 1920, "height": 1080}, resources=resources)
    (root / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Paths are relative to index.html. Generated from the delivered files."]
    for group, values in groups.items():
        lines.append(f"{group}:" if values else f"{group}: []")
        lines.extend("  - " + json.dumps(value, ensure_ascii=False) for value in values)
    (root / "assets-manifest.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# HTML 汇报文件\n\n"
        "解压整个 ZIP 后，用浏览器打开根目录 index.html。保留目录结构。\n\n"
        "推荐使用近期版本的 Chrome、Edge 或 Safari。基本播放无需运行 MineM。\n\n"
        "使用页面上的前后箭头、键盘左右方向键或页码输入框翻页，全屏按钮进入全屏。"
        "在输入框和媒体控件中，按键由该控件处理。视频和音频需要点击播放。\n\n"
        "pages、sources、deck-resources、assets、input、prototypes 为实际页面和依赖目录，"
        "具体目录以本包为准。assets-manifest.yaml 列出文件，JSON 清单记录页序、来源和 SHA-256。\n\n"
        "媒体按原始字节保存。PDF 是静态副本，音视频和互动请打开 HTML。\n\n"
        "本格式的隔离验收使用 Chromium，覆盖本地文件打开、中文与空格路径、"
        "翻页及媒体暂停。各来源页面的业务交互和浏览器差异需结合实际内容验收。\n",
        encoding="utf-8",
    )
