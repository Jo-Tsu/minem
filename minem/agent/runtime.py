from pathlib import Path

from .audit import append_audit, read_audit
from .checkpoints import create_checkpoint
from .planner import analyze_task
from .repo_map import build_repo_map
from .validator import validate_change


class AgentRuntime:
    def __init__(self, root, data_dir):
        self.root = Path(root)
        self.data_dir = Path(data_dir)

    def map(self, *, focus=""):
        payload = {"ok": True, "map": build_repo_map(self.root, focus=focus)}
        append_audit(self.data_dir, "agent.map", {"focus": focus, "fileCount": payload["map"]["summary"]["fileCount"]})
        return payload

    def analyze(self, task, *, focus=""):
        payload = analyze_task(self.root, task, focus=focus)
        append_audit(self.data_dir, "agent.analyze", {
            "task": task,
            "capabilities": payload.get("matchedCapabilities", []),
            "risk": payload.get("risk", ""),
            "validations": payload.get("recommendedValidations", []),
        })
        return payload

    def checkpoint(self, *, label="", task=""):
        payload = create_checkpoint(self.root, self.data_dir, label=label, task=task)
        append_audit(self.data_dir, "agent.checkpoint", {"id": payload.get("id"), "label": label, "task": task})
        return payload

    def validate(self, *, checks=None, base_url="http://127.0.0.1:8790"):
        payload = validate_change(self.root, checks=checks, base_url=base_url)
        append_audit(self.data_dir, "agent.validate", {
            "checks": checks or ["python_compile"],
            "ok": payload.get("ok"),
        })
        return payload

    def audit(self, *, limit=50):
        return read_audit(self.data_dir, limit=limit)
