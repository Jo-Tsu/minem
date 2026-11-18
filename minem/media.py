"""Media classification and legacy metadata decoding."""

import re


def split_tags(value):
    return [tag.strip() for tag in (value or "").split(",") if tag.strip()]


def image_traits(path, *, image_module=None, image_sequence_module=None):
    if image_module is None:
        return {}
    try:
        image = image_module.open(path)
        if getattr(image, "is_animated", False) and image_sequence_module is not None:
            image.seek(0)
        width, height = image.size
        has_alpha = image.mode in {"RGBA", "LA"} or ("transparency" in image.info)
        return {"width": width, "height": height, "has_alpha": has_alpha}
    except Exception:
        return {}


def resource_kind_for(path, media_kind, title="", tags="", *, image_module=None, image_sequence_module=None):
    if media_kind == "video":
        return "video"
    if media_kind == "gif":
        return "gif"
    text = " ".join([title or "", tags or "", path.name, path.as_posix()]).lower()
    basename = path.name.lower()
    logo_words = ("logo", "logotype", "brand", "mark", "商标", "品牌", "标志", "徽标")
    icon_words = ("icon", "icons", "favicon", "avatar", "badge", "图标", "头像", "按钮")
    if re.search(r"(^|[-_])icon([-_.]|$)", basename) or any(word in text for word in icon_words):
        return "icon"
    if any(word in text for word in logo_words):
        return "logo"
    if media_kind == "svg":
        return "icon"
    if media_kind == "image":
        traits = image_traits(path, image_module=image_module, image_sequence_module=image_sequence_module)
        width = traits.get("width") or 0
        height = traits.get("height") or 0
        has_alpha = traits.get("has_alpha")
        if width and height:
            max_side = max(width, height)
            min_side = min(width, height)
            ratio = max_side / min_side if min_side else 99
            if has_alpha and max_side <= 420 and ratio <= 4.5:
                return "logo" if ratio >= 2.1 else "icon"
            if max_side <= 160 and ratio <= 1.6:
                return "icon"
        return "image"
    return "other"
