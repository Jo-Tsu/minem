#!/usr/bin/env python3
"""Download requested Drive folders with the local user's official Feishu CLI."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minem.drive_import import DRIVE_DOWNLOAD_SECONDS, DRIVE_FOLDER_TOKEN, DRIVE_JOB_ID, DRIVE_STALL_SECONDS, drive_import_queue, write_json_atomically
from minem.drive_project import DriveProject


def downloaded_size(folder):
    count = size = 0
    for path in folder.rglob("*"):
        try:
            entry = path.lstat()
        except FileNotFoundError:  # A temporary download was just renamed.
            continue
        if stat.S_ISREG(entry.st_mode):
            count += 1
            size += entry.st_size
    return count, size


def pull_once(job, request, cli, deadline, attempt, started_at):
    progress = job / "progress.json"
    folder = job / "pull"
    state = {"attempt": attempt, "bytes": downloaded_size(folder)[1], "startedAt": started_at}
    write_json_atomically(progress, state)
    since = next_sample = time.monotonic()
    last_sample = None
    with TemporaryFile() as response:
        with subprocess.Popen(
            [cli, "drive", "+pull", "--as", "user", "--folder-token", request["token"],
             "--local-dir", "pull", "--if-exists", "smart"],
            cwd=job, stdin=subprocess.DEVNULL, stdout=response, stderr=subprocess.DEVNULL,
        ) as process:
            try:
                while process.poll() is None:
                    now = time.monotonic()
                    if now >= next_sample:
                        if not (job / "request.json").is_file():
                            raise ValueError("导入任务已结束")
                        sample = downloaded_size(folder)
                        if sample[0] > request["max_files"] + 1 or sample[1] > request["max_bytes"]:
                            raise ValueError("飞书文件夹超过素材包的大小或文件数量限制")
                        if sample != last_sample:
                            last_sample, since = sample, now
                            state["bytes"] = sample[1]
                            write_json_atomically(progress, state)
                        next_sample = now + 2
                    if now >= deadline:
                        raise ValueError("下载超过 30 分钟，请使用较小的汇报文件夹")
                    if now - since >= DRIVE_STALL_SECONDS:
                        raise TimeoutError("飞书下载长时间没有进展")
                    time.sleep(.5)
            finally:
                if process.poll() is None:
                    process.kill()
        response.seek(0)
        try:
            return json.load(response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("无法下载飞书文件夹，请检查链接和访问权限") from None


def download(job, request, cli):
    deadline = time.monotonic() + DRIVE_DOWNLOAD_SECONDS
    progress = job / "progress.json"
    started_at = time.time()
    write_json_atomically(progress, {"attempt": 1, "bytes": 0, "startedAt": started_at})
    project = DriveProject(cli, job, request, deadline)
    entries = project.list_folder(request["token"])
    if any(name in entries and entries[name] is None for name in ("index.html", "output")):
        raise ValueError("飞书文件夹存在同名入口，请保留一个正式汇报入口")
    index = entries.get("index.html") or {}
    output = entries.get("output") or {}
    if index.get("type") != "file":
        if output.get("type") != "folder":
            raise ValueError("飞书文件夹需要包含 index.html 或 output/index.html")

        def update_progress(received):
            write_json_atomically(progress, {"attempt": 1, "bytes": received, "startedAt": started_at})

        project.download_export(output["token"], update_progress)
        write_json_atomically(job / "result.json", {"ok": True})
        return
    folder = job / "pull"
    folder.mkdir(exist_ok=True)
    for attempt in (1, 2):
        try:
            data = pull_once(job, request, cli, deadline, attempt, started_at)
        except TimeoutError as error:
            if attempt == 1:
                continue
            raise ValueError(f"{error}，自动重试后仍未下载完成") from None
        payload = data.get("data") or {}
        summary = payload.get("summary") or {}
        items = payload.get("items") or []
        if not data.get("ok") or summary.get("failed") or summary.get("aborted"):
            error = data.get("error") or {}
            if error.get("type") in {"auth", "authorization", "authentication"}:
                raise ValueError("飞书未授权访问此文件夹，请确认本机飞书登录及文件夹权限")
            if attempt == 1 and (error.get("retryable") is True or any(item.get("retryable") is True for item in items)):
                continue
            raise ValueError("未能下载完整飞书文件夹，请检查链接、访问权限和网络后重试")
        files = [item["rel_path"] for item in items if item["action"] in {"downloaded", "skipped"}]
        if not files:
            raise ValueError("文件夹没有可导入的文件")
        if len(files) > request["max_files"] or len(set(files)) != len(files):
            raise ValueError("飞书文件夹的文件数量或路径不符合素材包要求")
        # Stage only confirmed files so an interrupted download cannot leave partial files in the report.
        source = job / "drive-source"
        source.mkdir()
        for file in files:
            rel = Path(file)
            path = folder / rel
            if rel.is_absolute() or ".." in rel.parts or path.resolve() != path or not path.is_file():
                raise ValueError("飞书返回的文件列表与下载内容不一致")
            target = source / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)
        write_json_atomically(job / "result.json", {"ok": True})
        return


def heartbeat(path, lock, stopped):
    identity = os.fstat(lock.fileno())
    try:
        while os.path.samestat(identity, (path.parent / ".worker-lock").stat()):
            path.touch()
            time.sleep(1)
    except OSError:
        pass
    finally:
        stopped.set()


def main():
    root = drive_import_queue(Path(sys.argv[1]).resolve())
    cli = sys.argv[2]
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / ".worker-lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    stopped = threading.Event()
    threading.Thread(target=heartbeat, args=(root / ".worker", lock, stopped), daemon=True).start()
    while not stopped.is_set():
        for request_file in sorted(root.glob("*/request.json")):
            if stopped.is_set():
                return
            job = request_file.parent
            if not DRIVE_JOB_ID.fullmatch(job.name) or job.is_symlink() or (job / "result.json").exists():
                continue
            try:
                request = json.loads(request_file.read_text(encoding="utf-8"))
                if time.time() >= request["expires"]:
                    write_json_atomically(job / "result.json", {"ok": False, "error": "飞书下载排队超时，请重新导入"})
                    continue
                if not DRIVE_FOLDER_TOKEN.fullmatch(request["token"]):
                    raise ValueError("飞书文件夹链接无效")
                shutil.rmtree(job / "drive-source", ignore_errors=True)
                download(job, request, cli)
            except (OSError, ValueError, KeyError, TypeError) as error:
                safe_message = str(error) if type(error) is ValueError else "飞书下载任务中断，请重新导入"
                try:
                    write_json_atomically(job / "result.json", {"ok": False, "error": safe_message})
                except FileNotFoundError:
                    pass  # MineM stopped waiting and removed the job.
        time.sleep(.5)


if __name__ == "__main__":
    main()
