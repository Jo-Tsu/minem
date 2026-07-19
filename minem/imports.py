import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from minem.html_dependencies import audit_dependency_closure, write_dependency_audit


HTML_RESOURCE_DIRS = {
    "asset",
    "assets",
    "image",
    "images",
    "img",
    "media",
    "public",
    "resource",
    "resources",
    "static",
}
HTML_REFERENCE_RE = re.compile(
    r"""(?:src|href|poster|data-fs-src)\s*=\s*["']([^"'#]+)["']|url\(\s*["']?([^"')]+)["']?\s*\)""",
    re.IGNORECASE,
)
MAX_HTML_DEPENDENCY_FILES = 1200
MAX_HTML_DEPENDENCY_BYTES = 350 * 1024 * 1024


def runtime_record_path(path, runtime_root):
    """Store platform-owned paths relative to the runtime root."""
    candidate = Path(path).expanduser().resolve()
    root = Path(runtime_root).expanduser().resolve()
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return str(candidate)


def create_import_task(store, task):
    return store.create(task) if task else None


def update_import_task(store, task_id, **updates):
    return store.update(task_id, **updates)


def list_import_tasks(store, *, limit=8):
    return store.list(limit=limit)


def get_import_task(store, task_id):
    return store.get(task_id)


def _path_within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _clean_local_html_reference(reference):
    value = str(reference or "").strip()
    if not value or value.startswith("#"):
        return ""
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return ""
    path = unquote(parsed.path or value)
    if not path or path.startswith(("/", "\\")):
        return ""
    if "\x00" in path:
        return ""
    return path


def _iter_html_references(html_text):
    for match in HTML_REFERENCE_RE.finditer(html_text or ""):
        reference = match.group(1) or match.group(2) or ""
        cleaned = _clean_local_html_reference(reference)
        if cleaned:
            yield cleaned


def _copy_file_limited(src, dest, state):
    if state["files"] >= MAX_HTML_DEPENDENCY_FILES or not src.exists() or not src.is_file():
        return False
    try:
        size = src.stat().st_size
    except OSError:
        return False
    if state["bytes"] + size > MAX_HTML_DEPENDENCY_BYTES:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or src.stat().st_mtime_ns != dest.stat().st_mtime_ns or size != dest.stat().st_size:
        shutil.copy2(src, dest)
    state["files"] += 1
    state["bytes"] += size
    return True


def _copy_tree_limited(src_dir, dest_dir, state):
    if not src_dir.exists() or not src_dir.is_dir():
        return
    for path in src_dir.rglob("*"):
        if state["files"] >= MAX_HTML_DEPENDENCY_FILES:
            return
        if not path.is_file():
            continue
        rel = path.relative_to(src_dir)
        _copy_file_limited(path, dest_dir / rel, state)


def copy_html_dependency_bundle(source_path, target_root, bundle_name, entry_name=""):
    """Copy an HTML file with its local dependencies into an isolated bundle."""
    source_path = Path(source_path).resolve()
    target_root = Path(target_root)
    source_dir = source_path.parent.resolve()
    target_root_resolved = target_root.resolve()
    bundle_dir = target_root / "bundles" / bundle_name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    dest_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", entry_name or source_path.name).strip("-") or source_path.name
    dest = bundle_dir / dest_name
    state = {"files": 0, "bytes": 0}
    _copy_file_limited(source_path, dest, state)

    for child in source_dir.iterdir():
        if child.is_dir() and child.name.lower() in HTML_RESOURCE_DIRS:
            _copy_tree_limited(child, bundle_dir / child.name, state)

    try:
        html_text = source_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        html_text = ""
    for reference in _iter_html_references(html_text):
        src = (source_dir / reference).resolve()
        dest_for_reference = (bundle_dir / reference).resolve()
        if not _path_within(dest_for_reference, target_root_resolved):
            continue
        # Generated report pages often reference shared assets above the page
        # directory, for example ../../assets/logos/feishu.svg. Keep the same
        # relative shape inside the import batch so the HTML can render without
        # rewriting user-generated source.
        if not _path_within(src, source_dir):
            walked_up = any(part == ".." for part in Path(reference).parts)
            inside_parent = any(_path_within(src, parent) for parent in source_dir.parents[:6])
            if not walked_up or not inside_parent:
                continue
        if src.is_file():
            _copy_file_limited(src, dest_for_reference, state)
        elif src.is_dir() and Path(reference).name.lower() in HTML_RESOURCE_DIRS:
            _copy_tree_limited(src, dest_for_reference, state)

    # HTML reports commonly nest reusable pages in iframes. Keep walking those
    # pages (and their CSS) so a copied page is a real dependency closure,
    # rather than a shell that only works beside its original source folder.
    queue = [(source_path, dest)]
    visited = set()
    allowed_parents = source_path.parents[:7]
    while queue and state["files"] < MAX_HTML_DEPENDENCY_FILES:
        current_source, current_dest = queue.pop()
        current_source = current_source.resolve()
        if current_source in visited or not current_source.exists():
            continue
        visited.add(current_source)
        try:
            current_text = current_source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for reference in _iter_html_references(current_text):
            source_ref = (current_source.parent / reference).resolve()
            dest_ref = (current_dest.parent / reference).resolve()
            if not _path_within(dest_ref, target_root_resolved):
                continue
            if not any(_path_within(source_ref, parent) for parent in allowed_parents):
                continue
            if source_ref.is_file():
                if _copy_file_limited(source_ref, dest_ref, state) and source_ref.suffix.lower() in {".html", ".htm", ".css"}:
                    queue.append((source_ref, dest_ref))
            elif source_ref.is_dir() and Path(reference).name.lower() in HTML_RESOURCE_DIRS:
                _copy_tree_limited(source_ref, dest_ref, state)
    return dest, dest.relative_to(target_root).as_posix()


def load_import_sources(config_path, default_sources, default_excludes, *, default_max_depth=5):
    config_path = Path(config_path)
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            roots = payload.get("roots", default_sources)
            excludes = set(payload.get("excludes", [])) | set(default_excludes)
            max_depth = int(payload.get("maxDepth", default_max_depth))
            return [Path(root).expanduser() for root in roots], excludes, max_depth
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return [Path(root).expanduser() for root in default_sources], set(default_excludes), default_max_depth


def should_skip_dir(path, excludes):
    return bool(set(Path(path).parts).intersection(excludes))


def iter_import_candidates(
    roots,
    excludes,
    max_depth,
    *,
    allowed_suffixes,
    zip_suffixes,
    excluded_file_keywords=None,
):
    excluded_file_keywords = set(excluded_file_keywords or [])
    suffixes = set(allowed_suffixes) | set(zip_suffixes)
    seen = set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        if root.is_file():
            if root.suffix.lower() in suffixes:
                yield root
            continue
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            try:
                depth = len(current_path.relative_to(root).parts)
            except ValueError:
                depth = 0
            dirs[:] = [name for name in dirs if name not in excludes and depth < max_depth]
            if should_skip_dir(current_path, excludes):
                dirs[:] = []
                continue
            for name in files:
                if any(keyword in name for keyword in excluded_file_keywords):
                    continue
                path = current_path / name
                if path.suffix.lower() in suffixes:
                    yield path


def normalized_package_hash(extract_root):
    """Hash a package by relative paths and bytes, independent of ZIP metadata."""
    extract_root = Path(extract_root)
    digest = hashlib.sha256()
    for path in sorted(item for item in extract_root.rglob("*") if item.is_file() and item.name != ".minem-dependency-audit.json"):
        digest.update(path.relative_to(extract_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return f"package-v1:{digest.hexdigest()}"


def run_import_task(
    task_id,
    stored_path,
    original,
    upload_id,
    description,
    *,
    extracted_dir,
    zip_suffixes,
    update_task,
    connect,
    safe_extract,
    scan_upload,
    generate_upload_thumbnails,
    import_result_for_upload,
    existing_result_for_extract_root,
    now_ms,
    content_hash="",
):
    stored_path = Path(stored_path)
    suffix = stored_path.suffix.lower()
    extract_root = Path(extracted_dir) / upload_id
    update_task(task_id, status="running", progress=12, message="正在解析文件")
    try:
        if extract_root.exists():
            shutil.rmtree(extract_root)
        if suffix in zip_suffixes:
            try:
                safe_extract(stored_path, extract_root)
            except zipfile.BadZipFile:
                raise ValueError("压缩包无法解压")
        elif suffix in {".html", ".htm"}:
            extract_root.mkdir(parents=True, exist_ok=True)
            copy_html_dependency_bundle(stored_path, extract_root, "upload-html")
        else:
            extract_root.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stored_path, extract_root / original)

        dependency_audit = audit_dependency_closure(extract_root)
        write_dependency_audit(extract_root, dependency_audit)
        if dependency_audit["missing"]:
            sample = ", ".join(item["resolved"] for item in dependency_audit["missing"][:3])
            raise ValueError(f"导入包缺少 {len(dependency_audit['missing'])} 个本地资源：{sample}")

        package_hash = normalized_package_hash(extract_root)
        with connect() as conn:
            duplicate = conn.execute(
                """select id from uploads where id <> ? and content_hash = ?
                   and exists(select 1 from assets where upload_id = uploads.id)
                   order by created_at desc limit 1""",
                (upload_id, package_hash),
            ).fetchone()
        if duplicate:
            result = import_result_for_upload(duplicate["id"])
            shutil.rmtree(extract_root, ignore_errors=True)
            stored_path.unlink(missing_ok=True)
            update_task(
                task_id, status="success", progress=100, message="相同内容已存在，已复用历史批次",
                error="", fileCount=0, assetCount=0, thumbnailCount=0, uploadId=duplicate["id"], **result,
            )
            return

        update_task(task_id, progress=38, message="正在事务性写入素材库")
        runtime_root = Path(extracted_dir).resolve().parent
        with connect() as conn:
            conn.execute(
                "insert or replace into uploads (id, filename, stored_path, extract_path, content_hash, created_at) values (?, ?, ?, ?, ?, ?)",
                (
                    upload_id,
                    original,
                    runtime_record_path(stored_path, runtime_root),
                    runtime_record_path(extract_root, runtime_root),
                    package_hash,
                    now_ms(),
                ),
            )
            file_count, asset_count = scan_upload(upload_id, extract_root, description, conn=conn)
        update_task(task_id, progress=72, message="正在生成预览")
        thumbnail_count = generate_upload_thumbnails(upload_id)
        result = import_result_for_upload(upload_id)
        if not result.get("previewUrl") and existing_result_for_extract_root:
            result = existing_result_for_extract_root(extract_root)
            if result.get("previewUrl"):
                update_task(
                    task_id,
                    status="success",
                    progress=100,
                    message="素材已存在，已关联到历史素材",
                    error="",
                    fileCount=file_count,
                    assetCount=asset_count,
                    thumbnailCount=thumbnail_count,
                    uploadId=upload_id,
                    **result,
                )
                return
        if asset_count <= 0 or not result.get("previewUrl"):
            update_task(
                task_id,
                status="failed",
                progress=100,
                message="导入失败",
                error="没有识别到可预览的素材，或素材已存在",
                fileCount=file_count,
                assetCount=asset_count,
                thumbnailCount=thumbnail_count,
                uploadId=upload_id,
            )
            return
        update_task(
            task_id,
            status="success",
            progress=100,
            message="导入成功，可点击预览",
            fileCount=file_count,
            assetCount=asset_count,
            thumbnailCount=thumbnail_count,
            uploadId=upload_id,
            **result,
        )
    except Exception as error:
        update_task(
            task_id,
            status="failed",
            progress=100,
            message="导入失败",
            error=str(error),
            uploadId=upload_id,
        )


def import_direct_file(
    conn,
    source_path,
    import_id,
    target_root,
    *,
    file_hash,
    asset_exists,
    insert_asset_record,
):
    source_path = Path(source_path)
    target_root = Path(target_root)
    source_hash = f"direct-content:{file_hash(source_path)}"
    if asset_exists(conn, source_hash):
        return False
    digest = hashlib.sha1(str(source_path.resolve()).encode("utf-8")).hexdigest()[:10]
    if source_path.suffix.lower() in {".html", ".htm"}:
        dest, rel = copy_html_dependency_bundle(source_path, target_root, digest, f"{digest}-{source_path.name}")
    else:
        rel = f"{digest}-{source_path.name}"
        dest = target_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest)
    insert_asset_record(
        conn,
        file_path=dest,
        rel=rel,
        upload_id=import_id,
        source_type="auto",
        source_hash=source_hash,
        usage=f"从本机历史素材自动导入：{source_path}",
    )
    return True


def import_zip_file(
    source_path,
    *,
    connect,
    uploads_dir,
    extracted_dir,
    safe_extract,
    scan_upload,
    now_ms,
    extraction_errors=(),
):
    source_path = Path(source_path)
    with connect() as conn:
        if conn.execute("select 1 from uploads where stored_path = ? limit 1", (str(source_path),)).fetchone():
            return 0, 0
    upload_id = f"auto-{time.strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1(str(source_path).encode()).hexdigest()[:8]}"
    stored = Path(uploads_dir) / f"{upload_id}.zip"
    shutil.copy2(source_path, stored)
    extract_root = Path(extracted_dir) / upload_id
    handled_errors = (zipfile.BadZipFile,) + tuple(extraction_errors)
    try:
        safe_extract(stored, extract_root)
    except handled_errors:
        stored.unlink(missing_ok=True)
        return 0, 0
    dependency_audit = audit_dependency_closure(extract_root)
    write_dependency_audit(extract_root, dependency_audit)
    if dependency_audit["missing"]:
        # Auto-import has no task drawer, so reject an incomplete package here
        # rather than creating records that can only render with broken media.
        shutil.rmtree(extract_root, ignore_errors=True)
        stored.unlink(missing_ok=True)
        return 0, 0
    with connect() as conn:
        conn.execute(
            "insert into uploads (id, filename, stored_path, extract_path, created_at) values (?, ?, ?, ?, ?)",
            (
                upload_id,
                f"auto:{source_path.name}",
                str(source_path.resolve()),
                runtime_record_path(extract_root, Path(extracted_dir).resolve().parent),
                now_ms(),
            ),
        )
        return scan_upload(upload_id, extract_root, conn=conn)


def auto_import_sources(
    *,
    load_sources,
    iter_candidates,
    import_zip,
    import_direct,
    connect,
    extracted_dir,
    zip_suffixes,
    now_ms,
):
    roots, excludes, max_depth = load_sources()
    import_id = f"auto-{time.strftime('%Y%m%d-%H%M%S')}"
    target_root = Path(extracted_dir) / import_id
    scanned = 0
    inserted = 0
    zip_files = 0
    with connect() as conn:
        conn.execute(
            "insert or ignore into uploads (id, filename, stored_path, extract_path, created_at) values (?, ?, ?, ?, ?)",
            (
                import_id,
                "auto-import",
                ",".join(str(root) for root in roots),
                runtime_record_path(target_root, Path(extracted_dir).resolve().parent),
                now_ms(),
            ),
        )
    for path in iter_candidates(roots, excludes, max_depth):
        scanned += 1
        if path.suffix.lower() in zip_suffixes:
            zip_files += 1
            _, added = import_zip(path)
            inserted += added
            continue
        with connect() as conn:
            if import_direct(conn, path, import_id, target_root):
                inserted += 1
    with connect() as conn:
        conn.execute(
            "update uploads set file_count = ?, asset_count = ? where id = ?",
            (scanned, inserted, import_id),
        )
        if inserted == 0:
            conn.execute("delete from uploads where id = ?", (import_id,))
            shutil.rmtree(target_root, ignore_errors=True)
    return {
        "ok": True,
        "importId": import_id,
        "roots": [str(root) for root in roots],
        "scanned": scanned,
        "assetCount": inserted,
        "zipCount": zip_files,
    }
