"""The local Drive import worker and MineM exchange bounded jobs via runtime files."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_DRIVE_LINKS = 8
DRIVE_QUEUE_SECONDS = 1800
DRIVE_DOWNLOAD_SECONDS = 1800
DRIVE_STALL_SECONDS = 120
DRIVE_FOLDER_TOKEN = re.compile(r"[a-zA-Z0-9]{10,100}")
DRIVE_JOB_ID = re.compile(r"task-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}")


def drive_import_queue(runtime):
    return Path(runtime) / "drive-imports" / "queue"


def parse_drive_folder_link(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("请提供飞书云空间文件夹链接")
    url = urlsplit(value.strip())
    host = url.hostname or ""
    if (url.scheme != "https" or url.netloc != host or not re.fullmatch(
        r"(?:[a-z0-9-]+\.)*(?:feishu\.cn|larkoffice\.com|larksuite\.com)", host
    )):
        raise ValueError("请提供飞书云空间文件夹的 HTTPS 链接")
    match = re.fullmatch(r"/drive/folder/([a-zA-Z0-9]{10,100})/?", url.path)
    if not match:
        raise ValueError("请提供飞书云空间文件夹链接")
    return match[1]


def drive_worker_alive(root):
    try:
        return abs(time.time() - (root / ".worker").stat().st_mtime) < 12
    except OSError:
        return False


def write_json_atomically(path, payload):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
