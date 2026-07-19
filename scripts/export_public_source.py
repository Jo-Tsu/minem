#!/usr/bin/env python3
"""Export the approved MineM source boundary into a new clean directory."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from check_public_boundary import is_included


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("output must be outside the internal source tree")
    if output.exists():
        raise SystemExit(f"output already exists: {output}")

    manifest = json.loads((ROOT / "public-release.json").read_text(encoding="utf-8"))
    includes = [str(value) for value in manifest.get("include", [])]
    excludes = [str(value) for value in manifest.get("exclude", [])]
    candidates: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(".git/") or not is_included(relative, includes, excludes):
            continue
        if path.is_symlink():
            raise SystemExit(f"symbolic links are not allowed in the public snapshot: {relative}")
        candidates.append(path)

    output.mkdir(parents=True)
    for source in sorted(candidates):
        relative = source.relative_to(ROOT)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    checks = [
        [sys.executable, str(output / "scripts/check_public_boundary.py"), "--root", str(output), "--strict-tree"],
        [sys.executable, str(output / "scripts/check_repository_docs.py"), "--root", str(output)],
    ]
    for command in checks:
        result = subprocess.run(command, cwd=output, check=False)
        if result.returncode:
            raise SystemExit(f"public snapshot validation failed: {' '.join(command)}")

    print(json.dumps({"ok": True, "output": str(output), "files": len(candidates)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
