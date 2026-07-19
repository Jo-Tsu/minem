#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from minem.agent import AgentRuntime


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="MineM internal agent runtime.")
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="MineM project root")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze an engineering task")
    analyze.add_argument("task", help="Task text")
    analyze.add_argument("--focus", default="", help="Optional focus hint")

    repo_map = sub.add_parser("map", help="Build a source repo map")
    repo_map.add_argument("--focus", default="", help="Optional focus hint")

    validate = sub.add_parser("validate", help="Run whitelisted validations")
    validate.add_argument("--check", action="append", dest="checks", help="Validation check name")
    validate.add_argument("--base-url", default="http://127.0.0.1:8790", help="MineM server base URL")

    checkpoint = sub.add_parser("checkpoint", help="Record current git state")
    checkpoint.add_argument("--label", default="", help="Checkpoint label")
    checkpoint.add_argument("--task", default="", help="Related task")

    audit = sub.add_parser("audit", help="Read recent agent audit records")
    audit.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    root = Path(args.root).resolve()
    runtime = AgentRuntime(root, root / "data")

    if args.command == "analyze":
        print_json(runtime.analyze(args.task, focus=args.focus))
    elif args.command == "map":
        print_json(runtime.map(focus=args.focus))
    elif args.command == "validate":
        print_json(runtime.validate(checks=args.checks, base_url=args.base_url))
    elif args.command == "checkpoint":
        print_json(runtime.checkpoint(label=args.label, task=args.task))
    elif args.command == "audit":
        print_json(runtime.audit(limit=args.limit))


if __name__ == "__main__":
    main()
