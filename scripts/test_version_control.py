#!/usr/bin/env python3
"""Regression checks for MineM release version transitions."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import version_control
from scripts.version_control import next_version, python_version, release_channel


def main() -> None:
    assert next_version("0.5.0-alpha.33", "beta") == "0.5.0-beta.1"
    assert next_version("0.5.0-beta.1", "prerelease") == "0.5.0-beta.2"
    assert next_version("0.5.0-beta.2", "rc") == "0.5.0-rc.1"
    assert next_version("0.5.0", "beta") == "0.5.0-beta.1"
    assert python_version("0.5.0-beta.1") == "0.5.0b1"
    assert release_channel("0.5.0-alpha.33") == "internal"
    assert release_channel("0.5.0-beta.1") == "beta"
    assert release_channel("0.5.0-rc.1") == "beta"
    assert release_channel("0.5.0") == "stable"
    try:
        next_version("0.5.0-beta.1", "alpha")
        raise AssertionError("prerelease stage regression should fail")
    except ValueError as error:
        assert "不能从 beta 回退到 alpha" in str(error)

    with tempfile.TemporaryDirectory(prefix="minem-version-test-") as temp_dir:
        root = Path(temp_dir)
        root_lock = root / "package-lock.json"
        desktop_lock = root / "desktop-package-lock.json"
        for path in (root_lock, desktop_lock):
            path.write_text(
                '{"version":"old","packages":{"":{"version":"old"}}}\n',
                encoding="utf-8",
            )
        with (
            patch.object(version_control, "JSON_TARGETS", ()),
            patch.object(version_control, "CARGO", root / "Cargo.toml"),
            patch.object(version_control, "CARGO_LOCK", root / "Cargo.lock"),
            patch.object(version_control, "PYPROJECT", root / "pyproject.toml"),
            patch.object(version_control, "PACKAGE_LOCK", root_lock),
            patch.object(version_control, "DESKTOP_PACKAGE_LOCK", desktop_lock),
            patch.object(version_control, "DOCKER_COMPOSE", root / "docker-compose.yml"),
        ):
            (root / "Cargo.toml").write_text('version = "old"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text(
                'name = "minem-desktop"\nversion = "old"\n',
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text('version = "old"\n', encoding="utf-8")
            (root / "docker-compose.yml").write_text(
                "$" + "{MINEM_VERSION:-old}\n$" + "{MINEM_VERSION:-old}\n",
                encoding="utf-8",
            )
            version_control.synchronize("0.5.0-beta.9")
        for path in (root_lock, desktop_lock):
            text = path.read_text(encoding="utf-8")
            assert text.count('"0.5.0-beta.9"') == 2
    print("version control checks passed")


if __name__ == "__main__":
    main()
