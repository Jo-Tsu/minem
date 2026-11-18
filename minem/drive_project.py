"""Fetch the playback files from a Drive authoring project's output directory."""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from minem.html_dependencies import DependencyParser, HTML_SUFFIXES, css_references, local_path


class DriveProject:
    def __init__(self, cli, job, request, deadline):
        self.cli = cli
        self.job = job
        self.request = request
        self.deadline = deadline
        self.directories = {}

    def run(self, args, timeout):
        for attempt in range(2):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not (self.job / "request.json").is_file():
                raise ValueError("飞书下载任务已超过等待时间")
            try:
                result = subprocess.run(
                    [self.cli, "drive", *args, "--as", "user"],
                    cwd=self.job, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=min(timeout, remaining),
                )
                response = json.loads(result.stdout)
            except (subprocess.TimeoutExpired, UnicodeDecodeError, json.JSONDecodeError):
                if attempt == 0:
                    continue
                raise ValueError("飞书目录或文件读取超时，自动重试后仍未完成") from None
            if not result.returncode and response.get("ok"):
                return response.get("data") or {}
            error = response.get("error") or {}
            if attempt == 0 and error.get("retryable") is True:
                continue
            if error.get("type") in {"auth", "authorization", "authentication"}:
                raise ValueError("飞书未授权访问，请确认本机飞书登录及文件夹权限")
            raise ValueError("飞书未能读取目录或文件，请检查链接及访问权限")

    def list_folder(self, token):
        if token not in self.directories:
            entries = {}
            page_token = ""
            while True:
                args = ["files", "list", "--folder-token", token, "--page-size", "200"]
                if page_token:
                    args += ["--page-token", page_token]
                data = self.run(args, 30)
                for item in data.get("files") or []:
                    name = item["name"]
                    entries[name] = item if name not in entries else None
                if not data.get("has_more"):
                    break
                next_page = data.get("next_page_token")
                if not next_page or next_page == page_token:
                    raise ValueError("未能完整列出飞书文件夹")
                if len(entries) > self.request["max_files"]:
                    raise ValueError("飞书目录包含过多文件")
                page_token = next_page
            self.directories[token] = entries
        return self.directories[token]

    def find_file(self, token, relative):
        parts = relative.parts
        for index, name in enumerate(parts):
            entries = self.list_folder(token)
            item = entries.get(name)
            if name in entries and item is None:
                raise ValueError(f"飞书目录中存在同名文件或文件夹：{relative.as_posix()}")
            expected = "file" if index == len(parts) - 1 else "folder"
            if not item or item.get("type") != expected:
                return None
            token = item["token"]
        return token

    def fetch(self, item):
        path, token = item
        path.parent.mkdir(parents=True, exist_ok=True)
        self.run([
            "+download", "--file-token", token, "--output", path.relative_to(self.job).as_posix(), "--overwrite",
        ], 240)
        if not path.is_file():
            raise ValueError("飞书未能保存汇报所需文件")
        return path

    def download_export(self, token, progress):
        root = self.job / "drive-source"
        root.mkdir()
        seen = set()
        required = {root / "index.html"}
        optional = {root / "slide-index.json"}
        received = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            while required or optional:
                requests = []
                for path in sorted((required | optional) - seen):
                    relative = path.relative_to(root)
                    file_token = self.find_file(token, relative)
                    if not file_token and path in required:
                        raise ValueError(f"飞书汇报缺少播放所需文件：{relative.as_posix()}")
                    if file_token:
                        requests.append((path, file_token))
                    seen.add(path)
                if len(seen) > self.request["max_files"]:
                    raise ValueError("飞书汇报引用的文件数量超过素材包限制")
                required.clear()
                optional.clear()
                for finished in as_completed(pool.submit(self.fetch, item) for item in requests):
                    path = finished.result()
                    received += path.stat().st_size
                    if received > self.request["max_bytes"]:
                        raise ValueError("飞书汇报所需资源超过素材包大小限制")
                    progress(received)
                    for value, base in playback_references(path):
                        target = local_path(root, path, base, value)
                        if target and target not in seen and len(target.relative_to(root).parts) <= 32:
                            required.add(target)


def playback_references(path):
    suffix = path.suffix.lower()
    if suffix == ".css":
        return [(value, "") for value in css_references(path.read_text(encoding="utf-8", errors="replace"))]
    if suffix not in HTML_SUFFIXES:
        return []
    parser = DependencyParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser.close()
    parser.finish()
    return [(value, parser.base_href) for _, value in parser.references]
