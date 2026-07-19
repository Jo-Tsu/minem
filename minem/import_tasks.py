import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


IMPORT_TASKS_SCHEMA = """
create table if not exists import_tasks (
  id text primary key,
  status text not null default 'queued',
  progress integer not null default 0,
  message text not null default '',
  file_name text not null default '',
  file_count integer not null default 0,
  asset_count integer not null default 0,
  thumbnail_count integer not null default 0,
  upload_id text not null default '',
  asset_id text not null default '',
  asset_code text not null default '',
  asset_title text not null default '',
  asset_type text not null default '',
  preview_url text not null default '',
  error text not null default '',
  stored_path text not null default '',
  created_at integer not null,
  updated_at integer not null
);
"""


PUBLIC_KEYS = [
    "id",
    "status",
    "progress",
    "message",
    "fileName",
    "fileCount",
    "assetCount",
    "thumbnailCount",
    "uploadId",
    "assetId",
    "assetCode",
    "assetTitle",
    "assetType",
    "previewUrl",
    "error",
    "storedPath",
    "createdAt",
    "updatedAt",
]


COLUMN_BY_KEY = {
    "id": "id",
    "status": "status",
    "progress": "progress",
    "message": "message",
    "fileName": "file_name",
    "fileCount": "file_count",
    "assetCount": "asset_count",
    "thumbnailCount": "thumbnail_count",
    "uploadId": "upload_id",
    "assetId": "asset_id",
    "assetCode": "asset_code",
    "assetTitle": "asset_title",
    "assetType": "asset_type",
    "previewUrl": "preview_url",
    "error": "error",
    "storedPath": "stored_path",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
}


DEFAULT_TASK = {
    "status": "queued",
    "progress": 0,
    "message": "",
    "fileName": "",
    "fileCount": 0,
    "assetCount": 0,
    "thumbnailCount": 0,
    "uploadId": "",
    "assetId": "",
    "assetCode": "",
    "assetTitle": "",
    "assetType": "",
    "previewUrl": "",
    "error": "",
    "storedPath": "",
}


def now_ms():
    return int(time.time() * 1000)


def public_import_task(task):
    safe = {key: task.get(key, DEFAULT_TASK.get(key, "")) for key in PUBLIC_KEYS if key in task or key in DEFAULT_TASK or key == "id"}
    safe.pop("storedPath", None)
    return safe


class ImportTaskStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.lock = threading.RLock()

    @contextmanager
    def connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma busy_timeout = 30000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def ensure_schema(self, conn=None):
        if conn is not None:
            conn.executescript(IMPORT_TASKS_SCHEMA)
            return
        with self.connect() as local:
            local.executescript(IMPORT_TASKS_SCHEMA)

    def create(self, task):
        created = task.get("createdAt") or now_ms()
        payload = {**DEFAULT_TASK, **task, "createdAt": created, "updatedAt": task.get("updatedAt") or created}
        self._save(payload)
        return public_import_task(payload)

    def update(self, task_id, **updates):
        with self.lock:
            current = self.get(task_id, include_private=True)
            if not current:
                return None
            current.update(updates)
            current["updatedAt"] = now_ms()
            self._save(current)
            return public_import_task(current)

    def list(self, limit=8):
        self.ensure_schema()
        with self.connect() as conn:
            rows = conn.execute(
                "select * from import_tasks order by updated_at desc, created_at desc, id desc limit ?",
                (limit,),
            ).fetchall()
        return [public_import_task(self._row_to_task(row)) for row in rows]

    def get(self, task_id, include_private=False):
        self.ensure_schema()
        with self.connect() as conn:
            row = conn.execute("select * from import_tasks where id = ?", (task_id,)).fetchone()
        if not row:
            return None
        task = self._row_to_task(row)
        return task if include_private else public_import_task(task)

    def _save(self, task):
        if not task.get("id"):
            raise ValueError("import task id is required")
        self.ensure_schema()
        columns = [COLUMN_BY_KEY[key] for key in PUBLIC_KEYS]
        values = [task.get(key, DEFAULT_TASK.get(key, "")) for key in PUBLIC_KEYS]
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "id")
        sql = f"""
            insert into import_tasks ({", ".join(columns)})
            values ({placeholders})
            on conflict(id) do update set {updates}
        """
        with self.lock:
            with self.connect() as conn:
                conn.execute(sql, values)

    def _row_to_task(self, row):
        return {key: row[COLUMN_BY_KEY[key]] for key in PUBLIC_KEYS}
