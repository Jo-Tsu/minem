import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class ReportExportOfflineTests(unittest.TestCase):
    def test_localhost_extracted_asset_is_copied_and_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            extracted = root / "extracted"
            source = extracted / "source-a" / "page.html"
            asset = extracted / "source-b" / "assets" / "logo.svg"
            bundle = root / "bundle"
            destination = bundle / "pages" / "page-001" / "page.html"
            source.parent.mkdir(parents=True)
            asset.parent.mkdir(parents=True)
            asset.write_text("<svg/>", encoding="utf-8")
            source.write_text(
                '<img src="http://127.0.0.1:8790/extracted/source-b/assets/logo.svg?embed=1">',
                encoding="utf-8",
            )

            with patch.object(server, "EXTRACTED", extracted):
                server.copy_report_export_dependency(source, destination, extracted / "source-a", bundle, set())

            exported = destination.read_text(encoding="utf-8")
            self.assertNotIn("127.0.0.1", exported)
            self.assertIn("../../extracted/source-b/assets/logo.svg", exported)
            self.assertTrue((bundle / "extracted/source-b/assets/logo.svg").is_file())


if __name__ == "__main__":
    unittest.main()
