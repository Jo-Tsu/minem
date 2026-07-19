import sqlite3
from pathlib import Path


VALID_JOURNAL_MODES = {"delete", "truncate", "persist", "memory", "wal", "off"}


CORE_SCHEMA_SQL = """
create table if not exists assets (
  id text primary key,
  title text not null,
  category text not null default 'code',
  usage text not null default '',
  tags text not null default '',
  snippet text not null default '',
  asset_type text not null default 'control',
  asset_code text not null default '',
  media_kind text not null default 'none',
  source_type text not null default 'manual',
  source_path text not null default '',
  preview_url text not null default '',
  upload_id text,
  created_at integer not null,
  updated_at integer not null
);

create table if not exists uploads (
  id text primary key,
  filename text not null,
  stored_path text not null,
  extract_path text not null,
  file_count integer not null default 0,
  asset_count integer not null default 0,
  content_hash text not null default '',
  created_at integer not null
);

create table if not exists report_page_slots (
  report_id text not null,
  page_number integer not null,
  title text not null default '',
  status text not null default 'planned',
  control_id text not null default '',
  task_key text not null default '',
  note text not null default '',
  created_at integer not null,
  updated_at integer not null,
  primary key (report_id, page_number)
);

create table if not exists report_page_arrangements (
  report_id text primary key,
  page_order text not null default '[]',
  hidden_page_ids text not null default '[]',
  updated_by text not null default 'manual-arrangement',
  updated_at integer not null
);

create table if not exists report_page_normalizations (
  report_id text not null,
  source_control_id text not null,
  normalized_control_id text not null,
  target_width integer not null,
  target_height integer not null,
  source_width integer not null default 0,
  source_height integer not null default 0,
  source_fingerprint text not null default '',
  created_at integer not null,
  updated_at integer not null,
  primary key (report_id, source_control_id, target_width, target_height)
);

create table if not exists report_page_candidates (
  id text primary key,
  report_id text not null,
  page_number integer not null,
  control_id text not null,
  title text not null default '',
  status text not null default 'candidate',
  note text not null default '',
  created_at integer not null,
  updated_at integer not null
);

create table if not exists asset_history (
  id text primary key,
  asset_id text not null,
  asset_code text not null default '',
  version_no integer not null,
  title text not null default '',
  category text not null default '',
  usage text not null default '',
  tags text not null default '',
  snippet text not null default '',
  asset_type text not null default '',
  media_kind text not null default '',
  source_type text not null default '',
  source_path text not null default '',
  preview_url text not null default '',
  upload_id text,
  source_hash text not null default '',
  snapshot_path text not null default '',
  change_note text not null default '',
  created_at integer not null,
  captured_at integer not null
);

create table if not exists report_storyline_collections (
  id text primary key,
  code text not null default '',
  title text not null default '',
  source_report_id text not null,
  source_report_code text not null default '',
  output_report_id text not null,
  output_report_code text not null default '',
  target_report_id text not null default '',
  mode text not null default 'collection',
  note text not null default '',
  tags text not null default '',
  version_group text not null default '',
  version_no integer not null default 1,
  version_parent_id text not null default '',
  created_at integer not null,
  updated_at integer not null
);
"""


def connect_database(db_path, *, timeout=5):
    conn = sqlite3.connect(Path(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma busy_timeout = 5000")
    conn.execute("pragma foreign_keys = on")
    return conn


def normalize_journal_mode(value):
    mode = str(value or "wal").strip().lower() or "wal"
    return mode if mode in VALID_JOURNAL_MODES else "wal"


def configure_connection(conn, *, journal_mode="wal", on_warning=None):
    mode = normalize_journal_mode(journal_mode)
    try:
        conn.execute(f"pragma journal_mode = {mode}")
    except sqlite3.OperationalError as error:
        if on_warning:
            on_warning(f"SQLite journal mode unchanged: {error}")
    conn.execute("pragma synchronous = normal")


def table_columns(conn, table):
    rows = conn.execute(f"pragma table_info({table})").fetchall()
    return {row["name"] for row in rows}


def ensure_asset_schema(conn):
    columns = table_columns(conn, "assets")
    if "asset_type" not in columns:
        conn.execute("alter table assets add column asset_type text not null default 'control'")
    if "asset_code" not in columns:
        conn.execute("alter table assets add column asset_code text not null default ''")
    if "media_kind" not in columns:
        conn.execute("alter table assets add column media_kind text not null default 'none'")
    if "source_hash" not in columns:
        conn.execute("alter table assets add column source_hash text not null default ''")
    if "version_group" not in columns:
        conn.execute("alter table assets add column version_group text not null default ''")
    if "version_no" not in columns:
        conn.execute("alter table assets add column version_no integer not null default 1")
    if "version_parent_id" not in columns:
        conn.execute("alter table assets add column version_parent_id text not null default ''")
    if "similarity_score" not in columns:
        conn.execute("alter table assets add column similarity_score real not null default 1.0")
    if "similarity_method" not in columns:
        conn.execute("alter table assets add column similarity_method text not null default ''")
    if "resource_kind" not in columns:
        conn.execute("alter table assets add column resource_kind text not null default ''")
    if "tag_seeded" not in columns:
        conn.execute("alter table assets add column tag_seeded integer not null default 0")
    if "trusted_entry_ok" not in columns:
        conn.execute("alter table assets add column trusted_entry_ok integer not null default 0")
    if "trusted_entry_url" not in columns:
        conn.execute("alter table assets add column trusted_entry_url text not null default ''")
    if "trusted_page_count" not in columns:
        conn.execute("alter table assets add column trusted_page_count integer not null default 0")
    if "trusted_viewer_page_count" not in columns:
        conn.execute("alter table assets add column trusted_viewer_page_count integer not null default 0")
    if "trusted_hash" not in columns:
        conn.execute("alter table assets add column trusted_hash text not null default ''")
    if "trusted_size" not in columns:
        conn.execute("alter table assets add column trusted_size integer not null default 0")
    if "trusted_checked_at" not in columns:
        conn.execute("alter table assets add column trusted_checked_at integer not null default 0")
    conn.execute("create unique index if not exists idx_assets_asset_code on assets(asset_code) where asset_code <> ''")
    conn.execute("create unique index if not exists idx_assets_source_hash on assets(source_hash) where source_hash <> ''")
    conn.execute("create index if not exists idx_assets_version_group on assets(version_group)")
    conn.execute("create index if not exists idx_assets_version_parent on assets(version_parent_id)")
    conn.execute("create index if not exists idx_assets_list_primary on assets(asset_type, version_parent_id, updated_at desc, created_at desc)")
    conn.execute("create index if not exists idx_assets_version_activity on assets(version_group, updated_at desc)")
    conn.execute("create index if not exists idx_assets_resource_kind on assets(resource_kind)")
    conn.execute("create index if not exists idx_asset_history_asset on asset_history(asset_id, version_no)")
    conn.execute("create unique index if not exists idx_report_page_candidates_unique on report_page_candidates(report_id, page_number, control_id)")
    conn.execute("create index if not exists idx_report_page_candidates_report on report_page_candidates(report_id, page_number, status)")
    conn.execute("create index if not exists idx_report_page_candidates_control on report_page_candidates(control_id)")
    conn.execute("create index if not exists idx_report_storyline_source on report_storyline_collections(source_report_id)")
    conn.execute("create index if not exists idx_report_storyline_output on report_storyline_collections(output_report_id)")
    conn.execute("create index if not exists idx_report_storyline_target on report_storyline_collections(target_report_id)")
    storyline_columns = table_columns(conn, "report_storyline_collections")
    if "version_group" not in storyline_columns:
        conn.execute("alter table report_storyline_collections add column version_group text not null default ''")
    if "version_no" not in storyline_columns:
        conn.execute("alter table report_storyline_collections add column version_no integer not null default 1")
    if "version_parent_id" not in storyline_columns:
        conn.execute("alter table report_storyline_collections add column version_parent_id text not null default ''")
    conn.execute("create index if not exists idx_report_storyline_version_group on report_storyline_collections(version_group, version_no)")
    conn.execute("update assets set version_group = id where version_group = ''")
    conn.execute("update report_storyline_collections set version_group = id where version_group = ''")


def ensure_upload_schema(conn):
    columns = table_columns(conn, "uploads")
    if "content_hash" not in columns:
        conn.execute("alter table uploads add column content_hash text not null default ''")
    conn.execute("create index if not exists idx_uploads_content_hash on uploads(content_hash) where content_hash <> ''")


def create_core_schema(conn):
    conn.executescript(CORE_SCHEMA_SQL)


def run_compat_migrations(conn):
    conn.execute("create index if not exists idx_report_page_slots_control on report_page_slots(control_id)")
    conn.execute("create index if not exists idx_report_page_arrangements_updated on report_page_arrangements(updated_at desc)")
    conn.execute("create index if not exists idx_report_page_normalizations_control on report_page_normalizations(normalized_control_id)")
    conn.execute("update assets set asset_type = 'report' where asset_type = 'page'")
    conn.execute("update assets set asset_code = replace(asset_code, 'PAGE-', 'RPT-') where asset_code like 'PAGE-%'")
    conn.execute("update assets set tags = replace(tags, '页面素材', '汇报素材') where tags like '%页面素材%'")
    legacy_storyline_outputs = """
        select output_report_id
        from report_storyline_collections
        where output_report_id <> ''
          and output_report_id in (
            select id from assets where source_type = 'storyline-collection'
          )
    """
    conn.execute(f"delete from asset_history where asset_id in ({legacy_storyline_outputs})")
    conn.execute(f"delete from report_page_slots where report_id in ({legacy_storyline_outputs})")
    conn.execute(f"delete from report_page_candidates where report_id in ({legacy_storyline_outputs})")
    conn.execute(f"delete from assets where id in ({legacy_storyline_outputs})")
    conn.execute(
        """
        update report_storyline_collections
        set output_report_id = '',
            output_report_code = '',
            target_report_id = '',
            mode = 'collection',
            tags = replace(replace(tags, ',新汇报', ''), ',版本', '')
        where output_report_id <> ''
          and output_report_id not in (select id from assets)
        """
    )


def ensure_storage_dirs(*paths):
    for path in paths:
        Path(path).mkdir(parents=True, exist_ok=True)


def initialize_database(
    *,
    data_dir,
    uploads_dir,
    extracted_dir,
    history_dir,
    thumbnails_dir,
    connect,
    import_task_store=None,
    backfill_asset_codes=None,
    backfill_resource_kinds=None,
    journal_mode="wal",
    on_warning=None,
):
    ensure_storage_dirs(data_dir, uploads_dir, extracted_dir, history_dir, thumbnails_dir)
    with connect() as conn:
        configure_connection(conn, journal_mode=journal_mode, on_warning=on_warning)
        create_core_schema(conn)
        if import_task_store:
            import_task_store.ensure_schema(conn)
        ensure_upload_schema(conn)
        ensure_asset_schema(conn)
        run_compat_migrations(conn)
        if backfill_asset_codes:
            backfill_asset_codes(conn)
        if backfill_resource_kinds:
            backfill_resource_kinds(conn)
