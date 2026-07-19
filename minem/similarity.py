import hashlib
import re


def hamming_distance(left, right):
    return (left ^ right).bit_count()


def dhash_image(path, hash_size=8, *, image_module=None, image_sequence_module=None):
    if image_module is None:
        return None
    try:
        image = image_module.open(path)
        if getattr(image, "is_animated", False) and image_sequence_module is not None:
            image.seek(0)
        image = image.convert("L").resize((hash_size + 1, hash_size), image_module.Resampling.LANCZOS)
        pixels = list(image.getdata())
        value = 0
        for row in range(hash_size):
            for col in range(hash_size):
                left = pixels[row * (hash_size + 1) + col]
                right = pixels[row * (hash_size + 1) + col + 1]
                value = (value << 1) | (1 if left > right else 0)
        width, height = image_module.open(path).size
        return {"hash": value, "width": width, "height": height}
    except Exception:
        return None


def normalized_svg_hash(path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return None
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([{}:;,<>/=])\s*", r"\1", text)
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()


def collect_similarity_features(conn, *, version_candidate_path, image_module=None, image_sequence_module=None):
    rows = conn.execute(
        """
        select * from assets
        where asset_type = 'resource'
          and media_kind in ('image', 'gif', 'svg')
        order by media_kind, created_at, asset_code
        """
    ).fetchall()
    features = []
    skipped = 0
    for row in rows:
        path = version_candidate_path(row)
        if not path:
            skipped += 1
            continue
        suffix = path.suffix.lower()
        if row["media_kind"] == "svg":
            svg_hash = normalized_svg_hash(path)
            if not svg_hash:
                skipped += 1
                continue
            features.append({"row": row, "path": path, "kind": "svg", "suffix": suffix, "svg_hash": svg_hash})
            continue
        digest = dhash_image(path, image_module=image_module, image_sequence_module=image_sequence_module)
        if not digest:
            skipped += 1
            continue
        features.append({"row": row, "path": path, "kind": row["media_kind"], "suffix": suffix, **digest})
    return features, skipped


def same_shape(left, right):
    lw, lh = left["width"], left["height"]
    rw, rh = right["width"], right["height"]
    if not lw or not lh or not rw or not rh:
        return False
    ratio_delta = abs((lw / lh) - (rw / rh))
    area_left = lw * lh
    area_right = rw * rh
    area_ratio = min(area_left, area_right) / max(area_left, area_right)
    return ratio_delta <= 0.03 and area_ratio >= 0.72


def normalized_stem(path):
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return stem


def same_named_scale_variant(left, right):
    if left["hash"] != right["hash"]:
        return False
    lw, lh = left["width"], left["height"]
    rw, rh = right["width"], right["height"]
    if not lw or not lh or not rw or not rh:
        return False
    ratio_delta = abs((lw / lh) - (rw / rh))
    if ratio_delta > 0.03:
        return False
    left_stem = normalized_stem(left["path"])
    right_stem = normalized_stem(right["path"])
    return bool(left_stem and left_stem == right_stem)


def similarity_for(left, right):
    if left["kind"] != right["kind"]:
        return None
    if left["kind"] == "svg":
        if left["svg_hash"] == right["svg_hash"]:
            return 1.0, "svg-normalized"
        return None
    if same_named_scale_variant(left, right):
        return 1.0, "dhash64-scaled-name"
    if not same_shape(left, right):
        return None
    distance = hamming_distance(left["hash"], right["hash"])
    score = 1 - (distance / 64)
    if distance <= 4:
        return score, "dhash64"
    return None


def build_similarity_groups(features):
    consumed = set()
    groups = []
    for index, feature in enumerate(features):
        asset_id = feature["row"]["id"]
        if asset_id in consumed:
            continue
        group = [feature]
        consumed.add(asset_id)
        for other in features[index + 1:]:
            other_id = other["row"]["id"]
            if other_id in consumed:
                continue
            result = similarity_for(feature, other)
            if not result:
                continue
            score, method = result
            other["score"] = score
            other["method"] = method
            group.append(other)
            consumed.add(other_id)
        if len(group) > 1:
            groups.append(group)
    return groups


def apply_similarity_versions(conn, groups):
    merged_assets = 0
    for group in groups:
        group.sort(key=lambda item: (item["row"]["created_at"], item["row"]["asset_code"]))
        primary = group[0]["row"]
        primary_id = primary["id"]
        conn.execute(
            """
            update assets
            set version_group = ?, version_no = 1, version_parent_id = '', similarity_score = 1.0, similarity_method = ?
            where id = ?
            """,
            (primary_id, group[0].get("method", "primary"), primary_id),
        )
        for index, item in enumerate(group[1:], start=2):
            row = item["row"]
            conn.execute(
                """
                update assets
                set version_group = ?, version_no = ?, version_parent_id = ?, similarity_score = ?, similarity_method = ?
                where id = ?
                """,
                (primary_id, index, primary_id, item.get("score", 1.0), item.get("method", "similar"), row["id"]),
            )
            merged_assets += 1
    return merged_assets


def merge_similar_resource_versions(
    *,
    connect,
    reset_asset_versions,
    version_candidate_path,
    image_module=None,
    image_sequence_module=None,
):
    with connect() as conn:
        reset_asset_versions(conn, "resource")
        features, skipped = collect_similarity_features(
            conn,
            version_candidate_path=version_candidate_path,
            image_module=image_module,
            image_sequence_module=image_sequence_module,
        )
        groups = build_similarity_groups(features)
        merged_assets = apply_similarity_versions(conn, groups)
    return {
        "ok": True,
        "scanned": len(features),
        "skipped": skipped,
        "groups": len(groups),
        "mergedAssets": merged_assets,
        "rule": "resource images/gifs/svg only; dHash distance <= 4; similar aspect and area",
    }
