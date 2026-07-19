#!/usr/bin/env python3
"""MineM product version source, synchronization, and release checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "product-version.json"
CHANGELOG = ROOT / "CHANGELOG.md"
JSON_TARGETS = (ROOT / "package.json", ROOT / "desktop/package.json", ROOT / "desktop/src-tauri/tauri.conf.json")
CARGO = ROOT / "desktop/src-tauri/Cargo.toml"
CARGO_LOCK = ROOT / "desktop/src-tauri/Cargo.lock"
PACKAGE_LOCK = ROOT / "package-lock.json"
DOCKER_COMPOSE = ROOT / "docker-compose.yml"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


def load_manifest() -> dict:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not SEMVER.match(str(payload.get("version") or "")):
        raise ValueError("product-version.json 的 version 必须为 SemVer 版本号")
    return payload


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cargo_version() -> str:
    content = CARGO.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', content)
    return match.group(1) if match else ""


def check(manifest: dict) -> list[str]:
    version = manifest["version"]
    issues = []
    for path in JSON_TARGETS:
        value = json.loads(path.read_text(encoding="utf-8")).get("version")
        if value != version:
            issues.append(f"{path.relative_to(ROOT)}: {value!r} != {version!r}")
    if cargo_version() != version:
        issues.append(f"desktop/src-tauri/Cargo.toml: {cargo_version()!r} != {version!r}")
    cargo_lock = CARGO_LOCK.read_text(encoding="utf-8")
    desktop_lock = re.search(r'(?ms)^name = "minem-desktop"\nversion = "([^"]+)"', cargo_lock)
    if not desktop_lock or desktop_lock.group(1) != version:
        value = desktop_lock.group(1) if desktop_lock else ""
        issues.append(f"desktop/src-tauri/Cargo.lock: {value!r} != {version!r}")
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    if lock.get("version") != version or (lock.get("packages", {}).get("", {}) or {}).get("version") != version:
        issues.append(f"package-lock.json: version entries != {version!r}")
    compose_versions = re.findall(r"MINEM_VERSION:-([^}]+)", DOCKER_COMPOSE.read_text(encoding="utf-8"))
    if not compose_versions or any(item != version for item in compose_versions):
        issues.append(f"docker-compose.yml: {compose_versions!r} != {version!r}")
    if f"## [{version}]" not in CHANGELOG.read_text(encoding="utf-8"):
        issues.append(f"CHANGELOG.md: 缺少 {version} 的发布段落")
    return issues


def next_version(version: str, level: str) -> str:
    major, minor, patch = (int(value) for value in version.split("-", 1)[0].split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def synchronize(version: str) -> None:
    for path in JSON_TARGETS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["version"] = version
        write_json(path, payload)
    content = CARGO.read_text(encoding="utf-8")
    updated, count = re.subn(r'(?m)^version\s*=\s*"[^"]+"', f'version = "{version}"', content, count=1)
    if count != 1:
        raise ValueError("无法同步 desktop/src-tauri/Cargo.toml 版本")
    CARGO.write_text(updated, encoding="utf-8")
    cargo_lock = CARGO_LOCK.read_text(encoding="utf-8")
    cargo_lock, count = re.subn(
        r'(?ms)(^name = "minem-desktop"\nversion = ")[^"]+("$)',
        rf'\g<1>{version}\2',
        cargo_lock,
        count=1,
    )
    if count != 1:
        raise ValueError("无法同步 desktop/src-tauri/Cargo.lock 版本")
    CARGO_LOCK.write_text(cargo_lock, encoding="utf-8")
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    lock["version"] = version
    lock.setdefault("packages", {}).setdefault("", {})["version"] = version
    write_json(PACKAGE_LOCK, lock)
    compose = DOCKER_COMPOSE.read_text(encoding="utf-8")
    compose, count = re.subn(r"MINEM_VERSION:-[^}]+", f"MINEM_VERSION:-{version}", compose)
    if count < 2:
        raise ValueError("无法同步 docker-compose.yml 版本")
    DOCKER_COMPOSE.write_text(compose, encoding="utf-8")


def prepend_changelog(version: str, headline: str) -> None:
    content = CHANGELOG.read_text(encoding="utf-8")
    entry = f"## [{version}] - {date.today().isoformat()}\n\n### 变更\n\n- {headline}\n\n"
    marker = "## ["
    index = content.find(marker)
    if index < 0:
        raise ValueError("CHANGELOG.md 缺少版本段落")
    CHANGELOG.write_text(content[:index] + entry + content[index:], encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="MineM product version control")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="show current product version")
    commands.add_parser("check", help="verify all version entry points")
    bump = commands.add_parser("bump", help="bump and synchronize version metadata")
    bump.add_argument("level", choices=("major", "minor", "patch"))
    bump.add_argument("--headline", required=True, help="release headline for CHANGELOG draft")
    args = parser.parse_args()

    manifest = load_manifest()
    if args.command == "show":
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "check":
        issues = check(manifest)
        if issues:
            print("版本检查失败：", file=sys.stderr)
            print("\n".join(f"- {item}" for item in issues), file=sys.stderr)
            return 1
        print(f"MineM v{manifest['version']} 版本入口一致")
        return 0

    version = next_version(manifest["version"], args.level)
    manifest["version"] = version
    manifest["releasedAt"] = date.today().isoformat()
    manifest["headline"] = args.headline.strip()
    write_json(MANIFEST, manifest)
    synchronize(version)
    prepend_changelog(version, args.headline.strip())
    print(f"已升级至 MineM v{version}；请完善 CHANGELOG 并运行版本检查。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
