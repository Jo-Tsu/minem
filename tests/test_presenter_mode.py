import unittest

from minem.presenter_mode import (
    attach_presenter_notes,
    render_audience_view,
    render_presenter_console,
)


class PresenterModeTest(unittest.TestCase):
    def test_notes_follow_stable_page_identity_before_position(self) -> None:
        pages = [
            {"id": "control-b", "code": "CTRL-B", "title": "第二页", "src": "/pages/control-b/index.html"},
            {"id": "control-a", "code": "CTRL-A", "title": "第一页", "src": "/pages/control-a/index.html"},
        ]
        legacy_pages = [
            {"id": "legacy-a", "code": "CTRL-A", "title": "第一页", "src": "a.html"},
            {"id": "legacy-b", "code": "CTRL-B", "title": "第二页", "src": "b.html"},
        ]
        notes = {"legacy-a": "第一页讲稿", "legacy-b": "第二页讲稿"}

        result = attach_presenter_notes(pages, legacy_pages, notes)

        self.assertEqual(result[0]["speakerNote"], "第二页讲稿")
        self.assertEqual(result[1]["speakerNote"], "第一页讲稿")

    def test_console_and_audience_share_one_platform_channel(self) -> None:
        pages = [{
            "id": "control-a",
            "code": "CTRL-A",
            "title": "第一页",
            "src": "/pages/control-a/index.html",
            "thumbnailUrl": "/thumbs/control-a.png",
            "speakerNote": "提示词",
        }]

        console = render_presenter_console("report-a", "测试汇报", pages)
        audience = render_audience_view("report-a", "测试汇报", pages)

        self.assertIn("minem-presenter:${reportId}", console)
        self.assertIn("/reports/report-a/audience.html", console)
        self.assertIn("当前页提示词", console)
        self.assertIn('class="notes-editor"', console)
        self.assertIn("/presenter-notes", console)
        self.assertIn("⌘S 保存", console)
        self.assertNotIn("下一页预览", console)
        self.assertNotIn("<h2>下一页</h2>", console)
        self.assertIn("投影窗口", console)
        self.assertIn("BroadcastChannel", audience)
        self.assertIn('url.searchParams.set("embed", "1")', audience)
        self.assertIn("--deck-scale", audience)
        self.assertIn("window.innerWidth / 1920", audience)


if __name__ == "__main__":
    unittest.main()
