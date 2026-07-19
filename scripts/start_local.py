#!/usr/bin/env python3
"""Prepare and start MineM locally without Docker."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
PUBLIC_INDEX = ROOT / "public" / "index.html"
FRONTEND_STAMP = ROOT / "public" / ".minem-build-sha256"
PACKAGE_STAMP = ROOT / "node_modules" / ".minem-package-lock-sha256"
REQUIREMENTS_STAMP = VENV / ".minem-requirements-sha256"


def fail(message: str) -> None:
    raise SystemExit(f"MineM startup error: {message}")


def run(command: list[str], label: str) -> None:
    print(f"[MineM] {label}")
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode:
        fail(f"{label} failed with exit code {result.returncode}")


def file_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
        elif path.is_file():
            files.append(path)
    for path in sorted(set(files)):
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def read_stamp(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_stamp(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{value}\n", encoding="utf-8")


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def prepare_python(skip_install: bool) -> Path:
    if skip_install:
        candidate = venv_python()
        return candidate if candidate.is_file() else Path(sys.executable)
    if not venv_python().is_file():
        run([sys.executable, "-m", "venv", str(VENV)], "creating Python virtual environment")
    python = venv_python()
    requirements_hash = file_digest([ROOT / "requirements.txt"])
    if read_stamp(REQUIREMENTS_STAMP) != requirements_hash:
        run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt")],
            "installing Python dependencies",
        )
        write_stamp(REQUIREMENTS_STAMP, requirements_hash)
    return python


def supported_node_version() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    result = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    try:
        major, minor, *_ = (int(value) for value in result.stdout.strip().lstrip("v").split("."))
    except ValueError:
        return False
    return (major == 20 and minor >= 19) or (major >= 22 and (major != 22 or minor >= 12))


def prepare_frontend(skip_install: bool, no_build: bool) -> None:
    if no_build:
        if not PUBLIC_INDEX.is_file():
            fail("public/index.html is missing; remove --no-build for the first start")
        return
    npm = shutil.which("npm")
    if not npm or not supported_node_version():
        fail("Node.js ^20.19.0 or >=22.12.0 and npm are required")
    package_hash = file_digest([ROOT / "package.json", ROOT / "package-lock.json"])
    if not skip_install and read_stamp(PACKAGE_STAMP) != package_hash:
        run([npm, "ci"], "installing frontend dependencies")
        write_stamp(PACKAGE_STAMP, package_hash)
    if not (ROOT / "node_modules").is_dir():
        fail("node_modules is missing; remove --skip-install")
    build_hash = file_digest(
        [
            ROOT / "frontend",
            ROOT / "package.json",
            ROOT / "package-lock.json",
            ROOT / "tsconfig.json",
            ROOT / "vite.config.ts",
        ]
    )
    if not PUBLIC_INDEX.is_file() or read_stamp(FRONTEND_STAMP) != build_hash:
        run([npm, "run", "build"], "building the frontend")
        write_stamp(FRONTEND_STAMP, build_hash)


def open_when_ready(url: str) -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{url}/api/version", timeout=1):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8790")))
    parser.add_argument("--data-dir", type=Path, help="optional runtime data directory")
    parser.add_argument("--skip-install", action="store_true", help="do not install Python or npm dependencies")
    parser.add_argument("--no-build", action="store_true", help="reuse the current frontend build")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser after startup")
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        fail("Python 3.10 or newer is required; Python 3.12 is recommended")
    python = prepare_python(args.skip_install)
    prepare_frontend(args.skip_install, args.no_build)

    environment = os.environ.copy()
    environment["HOST"] = args.host
    environment["PORT"] = str(args.port)
    environment.setdefault("AUTO_IMPORT_ON_START", "0")
    environment.setdefault("MINEM_AGENT_INTERNAL_API", "0")
    if args.data_dir:
        environment["MINEM_DATA_DIR"] = str(args.data_dir.expanduser().resolve())

    browser_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{browser_host}:{args.port}"
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    print(f"[MineM] starting {url}")
    return subprocess.call([str(python), str(ROOT / "server.py")], cwd=ROOT, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
