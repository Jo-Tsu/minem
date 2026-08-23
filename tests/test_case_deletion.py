from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from minem.asset_deletion import AssetDeletionError
from minem.case_deletion import (
    apply_case_group_deletion_plan,
    build_case_group_deletion_plan,
)
from minem.case_groups import (
    case_group_asset_codes,
    case_group_control_codes,
    case_group_manifest_paths,
)
from minem.db import create_core_schema, ensure_asset_schema, ensure_upload_schema


class CaseGroupDeletionTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        create_core_schema(self.conn)
        ensure_asset_schema(self.conn)
        ensure_upload_schema(self.conn)
        self._asset("case-page-1", "CTRL-CASE-001", "control", version_group="case-page-1")
        self._asset(
            "case-page-1-v2",
            "CTRL-CASE-001-V2",
            "control",
            version_group="case-page-1",
            version_parent_id="case-page-1",
            version_no=2,
        )
        self._asset("case-page-2", "CTRL-CASE-002", "control", version_group="case-page-2")
        self._asset("case-resource", "RES-CASE-001", "resource", version_group="case-resource")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _asset(
        self,
        asset_id,
        asset_code,
        asset_type,
        *,
        version_group,
        version_parent_id="",
        version_no=1,
    ):
        self.conn.execute(
            """
            insert into assets (
                id, title, asset_type, asset_code, source_path, preview_url,
                created_at, updated_at, version_group, version_parent_id, version_no
            ) values (?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?)
            """,
            (
                asset_id,
                asset_code,
                asset_type,
                asset_code,
                f"{asset_id}/index.html",
                f"/pages/{asset_id}/index.html",
                version_group,
                version_parent_id,
                version_no,
            ),
        )

    def test_deletes_all_case_pages_and_versions_but_retains_resources(self):
        controls = [
            {"code": "CTRL-CASE-001"},
            {"code": "CTRL-CASE-001"},
            {"code": "CTRL-CASE-002"},
        ]
        with self.conn:
            plan = build_case_group_deletion_plan(self.conn, "CASE-TEST-001", controls)
            result = apply_case_group_deletion_plan(self.conn, plan, timestamp=2)

        self.assertEqual(result["deleted_page_count"], 2)
        self.assertEqual(result["deleted_asset_count"], 3)
        remaining = self.conn.execute(
            "select id, asset_type from assets order by id"
        ).fetchall()
        self.assertEqual([dict(row) for row in remaining], [
            {"id": "case-resource", "asset_type": "resource"},
        ])

    def test_reference_blocks_the_entire_case_deletion(self):
        self._asset("case-report", "RPT-CASE-001", "report", version_group="case-report")
        self.conn.execute(
            """
            insert into report_page_slots (
                report_id, page_number, title, status, control_id,
                task_key, note, created_at, updated_at
            ) values ('case-report', 1, '案例页', 'completed', 'case-page-2', '', '', 2, 2)
            """
        )
        self.conn.commit()

        with self.assertRaises(AssetDeletionError) as raised:
            with self.conn:
                self.conn.execute("begin immediate")
                build_case_group_deletion_plan(
                    self.conn,
                    "CASE-TEST-001",
                    [{"code": "CTRL-CASE-001"}, {"code": "CTRL-CASE-002"}],
                )

        error = raised.exception
        self.assertEqual(error.status, 409)
        self.assertEqual(error.details["referenceCodes"], ["RPT-CASE-001"])
        self.assertEqual(error.details["blockedPages"][0]["code"], "CTRL-CASE-002")
        self.assertEqual(
            self.conn.execute(
                "select count(*) from assets where id like 'case-page-%'"
            ).fetchone()[0],
            3,
        )

    def test_manifest_lookup_includes_pages_filtered_out_of_the_visible_list(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_root = root / "20-case-control-library" / "CASE-TEST-001"
            case_root.mkdir(parents=True)
            manifest = case_root / "manifest.json"
            manifest.write_text(json.dumps({
                "code": "CASE-TEST-001",
                "controls": [
                    {"code": "CTRL-CASE-001"},
                    {"control_code": "CTRL-CASE-HIDDEN"},
                    {"code": "CTRL-CASE-001"},
                ],
            }), encoding="utf-8")

            self.assertEqual(
                case_group_manifest_paths(root, [], "CASE-TEST-001"),
                [manifest.resolve()],
            )
            self.assertEqual(
                case_group_control_codes(root, [], "CASE-TEST-001"),
                ["CTRL-CASE-001", "CTRL-CASE-HIDDEN"],
            )
            self.assertEqual(
                case_group_asset_codes(root, []),
                ["CTRL-CASE-001", "CTRL-CASE-HIDDEN"],
            )


if __name__ == "__main__":
    unittest.main()
