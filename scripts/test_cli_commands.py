#!/usr/bin/env python3
"""Check CLI table output against the report page API contract."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minem.cli.commands import CommandContext, report_pages


class PageClient:
    def request(self, method, path):
        if path == "/api/assets/report":
            return {"asset": {"id": "report", "asset_type": "report", "asset_code": "RPT-001"}}
        if path == "/api/reports/report/pages":
            return {"slots": [
                {"page_number": 1, "title": "封面", "control_id": "cover", "control": {"id": "cover", "asset_code": "CTRL-COVER"}},
                {"page_number": 2, "title": "正文", "control_id": "page", "control": {"id": "page", "asset_code": "CTRL-PAGE"}},
                {"page_number": 3, "title": "计划页", "control_id": "", "control": None},
            ]}
        raise AssertionError((method, path))


class PageTableChecks(unittest.TestCase):
    def test_report_pages_expose_public_codes_for_member_operations(self):
        ctx = CommandContext(PageClient(), "http://127.0.0.1", 30, True)
        result = report_pages(ctx, SimpleNamespace(report="report"))
        self.assertEqual(result["rows"], [
            {"position": 1, "code": "CTRL-COVER", "title": "封面", "id": "cover"},
            {"position": 2, "code": "CTRL-PAGE", "title": "正文", "id": "page"},
            {"position": 3, "code": "", "title": "计划页", "id": ""},
        ])


if __name__ == "__main__":
    unittest.main()
