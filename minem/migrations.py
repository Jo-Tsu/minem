from __future__ import annotations

import hashlib
import inspect
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


MIGRATION_TABLE_SQL = """
create table if not exists schema_migrations (
  version integer primary key,
  name text not null,
  checksum text not null,
  applied_at integer not null
);
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]
    checksum_source: str = ""

    @property
    def checksum(self) -> str:
        if self.checksum_source:
            identity = f"{self.version}:{self.name}:{self.checksum_source}"
            return hashlib.sha256(identity.encode("utf-8")).hexdigest()
        try:
            implementation = inspect.getsource(self.apply)
        except (OSError, TypeError):
            code = getattr(self.apply, "__code__", None)
            implementation = repr(
                (
                    getattr(code, "co_code", b""),
                    getattr(code, "co_consts", ()),
                    getattr(code, "co_names", ()),
                )
            )
        identity = (
            f"{self.version}:{self.name}:{self.apply.__module__}:"
            f"{self.apply.__qualname__}:{implementation}"
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def now_ms() -> int:
    return int(time.time() * 1000)


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(MIGRATION_TABLE_SQL)


def applied_migrations(conn: sqlite3.Connection) -> dict[int, dict]:
    exists = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'schema_migrations'"
    ).fetchone()
    if not exists:
        return {}
    rows = conn.execute(
        "select version, name, checksum, applied_at from schema_migrations order by version"
    ).fetchall()
    return {
        int(row["version"] if isinstance(row, sqlite3.Row) else row[0]): {
            "version": int(row["version"] if isinstance(row, sqlite3.Row) else row[0]),
            "name": row["name"] if isinstance(row, sqlite3.Row) else row[1],
            "checksum": row["checksum"] if isinstance(row, sqlite3.Row) else row[2],
            "appliedAt": int(row["applied_at"] if isinstance(row, sqlite3.Row) else row[3]),
        }
        for row in rows
    }


def migration_status(conn: sqlite3.Connection, migrations: Iterable[Migration]) -> dict:
    ordered = sorted(migrations, key=lambda item: item.version)
    applied = applied_migrations(conn)
    pending = [migration for migration in ordered if migration.version not in applied]
    return {
        "currentVersion": max(applied, default=0),
        "targetVersion": max((migration.version for migration in ordered), default=0),
        "applied": [applied[version] for version in sorted(applied)],
        "pending": [
            {"version": migration.version, "name": migration.name, "checksum": migration.checksum}
            for migration in pending
        ],
    }


def backup_database(
    conn: sqlite3.Connection,
    backup_dir: str | Path,
    *,
    target_version: int,
    retain: int = 3,
) -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / (
        f"materials-before-v{int(target_version)}-{time.strftime('%Y%m%d-%H%M%S')}.db"
    )
    temporary = destination.with_suffix(f".tmp-{os.getpid()}")
    target = sqlite3.connect(temporary)
    try:
        conn.backup(target)
    finally:
        target.close()
    temporary.replace(destination)

    retained = max(1, int(retain))
    candidates = sorted(
        backup_dir.glob("materials-before-v*.db"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for stale in candidates[retained:]:
        stale.unlink(missing_ok=True)
    return destination


def run_migrations(
    conn: sqlite3.Connection,
    migrations: Iterable[Migration],
    *,
    backup_dir: str | Path | None = None,
    backup_from_version: int = 2,
    backup_retain: int = 3,
) -> dict:
    ordered = sorted(migrations, key=lambda item: item.version)
    versions = [migration.version for migration in ordered]
    if len(versions) != len(set(versions)):
        raise ValueError("migration versions must be unique")
    if versions != sorted(versions):
        raise ValueError("migrations must be ordered")

    before = migration_status(conn, ordered)
    backup_path = None
    pending_versions = [item["version"] for item in before["pending"]]
    if (
        backup_dir is not None
        and pending_versions
        and max(pending_versions) >= int(backup_from_version)
    ):
        backup_path = backup_database(
            conn,
            backup_dir,
            target_version=max(pending_versions),
            retain=backup_retain,
        )

    nested = conn.in_transaction
    if nested:
        conn.execute("savepoint minem_schema_migrations")
    else:
        conn.execute("begin immediate")
    try:
        ensure_migration_table(conn)
        applied = applied_migrations(conn)
        executed = []
        for migration in ordered:
            existing = applied.get(migration.version)
            if existing:
                if existing["name"] != migration.name or existing["checksum"] != migration.checksum:
                    raise RuntimeError(
                        f"migration {migration.version} does not match its applied checksum"
                    )
                continue
            migration.apply(conn)
            conn.execute(
                "insert into schema_migrations(version, name, checksum, applied_at) values (?, ?, ?, ?)",
                (migration.version, migration.name, migration.checksum, now_ms()),
            )
            executed.append({"version": migration.version, "name": migration.name})
        if nested:
            conn.execute("release savepoint minem_schema_migrations")
        else:
            conn.commit()
    except Exception:
        if nested:
            conn.execute("rollback to savepoint minem_schema_migrations")
            conn.execute("release savepoint minem_schema_migrations")
        else:
            conn.rollback()
        raise

    status = migration_status(conn, ordered)
    status["executed"] = executed
    status["backupPath"] = str(backup_path) if backup_path else ""
    return status
