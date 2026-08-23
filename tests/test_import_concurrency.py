from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile

from minem.db import connect_database, create_core_schema, ensure_asset_schema, ensure_upload_schema
from minem.imports import run_import_task


class ImportConcurrencyTest(unittest.TestCase):
    def test_fully_deduplicated_scan_removes_empty_upload_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "materials.db"
            extracted = root / "extracted"
            uploads = root / "uploads"
            extracted.mkdir()
            uploads.mkdir()
            archive = uploads / "duplicate.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("index.html", "<!doctype html><title>Existing page</title>")

            conn = connect_database(database)
            try:
                create_core_schema(conn)
                ensure_asset_schema(conn)
                ensure_upload_schema(conn)
                conn.execute(
                    """
                    insert into uploads
                    (id,filename,stored_path,extract_path,file_count,asset_count,created_at)
                    values ('existing-upload','existing.zip','','',1,1,1)
                    """
                )
                conn.execute(
                    """
                    insert into assets
                    (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                     preview_url,upload_id,source_hash,version_group,created_at,updated_at)
                    values ('existing-asset','Existing page','page','control','CTRL-EXISTING',
                            'html','test','index.html','/extracted/existing-upload/index.html',
                            'existing-upload','existing-source','existing-asset',1,1)
                    """
                )
                conn.commit()
            finally:
                conn.close()

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
                    "update uploads set file_count = 1, asset_count = 0 where id = ?",
                    (upload_id,),
                )
                return 1, 0, []

            run_import_task(
                "duplicate-task",
                archive,
                archive.name,
                "duplicate-upload",
                "",
                extracted_dir=extracted,
                zip_suffixes={".zip"},
                update_task=update_task,
                connect=connect,
                safe_extract=safe_extract,
                scan_upload=scan_upload,
                generate_upload_thumbnails=lambda _upload_id: 0,
                import_result_for_upload=lambda _upload_id: {},
                existing_result_for_extract_root=lambda _root: {
                    "assetId": "existing-asset",
                    "assetCode": "CTRL-EXISTING",
                    "previewUrl": "/extracted/existing-upload/index.html",
                    "assetTitle": "Existing page",
                    "assetType": "control",
                    "sourceUploadId": "existing-upload",
                },
                now_ms=lambda: 1,
            )

            with connect() as active:
                upload_ids = [
                    row["id"]
                    for row in active.execute("select id from uploads order by id").fetchall()
                ]
            self.assertEqual(upload_ids, ["existing-upload"])
            self.assertEqual(task["status"], "success")
            self.assertEqual(task["uploadId"], "existing-upload")
            self.assertFalse(archive.exists())
            self.assertFalse((extracted / "duplicate-upload").exists())

    def test_identical_concurrent_packages_reuse_one_upload(self) -> None:
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

            archives = []
            for index in range(2):
                archive = uploads / f"package-{index}.zip"
                with zipfile.ZipFile(archive, "w") as package:
                    package.writestr("index.html", "<!doctype html><title>Same package</title>")
                archives.append(archive)

            @contextmanager
            def connect():
                active = connect_database(database, timeout=30)
                try:
                    with active:
                        yield active
                finally:
                    active.close()

            tasks = {}
            task_lock = threading.Lock()

            def update_task(task_id, **updates):
                with task_lock:
                    tasks.setdefault(task_id, {}).update(updates)

            def safe_extract(archive, target):
                with zipfile.ZipFile(archive) as package:
                    package.extractall(target)

            def scan_upload(upload_id, _extract_root, _description, *, conn):
                conn.execute(
                    """
                    insert into assets
                    (id,title,category,asset_type,asset_code,media_kind,source_type,source_path,
                     preview_url,upload_id,source_hash,version_group,created_at,updated_at)
                    values (?,?,'page','control',?,'html','test','index.html',?,?,?, ?,1,1)
                    """,
                    (
                        f"asset-{upload_id}",
                        "Same package",
                        f"CTRL-{upload_id}",
                        f"/extracted/{upload_id}/index.html",
                        upload_id,
                        f"source-{upload_id}",
                        f"asset-{upload_id}",
                    ),
                )
                conn.execute(
                    "update uploads set file_count = 1, asset_count = 1 where id = ?",
                    (upload_id,),
                )
                return 1, 1, []

            def import_result(upload_id):
                with connect() as active:
                    row = active.execute(
                        "select * from assets where upload_id = ? limit 1",
                        (upload_id,),
                    ).fetchone()
                return {
                    "assetId": row["id"] if row else "",
                    "assetCode": row["asset_code"] if row else "",
                    "previewUrl": row["preview_url"] if row else "",
                    "assetTitle": row["title"] if row else "",
                    "assetType": row["asset_type"] if row else "",
                }

            barrier = threading.Barrier(2)

            def execute(index):
                barrier.wait()
                run_import_task(
                    f"task-{index}",
                    archives[index],
                    archives[index].name,
                    f"upload-{index}",
                    "",
                    extracted_dir=extracted,
                    zip_suffixes={".zip"},
                    update_task=update_task,
                    connect=connect,
                    safe_extract=safe_extract,
                    scan_upload=scan_upload,
                    generate_upload_thumbnails=lambda _upload_id: 1,
                    import_result_for_upload=import_result,
                    existing_result_for_extract_root=None,
                    now_ms=lambda: 1,
                )

            threads = [threading.Thread(target=execute, args=(index,)) for index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            with connect() as active:
                self.assertEqual(active.execute("select count(*) from uploads").fetchone()[0], 1)
                self.assertEqual(active.execute("select count(*) from assets").fetchone()[0], 1)
            self.assertEqual({task["status"] for task in tasks.values()}, {"success"})
            self.assertIn(
                "相同内容已存在，已复用历史批次",
                {task["message"] for task in tasks.values()},
            )


if __name__ == "__main__":
    unittest.main()
