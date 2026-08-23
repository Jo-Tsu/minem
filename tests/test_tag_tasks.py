from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from minem import tag_tasks


class TagTaskIsolationTest(unittest.TestCase):
    def test_one_bad_asset_does_not_abort_the_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "materials.db"
            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                create table assets (
                  id text primary key,title text,usage text default '',snippet text default '',
                  asset_type text,asset_code text,source_type text default '',source_path text default '',
                  preview_url text default '',upload_id text,created_at integer,updated_at integer,
                  source_hash text default '',media_kind text default '',resource_kind text default '',
                  tags text default '',tag_seeded integer default 0
                );
                create table report_page_slots (
                  report_id text,control_id text,page_number integer,updated_at integer
                );
                insert into assets(id,title,asset_type,asset_code,created_at,updated_at)
                values ('bad','Bad','control','CTRL-BAD',1,1);
                insert into assets(id,title,asset_type,asset_code,created_at,updated_at)
                values ('good','Good','control','CTRL-GOOD',1,1);
                """
            )
            tag_tasks.ensure_schema(conn)
            task = tag_tasks.create_task(conn, ["bad", "good"])
            conn.commit()
            conn.close()

            real_collect = tag_tasks.collect_evidence

            def collect(conn, asset, extracted_root):
                if asset["id"] == "bad":
                    raise ValueError("broken asset")
                return real_collect(conn, asset, extracted_root)

            with patch.object(tag_tasks, "collect_evidence", side_effect=collect):
                tag_tasks.run_task(database, Path(temp_dir), task["taskId"])

            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "select * from tag_analysis_tasks where id = ?",
                    (task["taskId"],),
                ).fetchone()
                evidence_ids = {
                    item["asset_id"]
                    for item in conn.execute("select asset_id from asset_tag_evidence")
                }
            finally:
                conn.close()

            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["processed_count"], 2)
            self.assertEqual(row["error_count"], 1)
            self.assertIn("1 个素材分析失败", row["message"])
            self.assertEqual(evidence_ids, {"good"})


if __name__ == "__main__":
    unittest.main()
