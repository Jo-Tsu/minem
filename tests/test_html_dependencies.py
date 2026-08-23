from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from minem.html_dependencies import audit_dependency_closure


class HtmlDependencyAuditTests(unittest.TestCase):
    def test_missing_direct_html_resource_is_blocking(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text('<img src="assets/required.png">', encoding="utf-8")

            audit = audit_dependency_closure(root)

            self.assertEqual(len(audit["blockingMissing"]), 1)
            self.assertEqual(audit["blockingMissing"][0]["resolved"], "assets/required.png")
            self.assertEqual(audit["warningMissing"], [])

    def test_missing_stylesheet_url_is_a_non_blocking_warning(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            css = root / "css" / "deck.css"
            css.parent.mkdir(parents=True)
            (root / "index.html").write_text(
                '<link rel="stylesheet" href="css/deck.css"><main>Ready</main>',
                encoding="utf-8",
            )
            css.write_text(
                '.unused-avatar { background-image: url("assets/missing-avatar.png"); }',
                encoding="utf-8",
            )

            audit = audit_dependency_closure(root)

            self.assertEqual(audit["blockingMissing"], [])
            self.assertEqual(len(audit["warningMissing"]), 1)
            self.assertEqual(audit["warningMissing"][0]["severity"], "warning")
            self.assertEqual(audit["warningMissing"][0]["resolved"], "css/assets/missing-avatar.png")

    def test_missing_stylesheet_url_used_by_html_is_blocking(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            css = root / "css" / "deck.css"
            css.parent.mkdir(parents=True)
            (root / "index.html").write_text(
                '<link rel="stylesheet" href="css/deck.css"><main class="hero">Ready</main>',
                encoding="utf-8",
            )
            css.write_text(
                '.hero { background-image: url("assets/required-background.png"); }',
                encoding="utf-8",
            )

            audit = audit_dependency_closure(root)

            self.assertEqual(len(audit["blockingMissing"]), 1)
            self.assertEqual(audit["blockingMissing"][0]["resolved"], "css/assets/required-background.png")
            self.assertEqual(audit["warningMissing"], [])

    def test_unique_missing_collapses_repeated_css_references(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            css_dir = root / "css"
            css_dir.mkdir(parents=True)
            (root / "index.html").write_text(
                '<link rel="stylesheet" href="css/a.css"><link rel="stylesheet" href="css/b.css">',
                encoding="utf-8",
            )
            for name in ("a.css", "b.css"):
                (css_dir / name).write_text(
                    '.unused { background: url("assets/shared.png"); }',
                    encoding="utf-8",
                )

            audit = audit_dependency_closure(root)

            self.assertEqual(len(audit["warningMissing"]), 2)
            self.assertEqual(len(audit["uniqueMissing"]), 1)


if __name__ == "__main__":
    unittest.main()
