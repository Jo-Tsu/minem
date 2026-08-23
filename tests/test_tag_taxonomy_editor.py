from pathlib import Path
import sqlite3
import tempfile
import unittest

from minem.tag_tasks import (
    ensure_schema,
    taxonomy_definitions,
    update_taxonomy_definitions,
)


class TagTaxonomyEditorTest(unittest.TestCase):
    def test_updates_persist_and_govern_existing_asset_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "materials.db"
            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                create table assets (
                  id text primary key,
                  tags text default '',
                  tag_seeded integer default 0
                );
                insert into assets(id,tags,tag_seeded) values ('asset-a','制造,质量管理',1);
                """
            )
            ensure_schema(conn)
            conn.execute(
                """
                insert into asset_tags(
                  asset_id,tag,dimension,source,confidence,evidence_json,confirmed_at,updated_at
                ) values ('asset-a','制造','行业','manual',1,'[]',1,1)
                """
            )
            conn.execute(
                """
                insert into asset_tags(
                  asset_id,tag,dimension,source,confidence,evidence_json,confirmed_at,updated_at
                ) values ('asset-a','质量管理','业务主题','manual',1,'[]',1,1)
                """
            )
            payload = taxonomy_definitions(conn)
            definitions = [
                {
                    "tag": item["tag"],
                    "dimension": "业务主题" if item["tag"] == "制造" else item["dimension"],
                    "active": False if item["tag"] == "质量管理" else item["active"],
                }
                for item in payload["definitions"]
            ]

            result = update_taxonomy_definitions(conn, {"definitions": definitions})
            self.assertTrue(result["ok"], result)
            ensure_schema(conn)

            manufacturing = conn.execute(
                "select dimension,active from tag_definitions where tag='制造'"
            ).fetchone()
            quality = conn.execute(
                "select dimension,active from tag_definitions where tag='质量管理'"
            ).fetchone()
            relation = conn.execute(
                "select dimension from asset_tags where asset_id='asset-a' and tag='制造'"
            ).fetchone()
            cache = conn.execute("select tags from assets where id='asset-a'").fetchone()["tags"]
            conn.close()

            self.assertEqual(manufacturing["dimension"], "业务主题")
            self.assertEqual(manufacturing["active"], 1)
            self.assertEqual(quality["active"], 0)
            self.assertEqual(relation["dimension"], "业务主题")
            self.assertEqual(cache, "制造")

    def test_rejects_unknown_dimension_and_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conn = sqlite3.connect(Path(temp_dir) / "materials.db")
            conn.row_factory = sqlite3.Row
            ensure_schema(conn)
            unknown_dimension = update_taxonomy_definitions(
                conn,
                {"definitions": [{"tag": "制造", "dimension": "未知维度", "active": True}]},
            )
            unknown_tag = update_taxonomy_definitions(
                conn,
                {"definitions": [{"tag": "不存在", "dimension": "行业", "active": True}]},
            )
            conn.close()

            self.assertFalse(unknown_dimension["ok"])
            self.assertFalse(unknown_tag["ok"])


if __name__ == "__main__":
    unittest.main()
