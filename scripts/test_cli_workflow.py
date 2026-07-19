#!/usr/bin/env python3
"""End-to-end regression test for the public MineM CLI v1 workflow."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def invoke(base_url: str, config_file: Path, *args: str, expected: int = 0, json_output: bool = True):
    command = [sys.executable, "-m", "minem.cli", *args, "--base-url", base_url, "--no-input"]
    if json_output:
        command.extend(["--output", "json"])
    environment = {**os.environ, "MINEM_CONFIG_FILE": str(config_file)}
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=240)
    if result.returncode != expected:
        raise AssertionError(
            f"CLI exit mismatch ({' '.join(args)}): expected {expected}, got {result.returncode}\n"
            f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
        )
    if not json_output:
        return result
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"CLI returned invalid JSON:\n{result.stdout}\nstderr:\n{result.stderr}") from error
    assert payload["schemaVersion"] == "minem.cli/v1", payload
    assert payload["requestId"].startswith("req_"), payload
    assert payload["meta"]["serverUrl"] == base_url, payload
    assert payload["ok"] is (expected == 0), payload
    return payload


def page_html(title: str, body: str, background: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title>
<style>html,body{{margin:0;width:100%;height:100%;background:{background};color:white}}
main{{box-sizing:border-box;width:1600px;height:900px;padding:96px;font-family:sans-serif}}
h1{{font-size:72px}}p{{font-size:34px;line-height:1.5;max-width:1100px}}</style></head>
<body><main class="slide-frame"><h1>{title}</h1><p>{body}</p></main></body></html>"""


def assert_url(url: str) -> None:
    with urllib.request.urlopen(url, timeout=20) as response:
        body = response.read()
        assert response.status == 200, (response.status, url)
        assert len(body) > 100, (len(body), url)


def import_page(base_url: str, config: Path, source: Path, name: str) -> dict:
    result = invoke(base_url, config, "page", "import", str(source), "--name", name, "--wait")
    resource = result["resource"]
    assert resource["type"] == "page", result
    assert resource["code"].startswith("CTRL-"), result
    assert resource["title"] == name, result
    assert_url(resource["previewUrl"])
    return resource


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8790")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    with tempfile.TemporaryDirectory(prefix="minem-cli-workflow-") as temp_dir:
        root = Path(temp_dir)
        config = root / "config.json"
        page_a = root / "page-a.html"
        page_b = root / "page-b.html"
        page_c = root / "page-c.html"
        case_doc = root / "case.md"
        page_a.write_text(page_html("AI 创建页面素材", "模型生成页面，MineM 负责入库与追溯。", "#07111f"), encoding="utf-8")
        page_b.write_text(page_html("AI 管理汇报", "模型可以创建并编排完整汇报。", "#101827"), encoding="utf-8")
        page_c.write_text(page_html("版本与来源", "页面替换后仍保留原始素材。", "#071b18"), encoding="utf-8")
        case_doc.write_text(
            "# 制造业协同案例\n\n## 挑战\n页面重复且来源难追踪。\n\n"
            "## 方案\n通过 MineM 和 CLI 创建、管理并编排素材。\n",
            encoding="utf-8",
        )

        version = invoke(base_url, config, "version")
        assert version["data"]["schemaVersion"] == "minem.cli/v1", version
        assert invoke(base_url, config, "status")["data"]["connected"] is True
        assert invoke(base_url, config, "doctor")["data"]["healthy"] is True

        capabilities = invoke(base_url, config, "agent", "capabilities")
        names = {item["name"] for item in capabilities["data"]["capabilities"]}
        assert {"page.import", "report.create", "report.page.add", "report.page.replace"} <= names
        assert invoke(base_url, config, "agent", "schema", "report.page.add")["data"]["schema"]["type"] == "object"

        invoke(base_url, config, "config", "set", "output", "table")
        assert invoke(base_url, config, "config", "get", "output")["data"]["value"] == "table"
        invoke(base_url, config, "config", "unset", "output")

        first = import_page(base_url, config, page_a, "AI 创建页面素材")
        second = import_page(base_url, config, page_b, "AI 管理汇报")
        replacement = import_page(base_url, config, page_c, "版本与来源")

        case_result = invoke(
            base_url,
            config,
            "case",
            "import",
            str(case_doc),
            "--name",
            "制造业协同案例",
            "--industry",
            "制造业",
            "--wait",
        )
        case = case_result["resource"]
        assert case["type"] == "page", case_result
        assert case["title"] == "制造业协同案例", case_result
        assert case_result["data"]["task"]["status"] == "success", case_result
        assert_url(case["previewUrl"])

        by_id = invoke(base_url, config, "asset", "get", first["id"])["resource"]
        by_code = invoke(base_url, config, "asset", "get", first["code"])["resource"]
        by_link = invoke(base_url, config, "asset", "get", first["previewUrl"])["resource"]
        assert {by_id["id"], by_code["id"], by_link["id"]} == {first["id"]}
        versions = invoke(base_url, config, "asset", "versions", first["code"])
        assert any(item["id"] == first["id"] for item in versions["data"]["items"]), versions
        lineage = invoke(base_url, config, "asset", "lineage", first["code"])
        assert lineage["resource"]["id"] == first["id"], lineage

        searched = invoke(base_url, config, "asset", "search", "AI 创建页面素材")
        assert any(item["id"] == first["id"] for item in searched["data"]["items"]), searched
        human = invoke(base_url, config, "asset", "list", "--type", "page", "--limit", "5", json_output=False)
        assert "CODE" in human.stdout and not human.stdout.lstrip().startswith("{"), human.stdout

        report_result = invoke(
            base_url,
            config,
            "report",
            "create",
            "--name",
            "AI CLI v1 端到端测试",
            "--page",
            first["code"],
            "--page",
            second["previewUrl"],
        )
        report = report_result["resource"]
        assert report["type"] == "report" and report["code"].startswith("RPT-"), report_result
        assert_url(report_result["links"]["preview"])

        initial_pages = invoke(base_url, config, "report", "pages", report["code"])
        rows = initial_pages["data"]["rows"]
        assert len(rows) == 2, initial_pages
        first_member = rows[0]["code"] or rows[0]["id"]
        second_member = rows[1]["code"] or rows[1]["id"]

        dry_run = invoke(
            base_url,
            config,
            "report",
            "page",
            "add",
            report["code"],
            "--page",
            case["code"],
            "--after",
            first_member,
            "--dry-run",
        )
        assert dry_run["data"]["dryRun"] is True
        unchanged = invoke(base_url, config, "report", "pages", report["id"])
        assert len(unchanged["data"]["rows"]) == 2

        confirmation = invoke(
            base_url,
            config,
            "report",
            "page",
            "add",
            report["code"],
            "--page",
            case["code"],
            "--after",
            first_member,
            expected=4,
        )
        assert confirmation["error"]["code"] == "CONFIRMATION_REQUIRED", confirmation

        added = invoke(base_url, config, "report", "page", "add", report["code"], "--page", case["code"], "--after", first_member, "--confirm")
        assert len(added["data"]["arrangement"]["pages"]) == 3, added

        duplicate_replace = invoke(base_url, config, "report", "page", "replace", report["code"], "--page", second_member, "--with", first_member, "--confirm", expected=1)
        assert duplicate_replace["error"]["code"] == "CONFLICT", duplicate_replace
        self_move = invoke(base_url, config, "report", "page", "move", report["code"], "--page", first_member, "--after", first_member, "--confirm", expected=2)
        assert self_move["error"]["code"] == "INVALID_ARGUMENT", self_move

        replaced = invoke(base_url, config, "report", "page", "replace", report["code"], "--page", second_member, "--with", replacement["code"], "--confirm")
        replaced_codes = [item.get("code") for item in replaced["data"]["arrangement"]["pages"]]
        assert replacement["code"] in replaced_codes, replaced

        invoke(base_url, config, "report", "page", "move", report["code"], "--page", replacement["code"], "--before", first_member, "--confirm")
        hidden = invoke(base_url, config, "report", "page", "hide", report["code"], "--page", case["code"], "--confirm")
        assert any(item["id"] == case["id"] and item["hidden"] for item in hidden["data"]["arrangement"]["pages"]), hidden
        shown = invoke(base_url, config, "report", "page", "show", report["code"], "--page", case["code"], "--confirm")
        assert not any(item["id"] == case["id"] and item["hidden"] for item in shown["data"]["arrangement"]["pages"]), shown
        removed = invoke(base_url, config, "report", "page", "remove", report["code"], "--page", case["code"], "--confirm")
        assert len(removed["data"]["arrangement"]["pages"]) == 2, removed
        final = invoke(base_url, config, "report", "page", "add", report["code"], "--page", case["code"], "--after", first_member, "--confirm")
        assert len(final["data"]["arrangement"]["pages"]) == 3, final
        assert_url(final["links"]["preview"])

        for source in (first, second, replacement, case):
            assert invoke(base_url, config, "asset", "get", source["code"])["resource"]["id"] == source["id"]

        legacy = invoke(base_url, config, "page", "create", "--file", str(page_a), "--wait", "--json")
        assert any("deprecated" in warning for warning in legacy["warnings"]), legacy

        missing = invoke(base_url, config, "asset", "get", "CTRL-NOT-FOUND", expected=1)
        assert missing["error"]["code"] == "NOT_FOUND", missing

        invalid = invoke(base_url, config, "unknown-command", expected=2)
        assert invalid["error"]["code"] == "INVALID_ARGUMENT", invalid

        print(json.dumps({
            "ok": True,
            "schemaVersion": "minem.cli/v1",
            "reportId": report["id"],
            "reportCode": report["code"],
            "pageCount": 3,
            "previewUrl": final["links"]["preview"],
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
