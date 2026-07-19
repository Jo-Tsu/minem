#!/usr/bin/env python3
"""MineM CLI: wraps the local MineM HTTP API for material workflows."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "http://127.0.0.1:8790"


class MineMClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, body=None, headers=None):
        payload = None
        request_headers = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=payload, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8"))
            except Exception:
                detail = {"ok": False, "error": error.reason}
            detail.setdefault("ok", False)
            return detail
        except urllib.error.URLError as error:
            return {"ok": False, "error": f"无法连接 MineM：{error.reason}。请先运行 python3 server.py"}

    def upload(self, path: Path, description: str = ""):
        boundary = f"----MineM{int(time.time() * 1000)}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"description\"\r\n\r\n{description}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(
            self.base_url + "/api/import-tasks",
            data=b"".join(chunks), method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                return json.loads(error.read().decode("utf-8"))
            except Exception:
                return {"ok": False, "error": error.reason}
        except urllib.error.URLError as error:
            return {"ok": False, "error": f"无法连接 MineM：{error.reason}"}


def emit(result, as_json: bool):
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("ok", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"错误：{result.get('error', '未知错误')}", file=sys.stderr)
    return 0 if result.get("ok", False) else 1


def require_file(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"文件不存在：{path}")
    return path


def ids(value: str):
    return [item.strip() for item in value.split(",") if item.strip()]


def import_file(client, args):
    return client.upload(args.file, args.description or args.title or "")


def report_create(client, args):
    controls = ids(args.controls)
    if not controls:
        return {"ok": False, "error": "创建汇报至少需要一个已有页面素材 ID（--controls）"}
    return client.request("POST", "/api/storyline-reports", {
        "mode": "manual", "title": args.title, "controlIds": controls, "note": args.note or "",
    })


def report_pages(client, args):
    return client.request("GET", f"/api/reports/{urllib.parse.quote(args.report_id)}/pages")


def report_arrange(client, args):
    if not args.yes:
        return {"ok": False, "error": "该操作会更新正式汇报页面顺序；请添加 --yes 确认"}
    current = client.request("GET", f"/api/reports/{urllib.parse.quote(args.report_id)}/arrangement")
    if not current.get("ok"):
        return current
    arrangement = current.get("arrangement", current)
    order = list(arrangement.get("pageOrder") or arrangement.get("page_order") or [])
    hidden = list(arrangement.get("hiddenPageIds") or arrangement.get("hidden_page_ids") or [])
    if args.replace:
        old, new = args.replace.split(":", 1)
        if old not in order:
            return {"ok": False, "error": f"当前汇报未引用页面素材：{old}"}
        order[order.index(old)] = new
    if args.add:
        new, after = args.add.split(":", 1)
        if after not in order:
            return {"ok": False, "error": f"插入位置不存在：{after}"}
        order.insert(order.index(after) + 1, new)
    return client.request("POST", f"/api/reports/{urllib.parse.quote(args.report_id)}/arrangement", {
        "pageOrder": order,
        "hiddenPageIds": hidden,
    })


def page_create(client, args):
    # A page remains a first-class MineM asset by going through the normal importer.
    return client.upload(args.file, args.title or "页面素材")


def case_create(client, args):
    source = args.file.read_text(encoding="utf-8", errors="replace")
    title = args.title or args.file.stem
    lines = [line.strip("# -*\t ") for line in source.splitlines() if line.strip()]
    body = "\n".join(f"<p>{html.escape(line)}</p>" for line in lines[:80]) or "<p>待补充案例内容</p>"
    document = f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title><style>body{{margin:0;background:#071727;color:#edf5ff;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif}}main{{box-sizing:border-box;width:1600px;min-height:900px;padding:76px 112px;background:linear-gradient(135deg,#0b2b4b,#08131f)}}h1{{font-size:56px;margin:0 0 42px}}p{{font-size:26px;line-height:1.65;max-width:1220px;margin:12px 0;color:#d4e4f4}}</style></head><body><main class=\"slide-frame\"><h1>{html.escape(title)}</h1>{body}</main></body></html>"""
    with tempfile.NamedTemporaryFile("w", suffix="-case.html", encoding="utf-8", delete=False) as handle:
        handle.write(document)
        generated = Path(handle.name)
    try:
        return client.upload(generated, f"客户案例,案例页,{args.industry or ''}")
    finally:
        generated.unlink(missing_ok=True)


def build_parser():
    parser = argparse.ArgumentParser(prog="minem", description="MineM 本地素材工作台 CLI")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--json", action="store_true")
    commands = parser.add_subparsers(dest="group", required=True)

    import_cmd = commands.add_parser("import", help="导入外部汇报或页面材料")
    import_sub = import_cmd.add_subparsers(dest="action", required=True)
    for name in ("report", "page"):
        item = import_sub.add_parser(name)
        item.add_argument("file", type=require_file)
        item.add_argument("--title")
        item.add_argument("--description")
        item.set_defaults(handler=import_file)

    task = commands.add_parser("task", help="查看导入任务")
    task_sub = task.add_subparsers(dest="action", required=True)
    task_get = task_sub.add_parser("get")
    task_get.add_argument("task_id")
    task_get.set_defaults(handler=lambda client, args: client.request("GET", f"/api/import-tasks/{urllib.parse.quote(args.task_id)}"))

    report = commands.add_parser("report", help="创建或修改汇报")
    report_sub = report.add_subparsers(dest="action", required=True)
    create = report_sub.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--controls", required=True, help="逗号分隔的 CTRL 页面素材内部 ID")
    create.add_argument("--note")
    create.set_defaults(handler=report_create)
    pages = report_sub.add_parser("pages")
    pages.add_argument("report_id")
    pages.set_defaults(handler=report_pages)
    arrange = report_sub.add_parser("page", help="新增或替换汇报页面")
    arrange.add_argument("report_id")
    group = arrange.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", help="新页面ID:现有页面ID，插入到现有页之后")
    group.add_argument("--replace", help="旧页面ID:新页面ID")
    arrange.add_argument("--yes", action="store_true")
    arrange.set_defaults(handler=report_arrange)

    page = commands.add_parser("page", help="新增页面素材")
    page_sub = page.add_subparsers(dest="action", required=True)
    page_create_cmd = page_sub.add_parser("create")
    page_create_cmd.add_argument("--file", required=True, type=require_file, help="单页 HTML 或标准页面模板 ZIP")
    page_create_cmd.add_argument("--title")
    page_create_cmd.set_defaults(handler=page_create)

    case = commands.add_parser("case", help="外部文档转案例页面素材")
    case_sub = case.add_subparsers(dest="action", required=True)
    case_create_cmd = case_sub.add_parser("create")
    case_create_cmd.add_argument("--file", required=True, type=require_file, help="UTF-8 Markdown 或 TXT 文档")
    case_create_cmd.add_argument("--title")
    case_create_cmd.add_argument("--industry")
    case_create_cmd.set_defaults(handler=case_create)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    return emit(args.handler(MineMClient(args.base_url), args), args.json)


if __name__ == "__main__":
    raise SystemExit(main())
