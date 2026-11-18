#!/usr/bin/env python3
"""Verify material audits distinguish embedded data from missing files."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
import govern_material_data as audit
import run_core_tests as core


class MaterialAuditChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="minem-audit-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.extracted = self.root / "extracted"
        self.page = self.extracted / "upload" / "index.html"
        self.page.parent.mkdir(parents=True)
        self.row = {"upload_id": "upload", "source_path": "index.html", "preview_url": "/extracted/upload/index.html"}

    def missing(self, document):
        self.page.write_text(document)
        with patch.object(server, "EXTRACTED", self.extracted), patch.object(audit, "ROOT", self.root), patch.object(audit, "EXTRACTED", self.extracted):
            return audit.html_missing_refs(self.row)

    def test_entity_quoted_embedded_image_is_not_a_file(self):
        self.assertEqual(self.missing('<div style="background:url(&quot;data:image/png;base64,' + 'A' * 8000 + '&quot;)"></div>'), [])

    def test_missing_image_is_reported(self):
        self.assertEqual(self.missing('<img src="missing.svg">'), ["missing.svg"])

    def test_script_text_is_not_parsed_as_a_css_dependency(self):
        self.assertEqual(self.missing('<script>const example="url(not-a-file.png)";</script>'), [])

    def test_encoded_svg_fragment_is_not_a_file(self):
        self.assertEqual(self.missing('<svg style="fill:url(%23n)"><defs id="n"/></svg>'), [])

    def test_full_audit_passes_the_selected_runtime_to_dependency_audit(self):
        result = subprocess.run(
            [sys.executable, "-c", "import server; server.init_db()"], cwd=core.ROOT,
            env={**os.environ, "MINEM_DATA_DIR": str(self.root), "AUTO_IMPORT_ON_START": "0"},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        reporter = core.Reporter()
        with patch.object(core, "RUNTIME_ROOT", self.root), patch.dict(os.environ, {"MINEM_DATA_DIR": ""}):
            with core.connect(self.root / "data/materials.db") as conn:
                core.run_data_checks(conn, reporter)
        dependency_check = next(item for item in reporter.items if item["case"] == "DATA-002A")
        self.assertEqual(dependency_check["status"], "passed", dependency_check)


if __name__ == "__main__":
    unittest.main()
