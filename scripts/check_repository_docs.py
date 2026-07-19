#!/usr/bin/env python3
"""Check GitHub community files and local Markdown links for MineM."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


REQUIRED_FILES = {
    "README.md",
    "LICENSE",
    "NOTICE",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/data_preview_issue.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
}

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FORM_KEYS = ("name:", "description:", "body:")
FORBIDDEN_DOC_PATTERNS = {
    "private macOS home path": re.compile("/" + r"Users/"),
    "internal workspace name": re.compile(r"\bpitch_html/"),
    "retired private source name": re.compile(r"\bsuperclub\b", re.IGNORECASE),
}


def load_boundary(root: Path) -> tuple[list[str], list[str]]:
    manifest = json.loads((root / "public-release.json").read_text(encoding="utf-8"))
    return list(manifest.get("include", [])), list(manifest.get("exclude", []))


def path_matches(relative: str, patterns: list[str]) -> bool:
    parts = Path(relative).parts
    for pattern in patterns:
        normalized = pattern.strip("/")
        if not normalized:
            continue
        if relative == normalized or relative.startswith(f"{normalized}/"):
            return True
        if normalized.startswith("**/"):
            tail = normalized[3:].replace("/**", "")
            if tail in parts:
                return True
        if normalized.startswith("**/*.") and relative.endswith(normalized[4:]):
            return True
    return False


def public_markdown_files(root: Path, includes: list[str], excludes: list[str]) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".git/") or path_matches(relative, excludes):
            continue
        if path_matches(relative, includes):
            files.append(path)
    return sorted(files)


def link_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")]
    return raw.split(maxsplit=1)[0]


def check_links(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in files:
        content = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_DOC_PATTERNS.items():
            if pattern.search(content):
                errors.append(f"{label} found in {path.relative_to(root)}")
        for raw in MARKDOWN_LINK.findall(content):
            target = unquote(link_target(raw))
            parsed = urlparse(target)
            if not target or parsed.scheme or target.startswith(("#", "mailto:")):
                continue
            clean_target = target.split("#", 1)[0].split("?", 1)[0]
            if not clean_target:
                continue
            if clean_target.startswith("/"):
                errors.append(
                    f"repository link must be relative: {path.relative_to(root)} -> {target}"
                )
                continue
            resolved = (path.parent / clean_target).resolve()
            if not resolved.exists():
                errors.append(f"broken link: {path.relative_to(root)} -> {target}")
    return errors


def check_issue_forms(root: Path) -> list[str]:
    errors: list[str] = []
    forms = sorted((root / ".github/ISSUE_TEMPLATE").glob("*.yml"))
    forms = [path for path in forms if path.name != "config.yml"]
    for form in forms:
        content = form.read_text(encoding="utf-8")
        for key in FORM_KEYS:
            if not re.search(rf"^{re.escape(key)}", content, flags=re.MULTILINE):
                errors.append(f"issue form missing {key} {form.relative_to(root)}")
        ids = re.findall(r"^\s+id:\s*([A-Za-z0-9_-]+)\s*$", content, flags=re.MULTILINE)
        if len(ids) != len(set(ids)):
            errors.append(f"issue form has duplicate ids: {form.relative_to(root)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    errors: list[str] = []

    for relative in sorted(REQUIRED_FILES):
        if not (root / relative).is_file():
            errors.append(f"missing GitHub community file: {relative}")

    try:
        includes, excludes = load_boundary(root)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read public-release.json: {exc}")
        includes, excludes = [], []

    markdown_files = public_markdown_files(root, includes, excludes)
    errors.extend(check_links(root, markdown_files))
    errors.extend(check_issue_forms(root))

    result = {
        "ok": not errors,
        "root": str(root),
        "markdownFiles": len(markdown_files),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[{'PASS' if result['ok'] else 'FAIL'}] repository docs: {len(markdown_files)} files")
        for error in errors:
            print(f"error: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
