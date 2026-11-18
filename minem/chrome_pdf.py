"""Capture a PDF page through Chromium's local pipe, after real rendering readiness."""

import base64
import json
import os
import select
import subprocess
import sys
import tempfile
import time


def capture_ready_page(chrome, wrapper, output):
    reader, browser_input = os.pipe()
    browser_output, writer = os.pipe()
    process = None
    buffer = b""
    sequence = 0
    deadline = time.monotonic() + 45
    profile = tempfile.TemporaryDirectory(prefix="minem-pdf-chrome-")
    try:
        # A separate exec helper maps the pipes without using preexec_fn in
        # the threaded server. The debugging transport never opens a port.
        helper = "import os,sys;os.dup2(int(sys.argv[1]),3);os.dup2(int(sys.argv[2]),4);os.execv(sys.argv[3],sys.argv[3:])"
        process = subprocess.Popen([
            sys.executable, "-c", helper, str(reader), str(writer), chrome,
            "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--disable-background-networking", "--disable-extensions", "--hide-scrollbars",
            "--no-first-run", "--allow-file-access-from-files", "--remote-debugging-pipe",
            "--run-all-compositor-stages-before-draw", f"--user-data-dir={profile.name}", "about:blank",
        ], pass_fds=(reader, writer), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(reader)
        os.close(writer)
        reader = writer = None

        def call(method, params=None, session=None):
            nonlocal sequence, buffer
            sequence += 1
            message = {"id": sequence, "method": method, "params": params or {}}
            if session:
                message["sessionId"] = session
            os.write(browser_input, json.dumps(message).encode() + b"\0")
            while True:
                while b"\0" in buffer:
                    raw, buffer = buffer.split(b"\0", 1)
                    reply = json.loads(raw)
                    if reply.get("id") != sequence:
                        continue
                    if "error" in reply:
                        raise RuntimeError("Chromium 渲染失败：" + reply["error"].get("message", "未知错误"))
                    return reply.get("result", {})
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([browser_output], [], [], remaining)[0]:
                    raise RuntimeError("PDF 页面渲染超时")
                chunk = os.read(browser_output, 65536)
                if not chunk:
                    raise RuntimeError("Chromium 页面渲染中断")
                buffer += chunk

        target = call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        call("Emulation.setDeviceMetricsOverride", {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False}, session)
        call("Page.navigate", {"url": wrapper.resolve().as_uri()}, session)
        stage = "等待页面加载"
        while time.monotonic() < deadline:
            state = call("Runtime.evaluate", {
                "expression": "({ready:document.documentElement.dataset.pdfReady,error:document.documentElement.dataset.pdfError,stage:document.documentElement.dataset.pdfStage})",
                "returnByValue": True,
            }, session).get("result", {}).get("value", {})
            if state.get("error"):
                raise ValueError(state["error"])
            stage = state.get("stage") or stage
            if state.get("ready") == "ready":
                result = call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, session)
                output.write_bytes(base64.b64decode(result["data"], validate=True))
                return
            time.sleep(.1)
        raise ValueError("PDF 页面未完成渲染：" + stage)
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for descriptor in (reader, writer, browser_input, browser_output):
            if descriptor is not None:
                os.close(descriptor)
        profile.cleanup()
