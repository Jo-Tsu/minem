from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendLayoutContractsTest(unittest.TestCase):
    def test_arrangement_grid_rows_do_not_overlap(self) -> None:
        css = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".arrangement-grid.arrangement-workspace-grid {", css)
        self.assertIn("grid-auto-rows: max-content;", css)
        self.assertNotIn("grid-auto-rows: minmax(0, auto);", css)

    def test_detail_preview_uses_canvas_aspect_ratio(self) -> None:
        css = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("width: min(100%, 920px, calc(68vh * 16 / 9));", css)
        self.assertIn(".modal-preview .frame-shell {", css)
        self.assertIn("height: auto;", css)

    def test_report_iframes_use_public_read_only_viewer(self) -> None:
        preview = (ROOT / "frontend" / "src" / "components" / "AssetPreview.tsx").read_text(encoding="utf-8")
        app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("/reports/${encodeURIComponent(asset.id)}/index.html", preview)
        self.assertIn("/reports/${encodeURIComponent(source.id)}/index.html?embed=1", app)
        self.assertNotIn("/api/reports/${encodeURIComponent(asset.id)}/arrangement/viewer", preview)

    def test_material_libraries_use_five_column_desktop_grid(self) -> None:
        css = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".asset-grid {\n  display: grid;\n  grid-template-columns: repeat(5, minmax(0, 1fr));", css)
        self.assertIn(".case-card-grid {\n  display: grid;\n  grid-template-columns: repeat(5, minmax(0, 1fr));", css)
        self.assertIn(".page-picker-grid { overflow: auto; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));", css)

    def test_arrangement_uses_pointer_drag_handle_instead_of_native_card_drag(self) -> None:
        app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("beginPointerDrag", app)
        self.assertIn("onPointerMove={continuePointerDrag}", app)
        self.assertIn("onPointerUp={finishPointerDrag}", app)
        self.assertIn("document.elementsFromPoint(clientX, clientY)", app)
        self.assertIn("scrollArrangementAt(event.clientY)", app)
        self.assertIn("ref={arrangementGridRef}", app)
        self.assertNotIn('data-arrangement-page={page.id} tabIndex={0} draggable=', app)

    def test_preview_sandbox_only_trusts_platform_viewers(self) -> None:
        security = (ROOT / "frontend" / "src" / "previewSecurity.ts").read_text(encoding="utf-8")

        self.assertIn('TRUSTED_PREVIEW_SANDBOX = "allow-scripts allow-same-origin', security)
        self.assertNotIn('SOURCE_PREVIEW_SANDBOX = "allow-scripts allow-same-origin', security)
        self.assertIn('path.startsWith("/temp-reports/")', security)

    def test_narrow_topbar_navigation_scrolls_instead_of_overflowing(self) -> None:
        css = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(
            ".pill-nav { order: 3; width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }",
            css,
        )

    def test_import_task_dock_exposes_safe_cancellation(self) -> None:
        app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        widgets = (ROOT / "frontend" / "src" / "components" / "ImportWidgets.tsx").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

        self.assertIn("cancelImportTask", app)
        self.assertIn("cancelTask(task.id)", widgets)
        self.assertIn("/cancel`", api)

    def test_presenter_dialog_exposes_delete_and_restore(self) -> None:
        app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

        self.assertIn("deletePresenterScript", app)
        self.assertIn("restorePresenterScript", app)
        self.assertIn("恢复演讲稿", app)
        self.assertIn("deleteReportPresenterScript", api)
        self.assertIn("restoreReportPresenterScript", api)

    def test_report_detail_exposes_platform_presenter_mode(self) -> None:
        app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        types = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")

        self.assertIn("汇报模式", app)
        self.assertIn("/presenter.html", app)
        self.assertIn("presenterModeUrl", types)

    def test_tag_taxonomy_editor_is_available_from_global_actions(self) -> None:
        app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

        self.assertIn("TagTaxonomyDialog", app)
        self.assertIn('title="标签设置"', app)
        self.assertIn("updateTagTaxonomy", api)


if __name__ == "__main__":
    unittest.main()
