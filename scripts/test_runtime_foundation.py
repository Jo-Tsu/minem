#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.start_local import running_minem_release
from minem.jobs import ChannelConfig, JobQueueFullError, JobRuntime
from minem.migrations import Migration, migration_status, run_migrations
from minem.db import (
    SCHEMA_MIGRATIONS,
    connect_database,
    create_core_schema,
    ensure_asset_schema,
    ensure_upload_schema,
    initialize_database,
)
from minem.report_exports import ReportExportTaskStore
from minem.tag_tasks import (
    create_task as create_tag_task,
    recover_interrupted as recover_interrupted_tag_tasks,
)


def migration_checks() -> None:
    assert SCHEMA_MIGRATIONS[0].checksum == SCHEMA_MIGRATIONS[0].checksum
    assert len(SCHEMA_MIGRATIONS[0].checksum) == 64
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    def create_example(local):
        local.execute("create table example(id integer primary key, value text not null)")

    migrations = (Migration(1, "create-example", create_example),)
    first = run_migrations(conn, migrations)
    assert first["currentVersion"] == 1, first
    assert first["executed"] == [{"version": 1, "name": "create-example"}], first
    second = run_migrations(conn, migrations)
    assert second["executed"] == [], second
    assert migration_status(conn, migrations)["pending"] == []

    conn.execute("insert into example(value) values ('outer-transaction')")
    nested = run_migrations(conn, migrations)
    assert nested["currentVersion"] == 1
    assert conn.in_transaction is True
    conn.rollback()
    assert conn.execute("select count(*) from example").fetchone()[0] == 0

    def changed_example(local):
        local.execute("create table should_not_run(id integer)")

    try:
        run_migrations(conn, (Migration(1, "create-example", changed_example),))
        raise AssertionError("checksum drift should be rejected")
    except RuntimeError as error:
        assert "checksum" in str(error)

    failing = sqlite3.connect(":memory:")
    failing.row_factory = sqlite3.Row

    def create_before_failure(local):
        local.execute("create table before_failure(id integer)")

    def fail_after_write(local):
        local.execute("create table rolled_back(id integer)")
        raise RuntimeError("intentional migration failure")

    try:
        run_migrations(
            failing,
            (
                Migration(1, "create-before-failure", create_before_failure),
                Migration(2, "fail-after-write", fail_after_write),
            ),
        )
        raise AssertionError("failing migration should raise")
    except RuntimeError as error:
        assert "intentional migration failure" in str(error)
    tables = {
        row[0]
        for row in failing.execute(
            "select name from sqlite_master where type = 'table'"
        ).fetchall()
    }
    assert "before_failure" not in tables
    assert "rolled_back" not in tables
    assert "schema_migrations" not in tables

    with tempfile.TemporaryDirectory(prefix="minem-migration-backup-") as temp_dir:
        source_path = Path(temp_dir) / "materials.db"
        backup_dir = Path(temp_dir) / "backups"
        source = sqlite3.connect(source_path)
        source.row_factory = sqlite3.Row

        def baseline(local):
            local.execute("create table baseline(id integer primary key, value text)")

        run_migrations(source, (Migration(1, "baseline", baseline),))
        source.execute("insert into baseline(value) values ('protected')")
        source.commit()

        def version_two(local):
            local.execute("alter table baseline add column note text not null default ''")

        upgraded = run_migrations(
            source,
            (
                Migration(1, "baseline", baseline),
                Migration(2, "version-two", version_two),
            ),
            backup_dir=backup_dir,
            backup_from_version=2,
            backup_retain=2,
        )
        backup_path = Path(upgraded["backupPath"])
        assert backup_path.is_file(), upgraded
        backup = sqlite3.connect(backup_path)
        try:
            backup.row_factory = sqlite3.Row
            backup_columns = {
                row["name"] for row in backup.execute("pragma table_info(baseline)")
            }
            assert "note" not in backup_columns
            assert backup.execute("select value from baseline").fetchone()["value"] == "protected"
        finally:
            backup.close()
        upgraded_columns = {
            row["name"] for row in source.execute("pragma table_info(baseline)")
        }
        assert "note" in upgraded_columns
        source.close()

    with tempfile.TemporaryDirectory(prefix="minem-legacy-v2-") as temp_dir:
        root = Path(temp_dir)
        data_dir = root / "data"
        uploads_dir = root / "uploads"
        extracted_dir = root / "extracted"
        history_dir = extracted_dir / "_history"
        thumbnails_dir = root / "thumbnails"
        backup_dir = root / "state" / "backups"
        data_dir.mkdir(parents=True)
        db_path = data_dir / "materials.db"
        legacy = sqlite3.connect(db_path)
        legacy.row_factory = sqlite3.Row
        create_core_schema(legacy)
        ensure_upload_schema(legacy)
        ensure_asset_schema(legacy)
        legacy.execute(
            """
            insert into assets
            (id,title,category,asset_type,asset_code,media_kind,source_type,
             source_path,preview_url,source_hash,version_group,created_at,updated_at)
            values
            ('legacy-page','Legacy','page','control','CTRL-LEGACY','html','test',
             'index.html','/extracted/legacy/index.html','legacy-hash','legacy-page',1,1)
            """
        )
        legacy.commit()
        legacy.close()

        state = initialize_database(
            data_dir=data_dir,
            uploads_dir=uploads_dir,
            extracted_dir=extracted_dir,
            history_dir=history_dir,
            thumbnails_dir=thumbnails_dir,
            connect=lambda: connect_database(db_path, timeout=30),
            migration_backup_dir=backup_dir,
            migration_backup_retain=3,
        )
        assert state["currentVersion"] == 2, state
        backup_path = Path(state["backupPath"])
        assert backup_path.is_file(), state
        backup = sqlite3.connect(backup_path)
        try:
            backup_columns = {
                row[1] for row in backup.execute("pragma table_info(assets)")
            }
            assert "semantic_fingerprint" not in backup_columns
            assert backup.execute(
                "select count(*) from assets where id='legacy-page'"
            ).fetchone()[0] == 1
        finally:
            backup.close()

    conn.close()
    failing.close()


def job_runtime_checks() -> None:
    runtime = JobRuntime({
        "serial": ChannelConfig(workers=1, max_pending=1),
        "parallel": ChannelConfig(workers=1, max_pending=2),
    })
    serial_started = threading.Event()
    release_serial = threading.Event()
    parallel_finished = threading.Event()
    executions = []

    def blocking_job(label):
        executions.append(label)
        serial_started.set()
        release_serial.wait(timeout=2)
        return label

    first = runtime.submit("serial", "same-key", blocking_job, "first")
    assert serial_started.wait(timeout=1)
    duplicate = runtime.submit("serial", "same-key", blocking_job, "duplicate")
    assert duplicate.duplicate is True
    assert duplicate.future is first.future

    queued = runtime.submit("serial", "queued", lambda: "queued")
    try:
        runtime.submit("serial", "overflow", lambda: "overflow")
        raise AssertionError("full channel should reject work")
    except JobQueueFullError as error:
        assert error.channel == "serial"

    def parallel_job():
        parallel_finished.set()
        return "parallel"

    parallel = runtime.submit("parallel", "parallel", parallel_job)
    assert parallel_finished.wait(timeout=1)
    assert parallel.future.result(timeout=1) == "parallel"
    assert executions == ["first"]

    release_serial.set()
    assert first.future.result(timeout=1) == "first"
    assert queued.future.result(timeout=1) == "queued"
    assert runtime.wait_for_idle(timeout=1)

    snapshot = runtime.snapshot()
    assert snapshot["serial"]["pending"] == 0, snapshot
    assert snapshot["serial"]["queued"] == 0, snapshot
    assert snapshot["serial"]["completed"] == 2, snapshot
    assert snapshot["parallel"]["completed"] == 1, snapshot
    runtime.shutdown(wait=True)


def interrupted_task_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="minem-interrupted-jobs-") as temp_dir:
        db_path = Path(temp_dir) / "materials.db"
        export_store = ReportExportTaskStore(db_path)
        export_store.create({
            "id": "interrupted-export",
            "reportId": "report-1",
            "format": "html",
            "status": "running",
            "progress": 42,
        })
        assert export_store.recover_interrupted() == 1
        recovered_export = export_store.get("interrupted-export")
        assert recovered_export["status"] == "failed", recovered_export
        assert recovered_export["progress"] == 100, recovered_export
        assert "重新导出" in recovered_export["error"], recovered_export

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("create table assets(id text primary key)")
        conn.execute("insert into assets(id) values ('asset-1')")
        tag_task = create_tag_task(conn, ["asset-1"])
        assert tag_task["ok"] is True, tag_task
        conn.commit()
        assert recover_interrupted_tag_tasks(conn) == 1
        row = conn.execute(
            "select status, error from tag_analysis_tasks where id = ?",
            (tag_task["taskId"],),
        ).fetchone()
        assert row["status"] == "failed", dict(row)
        assert "重新创建任务" in row["error"], dict(row)
        conn.close()


def startup_reuse_checks() -> None:
    class VersionHandler(BaseHTTPRequestHandler):
        payload = b'{"ok":true,"release":{"product":"MineM","version":"test"}}'

        def do_GET(self):
            if self.path != "/api/version":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), VersionHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        release = running_minem_release(f"http://127.0.0.1:{server.server_port}")
        assert release and release["version"] == "test", release
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def main() -> None:
    migration_checks()
    job_runtime_checks()
    interrupted_task_checks()
    startup_reuse_checks()
    print("runtime foundation checks passed")


if __name__ == "__main__":
    main()
