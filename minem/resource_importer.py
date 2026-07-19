import base64
import binascii
import hashlib
import re
from pathlib import Path


INLINE_IMAGE_PATTERN = re.compile(
    r"data:(image/(?:png|jpe?g|webp|gif|svg\+xml));base64,([A-Za-z0-9+/=\s]+)",
    re.IGNORECASE,
)
INLINE_IMAGE_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}


def materialize_inline_image_resources(extract_root: Path) -> int:
    """Persist embedded image data URIs so they can become reusable assets.

    Imported reports may be fully self-contained and have no assets/ folder.
    Keeping a content-addressed copy under assets/_minem_inline preserves the
    original HTML while allowing the normal resource sync and de-duplication
    pipeline to index the underlying images.
    """
    extract_root = Path(extract_root)
    target_root = extract_root / "assets" / "_minem_inline"
    created = 0
    for html_path in extract_root.rglob("*.htm*"):
        if not html_path.is_file() or target_root in html_path.parents:
            continue
        try:
            source = html_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in INLINE_IMAGE_PATTERN.finditer(source):
            mime = match.group(1).lower()
            suffix = INLINE_IMAGE_SUFFIXES.get(mime)
            if not suffix:
                continue
            try:
                payload = base64.b64decode(re.sub(r"\s+", "", match.group(2)), validate=True)
            except (ValueError, binascii.Error):
                continue
            if not payload:
                continue
            digest = hashlib.sha1(payload).hexdigest()
            target = target_root / f"inline-{digest}{suffix}"
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_bytes(payload)
            except OSError:
                continue
            created += 1
    return created


def sync_report_package_resources(
    conn,
    upload_id,
    extract_root,
    report_code,
    report_title,
    *,
    resource_suffixes,
    media_kind_for,
    file_hash,
    find_existing_asset,
    resource_kind_for,
    merge_tags,
    resource_kinds,
    suggest_material_tags,
    normalize_role_tags,
    apply_company_logo_metadata,
    slugify,
    next_asset_code,
    now_ms,
):
    extract_root = Path(extract_root)
    materialize_inline_image_resources(extract_root)
    assets_root = extract_root / "assets"
    if not assets_root.exists():
        return 0
    inserted = 0
    for file_path in sorted(path for path in assets_root.rglob("*") if path.is_file() and path.suffix.lower() in resource_suffixes):
        rel = file_path.relative_to(extract_root).as_posix()
        media_kind = media_kind_for(file_path)
        source_hash = file_hash(file_path)
        path_existing = find_existing_asset(conn, upload_id, rel, "resource")
        content_existing = conn.execute(
            "select * from assets where asset_type = 'resource' and source_hash = ? order by created_at, asset_code limit 1",
            (source_hash,),
        ).fetchone()
        title = file_path.stem.replace("-", " ").replace("_", " ").strip() or file_path.name
        resource_kind = resource_kind_for(file_path, media_kind, title, "")
        tags = merge_tags(
            path_existing["tags"] if path_existing else "",
            ["资源素材", "汇报资源", report_code, report_title, resource_kinds.get(resource_kind, resource_kind), "自动同步"],
            suggest_material_tags(" ".join([title, rel, report_title]), resource_kind),
        )
        tags = normalize_role_tags(tags, "resource", resource_kind, " ".join([title, rel]))
        title, tag_text = apply_company_logo_metadata(title, ",".join(tags), rel, f"从汇报素材 {report_code} 自动同步", resource_kind)
        if content_existing and (not path_existing or content_existing["id"] != path_existing["id"]):
            usage = content_existing["usage"] or ""
            if report_code not in usage:
                usage = f"{usage}；复用到汇报素材 {report_code}".strip("；")
            conn.execute(
                "update assets set tags = ?, usage = ?, updated_at = ? where id = ?",
                (
                    ",".join(merge_tags(content_existing["tags"], tag_text, ["复用资源"])),
                    usage,
                    now_ms(),
                    content_existing["id"],
                ),
            )
            continue
        existing = path_existing
        asset_id = existing["id"] if existing else f"{upload_id}-resource-{slugify(file_path.stem)}-{hashlib.sha1(rel.encode('utf-8')).hexdigest()[:8]}"
        asset_code = existing["asset_code"] if existing else next_asset_code(conn, "resource", "visual", media_kind)
        conn.execute(
            """
            insert into assets
            (id, title, category, usage, tags, snippet, asset_type, asset_code, media_kind, resource_kind, source_type, source_path, preview_url, upload_id, source_hash, version_group, version_no, version_parent_id, similarity_score, similarity_method, tag_seeded, created_at, updated_at)
            values (?, ?, 'visual', ?, ?, '', 'resource', ?, ?, ?, 'report-material-sync', ?, ?, ?, ?, ?, 1, '', 1.0, '', 1, ?, ?)
            on conflict(id) do update set
              title=excluded.title,
              usage=excluded.usage,
              tags=excluded.tags,
              media_kind=excluded.media_kind,
              resource_kind=excluded.resource_kind,
              source_type=excluded.source_type,
              source_path=excluded.source_path,
              preview_url=excluded.preview_url,
              upload_id=excluded.upload_id,
              source_hash=excluded.source_hash,
              updated_at=excluded.updated_at
            """,
            (
                asset_id,
                title,
                f"从汇报素材 {report_code} 自动同步的基础资源。",
                tag_text,
                asset_code,
                media_kind,
                resource_kind,
                rel,
                f"/extracted/{upload_id}/{rel}",
                upload_id,
                source_hash,
                existing["version_group"] if existing else asset_id,
                existing["created_at"] if existing else now_ms(),
                now_ms(),
            ),
        )
        inserted += 1
    return inserted
