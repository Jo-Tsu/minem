"""MineM CLI domain commands."""

from __future__ import annotations

import html
import importlib.metadata
import json
import tempfile
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .config import config_path, load_config, runtime_details, set_value, unset_value
from .contracts import CliError, EXIT_CONFIRMATION, absolute_url, normalize_asset
from .resolver import TYPE_TO_API, resolve_asset, resolve_assets


@dataclass
class CommandContext:
    client: Any
    base_url: str
    timeout: int
    no_input: bool


def _version() -> str:
    try:
        return importlib.metadata.version("minem-cli")
    except importlib.metadata.PackageNotFoundError:
        path = Path(__file__).resolve().parents[2] / "product-version.json"
        try:
            return str(json.loads(path.read_text(encoding="utf-8")).get("version") or "dev")
        except (OSError, ValueError):
            return "dev"


def version(ctx: CommandContext, args) -> dict:
    server = None
    try:
        server = ctx.client.request("GET", "/api/version").get("release")
    except CliError:
        pass
    return {"version": _version(), "schemaVersion": SCHEMA_VERSION, "server": server}


def status(ctx: CommandContext, args) -> dict:
    release = ctx.client.request("GET", "/api/version").get("release") or {}
    stats = ctx.client.request("GET", "/api/stats")
    return {"connected": True, "release": release, "stats": stats}


def doctor(ctx: CommandContext, args) -> dict:
    release = ctx.client.request("GET", "/api/version").get("release") or {}
    compatible = int(release.get("apiVersion") or 0) == 1
    if not compatible:
        raise CliError("API_INCOMPATIBLE", "MineM server API is not compatible with CLI Schema v1", details=release)
    return {
        "healthy": True,
        "checks": [
            {"name": "configuration", "ok": True, "path": str(config_path())},
            {"name": "server", "ok": True, "url": ctx.base_url},
            {"name": "api", "ok": True, "version": release.get("apiVersion")},
        ],
        "runtime": runtime_details(),
    }


def config_command(ctx: CommandContext, args) -> dict:
    if args.config_action == "list":
        return {"values": load_config(), "path": str(config_path())}
    if args.config_action == "get":
        payload = load_config()
        if args.key not in payload:
            raise CliError("NOT_FOUND", f"Config value is not set: {args.key}")
        return {"key": args.key, "value": payload[args.key], "path": str(config_path())}
    if args.config_action == "set":
        return set_value(args.key, args.value)
    return unset_value(args.key)


def completion(ctx: CommandContext, args) -> dict:
    commands = "version status doctor config completion asset import page report case task agent"
    if args.shell == "zsh":
        script = f"#compdef minem\n_arguments '1:command:({commands})' '*::arg:->args'\n"
    elif args.shell == "fish":
        script = "\n".join(f"complete -c minem -f -a '{name}'" for name in commands.split()) + "\n"
    else:
        script = f"_minem_completion() {{ COMPREPLY=($(compgen -W \"{commands}\" -- \"${{COMP_WORDS[1]}}\")); }}\ncomplete -F _minem_completion minem\n"
    return {"shell": args.shell, "script": script}


def _asset_list(ctx: CommandContext, asset_type: str, query_text: str, limit: int, include_versions: bool = False) -> dict:
    api_type = TYPE_TO_API.get(asset_type, asset_type)
    query = urllib.parse.urlencode({
        "type": api_type,
        "q": query_text,
        "include_versions": "1" if include_versions else "0",
        "page": "1",
        "page_size": max(1, min(limit, 200)),
        "view": "list",
    })
    payload = ctx.client.request("GET", f"/api/assets?{query}")
    items = [normalize_asset(asset, ctx.base_url) for asset in payload.get("assets") or []]
    rows = [{"code": item["code"], "type": item["type"], "title": item["title"], "version": item["version"]} for item in items]
    return {
        "items": items,
        "pagination": payload.get("pagination") or {},
        "rows": rows,
        "columns": [
            {"key": "code", "label": "CODE"},
            {"key": "type", "label": "TYPE"},
            {"key": "title", "label": "TITLE"},
            {"key": "version", "label": "VERSION"},
        ],
    }


def asset_list(ctx: CommandContext, args) -> dict:
    return _asset_list(ctx, args.type, args.query or "", args.limit, args.include_versions)


def asset_get(ctx: CommandContext, args) -> dict:
    return {"asset": normalize_asset(resolve_asset(ctx.client, args.reference, args.type), ctx.base_url)}


def asset_versions(ctx: CommandContext, args) -> dict:
    asset = resolve_asset(ctx.client, args.reference, args.type)
    payload = ctx.client.request("GET", f"/api/assets/{urllib.parse.quote(asset['id'])}/versions")
    raw_versions = payload.get("versions") or [asset]
    items = [normalize_asset(item, ctx.base_url) for item in raw_versions]
    rows = [
        {"version": item.get("version"), "code": item.get("code"), "title": item.get("title"), "id": item.get("id")}
        for item in items
    ]
    return {
        "asset": normalize_asset(asset, ctx.base_url),
        "items": items,
        "rows": rows,
        "columns": [
            {"key": "version", "label": "VERSION"},
            {"key": "code", "label": "CODE"},
            {"key": "title", "label": "TITLE"},
            {"key": "id", "label": "ID"},
        ],
    }


def asset_lineage(ctx: CommandContext, args) -> dict:
    asset = resolve_asset(ctx.client, args.reference, args.type)
    payload = ctx.client.request("GET", f"/api/assets/{urllib.parse.quote(asset['id'])}/lineage")
    return {"asset": normalize_asset(asset, ctx.base_url), "lineage": payload}


def asset_open(ctx: CommandContext, args) -> dict:
    asset = normalize_asset(resolve_asset(ctx.client, args.reference, args.type), ctx.base_url)
    url = asset.get("previewUrl") or ""
    if not url:
        raise CliError("NOT_FOUND", f"Asset has no preview URL: {args.reference}")
    if not args.print_only and not ctx.no_input:
        webbrowser.open(url)
    return {"asset": asset, "opened": not args.print_only and not ctx.no_input, "url": url}


def asset_rename(ctx: CommandContext, args) -> dict:
    asset = resolve_asset(ctx.client, args.reference, args.type)
    payload = ctx.client.request("POST", f"/api/assets/{urllib.parse.quote(asset['id'])}/title", {"title": args.name})
    return {"asset": normalize_asset(payload.get("asset"), ctx.base_url)}


def _require_confirm(args, message: str) -> None:
    if not getattr(args, "confirm", False) and not getattr(args, "dry_run", False):
        raise CliError("CONFIRMATION_REQUIRED", message, exit_code=EXIT_CONFIRMATION)


def asset_delete(ctx: CommandContext, args) -> dict:
    asset = resolve_asset(ctx.client, args.reference, args.type)
    _require_confirm(args, "Deleting an asset requires --confirm")
    resource = normalize_asset(asset, ctx.base_url)
    if args.dry_run:
        return {"asset": resource, "dryRun": True, "operation": "delete"}
    payload = ctx.client.request("DELETE", f"/api/assets/{urllib.parse.quote(asset['id'])}")
    return {"asset": resource, "deleted": True, "server": payload}


def task_list(ctx: CommandContext, args) -> dict:
    tasks = ctx.client.request("GET", "/api/import-tasks").get("tasks") or []
    rows = [{"id": item.get("id"), "status": item.get("status"), "progress": item.get("progress"), "file": item.get("fileName")} for item in tasks]
    return {"items": tasks, "rows": rows, "columns": [{"key": "id", "label": "TASK"}, {"key": "status", "label": "STATUS"}, {"key": "progress", "label": "%"}, {"key": "file", "label": "FILE"}]}


def task_get(ctx: CommandContext, args) -> dict:
    return {"task": ctx.client.request("GET", f"/api/import-tasks/{urllib.parse.quote(args.task_id)}").get("task")}


def wait_for_task(ctx: CommandContext, task_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + max(1, timeout)
    current = {}
    while time.monotonic() < deadline:
        current = ctx.client.request("GET", f"/api/import-tasks/{urllib.parse.quote(task_id)}").get("task") or {}
        if current.get("status") == "success":
            return current
        if current.get("status") == "failed":
            raise CliError("IMPORT_FAILED", current.get("error") or "Import failed", details=current)
        time.sleep(0.25)
    raise CliError("TASK_TIMEOUT", f"Task did not finish within {timeout} seconds", details=current)


def task_wait(ctx: CommandContext, args) -> dict:
    return {"task": wait_for_task(ctx, args.task_id, args.timeout)}


def _source(args) -> Path:
    value = getattr(args, "source", None) or getattr(args, "file", None)
    if not value:
        raise CliError("INVALID_ARGUMENT", "A source file is required", exit_code=2)
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise CliError("INVALID_ARGUMENT", f"Source file does not exist: {path}", exit_code=2)
    return path


def import_material(ctx: CommandContext, args, expected_type: str) -> dict:
    source = _source(args)
    name = args.name or getattr(args, "title", None) or source.stem
    created = ctx.client.upload(source, args.description or name)
    task = created.get("task") or {}
    warnings = []
    if args.wait:
        task_id = task.get("id") or ""
        if not task_id:
            raise CliError("SERVER_ERROR", "MineM did not return an import task ID", details=created)
        task = wait_for_task(ctx, task_id, args.timeout)
    if task.get("status") != "success":
        return {"task": task, "queued": True, "warnings": warnings}
    actual_type = task.get("assetType") or ""
    wanted = TYPE_TO_API.get(expected_type, expected_type)
    if actual_type and actual_type != wanted:
        warnings.append(f"MineM classified the source as {actual_type}, not {wanted}; the correct asset type was preserved.")
    asset_id = task.get("assetId") or ""
    asset = None
    if asset_id:
        if name and not created.get("reused"):
            renamed = ctx.client.request("POST", f"/api/assets/{urllib.parse.quote(asset_id)}/title", {"title": name})
            asset = renamed.get("asset")
        if not asset:
            asset = ctx.client.request("GET", f"/api/assets/{urllib.parse.quote(asset_id)}").get("asset")
    resource = normalize_asset(asset, ctx.base_url)
    return {"task": task, "asset": resource, "reused": bool(created.get("reused")), "warnings": warnings}


def case_import(ctx: CommandContext, args) -> dict:
    source = _source(args)
    if source.suffix.lower() not in {".md", ".markdown", ".txt"}:
        raise CliError("INVALID_ARGUMENT", "case import currently accepts Markdown or TXT", exit_code=2)
    title = args.name or getattr(args, "title", None) or source.stem
    text = source.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip("# -*\t ") for line in text.splitlines() if line.strip()]
    body = "\n".join(f"<p>{html.escape(line)}</p>" for line in lines[:80]) or "<p>Content pending.</p>"
    document = f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title><style>html,body{{margin:0;width:100%;height:100%;background:#071727;color:#edf5ff}}main{{box-sizing:border-box;width:1600px;height:900px;padding:76px 112px;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif}}h1{{font-size:56px;margin:0 0 42px}}p{{font-size:26px;line-height:1.65;max-width:1220px;margin:12px 0;color:#d4e4f4}}</style></head><body><main class=\"slide-frame\"><h1>{html.escape(title)}</h1>{body}</main></body></html>"""
    with tempfile.NamedTemporaryFile("w", suffix="-case.html", encoding="utf-8", delete=False) as handle:
        handle.write(document)
        generated = Path(handle.name)
    original_source = args.source
    try:
        args.source = str(generated)
        args.description = f"case import,{args.industry or ''}"
        return import_material(ctx, args, "page")
    finally:
        args.source = original_source
        generated.unlink(missing_ok=True)


def report_create(ctx: CommandContext, args) -> dict:
    references = list(args.page or [])
    if args.controls:
        references.extend(item.strip() for item in args.controls.split(",") if item.strip())
    pages = resolve_assets(ctx.client, references, "page")
    if not pages:
        raise CliError("INVALID_ARGUMENT", "A report requires at least one --page", exit_code=2)
    payload = ctx.client.request("POST", "/api/storyline-reports", {"mode": "manual", "title": args.name or args.title, "controlIds": [item["id"] for item in pages], "note": args.note or ""})
    asset = normalize_asset(payload.get("asset"), ctx.base_url)
    return {"asset": asset, "url": absolute_url(ctx.base_url, payload.get("url")), "pages": [normalize_asset(item, ctx.base_url) for item in pages]}


def report_get(ctx: CommandContext, args) -> dict:
    return {"asset": normalize_asset(resolve_asset(ctx.client, args.report, "report"), ctx.base_url)}


def report_pages(ctx: CommandContext, args) -> dict:
    report = resolve_asset(ctx.client, args.report, "report")
    payload = ctx.client.request("GET", f"/api/reports/{urllib.parse.quote(report['id'])}/pages")
    slots = payload.get("slots") or []
    rows = [{"position": index + 1, "code": slot.get("asset_code") or slot.get("assetCode") or "", "title": slot.get("title") or "", "id": slot.get("control_id") or slot.get("controlId") or ""} for index, slot in enumerate(slots)]
    return {"report": normalize_asset(report, ctx.base_url), "items": slots, "rows": rows, "columns": [{"key": "position", "label": "#"}, {"key": "code", "label": "CODE"}, {"key": "title", "label": "TITLE"}, {"key": "id", "label": "ID"}]}


def report_open(ctx: CommandContext, args) -> dict:
    report = normalize_asset(resolve_asset(ctx.client, args.report, "report"), ctx.base_url)
    url = absolute_url(ctx.base_url, f"/reports/{urllib.parse.quote(report['id'])}/index.html")
    if not args.print_only and not ctx.no_input:
        webbrowser.open(url)
    return {"asset": report, "url": url, "opened": not args.print_only and not ctx.no_input}


def _arrangement(ctx: CommandContext, report_id: str) -> tuple[dict, list[str], list[str]]:
    payload = ctx.client.request("GET", f"/api/reports/{urllib.parse.quote(report_id)}/arrangement")
    arrangement = payload.get("arrangement") or payload
    pages = arrangement.get("pages") or []
    order = list(arrangement.get("pageOrder") or [item.get("id") for item in pages if item.get("id")])
    hidden = list(arrangement.get("hiddenPageIds") or [item.get("id") for item in pages if item.get("hidden")])
    return arrangement, order, hidden


def report_page_mutation(ctx: CommandContext, args) -> dict:
    report = resolve_asset(ctx.client, args.report, "report")
    _, order, hidden = _arrangement(ctx, report["id"])
    original_order = list(order)
    original_hidden = list(hidden)
    inserted = []
    removed = []

    if args.page_action == "add":
        page = resolve_asset(ctx.client, args.page, "page")
        after = resolve_asset(ctx.client, args.after, "page") if args.after else None
        before = resolve_asset(ctx.client, args.before, "page") if args.before else None
        if page["id"] in order:
            raise CliError("CONFLICT", "The report already contains that page")
        if after and after["id"] not in order:
            raise CliError("NOT_FOUND", "--after page is not in the report")
        if before and before["id"] not in order:
            raise CliError("NOT_FOUND", "--before page is not in the report")
        index = order.index(after["id"]) + 1 if after else order.index(before["id"]) if before else len(order)
        order.insert(index, page["id"])
        inserted.append(page["id"])
    elif args.page_action == "replace":
        old = resolve_asset(ctx.client, args.page, "page")
        new = resolve_asset(ctx.client, args.with_page, "page")
        if old["id"] not in order:
            raise CliError("NOT_FOUND", "The page to replace is not in the report")
        if new["id"] != old["id"] and new["id"] in order:
            raise CliError("CONFLICT", "The replacement page is already in the report")
        order[order.index(old["id"])] = new["id"]
        inserted.append(new["id"])
        removed.append(old["id"])
        hidden = [item for item in hidden if item != old["id"]]
    elif args.page_action == "move":
        page = resolve_asset(ctx.client, args.page, "page")
        anchor = resolve_asset(ctx.client, args.after or args.before, "page")
        if page["id"] not in order or anchor["id"] not in order:
            raise CliError("NOT_FOUND", "Both pages must be in the report")
        if page["id"] == anchor["id"]:
            raise CliError("INVALID_ARGUMENT", "A page cannot be moved relative to itself", exit_code=2)
        order.remove(page["id"])
        index = order.index(anchor["id"]) + (1 if args.after else 0)
        order.insert(index, page["id"])
    elif args.page_action in {"hide", "show", "remove"}:
        page = resolve_asset(ctx.client, args.page, "page")
        if page["id"] not in order:
            raise CliError("NOT_FOUND", "The page is not in the report")
        if args.page_action == "hide" and page["id"] not in hidden:
            hidden.append(page["id"])
        elif args.page_action == "show":
            hidden = [item for item in hidden if item != page["id"]]
        elif args.page_action == "remove":
            if len(order) <= 1:
                raise CliError("INVALID_ARGUMENT", "A report must keep at least one page")
            order.remove(page["id"])
            hidden = [item for item in hidden if item != page["id"]]
            removed.append(page["id"])

    _require_confirm(args, "Updating the formal report requires --confirm")
    plan = {"pageOrder": order, "hiddenPageIds": hidden, "insertedControlIds": inserted, "removedPageIds": removed}
    if args.dry_run:
        return {"report": normalize_asset(report, ctx.base_url), "dryRun": True, "before": {"pageOrder": original_order, "hiddenPageIds": original_hidden}, "after": plan}
    updated = ctx.client.request("POST", f"/api/reports/{urllib.parse.quote(report['id'])}/arrangement", plan)
    preview = absolute_url(ctx.base_url, updated.get("previewUrl") or f"/reports/{report['id']}/index.html")
    return {"report": normalize_asset(report, ctx.base_url), "arrangement": updated, "url": preview}


def report_export(ctx: CommandContext, args) -> dict:
    report = resolve_asset(ctx.client, args.report, "report")
    created = ctx.client.request("POST", f"/api/reports/{urllib.parse.quote(report['id'])}/exports", {"format": args.format})
    task = created.get("task") or {}
    if args.wait:
        deadline = time.monotonic() + max(1, args.timeout)
        while time.monotonic() < deadline:
            task = ctx.client.request("GET", f"/api/report-exports/{urllib.parse.quote(task.get('id') or '')}").get("task") or {}
            if task.get("status") == "completed":
                break
            if task.get("status") == "failed":
                raise CliError("EXPORT_FAILED", task.get("error") or "Export failed", details=task)
            time.sleep(0.4)
        else:
            raise CliError("TASK_TIMEOUT", f"Export did not finish within {args.timeout} seconds", details=task)
    download_url = task.get("downloadUrl") or ""
    destination = None
    if args.destination and download_url:
        target = Path(args.destination).expanduser().resolve()
        if target.is_dir():
            target = target / (task.get("filename") or f"report.{args.format}")
        destination = str(ctx.client.download(download_url, target))
    return {"report": normalize_asset(report, ctx.base_url), "task": task, "downloadUrl": absolute_url(ctx.base_url, download_url), "destination": destination}


CAPABILITIES = [
    {"name": "asset.list", "readOnly": True},
    {"name": "asset.search", "readOnly": True},
    {"name": "asset.get", "readOnly": True},
    {"name": "asset.versions", "readOnly": True},
    {"name": "asset.lineage", "readOnly": True},
    {"name": "asset.rename", "mutates": True},
    {"name": "asset.delete", "mutates": True, "confirmation": True, "dryRun": True},
    {"name": "import.report", "input": "HTML or ZIP", "async": True},
    {"name": "import.page", "input": "HTML or ZIP", "async": True},
    {"name": "page.import", "input": "HTML or ZIP", "async": True},
    {"name": "case.import", "input": "Markdown or TXT", "aiGenerated": False},
    {"name": "task.list", "readOnly": True},
    {"name": "task.get", "readOnly": True},
    {"name": "task.wait", "readOnly": True},
    {"name": "report.create", "mutates": True},
    {"name": "report.get", "readOnly": True},
    {"name": "report.pages", "readOnly": True},
    {"name": "report.page.add", "mutates": True, "confirmation": True, "dryRun": True},
    {"name": "report.page.replace", "mutates": True, "confirmation": True, "dryRun": True},
    {"name": "report.page.move", "mutates": True, "confirmation": True, "dryRun": True},
    {"name": "report.page.hide", "mutates": True, "confirmation": True, "dryRun": True},
    {"name": "report.page.show", "mutates": True, "confirmation": True, "dryRun": True},
    {"name": "report.page.remove", "mutates": True, "confirmation": True, "dryRun": True},
    {"name": "report.export", "async": True},
]


SCHEMAS = {
    "asset.search": {"required": ["query"], "properties": {"query": {"type": "string"}, "type": {"enum": ["all", "report", "page", "resource"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
    "import.report": {"required": ["source"], "properties": {"source": {"type": "string"}, "name": {"type": "string"}, "wait": {"type": "boolean"}}},
    "report.page.add": {"required": ["report", "page"], "properties": {"report": {"type": "string", "description": "Report ID, code, or URL"}, "page": {"type": "string", "description": "Page ID, code, or URL"}, "after": {"type": "string"}, "before": {"type": "string"}, "confirm": {"type": "boolean"}}},
    "report.page.replace": {"required": ["report", "page", "with"], "properties": {"report": {"type": "string"}, "page": {"type": "string"}, "with": {"type": "string"}, "confirm": {"type": "boolean"}}},
    "report.create": {"required": ["name", "page"], "properties": {"name": {"type": "string"}, "page": {"type": "array", "items": {"type": "string"}, "minItems": 1}, "note": {"type": "string"}}},
    "report.export": {"required": ["report"], "properties": {"report": {"type": "string"}, "format": {"enum": ["html", "pdf"]}, "destination": {"type": "string"}, "wait": {"type": "boolean"}}},
    "page.import": {"required": ["source"], "properties": {"source": {"type": "string"}, "name": {"type": "string"}, "wait": {"type": "boolean"}}},
    "case.import": {"required": ["source"], "properties": {"source": {"type": "string"}, "name": {"type": "string"}, "industry": {"type": "string"}, "wait": {"type": "boolean"}}},
}


def agent_capabilities(ctx: CommandContext, args) -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "modelAgnostic": True, "generationBoundary": "The agent generates content; MineM performs deterministic material operations.", "capabilities": CAPABILITIES}


def agent_schema(ctx: CommandContext, args) -> dict:
    schema = SCHEMAS.get(args.name)
    if not schema:
        raise CliError("NOT_FOUND", f"No schema is registered for capability: {args.name}", details={"available": sorted(SCHEMAS)})
    return {"name": args.name, "schema": {"type": "object", **schema}}
