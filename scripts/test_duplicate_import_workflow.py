#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def available_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def invoke(base_url: str, environment: dict[str, str], *args: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "minem.cli",
            *args,
            "--base-url",
            base_url,
            "--no-input",
            "--output",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if result.returncode:
        raise AssertionError(
            f"CLI failed: {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    return payload


def page_node(key: str, title: str, body: str) -> str:
    return f"""<div class="slide-frame"><section class="slide" data-slide-key="{key}">
    <h1>{title}</h1><p>{body}</p></section></div>"""


def page_document(node: str, wrapper: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
    <title>页面重复回归</title>
    <style>html,body,.slide{{margin:0;width:1920px;height:1080px;overflow:hidden}}</style>
    <script>window.wrapper={json.dumps(wrapper)}</script></head><body>{node}</body></html>"""


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="minem-duplicate-import-") as temp_dir:
        runtime_root = Path(temp_dir) / "runtime"
        input_root = Path(temp_dir) / "inputs"
        input_root.mkdir()
        shared = page_node(
            "shared-business-page",
            "跨汇报复用页面",
            "这是一张会在多个汇报中重复出现且应该进入版本链的业务页面正文。",
        )
        unique = page_node(
            "unique-report-page",
            "汇报独有页面",
            "这张页面只属于完整汇报，不应被合并。",
        )
        single = input_root / "single.html"
        report = input_root / "report.html"
        single.write_text(page_document(shared, "single"), encoding="utf-8")
        report.write_text(
            page_document(f'<main class="deck">{shared}{unique}</main>', "report").replace(
                "<title>页面重复回归</title>",
                '<title>页面重复回归</title><meta name="fs-deck-generator" content="render-deck">',
            ),
            encoding="utf-8",
        )

        port = available_port()
        environment = {
            **os.environ,
            "MINEM_DATA_DIR": str(runtime_root),
            "MINEM_SKIP_PORT_PRECHECK": "1",
            "PORT": str(port),
        }
        environment.pop("MINEM_SESSION_TOKEN", None)
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py")],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=1)
                    raise AssertionError(
                        f"service exited early\nstdout:\n{stdout}\nstderr:\n{stderr}"
                    )
                check = subprocess.run(
                    ["curl", "-fsS", f"{base_url}/api/version"],
                    capture_output=True,
                    timeout=2,
                )
                if check.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("service did not become ready")

            first = invoke(
                base_url,
                environment,
                "page",
                "import",
                str(single),
                "--name",
                "跨汇报复用页面",
                "--wait",
            )
            second = invoke(
                base_url,
                environment,
                "page",
                "import",
                str(report),
                "--name",
                "混合重复测试汇报",
                "--wait",
            )
            repeated = invoke(
                base_url,
                environment,
                "page",
                "import",
                str(single),
                "--name",
                "跨汇报复用页面",
                "--wait",
            )
            assert repeated["resource"]["id"] == first["resource"]["id"]
            assert second["resource"]["type"] == "report"

            conn = sqlite3.connect(runtime_root / "data" / "materials.db")
            conn.row_factory = sqlite3.Row
            controls = conn.execute(
                """
                select id,asset_code,version_group,version_no,version_parent_id,
                       similarity_method,semantic_key,semantic_dedupe_status
                from assets
                where asset_type='control'
                order by created_at,id
                """
            ).fetchall()
            shared_rows = [
                row for row in controls if row["semantic_key"] == "shared-business-page"
            ]
            unique_rows = [
                row for row in controls if row["semantic_key"] == "unique-report-page"
            ]
            slots = conn.execute(
                "select report_id,page_number,control_id from report_page_slots order by page_number"
            ).fetchall()
            assert len(controls) == 3, [dict(row) for row in controls]
            assert len(shared_rows) == 2 and len(unique_rows) == 1
            assert sum(not row["version_parent_id"] for row in shared_rows) == 1
            assert any(
                row["similarity_method"] == "semantic-visual-v1"
                and row["semantic_dedupe_status"] == "merged"
                for row in shared_rows
            )
            assert len(slots) == 2
            assert slots[0]["control_id"] in {row["id"] for row in shared_rows}
            assert slots[1]["control_id"] == unique_rows[0]["id"]
            assert conn.execute(
                "select count(*) from assets where asset_type='control' and version_parent_id=''"
            ).fetchone()[0] == 2
            assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"
            conn.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    print("duplicate import workflow passed")


if __name__ == "__main__":
    main()
