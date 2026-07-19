"""Argument parser and v0 compatibility normalization."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import commands
from .contracts import CliError, EXIT_ARGUMENT


PAGE_ACTIONS = {"add", "replace", "move", "hide", "show", "remove"}
GLOBAL_VALUE_OPTIONS = {"--base-url", "--output", "--timeout", "--request-id"}
GLOBAL_FLAG_OPTIONS = {"--json", "--quiet", "--no-input"}


class MineMParser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError("INVALID_ARGUMENT", message, exit_code=EXIT_ARGUMENT)


def normalize_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    globals_before = []
    command = []
    warnings = []
    index = 0
    while index < len(argv):
        token = argv[index]
        option = token.split("=", 1)[0]
        if option in GLOBAL_FLAG_OPTIONS:
            globals_before.append(token)
        elif option in GLOBAL_VALUE_OPTIONS:
            globals_before.append(token)
            if "=" not in token:
                if index + 1 >= len(argv):
                    raise CliError("INVALID_ARGUMENT", f"{token} requires a value", exit_code=EXIT_ARGUMENT)
                index += 1
                globals_before.append(argv[index])
        else:
            command.append(token)
        index += 1

    if len(command) >= 2 and command[:2] == ["page", "create"]:
        command[1] = "import"
        warnings.append("page create is deprecated; use page import")
    if len(command) >= 2 and command[:2] == ["case", "create"]:
        command[1] = "import"
        warnings.append("case create is deprecated; use case import")
    if len(command) >= 3 and command[:2] == ["report", "page"] and command[2] not in PAGE_ACTIONS:
        report = command[2]
        if "--add" in command:
            position = command.index("--add")
            new_page, after = command[position + 1].split(":", 1)
            command = ["report", "page", "add", report, "--page", new_page, "--after", after] + [item for item in command[3:] if item not in {"--add", command[position + 1]}]
            warnings.append("report page --add is deprecated; use report page add")
        elif "--replace" in command:
            position = command.index("--replace")
            old_page, new_page = command[position + 1].split(":", 1)
            command = ["report", "page", "replace", report, "--page", old_page, "--with", new_page] + [item for item in command[3:] if item not in {"--replace", command[position + 1]}]
            warnings.append("report page --replace is deprecated; use report page replace")
    return [*globals_before, *command], warnings


def _add_import_options(parser, positional=True):
    if positional:
        parser.add_argument("source", nargs="?", help="HTML, ZIP, Markdown, or TXT source")
    parser.add_argument("--file", help=argparse.SUPPRESS)
    parser.add_argument("--name")
    parser.add_argument("--title", help=argparse.SUPPRESS)
    parser.add_argument("--description")
    parser.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)


def _add_mutation_options(parser):
    parser.add_argument("--dry-run", action="store_true", help="Preview the mutation without writing")
    parser.add_argument("--confirm", "--yes", dest="confirm", action="store_true", help="Confirm a formal data change")


def build_parser() -> MineMParser:
    parser = MineMParser(prog="minem", description="Create, manage, arrange, and export MineM presentation material.")
    parser.add_argument("--base-url", help="MineM server URL")
    parser.add_argument("--output", choices=("table", "json", "jsonl", "yaml"), help="Output format")
    parser.add_argument("--json", action="store_true", help="Alias for --output json")
    parser.add_argument("--quiet", action="store_true", help="Print only the primary identifier")
    parser.add_argument("--no-input", action="store_true", help="Disable browser opening and interactive behavior")
    parser.add_argument("--timeout", type=int, default=120, help="Network and task timeout in seconds")
    parser.add_argument("--request-id", help="Stable request identifier supplied by an Agent")
    resources = parser.add_subparsers(dest="resource", required=True)

    version = resources.add_parser("version", help="Show CLI and server versions")
    version.set_defaults(handler=commands.version, command_name="version")
    status = resources.add_parser("status", help="Show server and library status")
    status.set_defaults(handler=commands.status, command_name="status")
    doctor = resources.add_parser("doctor", help="Check configuration and API compatibility")
    doctor.set_defaults(handler=commands.doctor, command_name="doctor")

    config = resources.add_parser("config", help="Manage non-secret CLI configuration")
    config_actions = config.add_subparsers(dest="config_action", required=True)
    config_list = config_actions.add_parser("list")
    config_list.set_defaults(handler=commands.config_command, command_name="config.list")
    config_get = config_actions.add_parser("get")
    config_get.add_argument("key")
    config_get.set_defaults(handler=commands.config_command, command_name="config.get")
    config_set = config_actions.add_parser("set")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_set.set_defaults(handler=commands.config_command, command_name="config.set")
    config_unset = config_actions.add_parser("unset")
    config_unset.add_argument("key")
    config_unset.set_defaults(handler=commands.config_command, command_name="config.unset")

    completion = resources.add_parser("completion", help="Generate shell completion")
    completion.add_argument("shell", choices=("bash", "zsh", "fish"))
    completion.set_defaults(handler=commands.completion, command_name="completion")

    asset = resources.add_parser("asset", help="Query and manage all material assets")
    asset_actions = asset.add_subparsers(dest="asset_action", required=True)
    asset_list = asset_actions.add_parser("list")
    asset_list.add_argument("--type", choices=("all", "report", "page", "resource"), default="all")
    asset_list.add_argument("--query", "-q")
    asset_list.add_argument("--limit", type=int, default=30)
    asset_list.add_argument("--include-versions", action="store_true")
    asset_list.set_defaults(handler=commands.asset_list, command_name="asset.list")
    asset_search = asset_actions.add_parser("search")
    asset_search.add_argument("query")
    asset_search.add_argument("--type", choices=("all", "report", "page", "resource"), default="all")
    asset_search.add_argument("--limit", type=int, default=30)
    asset_search.add_argument("--include-versions", action="store_true")
    asset_search.set_defaults(handler=commands.asset_list, command_name="asset.search")
    for action, handler in (("get", commands.asset_get), ("open", commands.asset_open), ("versions", commands.asset_versions), ("lineage", commands.asset_lineage)):
        item = asset_actions.add_parser(action)
        item.add_argument("reference")
        item.add_argument("--type", choices=("report", "page", "resource"))
        if action == "open":
            item.add_argument("--print-only", action="store_true")
        item.set_defaults(handler=handler, command_name=f"asset.{action}")
    rename = asset_actions.add_parser("rename")
    rename.add_argument("reference")
    rename.add_argument("--name", required=True)
    rename.add_argument("--type", choices=("report", "page", "resource"))
    rename.set_defaults(handler=commands.asset_rename, command_name="asset.rename")
    delete = asset_actions.add_parser("delete")
    delete.add_argument("reference")
    delete.add_argument("--type", choices=("report", "page", "resource"))
    _add_mutation_options(delete)
    delete.set_defaults(handler=commands.asset_delete, command_name="asset.delete")

    importing = resources.add_parser("import", help="Import external report or page material")
    import_actions = importing.add_subparsers(dest="import_type", required=True)
    for name in ("report", "page"):
        item = import_actions.add_parser(name)
        _add_import_options(item)
        item.set_defaults(handler=lambda ctx, args, kind=name: commands.import_material(ctx, args, kind), command_name=f"import.{name}")

    page = resources.add_parser("page", help="Create and version reusable page material")
    page_actions = page.add_subparsers(dest="page_command", required=True)
    page_import = page_actions.add_parser("import", aliases=["create"])
    _add_import_options(page_import)
    page_import.set_defaults(handler=lambda ctx, args: commands.import_material(ctx, args, "page"), command_name="page.import")

    case = resources.add_parser("case", help="Import deterministic case page material")
    case_actions = case.add_subparsers(dest="case_command", required=True)
    case_import = case_actions.add_parser("import", aliases=["create"])
    _add_import_options(case_import)
    case_import.add_argument("--industry")
    case_import.set_defaults(handler=commands.case_import, command_name="case.import")

    task = resources.add_parser("task", help="Inspect asynchronous import tasks")
    task_actions = task.add_subparsers(dest="task_action", required=True)
    tasks = task_actions.add_parser("list")
    tasks.set_defaults(handler=commands.task_list, command_name="task.list")
    for action, handler in (("get", commands.task_get), ("wait", commands.task_wait)):
        item = task_actions.add_parser(action)
        item.add_argument("task_id")
        item.set_defaults(handler=handler, command_name=f"task.{action}")

    report = resources.add_parser("report", help="Create, inspect, arrange, and export reports")
    report_actions = report.add_subparsers(dest="report_action", required=True)
    report_create = report_actions.add_parser("create")
    report_create.add_argument("--name")
    report_create.add_argument("--title", help=argparse.SUPPRESS)
    report_create.add_argument("--page", action="append", default=[])
    report_create.add_argument("--controls", help=argparse.SUPPRESS)
    report_create.add_argument("--note")
    report_create.set_defaults(handler=commands.report_create, command_name="report.create")
    for action, handler in (("get", commands.report_get), ("pages", commands.report_pages), ("open", commands.report_open)):
        item = report_actions.add_parser(action)
        item.add_argument("report")
        if action == "open":
            item.add_argument("--print-only", action="store_true")
        item.set_defaults(handler=handler, command_name=f"report.{action}")
    export = report_actions.add_parser("export")
    export.add_argument("report")
    export.add_argument("--format", choices=("html", "pdf"), default="html")
    export.add_argument("--destination")
    export.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)
    export.set_defaults(handler=commands.report_export, command_name="report.export")

    report_page = report_actions.add_parser("page", help="Arrange pages without deleting source material")
    page_actions = report_page.add_subparsers(dest="page_action", required=True)
    add = page_actions.add_parser("add")
    add.add_argument("report")
    add.add_argument("--page", required=True)
    position = add.add_mutually_exclusive_group()
    position.add_argument("--after")
    position.add_argument("--before")
    _add_mutation_options(add)
    add.set_defaults(handler=commands.report_page_mutation, command_name="report.page.add")
    replace = page_actions.add_parser("replace")
    replace.add_argument("report")
    replace.add_argument("--page", required=True)
    replace.add_argument("--with", dest="with_page", required=True)
    _add_mutation_options(replace)
    replace.set_defaults(handler=commands.report_page_mutation, command_name="report.page.replace")
    move = page_actions.add_parser("move")
    move.add_argument("report")
    move.add_argument("--page", required=True)
    move_position = move.add_mutually_exclusive_group(required=True)
    move_position.add_argument("--after")
    move_position.add_argument("--before")
    _add_mutation_options(move)
    move.set_defaults(handler=commands.report_page_mutation, command_name="report.page.move")
    for action in ("hide", "show", "remove"):
        item = page_actions.add_parser(action)
        item.add_argument("report")
        item.add_argument("--page", required=True)
        _add_mutation_options(item)
        item.set_defaults(handler=commands.report_page_mutation, command_name=f"report.page.{action}")

    agent = resources.add_parser("agent", help="Discover machine-readable Agent capabilities")
    agent_actions = agent.add_subparsers(dest="agent_action", required=True)
    capabilities = agent_actions.add_parser("capabilities")
    capabilities.set_defaults(handler=commands.agent_capabilities, command_name="agent.capabilities")
    schema = agent_actions.add_parser("schema")
    schema.add_argument("name")
    schema.set_defaults(handler=commands.agent_schema, command_name="agent.schema")
    return parser
