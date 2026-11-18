import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


REPORT_EXPORT_TASKS_SCHEMA = """
create table if not exists report_export_tasks (
  id text primary key,
  report_id text not null,
  format text not null,
  status text not null default 'queued',
  progress integer not null default 0,
  message text not null default '',
  page_count integer not null default 0,
  filename text not null default '',
  output_path text not null default '',
  error text not null default '',
  created_at integer not null,
  updated_at integer not null
);
create index if not exists idx_report_export_tasks_report on report_export_tasks(report_id, updated_at desc);
"""


PUBLIC_KEYS = [
    "id", "reportId", "format", "status", "progress", "message", "pageCount",
    "filename", "downloadUrl", "error", "createdAt", "updatedAt",
]

COLUMN_BY_KEY = {
    "id": "id",
    "reportId": "report_id",
    "format": "format",
    "status": "status",
    "progress": "progress",
    "message": "message",
    "pageCount": "page_count",
    "filename": "filename",
    "outputPath": "output_path",
    "error": "error",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
}

DEFAULT_TASK = {
    "format": "html",
    "status": "queued",
    "progress": 0,
    "message": "等待导出",
    "pageCount": 0,
    "filename": "",
    "outputPath": "",
    "error": "",
}


def now_ms():
    return int(time.time() * 1000)


def public_report_export_task(task):
    payload = {key: task.get(key, DEFAULT_TASK.get(key, "")) for key in PUBLIC_KEYS if key != "downloadUrl"}
    task_id = str(task.get("id") or "")
    payload["downloadUrl"] = f"/api/report-exports/{task_id}/download" if task.get("status") == "completed" and task_id else ""
    return payload


class ReportExportTaskStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.lock = threading.RLock()
        self._schema_ready = False

    @contextmanager
    def connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def ensure_schema(self, conn=None):
        if conn is not None:
            conn.executescript(REPORT_EXPORT_TASKS_SCHEMA)
            return
        with self.lock:
            if self._schema_ready:
                return
            with self.connect() as local:
                self.ensure_schema(local)
            self._schema_ready = True

    def create(self, task):
        created = task.get("createdAt") or now_ms()
        payload = {**DEFAULT_TASK, **task, "createdAt": created, "updatedAt": task.get("updatedAt") or created}
        self._save(payload)
        return public_report_export_task(payload)

    def update(self, task_id, **updates):
        self.ensure_schema()
        fields = {key: value for key, value in updates.items() if key in COLUMN_BY_KEY and key != "id"}
        fields["updatedAt"] = now_ms()
        assignments = ", ".join(f"{COLUMN_BY_KEY[key]} = ?" for key in fields)
        with self.lock, self.connect() as conn:
            changed = conn.execute(
                f"update report_export_tasks set {assignments} where id = ?",
                [*fields.values(), task_id],
            )
            if not changed.rowcount:
                return None
            row = conn.execute("select * from report_export_tasks where id = ?", (task_id,)).fetchone()
            return public_report_export_task(self._row_to_task(row))

    def get(self, task_id, include_private=False):
        self.ensure_schema()
        with self.connect() as conn:
            row = conn.execute("select * from report_export_tasks where id = ?", (task_id,)).fetchone()
        if not row:
            return None
        task = self._row_to_task(row)
        return task if include_private else public_report_export_task(task)

    def list(self, report_id, limit=12):
        self.ensure_schema()
        with self.connect() as conn:
            rows = conn.execute(
                "select * from report_export_tasks where report_id=? order by created_at desc, id desc limit ?",
                (report_id, limit),
            ).fetchall()
        return [public_report_export_task(self._row_to_task(row)) for row in rows]

    def _save(self, task):
        if not task.get("id"):
            raise ValueError("report export task id is required")
        self.ensure_schema()
        keys = [key for key in COLUMN_BY_KEY if key != "downloadUrl"]
        columns = [COLUMN_BY_KEY[key] for key in keys]
        values = [task.get(key, DEFAULT_TASK.get(key, "")) for key in keys]
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "id")
        sql = f"""
          insert into report_export_tasks ({", ".join(columns)}) values ({placeholders})
          on conflict(id) do update set {updates}
        """
        with self.lock:
            with self.connect() as conn:
                conn.execute(sql, values)

    def _row_to_task(self, row):
        return {key: row[COLUMN_BY_KEY[key]] for key in COLUMN_BY_KEY if key != "downloadUrl"}
