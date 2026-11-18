#!/usr/bin/env python3
"""Exercise task recovery through the actual database startup path."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minem.report_exports import ReportExportTaskStore


class RecoveryChecks(unittest.TestCase):
    def test_restart_fails_interrupted_exports_and_keeps_finished_exports(self):
        with tempfile.TemporaryDirectory(prefix="minem-recovery-test-") as runtime:
            store = ReportExportTaskStore(Path(runtime) / "data/materials.db")
            for status in ("queued", "running", "completed", "failed"):
                store.create({"id": status, "reportId": "report", "status": status, "progress": 42, "filename": "report.zip"})
            result = subprocess.run(
                [sys.executable, "-c", "import server; server.init_db()"], cwd=ROOT,
                env={**os.environ, "MINEM_DATA_DIR": runtime, "AUTO_IMPORT_ON_START": "0"}, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for status in ("queued", "running"):
                task = store.get(status)
                self.assertEqual(task["status"], "failed")
                self.assertEqual(task["progress"], 100)
                self.assertTrue(task["error"])
            self.assertEqual(store.get("completed")["status"], "completed")
            self.assertEqual(store.get("completed")["filename"], "report.zip")
            self.assertEqual(store.get("failed")["status"], "failed")


if __name__ == "__main__":
    unittest.main()
