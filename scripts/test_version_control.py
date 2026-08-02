#!/usr/bin/env python3
"""Regression checks for MineM release version transitions."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
    print("version control checks passed")


if __name__ == "__main__":
    main()
