#!/bin/sh
# Use the current user's Feishu CLI session to download files for MineM.
set -eu
project=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
lark_cli=$(command -v lark-cli)
cd "$project"
python3 - "$project" "$lark_cli" <<'PY'
import fcntl
import subprocess
import sys
import time
from pathlib import Path

from minem.drive_import import drive_import_queue, drive_worker_alive

project, cli = sys.argv[1:]
runtime = Path(project) / "runtime"
root = drive_import_queue(runtime)
root.mkdir(parents=True, exist_ok=True)
worker = None
with (root / ".worker-lock").open("a") as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if drive_worker_alive(root):
            sys.exit(0)
    else:
        (root / ".worker").unlink(missing_ok=True)
        fcntl.flock(lock, fcntl.LOCK_UN)
        with (root / "worker.log").open("ab") as log:
            worker = subprocess.Popen(
                [sys.executable, "-u", project + "/scripts/drive_import_worker.py", str(runtime), cli],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
            )
for _ in range(50):
    if drive_worker_alive(root):
        print("飞书下载服务已启动")
        sys.exit(0)
    if worker and worker.poll() not in (None, 0):
        break
    time.sleep(.1)
sys.exit("飞书下载服务启动失败，请查看 runtime/drive-imports/queue/worker.log")
PY
