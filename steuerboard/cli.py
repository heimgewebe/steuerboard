from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .action_plans import plan_switch_main
from .assessment import assess_repo
from .assessment_explanations import explain_assessment
from .inventory import build_duplicates_report, build_inventory, explain_scope
from .observation import observe_repo
from .omnipull_reports import load_omnipull_report


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

    assess_parser = subparsers.add_parser("assess", help="Read-only assessment commands.")
    assess_subparsers = assess_parser.add_subparsers(dest="assess_command", required=True)

    assess_repo_parser = assess_subparsers.add_parser(
        "repo",
        help="Derive a read-only assessment for one local repository.",
    )
    assess_repo_parser.add_argument("path", help="Repository path to assess.")
    assess_repo_parser.add_argument(
        "--config",
        help=(
            "Path to local-config.v1 JSON for scope classification. Defaults to "
            "$XDG_CONFIG_HOME/steuerboard/local-config.json, falling back to the checkout example."
        ),
    )
    assess_repo_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit repo-assessment.v1 JSON.",
    )

    assess_explain_parser = assess_subparsers.add_parser(
        "explain",
        help="Explain a repo-assessment JSON object without planning actions.",
    )
    assess_explain_parser.add_argument(
        "assessment_json",
        help="Path to a repo-assessment.v1 JSON file.",
    )
    assess_explain_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit repo-assessment-explanation.v1 JSON.",
    )

    plan_parser = subparsers.add_parser("plan", help="Read-only plan preview commands.")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)

    plan_switch_main_parser = plan_subparsers.add_parser(
        "switch-main",
        help="Derive an action-plan preview from a repo-assessment JSON file.",
    )
    plan_switch_main_parser.add_argument(
        "assessment_json",
        help="Path to a repo-assessment.v1 JSON file.",
    )
    plan_switch_main_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit action-plan.v1 JSON.",
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

    omnipull_report_parser = subparsers.add_parser(
        "omnipull-report",
        help="Read-only omnipull report artifact commands.",
    )
    omnipull_report_subparsers = omnipull_report_parser.add_subparsers(
        dest="omnipull_report_command",
        required=True,
    )

    omnipull_report_show_parser = omnipull_report_subparsers.add_parser(
        "show",
        help="Load and validate one omnipull-report.v1 JSON artifact.",
    )
    omnipull_report_show_parser.add_argument(
        "report_json",
        help="Path to an omnipull-report.v1 JSON file.",
    )
    omnipull_report_show_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit omnipull-report.v1 JSON.",
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

    if args.command == "assess" and args.assess_command == "repo":
        config_path = Path(args.config) if args.config else None
        assessment = assess_repo(Path(args.path), config_path=config_path)
        print(json.dumps(assessment, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "assess" and args.assess_command == "explain":
        try:
            with Path(args.assessment_json).open("r", encoding="utf-8") as handle:
                assessment = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"invalid assessment JSON: {exc}")

        try:
            explanation = explain_assessment(assessment)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(explanation, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "plan" and args.plan_command == "switch-main":
        try:
            with Path(args.assessment_json).open("r", encoding="utf-8") as handle:
                assessment = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"invalid assessment JSON: {exc}")

        try:
            plan = plan_switch_main(assessment)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "scope" and args.scope_command == "explain":
        config_path = Path(args.config) if args.config else None
        try:
            explanation = explain_scope(Path(args.path), config_path=config_path)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        print(json.dumps(explanation, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "omnipull-report" and args.omnipull_report_command == "show":
        try:
            report = load_omnipull_report(
                Path(args.report_json), source_path_ref=args.report_json
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    parser.error("unsupported command")
    return 2
