#!/usr/bin/env python3
"""End-to-end regression test for the public MineM CLI material workflow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "minem_cli.py"


def run_cli(base_url: str, *args: str) -> dict:
    command = [sys.executable, str(CLI), "--base-url", base_url, "--json", *args]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise AssertionError(f"CLI failed ({' '.join(args)}):\n{result.stderr}\n{result.stdout}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"CLI returned invalid JSON:\n{result.stdout}") from error
    assert payload.get("ok"), payload
    return payload


def page_html(title: str, body: str, background: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title>
<style>html,body{{margin:0;width:100%;height:100%;background:{background};color:white}}
main{{box-sizing:border-box;width:1600px;height:900px;padding:96px;font-family:sans-serif}}
h1{{font-size:72px}}p{{font-size:34px;line-height:1.5;max-width:1100px}}</style></head>
<body><main class="slide-frame"><h1>{title}</h1><p>{body}</p></main></body></html>"""


def assert_url(base_url: str, path: str) -> None:
    with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=20) as response:
        body = response.read()
        assert response.status == 200, (response.status, path)
        assert len(body) > 100, (len(body), path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8790")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="minem-cli-workflow-") as temp_dir:
        root = Path(temp_dir)
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

        first = run_cli(args.base_url, "page", "create", "--file", str(page_a), "--title", "AI 创建页面素材", "--wait")
        second = run_cli(args.base_url, "page", "create", "--file", str(page_b), "--title", "AI 管理汇报", "--wait")
        replacement = run_cli(args.base_url, "page", "create", "--file", str(page_c), "--title", "版本与来源", "--wait")
        case = run_cli(
            args.base_url,
            "case",
            "create",
            "--file",
            str(case_doc),
            "--title",
            "制造业协同案例",
            "--industry",
            "制造业",
            "--wait",
        )

        materials = [first, second, replacement, case]
        for item in materials:
            task = item["task"]
            assert task["status"] == "success", task
            assert task["assetType"] == "control", task
            assert task["assetId"], task
            assert task["previewUrl"], task
            assert item.get("asset", {}).get("title") == task["assetTitle"], item
            assert_url(args.base_url, task["previewUrl"])

        first_id = first["task"]["assetId"]
        second_id = second["task"]["assetId"]
        replacement_id = replacement["task"]["assetId"]
        case_id = case["task"]["assetId"]
        report = run_cli(
            args.base_url,
            "report",
            "create",
            "--title",
            "AI CLI 端到端测试",
            "--controls",
            f"{first_id},{second_id}",
            "--note",
            "automated CLI workflow",
        )
        report_id = report["asset"]["id"]
        assert report["asset"]["asset_type"] == "report", report
        assert report["asset"]["displayPageCount"] == 2, report
        assert_url(args.base_url, report["url"])

        pages = run_cli(args.base_url, "report", "pages", report_id)
        assert len(pages["slots"]) == 2, pages
        first_slot = pages["slots"][0]["control_id"]
        second_slot = pages["slots"][1]["control_id"]

        inserted = run_cli(
            args.base_url,
            "report",
            "page",
            report_id,
            "--add",
            f"{case_id}:{first_slot}",
            "--yes",
        )
        assert [page["id"] for page in inserted["pages"]] == [first_slot, case_id, second_slot], inserted

        replaced = run_cli(
            args.base_url,
            "report",
            "page",
            report_id,
            "--replace",
            f"{second_slot}:{replacement_id}",
            "--yes",
        )
        final_ids = [page["id"] for page in replaced["pages"]]
        assert final_ids == [first_slot, case_id, replacement_id], replaced
        assert second_slot not in final_ids, replaced
        assert_url(args.base_url, replaced["previewUrl"])

        print(json.dumps({
            "ok": True,
            "reportId": report_id,
            "reportCode": report["asset"]["asset_code"],
            "pageCount": len(final_ids),
            "pageIds": final_ids,
            "previewUrl": replaced["previewUrl"],
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
