"""MineM CLI execution entry point."""

from __future__ import annotations

import sys
import time

from .client import MineMClient
from .commands import CommandContext
from .config import effective_server, load_config
from .contracts import CliError, failure, new_request_id, normalize_asset, success
from .output import render
from .parser import build_parser, normalize_argv


def _global_value(argv: list[str], name: str) -> str:
    for index, token in enumerate(argv):
        if token.startswith(f"{name}="):
            return token.split("=", 1)[1]
        if token == name and index + 1 < len(argv):
            return argv[index + 1]
    return ""


def _envelope(command, request_id, base_url, started_at, payload, compatibility_warnings):
    payload = payload or {}
    resource = payload.pop("asset", None) or payload.pop("report", None)
    if resource and ("asset_type" in resource or "asset_code" in resource):
        resource = normalize_asset(resource, base_url)
    warnings = [*compatibility_warnings, *(payload.pop("warnings", []) or [])]
    url = payload.pop("url", "") or (resource or {}).get("previewUrl", "")
    download = payload.get("downloadUrl") or ""
    links = {}
    if url:
        links["preview"] = url
    if download:
        links["download"] = download
    return success(command, request_id, base_url, started_at, resource=resource, data=payload, links=links, warnings=warnings)


def main(argv=None) -> int:
    started_at = time.monotonic()
    raw = list(sys.argv[1:] if argv is None else argv)
    command = "unknown"
    request_id = new_request_id()
    base_url = _global_value(raw, "--base-url").rstrip("/")
    output = "json" if "--json" in raw else (_global_value(raw, "--output") or "table")
    quiet = "--quiet" in raw
    request_id = _global_value(raw, "--request-id") or request_id
    try:
        config = load_config()
        if "--json" not in raw and not _global_value(raw, "--output"):
            output = config.get("output") or "table"
        normalized, compatibility_warnings = normalize_argv(raw)
        args = build_parser().parse_args(normalized)
        command = args.command_name
        request_id = args.request_id or request_id
        output = "json" if args.json else (args.output or config.get("output") or "table")
        quiet = args.quiet
        base_url = effective_server(args.base_url)
        client = MineMClient(base_url, timeout=args.timeout, request_id=request_id)
        context = CommandContext(client=client, base_url=base_url, timeout=args.timeout, no_input=args.no_input)
        result = _envelope(command, request_id, base_url, started_at, args.handler(context, args), compatibility_warnings)
        render(result, output, quiet)
        return 0
    except CliError as error:
        result = failure(command, request_id, base_url, started_at, error)
        render(result, output, quiet)
        return error.exit_code
    except KeyboardInterrupt:
        error = CliError("CANCELLED", "Operation cancelled")
        render(failure(command, request_id, base_url, started_at, error), output, quiet)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
