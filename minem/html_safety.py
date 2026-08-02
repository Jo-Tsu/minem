from __future__ import annotations

import json
from typing import Any


def json_for_html_script(value: Any, *, indent: int | None = None) -> str:
    dumped = json.dumps(value, ensure_ascii=False, indent=indent)
    return (
        dumped
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
