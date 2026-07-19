#!/usr/bin/env python3
"""Validate MineM's public source boundary before creating a release snapshot."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Iterable


REQUIRED_FILES = {
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "docs/OPEN_SOURCE_RELEASE.md",
    "public-release.json",
}

TEXT_SUFFIXES = {
    "",
    ".c",
    ".css",
    ".dockerignore",
    ".gitignore",
    ".h",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

SENSITIVE_PATTERNS = {
    "macOS absolute path": re.compile("/" + r"Users/[^/\s`\"']+/"),
    "Linux home path": re.compile("/" + r"home/[^/\s`\"']+/"),
    "Windows user path": re.compile(r"[A-Za-z]:\\\\Users\\\\[^\\\s`\"']+\\\\"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
}

MAX_SOURCE_BYTES = 20 * 1024 * 1024


def normalize(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/")


def matches_path(path: str, patterns: Iterable[str]) -> bool:
    normalized = normalize(path)
    for raw_pattern in patterns:
        pattern = normalize(raw_pattern)
        if not pattern:
            continue
        if normalized == pattern or normalized.startswith(f"{pattern}/"):
            return True
        if fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def is_included(path: str, includes: list[str], excludes: list[str]) -> bool:
    return matches_path(path, includes) and not matches_path(path, excludes)


def iter_candidate_files(root: Path, includes: list[str], excludes: list[str]) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".git/"):
            continue
        if is_included(relative, includes, excludes):
            yield path


def scan_text(path: Path) -> list[str]:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "LICENSE", "NOTICE"}:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [label for label, pattern in SENSITIVE_PATTERNS.items() if pattern.search(content)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--strict-tree",
        action="store_true",
        help="Fail when any excluded path exists; use this against the clean public snapshot.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    manifest_path = root / "public-release.json"
    errors: list[str] = []
    warnings: list[str] = []

    if not manifest_path.is_file():
        errors.append("missing public-release.json")
        manifest: dict[str, object] = {}
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid public-release.json: {exc}")
            manifest = {}

    includes = [str(value) for value in manifest.get("include", [])]
    excludes = [str(value) for value in manifest.get("exclude", [])]
    if not includes:
        errors.append("public-release.json has no include entries")
    if not excludes:
        errors.append("public-release.json has no exclude entries")

    for relative in sorted(REQUIRED_FILES):
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")

    candidate_files = list(iter_candidate_files(root, includes, excludes)) if includes else []
    for path in candidate_files:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if size > MAX_SOURCE_BYTES:
            errors.append(f"source file exceeds 20 MiB: {relative} ({size} bytes)")
        for finding in scan_text(path):
            errors.append(f"{finding} found in {relative}")

    if args.strict_tree:
        for excluded in excludes:
            path = root / excluded
            if path.exists():
                errors.append(f"excluded path exists in strict tree: {excluded}")
    else:
        present_exclusions = [value for value in excludes if (root / value).exists()]
        if present_exclusions:
            warnings.append(
                "working tree contains excluded local state; this is allowed before creating the clean snapshot"
            )

    result = {
        "ok": not errors,
        "root": str(root),
        "candidateFiles": len(candidate_files),
        "errors": errors,
        "warnings": warnings,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"[{status}] public boundary: {len(candidate_files)} candidate files")
        for warning in warnings:
            print(f"warning: {warning}")
        for error in errors:
            print(f"error: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
