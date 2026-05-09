from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "observe" and args.observe_command == "repo":
        observation = observe_repo(Path(args.path))
        print(json.dumps(observation, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    parser.error("unsupported command")
    return 2
