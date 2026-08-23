from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from pathlib import Path

from minem.html_splitter import extract_control_page_node


FINGERPRINT_VERSION = 1
MIN_VISIBLE_TEXT_LENGTH = 12
AUTO_MAX_MEAN_ABSOLUTE_DIFFERENCE = 1.5
AUTO_MAX_CHANGED_PIXEL_RATIO = 0.03


@dataclass(frozen=True)
class PageFingerprint:
    page_key: str
    text_hash: str
    fingerprint: str
    text_length: int
    visible_text: str
    version: int = FINGERPRINT_VERSION


def _normalize_page_key(value: str) -> str:
    value = re.sub(r"\s+", "-", str(value or "").strip().lower())
    return re.sub(r"[^a-z0-9._:-]+", "-", value).strip("-")[:160]


def _visible_page_text(page_html: str) -> str:
    text = re.sub(
        r"<(?:script|style|template)\b[^>]*>.*?</(?:script|style|template)>",
        " ",
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    alt_text = re.findall(r"\balt\s*=\s*[\"']([^\"']+)", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join([html.unescape(text), *map(html.unescape, alt_text)])
    return re.sub(r"\s+", " ", text).strip().lower()


def fingerprint_html(html_text: str) -> PageFingerprint:
    page_html = extract_control_page_node(html_text)
    keys = {
        _normalize_page_key(value)
        for value in re.findall(
            r"\bdata-(?:slide|page)-key\s*=\s*[\"']([^\"']+)",
            page_html,
            flags=re.IGNORECASE,
        )
        if _normalize_page_key(value)
    }
    page_key = next(iter(keys)) if len(keys) == 1 else ""
    visible_text = _visible_page_text(page_html)
    text_hash = (
        hashlib.sha256(visible_text.encode("utf-8")).hexdigest()
        if visible_text
        else ""
    )
    fingerprint = ""
    if page_key and len(visible_text) >= MIN_VISIBLE_TEXT_LENGTH:
        fingerprint = hashlib.sha256(
            f"page-v{FINGERPRINT_VERSION}\0{page_key}\0{text_hash}".encode("utf-8")
        ).hexdigest()
    return PageFingerprint(
        page_key=page_key,
        text_hash=text_hash,
        fingerprint=fingerprint,
        text_length=len(visible_text),
        visible_text=visible_text,
    )


def fingerprint_file(path: str | Path | None) -> PageFingerprint:
    if not path:
        return fingerprint_html("")
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    return fingerprint_html(text)


def refresh_asset_fingerprint(
    conn,
    asset_id: str,
    path: str | Path | None,
    *,
    dedupe_status: str | None = None,
) -> PageFingerprint:
    identity = fingerprint_file(path) if path else fingerprint_html("")
    if dedupe_status is None:
        conn.execute(
            """
            update assets
            set semantic_key = ?,
                semantic_text_hash = ?,
                semantic_fingerprint = ?,
                semantic_fingerprint_version = ?
            where id = ? and asset_type = 'control'
            """,
            (
                identity.page_key,
                identity.text_hash,
                identity.fingerprint,
                identity.version,
                asset_id,
            ),
        )
    else:
        conn.execute(
            """
            update assets
            set semantic_key = ?,
                semantic_text_hash = ?,
                semantic_fingerprint = ?,
                semantic_fingerprint_version = ?,
                semantic_dedupe_status = ?
            where id = ? and asset_type = 'control'
            """,
            (
                identity.page_key,
                identity.text_hash,
                identity.fingerprint,
                identity.version,
                dedupe_status,
                asset_id,
            ),
        )
    return identity


def backfill_page_fingerprints(
    conn,
    *,
    path_for_asset,
    version: int = FINGERPRINT_VERSION,
) -> dict:
    rows = conn.execute(
        """
        select *
        from assets
        where asset_type = 'control'
          and semantic_fingerprint_version <> ?
        order by created_at, id
        """,
        (version,),
    ).fetchall()
    updated = 0
    auto_candidates = 0
    for row in rows:
        identity = refresh_asset_fingerprint(conn, row["id"], path_for_asset(row))
        updated += 1
        auto_candidates += bool(identity.fingerprint)
    return {
        "updated": updated,
        "autoCandidates": auto_candidates,
        "version": version,
    }


def thumbnail_difference(left_path, right_path, *, image_module) -> dict:
    if image_module is None:
        return {"ok": False}
    try:
        with image_module.open(left_path) as left_source:
            left = left_source.convert("RGB").resize(
                (320, 180),
                image_module.Resampling.LANCZOS,
            )
        with image_module.open(right_path) as right_source:
            right = right_source.convert("RGB").resize(
                (320, 180),
                image_module.Resampling.LANCZOS,
            )
    except (OSError, ValueError):
        return {"ok": False}

    left_bytes = left.tobytes()
    right_bytes = right.tobytes()
    if left_bytes == right_bytes:
        return {
            "ok": True,
            "pixelEqual": True,
            "meanAbsoluteDifference": 0.0,
            "changedPixelRatio": 0.0,
            "score": 1.0,
        }

    total = 320 * 180
    absolute_sum = 0
    changed = 0
    left_pixels = list(left.getdata())
    right_pixels = list(right.getdata())
    for left_pixel, right_pixel in zip(left_pixels, right_pixels):
        channel_difference = [
            abs(int(left_value) - int(right_value))
            for left_value, right_value in zip(left_pixel, right_pixel)
        ]
        absolute_sum += sum(channel_difference)
        if max(channel_difference) > 2:
            changed += 1
    mean_difference = absolute_sum / (total * 3)
    changed_ratio = changed / total
    return {
        "ok": True,
        "pixelEqual": False,
        "meanAbsoluteDifference": round(mean_difference, 6),
        "changedPixelRatio": round(changed_ratio, 6),
        "score": round(max(0.0, 1.0 - mean_difference / 255.0), 6),
    }


def is_auto_reusable_visual(metrics: dict) -> bool:
    return bool(
        metrics.get("ok")
        and (
            metrics.get("pixelEqual")
            or (
                float(metrics.get("meanAbsoluteDifference") or 999)
                <= AUTO_MAX_MEAN_ABSOLUTE_DIFFERENCE
                and float(metrics.get("changedPixelRatio") or 1)
                <= AUTO_MAX_CHANGED_PIXEL_RATIO
            )
        )
    )


def attach_duplicate_version(
    conn,
    *,
    asset_id: str,
    primary_id: str,
    similarity_score: float,
    timestamp: int,
    similarity_method: str = "semantic-visual-v1",
) -> bool:
    if not asset_id or not primary_id or asset_id == primary_id:
        return False
    asset = conn.execute(
        "select * from assets where id = ? and asset_type = 'control'",
        (asset_id,),
    ).fetchone()
    primary = conn.execute(
        """
        select *
        from assets
        where id = ?
          and asset_type = 'control'
          and version_parent_id = ''
        """,
        (primary_id,),
    ).fetchone()
    if not asset or not primary:
        return False
    source_group = asset["version_group"] or asset["id"]
    version_group = primary["version_group"] or primary["id"]
    if source_group == version_group:
        return False
    target_rows = conn.execute(
        """
        select *
        from assets
        where asset_type = 'control'
          and (version_group = ? or id = ?)
        order by
          case when id = ? then 0 else 1 end,
          version_no,
          created_at,
          asset_code,
          id
        """,
        (version_group, primary["id"], primary["id"]),
    ).fetchall()
    source_rows = conn.execute(
        """
        select *
        from assets
        where asset_type = 'control'
          and (version_group = ? or id = ?)
        order by
          case when id = ? then 0 else 1 end,
          version_no,
          created_at,
          asset_code,
          id
        """,
        (source_group, asset["id"], asset["id"]),
    ).fetchall()
    ordered = []
    seen = set()
    for row in [*target_rows, *source_rows]:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        ordered.append(row)
    conn.execute(
        """
        update assets
        set version_group = ?,
            version_no = 1,
            version_parent_id = ''
        where id = ?
        """,
        (version_group, primary["id"]),
    )
    score = max(0.0, min(1.0, float(similarity_score)))
    for version_no, row in enumerate(
        (row for row in ordered if row["id"] != primary["id"]),
        start=2,
    ):
        from_source_group = (
            (row["version_group"] or row["id"]) == source_group
        )
        conn.execute(
            """
            update assets
            set version_group = ?,
                version_no = ?,
                version_parent_id = ?,
                similarity_score = ?,
                similarity_method = case
                  when ? then ?
                  else similarity_method
                end,
                updated_at = case when ? then ? else updated_at end
            where id = ?
            """,
            (
                version_group,
                version_no,
                primary["id"],
                score if from_source_group else row["similarity_score"],
                1 if from_source_group else 0,
                similarity_method,
                1 if from_source_group else 0,
                timestamp,
                row["id"],
            ),
        )
    return True
