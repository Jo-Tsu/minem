#!/usr/bin/env python3
"""Isolated task persistence, concurrent updates and SQLite timeout checks."""

import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minem.db import connect_database
from minem.import_tasks import ImportTaskStore
from minem.report_exports import ReportExportTaskStore


class TaskStoreChecks:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="minem-task-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.db"
        self.store = self.store_type(self.path)
        self.store.create({"id": "task", "reportId": "report"})

    def test_task_survives_restart_without_exposing_private_paths(self):
        self.store.update("task", status="completed", progress=100, **{self.private_key: "/private/material.html"})
        restarted = self.store_type(self.path)
        task = restarted.get("task")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress"], 100)
        self.assertNotIn(self.private_key, task)
        self.assertEqual(restarted.get("task", include_private=True)[self.private_key], "/private/material.html")

    def test_missing_update_does_not_create_a_task(self):
        self.assertIsNone(self.store.update("missing", status="completed"))
        self.assertIsNone(self.store.get("missing"))

    def test_independent_writers_preserve_each_others_fields(self):
        peer = self.store_type(self.path)
        peer.get("task")
        with ThreadPoolExecutor(max_workers=2) as workers:
            for value in range(1, 41):
                start = threading.Barrier(2)

                def update(store, **fields):
                    start.wait(timeout=5)
                    return store.update("task", **fields)

                first = workers.submit(update, self.store, progress=value)
                second = workers.submit(update, peer, message=str(value))
                first.result(timeout=10)
                second.result(timeout=10)
                task = self.store.get("task")
                self.assertEqual(task["progress"], value)
                self.assertEqual(task["message"], str(value))


class ImportTaskChecks(TaskStoreChecks, unittest.TestCase):
    store_type = ImportTaskStore
    private_key = "storedPath"

    def test_legacy_task_schema_is_upgraded_on_first_access(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("alter table import_tasks drop column source_url")
        restarted = ImportTaskStore(self.path)
        self.assertEqual(restarted.get("task")["sourceUrl"], "")
        self.assertEqual(restarted.update("task", sourceUrl="https://example.com")["sourceUrl"], "https://example.com")


class ReportExportChecks(TaskStoreChecks, unittest.TestCase):
    store_type = ReportExportTaskStore
    private_key = "outputPath"


class DatabaseTimeoutChecks(unittest.TestCase):
    def test_configured_timeout_bounds_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory(prefix="minem-db-test-") as runtime:
            path = Path(runtime) / "test.db"
            writer = sqlite3.connect(path)
            self.addCleanup(writer.close)
            writer.execute("create table example (id integer)")
            writer.execute("begin immediate")
            contender = connect_database(path, timeout=0.05)
            self.addCleanup(contender.close)
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                contender.execute("insert into example values (1)")
            self.assertLess(time.monotonic() - started, 1.0)
            writer.rollback()


if __name__ == "__main__":
    unittest.main()
