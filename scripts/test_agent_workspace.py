#!/usr/bin/env python3
"""Check that the code map reads project source rather than generated material."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from minem.agent.workspace import iter_source_files


class WorkspaceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="minem-workspace-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# source\n")

    def sources(self, **options):
        return [path.relative_to(self.root).as_posix() for path in iter_source_files(self.root, **options)]

    def test_environment_and_material_files_do_not_enter_the_code_map(self):
        expected = ["frontend/src/App.tsx", "minem/imports.py", "server.py"]
        excluded = [".venv/lib/third_party.py", "runtime/extracted/page.html", "node_modules/package/index.js",
                    "desktop/node_modules/package/index.js", "desktop/src-tauri/target/debug/build/config.json",
                    "report-exports/report/index.html"]
        for relative in [*expected, *excluded]:
            self.write(relative)
        self.assertEqual(self.sources(), expected)

    def test_limit_counts_project_sources_and_retains_sorted_order(self):
        for relative in [".venv/lib/module.py", "z.py", "a/main.py", "a.py"]:
            self.write(relative)
        self.assertEqual(self.sources(max_files=2), ["a/main.py", "a.py"])
        self.assertEqual(self.sources(max_files=0), [])

    def test_directory_symlinks_are_not_followed(self):
        self.write("source/main.py")
        (self.root / "linked").symlink_to(self.root / "source", target_is_directory=True)
        self.assertEqual(self.sources(), ["source/main.py"])

    def test_missing_workspace_has_no_sources(self):
        self.assertEqual(list(iter_source_files(self.root / "missing")), [])


if __name__ == "__main__":
    unittest.main()
