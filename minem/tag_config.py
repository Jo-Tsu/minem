"""Load tag rules and classification config from external JSON file."""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent / "tag_rules.json"
_LOADED = None


def _load():
    global _LOADED
    if _LOADED is not None:
        return _LOADED
    try:
        _LOADED = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOADED = {}
    return _LOADED


def categories():
    return _load().get("categories", {})


def tag_rules():
    raw = _load().get("tag_rules", [])
    return [(item["label"], item["keywords"]) for item in raw]


def asset_types():
    return _load().get("asset_types", {})


def pipeline_stages():
    return _load().get("pipeline_stages", [])


def media_kinds():
    return _load().get("media_kinds", {})


def resource_kinds():
    return _load().get("resource_kinds", {})


def page_roles():
    return _load().get("page_roles", {})


def source_types():
    return _load().get("source_types", {})


def material_tag_taxonomy():
    return _load().get("material_tag_taxonomy", {})


def company_name_rules():
    raw = _load().get("company_name_rules", [])
    return [
        (tuple(item["aliases"]), item["display_name"], item["logo_tag"])
        for item in raw
    ]


def reload():
    """Force reload from disk (useful for tests or runtime config changes)."""
    global _LOADED
    _LOADED = None
    return _load()
