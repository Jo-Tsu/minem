"""Human and machine output renderers."""

from __future__ import annotations

import json
import sys
from typing import Any


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml(value: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.extend(_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.extend(_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return lines
    return [f"{pad}{_yaml_scalar(value)}"]


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "No results."
    widths = []
    for key, label in columns:
        widths.append(min(60, max(len(label), *(len(str(row.get(key, ""))) for row in rows))))
    header = "  ".join(label.ljust(widths[index]) for index, (_, label) in enumerate(columns))
    divider = "  ".join("-" * width for width in widths)
    body = []
    for row in rows:
        body.append("  ".join(str(row.get(key, ""))[:widths[index]].ljust(widths[index]) for index, (key, _) in enumerate(columns)))
    return "\n".join([header, divider, *body])


def human_text(result: dict) -> str:
    if not result.get("ok"):
        error = result.get("error") or {}
        return f"Error [{error.get('code', 'UNKNOWN')}]: {error.get('message', 'Unknown error')}"
    data = result.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("script"), str):
        return data["script"]
    if isinstance(data, dict) and isinstance(data.get("rows"), list) and isinstance(data.get("columns"), list):
        columns = [(item["key"], item["label"]) for item in data["columns"]]
        return _table(data["rows"], columns)
    resource = result.get("resource") or {}
    lines = []
    if resource:
        kind = str(resource.get("type") or "asset").upper()
        identity = resource.get("code") or resource.get("id") or ""
        lines.append(f"OK  {kind}  {identity}  {resource.get('title') or ''}".rstrip())
    for label, value in (("Preview", (result.get("links") or {}).get("preview")), ("Download", (result.get("links") or {}).get("download"))):
        if value:
            lines.append(f"{label}: {value}")
    if not lines and data:
        lines.append(json.dumps(data, ensure_ascii=False, indent=2))
    return "\n".join(lines) or "OK"


def render(result: dict, output: str = "table", quiet: bool = False) -> None:
    for warning in result.get("warnings") or []:
        print(f"warning: {warning}", file=sys.stderr)
    if quiet and result.get("ok"):
        resource = result.get("resource") or {}
        value = resource.get("code") or resource.get("id") or (result.get("links") or {}).get("preview") or ""
        if value:
            print(value)
        return
    if output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif output == "jsonl":
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    elif output == "yaml":
        print("\n".join(_yaml(result)))
    else:
        stream = sys.stdout if result.get("ok") else sys.stderr
        print(human_text(result), file=stream)
