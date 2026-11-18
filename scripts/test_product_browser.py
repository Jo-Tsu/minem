#!/usr/bin/env python3
"""Real browser regressions against an isolated MineM service and test material."""

import base64
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import wave
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minem.thumbnails import chrome_path


class ProductBrowserChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = tempfile.TemporaryDirectory(prefix="minem-browser-test-")
        cls.log = (Path(cls.runtime.name) / "server.log").open("w")
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        cls.service = subprocess.Popen(
            [sys.executable, "server.py"], cwd=ROOT, stdout=cls.log, stderr=cls.log,
            env={**os.environ, "MINEM_DATA_DIR": cls.runtime.name, "HOST": "127.0.0.1", "PORT": str(port), "AUTO_IMPORT_ON_START": "0"},
        )
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=chrome_path() or None, headless=True)
        cls.api = cls.playwright.request.new_context(base_url=cls.base)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if cls.api.get("/api/version").ok:
                    break
            except Exception:
                time.sleep(.1)
        else:
            raise AssertionError("Test service did not start")
        cls.pages = [cls.import_page(f"Browser test page {i}") for i in (1, 2)]
        response = cls.api.post("/api/reports", data={"title": "Browser test report", "pageIds": cls.pages})
        cls.report = response.json()["asset"]

    @classmethod
    def tearDownClass(cls):
        cls.api.dispose()
        cls.browser.close()
        cls.playwright.stop()
        cls.service.terminate()
        cls.service.wait(timeout=10)
        cls.log.close()
        cls.runtime.cleanup()

    @staticmethod
    def html(title):
        return f'<!doctype html><html><head><title>{title}</title></head><body><h1>{title}</h1><input aria-label="Page field"></body></html>'.encode()

    @classmethod
    def import_page(cls, title):
        response = cls.api.post("/api/import-tasks", multipart={"file": {"name": title + ".html", "mimeType": "text/html", "buffer": cls.html(title)}})
        task = response.json()["task"]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            task = cls.api.get("/api/import-tasks/" + task["id"]).json()["task"]
            if task["status"] == "success":
                return task["assetId"]
            if task["status"] == "failed":
                raise AssertionError(task["error"])
            time.sleep(.1)
        raise AssertionError("Test import did not finish")

    def setUp(self):
        self.report = self.api.post("/api/reports", data={"title": "Browser test report", "pageIds": self.pages}).json()["asset"]
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def open_arrangement(self):
        self.page.goto(self.base + "/?arrange=" + self.report["id"], wait_until="networkidle")
        self.page.locator(".arrangement-page").first.wait_for()

    def wait_arrangement_saved(self):
        # A previous success toast can still be visible while the next save is pending.
        self.page.get_by_role("button", name="确认编排", exact=True).wait_for()
        self.page.get_by_text("编排已确认并生效", exact=True).wait_for()
        self.page.get_by_role("dialog", name="保存成功").wait_for()
        self.page.get_by_role("button", name="继续编排", exact=True).click()

    def test_empty_library_completes_loading(self):
        self.page.route("**/api/assets?**", lambda route: route.fulfill(json={"assets": [], "pagination": {"page": 1, "pageSize": 30, "total": 0, "hasNext": False}, "pipeline": None}))
        self.page.goto(self.base, wait_until="networkidle")
        self.page.get_by_text("没有匹配的素材", exact=False).wait_for()
        self.assertEqual(self.errors, [])

    def test_service_failure_has_a_message_without_script_errors(self):
        self.page.route("**/api/assets?**", lambda route: route.fulfill(status=503, body="Service unavailable", content_type="text/html"))
        self.page.goto(self.base, wait_until="networkidle")
        self.page.locator(".empty-state").filter(has_text="503").wait_for()
        self.assertEqual(self.errors, [])

    def test_import_rejects_simultaneous_duplicate_submissions(self):
        requests = []
        def respond(route):
            if route.request.method != "POST":
                route.continue_()
                return
            requests.append(route.request.url)
            route.fulfill(status=400, json={"ok": False, "error": "Test rejection"})
        self.page.route("**/api/import-tasks", respond)
        self.page.goto(self.base, wait_until="networkidle")
        self.page.get_by_role("button", name="导入", exact=True).click()
        self.page.locator("input[type=file]").set_input_files({"name": "test.html", "mimeType": "text/html", "buffer": self.html("Test")})
        self.page.locator("form.import-panel").evaluate("form => {form.requestSubmit();form.requestSubmit();}")
        self.page.get_by_role("alert").wait_for()
        self.assertEqual(len(requests), 1)

    def test_completed_import_refreshes_library(self):
        title = "Browser imported page"
        self.page.goto(self.base, wait_until="networkidle")
        self.page.get_by_role("button", name="页面", exact=True).first.click()
        self.page.get_by_role("button", name="导入", exact=True).click()
        self.page.locator("input[type=file]").set_input_files({"name": title + ".html", "mimeType": "text/html", "buffer": self.html(title)})
        self.page.get_by_role("button", name="开始导入", exact=True).click()
        self.page.locator(".asset-card").filter(has_text=title).wait_for(timeout=35000)
        self.assertEqual(self.errors, [])

    def test_unused_resource_deletion_removes_record_and_source(self):
        response = self.api.post("/api/import-tasks", multipart={"file": {
            "name": "Unused resource.svg", "mimeType": "image/svg+xml",
            "buffer": b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><path d="M0,0 L20,20" stroke="green"/></svg>',
        }})
        task = response.json()["task"]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            task = self.api.get("/api/import-tasks/" + task["id"]).json()["task"]
            if task["status"] in ("success", "failed"):
                break
            time.sleep(.1)
        self.assertEqual(task["status"], "success", task.get("error"))
        asset = self.api.get("/api/assets/" + task["assetId"]).json()["asset"]
        self.assertTrue(self.api.get(asset["preview_url"]).ok)
        deleted = self.api.delete("/api/assets/" + asset["id"])
        self.assertTrue(deleted.ok, deleted.text())
        self.assertEqual(deleted.json()["deletedCount"], 1)
        self.assertIsNone(self.api.get("/api/assets/" + asset["id"]).json().get("asset"))
        self.assertEqual(self.api.get(asset["preview_url"]).status, 404)
        self.assertIsNotNone(self.api.get("/api/assets/" + self.pages[0]).json().get("asset"))

    def test_report_creation_keeps_selected_cover(self):
        self.page.goto(self.base, wait_until="networkidle")
        self.page.get_by_role("button", name="新建汇报", exact=True).click()
        form = self.page.locator("form.import-panel")
        form.get_by_label("汇报标题").fill("Selected cover report")
        form.locator('input[value="cover-2"]').check()
        with self.page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/reports")) as saved:
            form.get_by_role("button", name="创建汇报素材", exact=True).click()
        asset = saved.value.json()["asset"]
        manifest = json.loads((Path(self.runtime.name) / "extracted" / asset["id"] / "manifest.json").read_text())
        self.assertEqual(manifest["cover_template"], "cover-2")

    def test_report_creation_can_search_the_whole_page_library(self):
        searched = []
        source = self.api.get("/api/assets/" + self.pages[1]).json()["asset"]

        def search(route):
            if "q=older-library-page" not in route.request.url:
                route.continue_()
                return
            searched.append(route.request.url)
            route.fulfill(json={"ok": True, "assets": [{**source, "title": "Older library page"}],
                                "pagination": {"page": 1, "pageSize": 30, "total": 1, "totalPages": 1, "hasPrev": False, "hasNext": False}})

        self.page.route("**/api/assets?**", search)
        self.page.goto(self.base, wait_until="networkidle")
        self.page.get_by_role("button", name="新建汇报", exact=True).click()
        self.page.get_by_label("搜索页面素材", exact=True).fill("older-library-page")
        self.page.get_by_role("checkbox", name="Older library page", exact=False).wait_for(timeout=3000)
        self.assertTrue(searched, "Search must query the complete library, not just the first loaded page")

    def test_player_keyboard_works_after_clicking_navigation(self):
        self.page.goto(self.base + self.report["preview_url"], wait_until="networkidle")
        self.page.get_by_role("button", name="下一页", exact=True).click()
        self.page.keyboard.press("ArrowRight")
        self.assertEqual(int(self.page.locator("#page").input_value()), 3)
        self.page.get_by_role("button", name="上一页", exact=True).click()
        self.page.frame_locator("iframe.deck-frame").get_by_role("textbox", name="Page field").press("ArrowRight")
        self.assertEqual(int(self.page.locator("#page").input_value()), 2)
        self.page.get_by_role("button", name="下一页", exact=True).press("Space")
        self.assertEqual(int(self.page.locator("#page").input_value()), 3)

    def open_playback_fixture(self, delayed_page=None, delayed_image=False, wait_for_first=True, delayed_video=False):
        from server import inject_embedded_preview_style, report_viewer_html
        audio = io.BytesIO()
        with wave.open(audio, "wb") as track:
            track.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            track.writeframes(b"\0\0" * 8000)
        sound = "data:audio/wav;base64," + base64.b64encode(audio.getvalue()).decode()
        self.playback_requests = []
        self.pending_playback = []
        pages = [{"title": f"Playback page {number}", "src": f"/playback-test/page-{number}.html"} for number in range(1, 7)]
        pages[1]["canvas"] = {"width": 800, "height": 1200}
        document = report_viewer_html("Playback test", pages)

        def serve_page(route):
            number = int(route.request.url.split("page-")[1].split(".html")[0])
            self.playback_requests.append(number)
            source = f'''<!doctype html><html><head><style>
                .motion{{animation:move 10s linear infinite}}@keyframes move{{to{{transform:translateX(100px)}}}}
                </style></head><body><h1>Playback page {number}</h1><div class="motion">Animation</div>
                <audio src="{sound}" loop></audio><button onclick="document.querySelector('audio').play()">Play audio</button>
                </body></html>'''
            if delayed_image and number == 2:
                source = source.replace("</body>", '<img src="/playback-test/delayed.png"></body>')
            if delayed_video and number == 2:
                source = source.replace("</body>", '<video src="/playback-test/delayed.mp4" autoplay muted></video></body>')
            response = inject_embedded_preview_style(source)
            if number == delayed_page:
                self.pending_playback.append((route, response))
            else:
                route.fulfill(body=response, content_type="text/html")

        self.page.route("**/playback-test/page-*.html?*", serve_page)
        pixel = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGN8AAAAASUVORK5CYII=")
        self.page.route("**/playback-test/delayed.png", lambda route: self.pending_playback.append((route, pixel)))
        self.page.route("**/playback-test/delayed.mp4", lambda route: self.pending_playback.append((route, b"")))
        self.page.route(self.base + "/playback-test/index.html", lambda route: route.fulfill(body=document, content_type="text/html"))
        self.page.goto(self.base + "/playback-test/index.html", wait_until="domcontentloaded")
        if wait_for_first:
            self.playback_page(1).wait_for()

    def playback_page(self, number):
        return self.page.frame_locator("iframe.deck-frame").get_by_role("heading", name=f"Playback page {number}", exact=True)

    def test_fullscreen_player_reuses_previous_page(self):
        self.open_playback_fixture()
        self.page.get_by_role("button", name="全屏", exact=True).click()
        self.page.wait_for_function("Boolean(document.fullscreenElement)")
        self.page.get_by_role("button", name="下一页", exact=True).click()
        self.playback_page(2).wait_for()
        self.assertEqual(self.page.frame_locator("iframe.deck-frame").locator("body").evaluate("() => [innerWidth, innerHeight]"), [800, 1200])
        self.page.get_by_role("button", name="上一页", exact=True).click()
        self.playback_page(1).wait_for()
        self.assertEqual(self.playback_requests.count(1), 1, "Returning to the previous page must reuse its loaded document")

    def test_player_keeps_page_visible_until_next_page_is_loaded(self):
        self.open_playback_fixture(delayed_image=True)
        self.page.get_by_role("button", name="下一页", exact=True).click()
        self.page.wait_for_function("Array.from(document.querySelectorAll('.canvas iframe')).some(frame => frame.contentDocument?.querySelector('img'))")
        self.playback_page(1).wait_for(timeout=1500)
        loading = self.page.get_by_role("status").filter(has_text="正在加载第 2 页")
        loading.wait_for(timeout=2000)
        self.assertEqual(self.page.locator(".canvas").get_attribute("aria-busy"), "true")
        self.assertTrue(self.pending_playback)
        route, response = self.pending_playback.pop()
        route.fulfill(body=response, content_type="image/png")
        self.playback_page(2).wait_for()
        loading.wait_for(state="hidden")
        self.assertEqual(self.page.locator(".canvas").get_attribute("aria-busy"), "false")

    def test_player_preloads_only_adjacent_pages_and_bounds_memory(self):
        self.open_playback_fixture()
        self.page.wait_for_function("Array.from(document.querySelectorAll('.canvas iframe')).some(frame => frame.contentDocument?.readyState === 'complete' && frame.contentDocument.querySelector('h1')?.textContent === 'Playback page 2')")
        self.assertEqual(set(self.playback_requests), {1, 2})
        for number in (2, 3, 4, 5, 6):
            self.page.get_by_role("button", name="下一页", exact=True).click()
            self.playback_page(number).wait_for()
            self.assertLessEqual(self.page.locator(".canvas iframe").count(), 3)
        self.page.wait_for_function("document.querySelectorAll('.canvas iframe').length === 2", timeout=1500)

    def test_player_pauses_hidden_page_media_and_animation(self):
        self.open_playback_fixture()
        self.page.frame_locator("iframe.deck-frame").get_by_role("button", name="Play audio").click()
        self.page.wait_for_function("!document.querySelector('.deck-frame').contentDocument.querySelector('audio').paused")
        self.page.get_by_role("button", name="下一页", exact=True).click()
        self.playback_page(2).wait_for()
        state = self.page.evaluate("""() => {
            const previous = Array.from(document.querySelectorAll('.canvas iframe')).find(frame => frame.contentDocument?.querySelector('h1')?.textContent === 'Playback page 1');
            return previous ? {paused:previous.contentDocument.querySelector('audio').paused, animations:previous.contentDocument.getAnimations().map(animation => animation.playState)} : null;
        }""")
        self.assertIsNotNone(state)
        self.assertTrue(state["paused"])
        self.assertTrue(state["animations"] and all(status == "paused" for status in state["animations"]))
        self.page.get_by_role("button", name="上一页", exact=True).click()
        self.playback_page(1).wait_for()
        self.page.wait_for_function("!document.querySelector('.deck-frame').contentDocument.querySelector('audio').paused")
        self.page.wait_for_function("document.querySelector('.deck-frame').contentDocument.getAnimations().some(animation => animation.playState === 'running')")

    def test_player_ignores_late_load_of_an_earlier_selection(self):
        self.open_playback_fixture(delayed_page=2)
        self.page.get_by_role("button", name="下一页", exact=True).click()
        self.assertTrue(self.pending_playback)
        self.page.get_by_role("status").filter(has_text="正在加载第 2 页").wait_for(timeout=2000)
        self.page.get_by_role("button", name="下一页", exact=True).click()
        self.playback_page(3).wait_for()
        route, response = self.pending_playback.pop()
        route.fulfill(body=response, content_type="text/html")
        self.page.wait_for_function("Array.from(document.querySelectorAll('.canvas iframe')).some(frame => frame.contentDocument?.querySelector('h1')?.textContent === 'Playback page 2')")
        self.playback_page(3).wait_for()
        self.assertEqual(int(self.page.locator("#page").input_value()), 3)
        self.assertFalse(self.page.locator("#page-loading").is_visible())

    def test_player_loading_feedback_covers_initial_page(self):
        self.open_playback_fixture(delayed_page=1, wait_for_first=False)
        loading = self.page.get_by_role("status").filter(has_text="正在加载第 1 页")
        loading.wait_for(timeout=2000)
        route, response = self.pending_playback.pop()
        route.fulfill(body=response, content_type="text/html")
        self.playback_page(1).wait_for()
        loading.wait_for(state="hidden")

    def test_player_cached_navigation_does_not_flash_loading(self):
        self.open_playback_fixture()
        self.page.wait_for_function("Array.from(document.querySelectorAll('.canvas iframe')).some(frame => frame.contentDocument?.readyState === 'complete' && frame.contentDocument.querySelector('h1')?.textContent === 'Playback page 2')")
        self.page.evaluate("""() => {
            const loading = document.querySelector('#page-loading');
            window.loadingFlashed = false;
            new MutationObserver(() => { if (!loading.hidden) window.loadingFlashed = true; }).observe(loading, {attributes:true, attributeFilter:['hidden']});
        }""")
        self.page.get_by_role("button", name="下一页", exact=True).click()
        self.playback_page(2).wait_for()
        self.assertFalse(self.page.evaluate("window.loadingFlashed"))
        self.assertFalse(self.page.locator("#page-loading").is_visible())

    def test_player_refresh_displays_loading_feedback(self):
        self.open_playback_fixture()
        document = self.page.frame_locator("iframe.deck-frame").locator("html").evaluate("element => element.outerHTML")
        pending = []
        self.page.route("**/playback-test/page-1.html?*", lambda route: pending.append(route))
        self.page.get_by_role("button", name="刷新", exact=True).click()
        loading = self.page.get_by_role("status").filter(has_text="正在加载第 1 页")
        loading.wait_for(timeout=2000)
        pending.pop().fulfill(body=document, content_type="text/html")
        self.playback_page(1).wait_for()
        loading.wait_for(state="hidden")

    def test_preloaded_page_cannot_play_audio_before_images_load(self):
        self.open_playback_fixture(delayed_image=True)
        self.page.wait_for_function("Array.from(document.querySelectorAll('.canvas iframe')).some(frame => frame.contentDocument?.querySelector('img'))")
        background = next(frame for frame in self.page.frames if "/playback-test/page-2.html" in frame.url)
        background.evaluate("document.querySelector('audio').play().catch(() => {})")
        self.assertTrue(background.locator("audio").evaluate("media => media.paused"))
        route, pixel = self.pending_playback.pop()
        route.fulfill(body=pixel, content_type="image/png")
        background.wait_for_function("document.readyState === 'complete'")

    def test_player_refresh_reloads_the_visible_page(self):
        self.open_playback_fixture()
        with self.page.expect_response(lambda response: "/playback-test/page-1.html" in response.url):
            self.page.get_by_role("button", name="刷新", exact=True).click()
        self.playback_page(1).wait_for()
        self.assertEqual(self.playback_requests.count(1), 2)

    def test_video_network_request_does_not_block_page_display(self):
        self.open_playback_fixture(delayed_video=True)
        self.page.get_by_role("button", name="下一页", exact=True).click()
        try:
            self.playback_page(2).wait_for(timeout=2500)
            self.page.locator("#page-loading").wait_for(state="hidden", timeout=2500)
        finally:
            for route, _ in self.pending_playback:
                route.fulfill(status=503, body="Unavailable")
            self.pending_playback.clear()

    def test_native_video_request_does_not_block_embedded_playback(self):
        document = b'''<!doctype html><html><head><meta name="fs-deck-generator" content="render-deck">
        <title>Native playback deck</title><style>.slide{width:1920px;height:1080px}.slide-frame:not(.is-current){display:none}</style></head><body><div class="deck">
        <div class="slide-frame is-current"><div class="slide"><h1>Native video page</h1>
        <video src="delayed-native.mp4" autoplay muted></video></div></div>
        <div class="slide-frame"><div class="slide"><h1>Native closing page</h1></div></div>
        </div><script>function goTo(deck, frames, idx) { frames.forEach((frame, index) => frame.classList.toggle('is-current', index === idx)); }</script></body></html>'''
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("index.html", document)
            archive.writestr("delayed-native.mp4", b"Video fixture")
        task = self.api.post("/api/import-tasks", multipart={"file": {"name": "native-playback.zip", "mimeType": "application/zip", "buffer": package.getvalue()}}).json()["task"]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            task = self.api.get("/api/import-tasks/" + task["id"]).json()["task"]
            if task["status"] in ("success", "failed"):
                break
            time.sleep(.1)
        self.assertEqual(task["status"], "success", task.get("error"))
        native = task["assetId"]
        pages = self.api.get("/api/reports/" + native + "/arrangement").json()["pages"]
        from server import report_viewer_html
        document = report_viewer_html("Native playback", [
            {"title": "Native video page", "src": "/pages/" + pages[0]["id"] + "/index.html"},
            {"title": "Closing page", "src": self.api.get("/api/assets/" + self.pages[0]).json()["asset"]["preview_url"]},
        ])
        self.page.route(self.base + "/native-playback/index.html", lambda route: route.fulfill(body=document, content_type="text/html"))
        pending = []
        self.page.route("**/delayed-native.mp4", lambda route: pending.append(route))
        try:
            self.page.goto(self.base + "/native-playback/index.html", wait_until="domcontentloaded")
            self.page.frame_locator("iframe.deck-frame").get_by_role("heading", name="Native video page").wait_for(timeout=2500)
            self.page.locator("#page-loading").wait_for(state="hidden", timeout=2500)
            self.assertTrue(pending)
            self.page.frame_locator("iframe.deck-frame").get_by_role("heading", name="Native video page").click()
            self.page.keyboard.press("ArrowRight")
            self.page.wait_for_function("Number(document.querySelector('#page').value) === 2")
        finally:
            for route in pending:
                route.fulfill(status=503, body="Unavailable")

    def export_html(self, report):
        task = self.api.post("/api/reports/" + report["id"] + "/exports", data={"format": "html"}).json()["task"]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            task = self.api.get("/api/report-exports/" + task["id"]).json()["task"]
            if task["status"] == "completed":
                return self.api.get(task["downloadUrl"]).body()
            self.assertNotEqual(task["status"], "failed", task.get("error"))
            time.sleep(.1)
        self.fail("Export did not finish")

    def test_exported_report_reimports_as_a_complete_report(self):
        exported = self.export_html(self.report)
        task = self.api.post("/api/import-tasks", multipart={"file": {"name": "exported-report.zip", "mimeType": "application/zip", "buffer": exported}}).json()["task"]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            task = self.api.get("/api/import-tasks/" + task["id"]).json()["task"]
            if task["status"] in ("success", "failed"):
                break
            time.sleep(.1)
        self.assertEqual(task["status"], "success", task.get("error"))
        self.assertEqual(task["assetType"], "report")
        original = self.api.get("/api/reports/" + self.report["id"] + "/pages").json()["slots"]
        imported = self.api.get("/api/reports/" + task["assetId"] + "/pages").json()["slots"]
        self.assertEqual(len(imported), len(original))
        self.assertEqual([page["title"] for page in imported], [page["title"] for page in original])

    def test_offline_export_rejects_required_online_media(self):
        document = b'<!doctype html><html><head><title>Remote media page</title></head><body><h1>Remote media</h1><video src="https://example.invalid/required-video.mp4"></video></body></html>'
        task = self.api.post("/api/import-tasks", multipart={"file": {"name": "remote-page.html", "mimeType": "text/html", "buffer": document}}).json()["task"]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            task = self.api.get("/api/import-tasks/" + task["id"]).json()["task"]
            if task["status"] in ("success", "failed"): break
            time.sleep(.1)
        self.assertEqual(task["status"], "success", task.get("error"))
        report = self.api.post("/api/reports", data={"title": "Remote media report", "pageIds": [task["assetId"]]}).json()["asset"]
        task = self.api.post("/api/reports/" + report["id"] + "/exports", data={"format": "html"}).json()["task"]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            task = self.api.get("/api/report-exports/" + task["id"]).json()["task"]
            if task["status"] in ("completed", "failed"): break
            time.sleep(.1)
        self.assertEqual(task["status"], "failed")
        self.assertIn("联网", task["error"])

    def test_local_html_export_supports_keyboard_navigation(self):
        exported = self.export_html(self.report)
        temporary = tempfile.TemporaryDirectory(prefix="minem-local-html-中文-")
        self.addCleanup(temporary.cleanup)
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            archive.extractall(temporary.name)
        self.context.set_offline(True)
        self.page.goto((Path(temporary.name) / "index.html").as_uri(), wait_until="load")
        self.page.wait_for_function("document.querySelector('.canvas').getAttribute('aria-busy') === 'false'")
        self.page.frame_locator("iframe.deck-frame").locator("body").click(position={"x": 30, "y": 30})
        self.page.keyboard.press("ArrowRight")
        self.page.wait_for_function("Number(document.querySelector('#page').value) === 2", timeout=2000)

    def test_arrangement_save_keeps_editor_free_of_detail_modals(self):
        self.open_arrangement()
        hide = self.page.get_by_role("button", name="隐藏页面", exact=True)
        hide.last.click()
        self.page.get_by_role("button", name="确认编排", exact=True).click()
        self.wait_arrangement_saved()
        self.assertEqual(self.page.locator(".modal").count(), 0)
        self.page.get_by_role("button", name="恢复页面", exact=True).click()
        self.page.get_by_role("button", name="确认编排", exact=True).click()
        self.wait_arrangement_saved()

    def test_arrangement_picker_blocks_existing_pages(self):
        self.open_arrangement()
        path = "/api/reports/" + self.report["id"] + "/arrangement"
        original = self.api.get(path).json()
        self.page.locator(".arrangement-page").first.drag_to(self.page.locator(".arrangement-page").last)
        with self.page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/arrangement")) as saved:
            self.page.get_by_role("button", name="确认编排", exact=True).click()
        moved = saved.value.json()
        self.wait_arrangement_saved()
        self.assertEqual(moved["pages"][-1]["id"], original["pages"][0]["id"])
        self.page.get_by_role("button", name="插入页面", exact=True).click()
        existing = moved["pages"][0]
        card = self.page.locator(".page-picker-card").filter(has_text=existing["code"])
        card.wait_for()
        self.assertTrue(card.is_disabled())
        source = self.api.get("/api/assets/" + self.pages[0]).json()["asset"]
        self.page.locator(".page-picker-card").filter(has_text=source["asset_code"]).click()
        self.page.get_by_role("button", name="插入所选页面", exact=True).click()
        self.page.get_by_role("button", name="确认编排", exact=True).click()
        self.wait_arrangement_saved()
        self.assertEqual(len(self.api.get(path).json()["pages"]), 4)
        self.page.get_by_role("button", name="从当前汇报移出", exact=True).last.click()
        self.page.get_by_role("button", name="确认编排", exact=True).click()
        self.wait_arrangement_saved()
        self.assertEqual(len(self.api.get(path).json()["pages"]), 3)
        self.assertTrue(self.api.get("/api/assets/" + self.pages[0]).ok)
        self.page.get_by_role("button", name="隐藏页面", exact=True).last.click()
        self.page.get_by_role("button", name="返回汇报", exact=True).click()
        self.page.get_by_role("button", name="放弃修改", exact=True).click()
        self.assertFalse(any(page["hidden"] for page in self.api.get(path).json()["pages"]))

    def test_stale_arrangement_save_is_rejected(self):
        self.open_arrangement()
        path = "/api/reports/" + self.report["id"] + "/arrangement"
        original = self.api.get(path).json()
        self.api.post(path, data={"pageOrder": [page["id"] for page in original["pages"]], "hiddenPageIds": [], "expectedUpdatedAt": original["updatedAt"]})
        self.page.get_by_role("button", name="隐藏页面", exact=True).last.click()
        with self.page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/arrangement")) as saved:
            self.page.get_by_role("button", name="确认编排", exact=True).click()
        self.assertEqual(saved.value.status, 409)

    def test_arrangement_cannot_be_edited_or_closed_during_save(self):
        self.open_arrangement()
        pending = []
        path = self.base + "/api/reports/" + self.report["id"] + "/arrangement"

        def hold_save(route):
            if route.request.method == "POST":
                pending.append(route)
            else:
                route.continue_()

        self.page.route(path, hold_save)
        self.page.get_by_role("button", name="隐藏页面", exact=True).last.click()
        self.page.get_by_role("button", name="确认编排", exact=True).click()
        try:
            self.assertTrue(pending)
            self.assertTrue(self.page.get_by_role("button", name="隐藏页面", exact=True).first.is_disabled())
            self.assertTrue(self.page.get_by_role("button", name="从当前汇报移出", exact=True).first.is_disabled())
            self.assertTrue(self.page.get_by_role("button", name="返回汇报", exact=True).is_disabled())
        finally:
            for route in pending:
                route.continue_()
        self.page.get_by_role("button", name="确认编排", exact=True).wait_for()
        self.assertTrue(self.page.get_by_role("button", name="恢复页面", exact=True).is_enabled())

    def test_export_submission_failure_is_visible(self):
        self.page.route("**/api/reports/*/exports", lambda route: route.fulfill(status=503, json={"ok": False, "error": "Test export unavailable"}))
        self.page.goto(self.base, wait_until="networkidle")
        self.page.locator(".asset-card-hit").first.click()
        self.page.locator('summary[aria-label="更多操作"]').click()
        self.page.get_by_role("button", name="导出", exact=True).click()
        self.page.get_by_role("button", name="HTML", exact=False).click()
        self.page.get_by_role("alert").filter(has_text="Test export unavailable").wait_for()

    def test_mobile_navigation_and_statistics_remain_reachable(self):
        for width in (320, 375, 390, 414, 768, 1024, 1440):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 900})
                self.page.goto(self.base, wait_until="networkidle")
                self.assertFalse(self.page.get_by_role("navigation").get_by_text("资源", exact=True).count())
                if width <= 760:
                    self.page.get_by_role("button", name="更多操作", exact=True).click()
                self.page.get_by_role("button", name="导入", exact=True).click()
                self.page.get_by_role("dialog").wait_for()
                self.page.get_by_role("button", name="取消", exact=True).click()
                if width <= 520:
                    self.page.get_by_role("button", name="展开全部", exact=True).click()
                    self.assertTrue(self.page.locator(".stat-part").first.is_visible())
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), width)
                boxes = self.page.locator(".topbar button:visible").evaluate_all("items=>items.map(item=>{const r=item.getBoundingClientRect();return {x:r.x,right:r.right,w:r.width,h:r.height}})")
                self.assertTrue(all(box["x"] >= 0 and box["right"] <= width + 1 for box in boxes))
                if width <= 760:
                    self.assertTrue(all(box["w"] >= 44 and box["h"] >= 44 for box in boxes))
        self.assertEqual(self.errors, [])

    def test_library_sort_filters_and_list_are_real_controls(self):
        self.page.goto(self.base, wait_until="networkidle")
        with self.page.expect_response(lambda response: "/api/assets?" in response.url and "sort=title" in response.url):
            self.page.get_by_label("排序方式").select_option("title")
        titles = self.api.get("/api/assets?view=list&type=control&sort=title").json()["assets"]
        self.assertEqual([item["title"] for item in titles], sorted(item["title"] for item in titles))
        with self.page.expect_response(lambda response: "/api/assets?" in response.url and "days=7" in response.url):
            self.page.get_by_label("时间范围").select_option("7")
        self.page.get_by_role("button", name="列表", exact=True).click()
        self.assertTrue(self.page.locator(".asset-grid").evaluate("node=>node.classList.contains('is-list')"))
        self.assertEqual(self.errors, [])

    def test_import_history_keeps_original_link_and_retry(self):
        link = "https://example.larkoffice.com/drive/folder/example"
        task = {"id":"history-task","filename":"历史飞书文件夹","status":"failed","progress":100,"error":"下载失败","sourceUrl":link,"createdAt":1,"updatedAt":1}
        self.page.route("**/api/import-tasks", lambda route: route.fulfill(json={"ok":True,"tasks":[task]}))
        self.page.route("**/api/import-tasks/drive", lambda route: route.fulfill(json={"ok":True,"tasks":[{**task,"id":"retry-task","status":"queued"}]}))
        self.page.goto(self.base, wait_until="networkidle")
        self.page.get_by_role("button", name="导入记录", exact=True).click()
        history = self.page.get_by_role("dialog")
        self.assertEqual(history.get_by_role("link", name="原飞书链接").get_attribute("href"), link)
        with self.page.expect_request("**/api/import-tasks/drive") as retried:
            history.get_by_role("button", name="重试导入").click()
        self.assertEqual(retried.value.post_data_json["links"], [link])

    def test_failed_import_removes_uncommitted_files(self):
        for missing in (False, True):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("index.html" if missing else "README.txt", '<img src="missing.png">' if missing else "empty material")
            response = self.api.post("/api/import-tasks", multipart={"file":{"name":"broken.zip","mimeType":"application/zip","buffer":stream.getvalue()}})
            task = response.json()["task"]
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                task = self.api.get("/api/import-tasks/"+task["id"]).json()["task"]
                if task["status"] in ("success","failed"): break
                time.sleep(.1)
            self.assertEqual(task["status"], "failed", task)
            self.assertFalse((Path(self.runtime.name)/"extracted"/task["uploadId"]).exists())
            self.assertFalse(any((Path(self.runtime.name)/"uploads").glob(task["uploadId"]+"*")))

    def test_export_history_survives_reopening(self):
        task = self.api.post("/api/reports/"+self.report["id"]+"/exports", data={"format":"html"}).json()["task"]
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            task = self.api.get("/api/report-exports/"+task["id"]).json()["task"]
            if task["status"] in ("completed","failed"): break
            time.sleep(.1)
        self.assertEqual(task["status"], "completed", task)
        tasks = self.api.get("/api/reports/"+self.report["id"]+"/exports").json()["tasks"]
        self.assertIn(task["id"], [item["id"] for item in tasks])
        self.assertIn("filename*=UTF-8", self.api.get(task["downloadUrl"]).headers["content-disposition"])
        self.page.goto(self.base, wait_until="networkidle")
        self.page.locator(".asset-card-hit").first.click()
        self.page.locator('summary[aria-label="更多操作"]').click()
        self.page.get_by_role("button", name="导出", exact=True).click()
        self.page.locator(".export-history").get_by_role("link").first.wait_for()

    def test_report_thumbnail_follows_confirmed_first_page(self):
        detail = self.api.get("/api/assets/"+self.report["id"]).json()["asset"]
        before = detail.get("thumbnail_url")
        arrangement = self.api.get("/api/reports/"+self.report["id"]+"/arrangement").json()
        order = [item["id"] for item in arrangement["pages"]]
        changed = self.api.post("/api/reports/"+self.report["id"]+"/arrangement",data={"pageOrder":order,"hiddenPageIds":[order[0]],"expectedUpdatedAt":arrangement["updatedAt"]})
        self.assertTrue(changed.json()["ok"],changed.text())
        deadline = time.monotonic()+35
        while time.monotonic()<deadline:
            detail = self.api.get("/api/assets/"+self.report["id"]).json()["asset"]
            if detail.get("thumbnail_url") and detail["thumbnail_url"]!=before: break
            time.sleep(.2)
        else:self.fail("The report thumbnail did not refresh after confirmation")
        state=json.loads((Path(self.runtime.name)/"thumbnails"/(self.report["id"]+".json")).read_text())
        self.assertTrue(state["sourceFingerprint"])
        self.assertTrue(self.api.get(detail["thumbnail_url"]).ok)

    def test_arrangement_long_titles_do_not_resize_or_overlap_previews(self):
        path="/api/reports/"+self.report["id"]+"/arrangement"
        pages=self.api.get(path).json()["pages"]
        title="05 附录 · 五层安全体系：分层防御、全链路覆盖 · "+"LongTitle"*30
        self.api.post("/api/assets/"+pages[1]["id"]+"/title",data={"title":title})
        for width in (390,768,1280,1493):
            self.page.set_viewport_size({"width":width,"height":900})
            self.open_arrangement()
            bounds=self.page.locator(".arrangement-page").evaluate_all("""cards=>cards.map(card=>{
              const r=card.getBoundingClientRect(),t=card.querySelector('.arrangement-thumb').getBoundingClientRect();
              const actions=card.querySelector('.arrangement-actions').getBoundingClientRect();
              return {left:r.left,right:r.right,width:r.width,scroll:card.scrollWidth,thumbLeft:t.left,thumbRight:t.right,ratio:t.width/t.height,actionRight:actions.right};
            })""")
            for card in bounds:
                self.assertLessEqual(card["scroll"],card["width"]+1,(width,card))
                self.assertGreaterEqual(card["thumbLeft"],card["left"])
                self.assertLessEqual(card["thumbRight"],card["right"]+1)
                self.assertLessEqual(card["actionRight"],card["right"]+1)
                self.assertAlmostEqual(card["ratio"],16/9,places=2)
            self.assertLessEqual(self.page.locator('.arrangement-workspace').evaluate('e=>e.scrollWidth'),width)
        self.assertEqual(self.errors,[])

    def test_arrangement_success_opens_latest_and_allows_another_save(self):
        self.open_arrangement()
        save=self.page.get_by_role("button",name="确认编排",exact=True)
        self.assertTrue(save.is_disabled())
        self.page.get_by_role("button",name="隐藏页面",exact=True).last.click()
        save.click()
        dialog=self.page.get_by_role("dialog",name="保存成功")
        dialog.wait_for()
        link=dialog.get_by_role("link",name="查看最新汇报")
        self.assertIn("/reports/"+self.report["id"]+"/index.html?v=",link.get_attribute("href"))
        with self.page.expect_popup() as opened:link.click()
        latest=opened.value
        latest.locator("#page").wait_for()
        self.assertIn(self.report["id"],latest.url)
        latest.close()
        self.assertTrue(save.is_disabled())
        self.page.get_by_role("button",name="恢复页面",exact=True).click()
        self.assertTrue(save.is_enabled())
        save.click()
        dialog.wait_for()
        dialog.get_by_role("button",name="继续编排",exact=True).click()
        self.assertTrue(save.is_disabled())
        self.assertFalse(any(page["hidden"] for page in self.api.get("/api/reports/"+self.report["id"]+"/arrangement").json()["pages"]))

    def test_arrangement_preview_failure_does_not_lose_saved_version(self):
        self.open_arrangement()
        self.page.route("**/reports/*/index.html?**",lambda route:route.fulfill(status=503,body="Preview unavailable"))
        self.page.get_by_role("button",name="隐藏页面",exact=True).last.click()
        self.page.get_by_role("button",name="确认编排",exact=True).click()
        dialog=self.page.get_by_role("dialog",name="保存成功")
        dialog.get_by_text("编排已保存，汇报预览暂时不可用，请稍后查看。").wait_for()
        dialog.get_by_role("button",name="继续编排",exact=True).click()
        self.page.get_by_role("button",name="恢复页面",exact=True).click()
        with self.page.expect_response(lambda response: response.request.method=="POST" and response.url.endswith("/arrangement")) as saved:
            self.page.get_by_role("button",name="确认编排",exact=True).click()
        self.assertEqual(saved.value.status,200)
        dialog.wait_for()

    def test_arrangement_rejected_save_keeps_edits_available(self):
        self.open_arrangement()
        path=self.base+"/api/reports/"+self.report["id"]+"/arrangement"
        def reject(route):
            if route.request.method=="POST":route.fulfill(status=503,json={"ok":False,"error":"Save unavailable"})
            else:route.continue_()
        self.page.route(path,reject)
        self.page.get_by_role("button",name="隐藏页面",exact=True).last.click()
        self.page.get_by_role("button",name="确认编排",exact=True).click()
        self.page.get_by_role("alert").filter(has_text="Save unavailable").wait_for()
        self.assertTrue(self.page.get_by_role("button",name="确认编排",exact=True).is_enabled())
        self.assertFalse(self.page.get_by_role("dialog",name="保存成功").count())

    def test_arrangement_picker_failure_can_retry_and_missing_thumbnail_is_safe(self):
        self.open_arrangement()
        source=self.api.get("/api/assets/"+self.pages[0]).json()["asset"]
        source["thumbnail_url"]=""
        calls=[]
        def search(route):
            if "type=control" not in route.request.url:route.continue_();return
            calls.append(1)
            if len(calls)==1:route.fulfill(status=503,json={"ok":False,"error":"Page library unavailable"})
            else:route.fulfill(json={"ok":True,"assets":[source],"pagination":{"hasNext":False}})
        self.page.route("**/api/assets?**",search)
        self.page.get_by_role("button",name="插入页面",exact=True).click()
        self.page.get_by_role("alert").filter(has_text="Page library unavailable").wait_for()
        self.page.get_by_role("button",name="重试",exact=True).click()
        self.page.locator(".page-picker-card").click()
        self.page.get_by_role("button",name="插入所选页面",exact=True).click()
        card=self.page.locator(".arrangement-page").last
        self.assertEqual(card.locator("img").count(),0,"HTML must never be assigned to an image src")
        card.get_by_text("预览生成中",exact=True).wait_for()
        card.locator("img.is-loaded").wait_for(timeout=10000)
        self.assertFalse(card.locator("img").get_attribute("src").endswith(".html"))
        self.assertTrue(self.page.get_by_role("button",name="确认编排",exact=True).is_enabled())
        self.assertEqual(self.errors,[])


if __name__ == "__main__":
    unittest.main()
