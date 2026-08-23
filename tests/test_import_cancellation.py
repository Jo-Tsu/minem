from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile

from minem.db import connect_database, create_core_schema, ensure_asset_schema, ensure_upload_schema
from minem.imports import run_import_task
from minem.jobs import ChannelConfig, JobRuntime


class ImportCancellationTest(unittest.TestCase):
    def test_queued_job_can_be_cancelled_before_execution(self) -> None:
        runtime = JobRuntime({"imports": ChannelConfig(workers=1, max_pending=4)})
        blocker = threading.Event()
        started = threading.Event()

        def hold_worker():
            started.set()
            blocker.wait(timeout=5)

        first = runtime.submit("imports", "first", hold_worker)
        self.assertTrue(started.wait(timeout=2))
        second = runtime.submit("imports", "second", lambda: "should-not-run")

        self.assertTrue(runtime.cancel("imports", "second"))
        replacement = runtime.submit("imports", "second", lambda: "replacement-ran")
        blocker.set()
        self.assertTrue(runtime.wait_for_idle(timeout=3))
        self.assertTrue(first.future.done())
        self.assertTrue(second.future.cancelled())
        self.assertEqual(replacement.future.result(), "replacement-ran")

    def test_running_import_cancelled_before_commit_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "materials.db"
            extracted = root / "extracted"
            uploads = root / "uploads"
            extracted.mkdir()
            uploads.mkdir()

            conn = connect_database(database)
            try:
                create_core_schema(conn)
                ensure_asset_schema(conn)
                ensure_upload_schema(conn)
                conn.commit()
            finally:
                conn.close()

            archive = uploads / "cancel.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("index.html", "<!doctype html><title>Cancel me</title>")

            @contextmanager
            def connect():
                active = connect_database(database, timeout=30)
                try:
                    with active:
                        yield active
                finally:
                    active.close()

            task = {}

            def update_task(_task_id, **updates):
                task.update(updates)

            def safe_extract(source, target):
                with zipfile.ZipFile(source) as package:
                    package.extractall(target)

            def scan_upload(upload_id, _extract_root, _description, *, conn):
                conn.execute(
                    """
                    insert into assets
                    (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                     preview_url,upload_id,source_hash,version_group,created_at,updated_at)
                    values ('cancelled-asset','Cancelled','page','control','CTRL-CANCEL','html',
                            'test','index.html',? ,?,'cancelled-source','cancelled-asset',1,1)
                    """,
                    (f"/extracted/{upload_id}/index.html", upload_id),
                )
                return 1, 1, []

            run_import_task(
                "cancel-task",
                archive,
                archive.name,
                "cancel-upload",
                "",
                extracted_dir=extracted,
                zip_suffixes={".zip"},
                update_task=update_task,
                connect=connect,
                safe_extract=safe_extract,
                scan_upload=scan_upload,
                generate_upload_thumbnails=lambda _upload_id: 0,
                import_result_for_upload=lambda _upload_id: {},
                existing_result_for_extract_root=None,
                now_ms=lambda: 1,
                is_cancelled=lambda: False,
                begin_commit=lambda: False,
            )

            with connect() as active:
                self.assertEqual(active.execute("select count(*) from uploads").fetchone()[0], 0)
                self.assertEqual(active.execute("select count(*) from assets").fetchone()[0], 0)
            self.assertEqual(task["status"], "cancelled")
            self.assertFalse(archive.exists())
            self.assertFalse((extracted / "cancel-upload").exists())


if __name__ == "__main__":
    unittest.main()
