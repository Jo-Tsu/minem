"""Pytest configuration and shared fixtures for MineM integration tests."""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def tmp_runtime(tmp_path):
    """Create a temporary MineM runtime directory structure."""
    data = tmp_path / "data"
    data.mkdir()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    thumbnails = tmp_path / "thumbnails"
    thumbnails.mkdir()
    report_exports = tmp_path / "report-exports"
    report_exports.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    return tmp_path


@pytest.fixture
def db_path(tmp_runtime):
    """Return path to a fresh SQLite database with MineM schema."""
    from minem.db import connect_database, CORE_SCHEMA_SQL
    from minem.migrations import run_migrations, MIGRATIONS

    path = tmp_runtime / "data" / "materials.db"
    conn = connect_database(path, timeout=5)
    conn.executescript(CORE_SCHEMA_SQL)
    run_migrations(conn, MIGRATIONS)
    conn.close()
    return path


@pytest.fixture
def db_conn(db_path):
    """Yield an open database connection, closed after the test."""
    from minem.db import connect_database
    conn = connect_database(db_path, timeout=5)
    yield conn
    conn.close()


@pytest.fixture
def sample_html_zip(tmp_path):
    """Create a minimal ZIP containing a valid HTML page."""
    import zipfile
    zip_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("index.html", """<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body><div class="slide-frame">Page 1</div></body>
</html>""")
        zf.writestr("assets/logo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return zip_path


@pytest.fixture
def sample_report_zip(tmp_path):
    """Create a ZIP with multi-page report structure."""
    import zipfile
    zip_path = tmp_path / "report.zip"
    pages_html = """<!DOCTYPE html>
<html><head><title>Report</title></head>
<body>
<div class="slide-frame" data-page-index="0">Page 1</div>
<div class="slide-frame" data-page-index="1">Page 2</div>
<div class="slide-frame" data-page-index="2">Page 3</div>
</body></html>"""
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("index.html", pages_html)
    return zip_path
