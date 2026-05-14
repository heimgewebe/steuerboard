from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .inventory import build_inventory
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
        required=True,
        help="Emit repo-inventory.v1 JSON.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "observe" and args.observe_command == "repo":
        observation = observe_repo(Path(args.path))
        print(json.dumps(observation, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "inventory":
        config_path = Path(args.config) if args.config else None
        try:
            inventory = build_inventory(config_path=config_path)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        print(json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    parser.error("unsupported command")
    return 2
