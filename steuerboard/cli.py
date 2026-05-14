from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .inventory import build_duplicates_report, build_inventory, explain_scope
from .observation import observe_repo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="steuerboard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    observe_parser = subparsers.add_parser("observe", help="Read-only observation commands.")
    observe_subparsers = observe_parser.add_subparsers(dest="observe_command", required=True)

    observe_repo_parser = observe_subparsers.add_parser(
        "repo",
        help="Observe one local repository path without mutating it.",
    )
    observe_repo_parser.add_argument("path", help="Repository path to observe.")
    observe_repo_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit repo-observation.v1 JSON.",
    )

    inventory_parser = subparsers.add_parser(
        "inventory",
        help="Read-only inventory and local scope classification.",
    )
    inventory_subparsers = inventory_parser.add_subparsers(dest="inventory_command", required=False)

    inventory_parser.add_argument(
        "--config",
        help=(
            "Path to local-config.v1 JSON. Defaults to "
            "$XDG_CONFIG_HOME/steuerboard/local-config.json, falling back to the checkout example."
        ),
    )
    inventory_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit repo-inventory.v1 JSON.",
    )

    duplicates_parser = inventory_subparsers.add_parser(
        "duplicates",
        help="Emit read-only duplicate repository groups.",
    )
    duplicates_parser.add_argument(
        "--config",
        default=argparse.SUPPRESS,
        help=(
            "Path to local-config.v1 JSON. Defaults to "
            "$XDG_CONFIG_HOME/steuerboard/local-config.json, falling back to the checkout example."
        ),
    )
    duplicates_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit repo-duplicates.v1 JSON.",
    )

    scope_parser = subparsers.add_parser("scope", help="Read-only scope explanation commands.")
    scope_subparsers = scope_parser.add_subparsers(dest="scope_command", required=True)

    explain_parser = scope_subparsers.add_parser(
        "explain",
        help="Explain the local scope classification for one path.",
    )
    explain_parser.add_argument("path", help="Path to classify.")
    explain_parser.add_argument(
        "--config",
        help=(
            "Path to local-config.v1 JSON. Defaults to "
            "$XDG_CONFIG_HOME/steuerboard/local-config.json, falling back to the checkout example."
        ),
    )
    explain_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit scope-explanation.v1 JSON.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "observe" and args.observe_command == "repo":
        observation = observe_repo(Path(args.path))
        print(json.dumps(observation, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "inventory" and args.inventory_command == "duplicates":
        config_path = Path(args.config) if args.config else None
        try:
            duplicates = build_duplicates_report(config_path=config_path)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        print(json.dumps(duplicates, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "inventory":
        if not args.json:
            parser.error("the following arguments are required: --json")
        config_path = Path(args.config) if args.config else None
        try:
            inventory = build_inventory(config_path=config_path)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        print(json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "scope" and args.scope_command == "explain":
        config_path = Path(args.config) if args.config else None
        try:
            explanation = explain_scope(Path(args.path), config_path=config_path)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        print(json.dumps(explanation, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    parser.error("unsupported command")
    return 2
