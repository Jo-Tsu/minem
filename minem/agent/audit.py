import json
import time
from pathlib import Path


def append_audit(data_dir, event, payload):
    audit_dir = Path(data_dir) / "agent"
    audit_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "event": event,
        "createdAt": int(time.time() * 1000),
        "payload": payload,
    }
    path = audit_dir / "audit.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "path": str(path), "record": record}


def read_audit(data_dir, *, limit=50):
    path = Path(data_dir) / "agent" / "audit.jsonl"
    if not path.exists():
        return {"ok": True, "items": []}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return {"ok": False, "error": str(error), "items": []}
    items = []
    for line in lines[-limit:]:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"ok": True, "items": items}
