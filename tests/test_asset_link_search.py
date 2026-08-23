import sqlite3
import unittest

from minem.assets import asset_search_terms, list_assets_response


class AssetLinkSearchTests(unittest.TestCase):
    def test_report_viewer_link_exposes_fragment_page_code(self):
        url = (
            "http://127.0.0.1:8790/reports/import-20260808-215118-6cc0e7f4-report/"
            "index.html#page=CTRL-20260808-001-005"
        )

        terms = asset_search_terms(url)

        self.assertIn("/reports/import-20260808-215118-6cc0e7f4-report/index.html", terms)
        self.assertIn("CTRL-20260808-001-005", terms)

    def test_encoded_page_link_is_decoded(self):
        terms = asset_search_terms("http://127.0.0.1:8790/?page=CTRL%2DPAGE%2D031")

        self.assertIn("CTRL-PAGE-031", terms)

    def test_plain_asset_code_remains_searchable(self):
        self.assertEqual(asset_search_terms("CTRL-PAGE-031"), ["CTRL-PAGE-031"])

    def test_link_matching_a_historical_version_returns_the_primary_card(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            create table assets (
              id text primary key, asset_code text, title text, usage text, tags text,
              source_path text, preview_url text, upload_id text, asset_type text,
              category text, resource_kind text, page_role text, version_group text,
              version_parent_id text, created_at integer, updated_at integer
            );
            create table report_page_slots (control_id text, updated_at integer);
            create table report_page_candidates (control_id text, updated_at integer);
            insert into assets values
              ('primary','CTRL-PAGE-001','主版本','','','index.html','/pages/primary/index.html','batch','control','page','','','group-1','',10,20),
              ('history','CTRL-PAGE-001-C001','历史版本','','','index.html','/extracted/batch/history/index.html','batch','control','page','','','group-1','primary',5,15);
            """
        )

        payload = list_assets_response(
            conn,
            {
                "view": ["list"],
                "type": ["control"],
                "page": ["1"],
                "page_size": ["30"],
                "q": ["http://127.0.0.1:8790/extracted/batch/history/index.html"],
            },
            add_version_counts=lambda _conn, rows, **_kwargs: [dict(row) for row in rows],
            pipeline_summary=lambda _conn: {},
            categories={},
            asset_types={},
            resource_kinds={},
            page_roles={},
            tag_taxonomy={},
        )

        self.assertEqual([item["id"] for item in payload["assets"]], ["primary"])


if __name__ == "__main__":
    unittest.main()
