#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from minem.runtime_discovery import (
    DEFAULT_BASE_URL,
    discover_service_manifest,
    resolve_base_url,
    resolve_or_launch_base_url,
)
from minem.cli.config import effective_server


class RuntimeDiscoveryTests(unittest.TestCase):
    def test_explicit_url_has_highest_priority(self):
        with patch.dict(os.environ, {"MINEM_BASE_URL": "http://127.0.0.1:9000"}, clear=False):
            self.assertEqual(resolve_base_url("http://127.0.0.1:9100/"), "http://127.0.0.1:9100")

    def test_environment_url_precedes_manifest(self):
        with patch.dict(os.environ, {"MINEM_BASE_URL": "http://localhost:9000/"}, clear=False):
            self.assertEqual(resolve_base_url(), "http://localhost:9000")

    def test_running_manifest_is_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "service.json").write_text(
                json.dumps({
                    "status": "running",
                    "baseUrl": "http://127.0.0.1:9123",
                    "port": 9123,
                    "managedByClient": True,
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"MINEM_BASE_URL": ""}, clear=False), patch(
                "minem.runtime_discovery.candidate_data_roots", return_value=[root]
            ):
                manifest = discover_service_manifest()
                self.assertIsNotNone(manifest)
                self.assertEqual(resolve_base_url(), "http://127.0.0.1:9123")

    def test_external_manifest_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "service.json").write_text(
                json.dumps({"status": "running", "baseUrl": "https://example.com", "port": 443}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"MINEM_BASE_URL": ""}, clear=False), patch(
                "minem.runtime_discovery.candidate_data_roots", return_value=[root]
            ):
                self.assertIsNone(discover_service_manifest())
                self.assertEqual(resolve_base_url(), DEFAULT_BASE_URL)

    def test_unmanaged_mine_m_service_is_not_a_desktop_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "service.json").write_text(
                json.dumps({
                    "status": "running",
                    "baseUrl": "http://127.0.0.1:8790",
                    "port": 8790,
                    "managedByClient": False,
                }),
                encoding="utf-8",
            )
            with patch("minem.runtime_discovery.candidate_data_roots", return_value=[root]):
                self.assertIsNone(discover_service_manifest())

    def test_cli_launches_the_desktop_client_and_waits_for_its_manifest(self):
        manifest = {"baseUrl": "http://127.0.0.1:49152"}
        launch_result = type("Result", (), {"returncode": 0})()
        with (
            patch("minem.runtime_discovery.sys.platform", "darwin"),
            patch("minem.runtime_discovery.discover_service_manifest", side_effect=[None, manifest]),
            patch("minem.runtime_discovery.service_is_ready", return_value=True),
            patch("minem.runtime_discovery.subprocess.run", return_value=launch_result) as launch,
        ):
            self.assertEqual(
                resolve_or_launch_base_url(timeout=1, poll_interval=0.02),
                manifest["baseUrl"],
            )
        launch.assert_called_once()

    def test_modular_cli_uses_the_auto_launch_resolver(self):
        with (
            patch("minem.cli.config.load_config", return_value={}),
            patch(
                "minem.cli.config.resolve_or_launch_base_url",
                return_value="http://127.0.0.1:49200",
            ) as resolve,
        ):
            self.assertEqual(effective_server(), "http://127.0.0.1:49200")
        resolve.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
