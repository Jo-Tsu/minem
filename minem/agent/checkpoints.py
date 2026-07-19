import json
import subprocess
import time
from pathlib import Path


def _git(root, args, *, timeout=10):
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return proc.returncode == 0, proc.stdout.strip()
    except Exception as error:
        return False, str(error)


def repo_state(root):
    root = Path(root)
    head_ok, head = _git(root, ["rev-parse", "--short", "HEAD"])
    status_ok, status = _git(root, ["status", "--short"])
    return {
        "gitAvailable": head_ok or status_ok,
        "head": head if head_ok else "",
        "status": status.splitlines() if status_ok and status else [],
    }


def create_checkpoint(root, data_dir, *, label="", task=""):
    data_dir = Path(data_dir)
    checkpoint_dir = data_dir / "agent" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    created_at = int(time.time() * 1000)
    checkpoint_id = time.strftime("agent-%Y%m%d-%H%M%S", time.localtime(created_at / 1000))
    checkpoint_id = f"{checkpoint_id}-{created_at % 1000:03d}"
    state = repo_state(root)
    payload = {
        "ok": True,
        "id": checkpoint_id,
        "label": label,
        "task": task,
        "createdAt": created_at,
        "repo": state,
        "note": "Checkpoint records git state only; it does not create a commit.",
    }
    path = checkpoint_dir / f"{checkpoint_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["path"] = str(path)
    return payload
