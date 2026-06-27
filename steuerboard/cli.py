from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .action_approval_validations import validate_action_approval_binding
from .action_execution_readiness import validate_execution_readiness
from .action_git_pull import run_git_pull_ff_only
from .action_plans import plan_git_pull_ff_only, plan_switch_main
from .action_preflight_bindings import bind_preflight_to_action
from .action_runs import run_read_only_action
from .action_switch_main import run_switch_main
from .action_switch_main_readiness import validate_switch_main_readiness
from .assessment import assess_repo
from .run_evidence_chains import validate_run_evidence_chain
from .run_postchecks import run_read_only_postcheck
from .assessment_explanations import explain_assessment
from .inventory import (
    build_duplicates_report,
    build_favorites_report,
    build_inventory,
    explain_scope,
)
from .observation import observe_repo
from .omnipull_reports import load_omnipull_report
from .omnipull_run_indexes import load_omnipull_run_index, select_latest_report
from .recent_problem_repos import build_recent_problem_repos
from .remote_refresh import run_fetch_origin_prune
from .runbooks import run_runbook


def _sanitize_sentinel_reason(reason: str | object) -> str:
    """Sanitize a reason for use in a sentinel artifact.

    Converts multi-line or whitespace-heavy strings into single-line,
    compact form to comply with schema pattern ^\S(?:.*\S)?$.

    Parameters
    ----------
    reason
        Raw reason (string or any object; will be converted to string).
        May contain newlines or excess whitespace.

    Returns
    -------
    str
        Single-line, whitespace-collapsed string.
        If empty after sanitization, returns "unknown_error".
    """
    # Convert to string if needed
    reason_str = str(reason) if not isinstance(reason, str) else reason
    # Collapse all whitespace/newlines into single space
    sanitized = " ".join(reason_str.split())
    # If empty, return placeholder
    return sanitized if sanitized else "unknown_error"


def _emit_readiness_inconclusive(
    reason: str,
    *,
    action_plan_path: str,
    approval_validation_path: str,
    run_evidence_chain_path: str,
) -> int:
    now = datetime.now(timezone.utc)
    checked_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sanitized_reason = _sanitize_sentinel_reason(reason)
    print(
        json.dumps(
            {
                "schema_version": "action-execution-readiness.v1",
                "readiness_id": "readiness-blocked-precondition",
                "checked_at": checked_at,
                "action": "unknown",
                "plan_ref": "unknown",
                "approval_validation_ref": "unknown",
                "chain_ref": "unknown",
                "status": "inconclusive",
                "blocked_because": [],
                "failure_reasons": [sanitized_reason],
                "checks": [
                    {
                        "check": "preconditions_satisfied",
                        "passed": False,
                        "actual": sanitized_reason,
                    }
                ],
                "source_refs": [
                    "action-plan.v1",
                    "action-approval-validation.v1",
                    "run-evidence-chain.v1",
                ],
                "boundary": {
                    "does_not_execute": True,
                    "does_not_mutate": True,
                    "does_not_authorise_actions": True,
                },
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1


def _emit_chain_inconclusive(
    reason: str,
    *,
    action_plan_path: str,
    command_trace_path: str,
    run_result_path: str,
    run_postcheck_path: str,
) -> int:
    now = datetime.now(timezone.utc)
    checked_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    print(
        json.dumps(
            {
                "schema_version": "run-evidence-chain.v1",
                "chain_id": "chain-blocked-precondition",
                "checked_at": checked_at,
                "status": "inconclusive",
                "action": "git-status-read-only",
                "plan_ref": "unknown",
                "trace_ref": "unknown",
                "run_result_ref": "unknown",
                "postcheck_ref": "unknown",
                "run_id": "unknown",
                "evidence_paths": [
                    str(Path(action_plan_path).expanduser().resolve(strict=False)),
                    str(Path(command_trace_path).expanduser().resolve(strict=False)),
                    str(Path(run_result_path).expanduser().resolve(strict=False)),
                    str(Path(run_postcheck_path).expanduser().resolve(strict=False)),
                ],
                "source_refs": [
                    "action-plan.v1",
                    "command-trace.v1",
                    "run-result.v1",
                    "run-postcheck.v1",
                ],
                "checks": [
                    {
                        "check": "preconditions_satisfied",
                        "passed": False,
                        "actual": reason,
                    }
                ],
                "failure_reasons": [reason],
                "redaction_verified": False,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1


def _emit_preflight_binding_inconclusive(reason: str) -> int:
    now = datetime.now(timezone.utc)
    checked_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sanitized_reason = _sanitize_sentinel_reason(reason)
    print(
        json.dumps(
            {
                "schema_version": "action-preflight-binding.v1",
                "binding_id": "preflight-binding-blocked-precondition",
                "checked_at": checked_at,
                "plan_ref": "unknown",
                "plan_action": "unknown",
                "chain_ref": "unknown",
                "chain_action": "unknown",
                "binding_state": "binding_inconclusive",
                "blocked_because": [],
                "failure_reasons": [sanitized_reason],
                "checks": [
                    {
                        "check": "preconditions_satisfied",
                        "passed": False,
                        "actual": sanitized_reason,
                    }
                ],
                "source_refs": [
                    "action-plan.v1",
                    "run-evidence-chain.v1",
                ],
                "boundary": {
                    "does_not_execute": True,
                    "does_not_mutate": True,
                    "does_not_authorise_actions": True,
                },
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1


def _emit_switch_main_readiness_inconclusive(reason: str) -> int:
    """Emit a switch-main-readiness.v1 'inconclusive' sentinel for a precondition failure.

    No output file is written; the sentinel is emitted to stdout only and the
    process exits non-zero. Phase 9A is non-mutating: this never switches a
    branch, never authorises, and never executes.
    """
    now = datetime.now(timezone.utc)
    checked_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sanitized_reason = _sanitize_sentinel_reason(reason)
    print(
        json.dumps(
            {
                "schema_version": "switch-main-readiness.v1",
                "readiness_id": "switch-main-readiness-blocked-precondition",
                "checked_at": checked_at,
                "action": "switch-main",
                "plan_ref": "unknown",
                "proof_ref": "unknown",
                "status": "inconclusive",
                "blocked_because": [],
                "failure_reasons": [sanitized_reason],
                "checks": [
                    {
                        "check": "preconditions_satisfied",
                        "passed": False,
                        "actual": sanitized_reason,
                    }
                ],
                "source_refs": [
                    "action-plan.v1",
                    "switch-main-preflight-proof.v1",
                ],
                "boundary": {
                    "does_not_execute": True,
                    "does_not_mutate": True,
                    "does_not_authorise_actions": True,
                },
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1


def _emit_pull_blocked(reason: str) -> int:
    """Emit a run-result.v1 'blocked' sentinel for a git-pull precondition failure.

    No output files are written and no Git mutation occurs; the sentinel is
    emitted to stdout only.
    """
    sanitized_reason = _sanitize_sentinel_reason(reason)
    print(
        json.dumps(
            {
                "schema_version": "run-result.v1",
                "run_id": "run-git-pull-ff-only-blocked-precondition",
                "action": "git-pull-ff-only",
                "status": "blocked",
                "redaction_verified": True,
                "blocked_reasons": [sanitized_reason],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1


def _emit_switch_main_blocked(reason: str) -> int:
    """Emit a run-result.v1 'blocked' sentinel for a switch-main precondition failure.

    No output files are written and no Git mutation occurs; the sentinel is
    emitted to stdout only.
    """
    sanitized_reason = _sanitize_sentinel_reason(reason)
    print(
        json.dumps(
            {
                "schema_version": "run-result.v1",
                "run_id": "run-switch-main-blocked-precondition",
                "action": "switch-main",
                "status": "blocked",
                "redaction_verified": True,
                "blocked_reasons": [sanitized_reason],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1


def _emit_postcheck_inconclusive(reason: str) -> int:
    now = datetime.now(timezone.utc)
    checked_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    print(
        json.dumps(
            {
                "schema_version": "run-postcheck.v1",
                "postcheck_id": "postcheck-blocked-precondition",
                "run_id": "unknown",
                "trace_ref": "unknown",
                "run_result_ref": "unknown",
                "action": "git-status-read-only",
                "repo_toplevel": "unknown",
                "checked_at": checked_at,
                "status": "inconclusive",
                "observations": [],
                "redaction_verified": False,
                "failure_reasons": [reason],
                "source_refs": [],
                "evidence_paths": [],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1


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
    inventory_json_action = inventory_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit repo-inventory.v1 JSON.",
    )
    inventory_json_action.surface_required = True

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

    favorites_parser = inventory_subparsers.add_parser(
        "favorites",
        help="Join configured repository favorites with the read-only inventory.",
    )
    favorites_parser.add_argument(
        "--config",
        default=argparse.SUPPRESS,
        help=(
            "Path to local-config.v1 JSON. Defaults to "
            "$XDG_CONFIG_HOME/steuerboard/local-config.json, falling back to the checkout example."
        ),
    )
    favorites_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit repo-favorites.v1 JSON.",
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

    plan_git_pull_ff_only_parser = plan_subparsers.add_parser(
        "git-pull-ff-only",
        help="Derive a preview-only git-pull-ff-only plan from a repo-assessment JSON file.",
    )
    plan_git_pull_ff_only_parser.add_argument(
        "assessment_json",
        help="Path to a repo-assessment.v1 JSON file.",
    )
    plan_git_pull_ff_only_parser.add_argument(
        "--remote-refresh-result",
        help="Path to an optional remote-refresh-result.v1 JSON file for remote freshness evidence.",
    )
    plan_git_pull_ff_only_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit action-plan.v1 JSON.",
    )

    remote_refresh_parser = subparsers.add_parser(
        "remote-refresh",
        help="Bounded Stage-B remote refresh evidence commands.",
    )
    remote_refresh_subparsers = remote_refresh_parser.add_subparsers(
        dest="remote_refresh_command",
        required=True,
    )

    fetch_origin_prune_parser = remote_refresh_subparsers.add_parser(
        "fetch-origin-prune",
        help=(
            "Run exactly one bounded command (git fetch origin --prune), "
            "write command-trace.v1, and emit remote-refresh-result.v1 JSON."
        ),
    )
    fetch_origin_prune_parser.add_argument(
        "repo_path",
        help="Explicit repository path to refresh.",
    )
    fetch_origin_prune_parser.add_argument(
        "--config",
        required=True,
        help="Path to local-config.v1 JSON for canonical scope gating.",
    )
    fetch_origin_prune_parser.add_argument(
        "--assessment-id",
        required=True,
        help="Assessment id used to bind repo_ref as repo-<assessment-id>.",
    )
    fetch_origin_prune_parser.add_argument(
        "--command-trace-out",
        required=True,
        help="Path for command-trace.v1 output. Must not already exist.",
    )
    fetch_origin_prune_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit remote-refresh-result.v1 JSON.",
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

    omnipull_report_latest_parser = omnipull_report_subparsers.add_parser(
        "latest",
        help=(
            "Select the latest omnipull-report reference from one explicit "
            "omnipull-run-index.v1 JSON artifact."
        ),
    )
    omnipull_report_latest_parser.add_argument(
        "run_index_json",
        help="Path to an omnipull-run-index.v1 JSON file.",
    )
    omnipull_report_latest_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit omnipull-report-ref.v1 JSON.",
    )

    omnipull_report_recent_problems_parser = omnipull_report_subparsers.add_parser(
        "recent-problems",
        help=(
            "Select the latest problem occurrence per repository from explicit "
            "omnipull-report.v1 artifacts."
        ),
    )
    omnipull_report_recent_problems_parser.add_argument(
        "report_json",
        nargs="+",
        help="One or more explicit omnipull-report.v1 JSON artifact paths.",
    )
    omnipull_report_recent_problems_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum repositories to return (1..100; default: 20).",
    )
    omnipull_report_recent_problems_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit recent-problem-repos.v1 JSON.",
    )

    action_parser = subparsers.add_parser(
        "action",
        help="Bounded action runner commands.",
    )
    action_subparsers = action_parser.add_subparsers(dest="action_command", required=True)

    action_run_read_only_parser = action_subparsers.add_parser(
        "run-read-only",
        help=(
            "Execute a single bounded read-only action from an action-plan.v1 artifact. "
            "Writes command-trace.v1 and run-result.v1. "
            "No mutation, no pull, no branch switch, no free shell."
        ),
    )
    action_run_read_only_parser.add_argument(
        "action_plan_json",
        help="Path to an action-plan.v1 JSON file.",
    )
    action_run_read_only_parser.add_argument(
        "--repo-path",
        required=True,
        help="Explicit path to the local git repository to operate on.",
    )
    action_run_read_only_parser.add_argument(
        "--command-trace-out",
        required=True,
        help="Output path for command-trace.v1 JSON. Must not already exist.",
    )
    action_run_read_only_parser.add_argument(
        "--run-result-out",
        required=True,
        help="Output path for run-result.v1 JSON. Must not already exist.",
    )
    action_run_read_only_parser.add_argument(
        "--preflight-for-action-plan",
        required=False,
        default=None,
        help=(
            "Optional Phase 8D.2 path to an action-plan.v1 JSON file for a "
            "git-pull-ff-only plan. When supplied, embeds contract-defined "
            "proof material (plan_ref, plan_action, plan_content_sha256) into "
            "the emitted run-result.v1 so downstream binding can prove this "
            "read-only run was produced as preflight for that exact pull plan. "
            "Does not change the executed command or action."
        ),
    )
    action_run_read_only_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit run-result.v1 JSON.",
    )

    action_postcheck_read_only_parser = action_subparsers.add_parser(
        "postcheck-read-only",
        help=(
            "Run a bounded read-only postcheck against a prior git-status-read-only run. "
            "Validates command-trace.v1 and run-result.v1, re-runs git status, "
            "and writes a run-postcheck.v1 artifact. "
            "No mutation, no pull, no fetch, no free shell."
        ),
    )
    action_postcheck_read_only_parser.add_argument(
        "run_result_json",
        help="Path to the run-result.v1 JSON file from the prior run.",
    )
    action_postcheck_read_only_parser.add_argument(
        "--command-trace",
        required=True,
        help="Path to the command-trace.v1 JSON file from the prior run.",
    )
    action_postcheck_read_only_parser.add_argument(
        "--repo-path",
        required=True,
        help="Explicit path to the local git repository to postcheck.",
    )
    action_postcheck_read_only_parser.add_argument(
        "--postcheck-out",
        required=True,
        help="Output path for run-postcheck.v1 JSON. Must not already exist.",
    )
    action_postcheck_read_only_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit run-postcheck.v1 JSON.",
    )

    action_validate_run_chain_parser = action_subparsers.add_parser(
        "validate-run-chain",
        help=(
            "Validate one read-only evidence chain from action-plan.v1, command-trace.v1, "
            "run-result.v1, and run-postcheck.v1. Writes run-evidence-chain.v1. "
            "No execution, no pull, no fetch, no free shell."
        ),
    )
    action_validate_run_chain_parser.add_argument(
        "action_plan_json",
        help="Path to an action-plan.v1 JSON file.",
    )
    action_validate_run_chain_parser.add_argument(
        "--command-trace",
        required=True,
        help="Path to the command-trace.v1 JSON file for the run.",
    )
    action_validate_run_chain_parser.add_argument(
        "--run-result",
        required=True,
        help="Path to the run-result.v1 JSON file for the run.",
    )
    action_validate_run_chain_parser.add_argument(
        "--run-postcheck",
        required=True,
        help="Path to the run-postcheck.v1 JSON file for the run.",
    )
    action_validate_run_chain_parser.add_argument(
        "--chain-out",
        required=True,
        help="Output path for run-evidence-chain.v1 JSON. Must not already exist.",
    )
    action_validate_run_chain_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit run-evidence-chain.v1 JSON.",
    )

    action_validate_execution_readiness_parser = action_subparsers.add_parser(
        "validate-execution-readiness",
        help=(
            "Validate Stage-D execution readiness from action-plan.v1, "
            "action-approval-validation.v1, and run-evidence-chain.v1. "
            "Writes action-execution-readiness.v1. "
            "No execution, no pull, no fetch, no free shell. "
            "Phase 8D.0 — pure readiness assessment artifact only."
        ),
    )
    action_validate_execution_readiness_parser.add_argument(
        "action_plan_json",
        help="Path to an action-plan.v1 JSON file.",
    )
    action_validate_execution_readiness_parser.add_argument(
        "--approval-validation",
        required=True,
        help="Path to an action-approval-validation.v1 JSON file.",
    )
    action_validate_execution_readiness_parser.add_argument(
        "--run-evidence-chain",
        required=True,
        help="Path to a run-evidence-chain.v1 JSON file.",
    )
    action_validate_execution_readiness_parser.add_argument(
        "--readiness-out",
        required=True,
        help="Output path for action-execution-readiness.v1 JSON. Must not already exist.",
    )
    action_validate_execution_readiness_parser.add_argument(
        "--preflight-binding",
        required=False,
        default=None,
        help=(
            "Optional Phase 8D.1/8D.2 action-preflight-binding.v1 JSON file. "
            "When supplied, the binding artifact is consistency-checked and recorded. "
            "Phase 8D.2: when the binding carries a preflight_for_action_plan proof "
            "object whose plan_ref, plan_action, and plan_content_sha256 match the "
            "supplied action plan, binding_valid elevates the binding gate to proven "
            "and readiness can reach 'ready'. Without matching proof, readiness "
            "remains inconclusive."
        ),
    )
    action_validate_execution_readiness_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit action-execution-readiness.v1 JSON.",
    )

    action_bind_preflight_parser = action_subparsers.add_parser(
        "bind-preflight-to-action",
        help=(
            "Bind one git-pull-ff-only action-plan.v1 to one git-status-read-only "
            "run-evidence-chain.v1 as a Phase 8D.1 action-preflight-binding.v1 artifact. "
            "Pure artifact validation only — no execution, no mutation, no authorisation."
        ),
    )
    action_bind_preflight_parser.add_argument(
        "action_plan_json",
        help="Path to an action-plan.v1 JSON file (git-pull-ff-only).",
    )
    action_bind_preflight_parser.add_argument(
        "--run-evidence-chain",
        required=True,
        help="Path to a run-evidence-chain.v1 JSON file (git-status-read-only).",
    )
    action_bind_preflight_parser.add_argument(
        "--binding-out",
        required=True,
        help="Output path for action-preflight-binding.v1 JSON. Must not already exist.",
    )
    action_bind_preflight_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit action-preflight-binding.v1 JSON.",
    )

    action_validate_switch_main_readiness_parser = action_subparsers.add_parser(
        "validate-switch-main-readiness",
        help=(
            "Validate Phase 9A switch-main readiness from a switch-main action-plan.v1 "
            "and a switch-main-preflight-proof.v1. Writes switch-main-readiness.v1. "
            "Pure artifact validation only — no execution, no branch switch, no "
            "mutation, no authorisation. Proof that a later switch could be "
            "evaluated, never permission to switch."
        ),
    )
    action_validate_switch_main_readiness_parser.add_argument(
        "action_plan_json",
        help="Path to an action-plan.v1 JSON file (action must be switch-main).",
    )
    action_validate_switch_main_readiness_parser.add_argument(
        "--preflight-proof",
        required=True,
        help="Path to a switch-main-preflight-proof.v1 JSON file.",
    )
    action_validate_switch_main_readiness_parser.add_argument(
        "--readiness-out",
        required=True,
        help="Output path for switch-main-readiness.v1 JSON. Must not already exist.",
    )
    action_validate_switch_main_readiness_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit switch-main-readiness.v1 JSON.",
    )

    action_run_git_pull_ff_only_parser = action_subparsers.add_parser(
        "run-git-pull-ff-only",
        help=(
            "Execute a Stage-D approved git-pull-ff-only action. "
            "Requires a valid readiness gate reproduced from action-plan.v1, "
            "action-approval-validation.v1, run-evidence-chain.v1, and "
            "action-preflight-binding.v1. "
            "Writes command-trace.v1, run-result.v1, and run-postcheck.v1. "
            "No free shell. Exactly one fast-forward pull."
        ),
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "action_plan_json",
        help="Path to an action-plan.v1 JSON file (action must be git-pull-ff-only).",
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "--approval-validation",
        required=True,
        help="Path to an action-approval-validation.v1 JSON file.",
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "--run-evidence-chain",
        required=True,
        help="Path to a run-evidence-chain.v1 JSON file.",
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "--preflight-binding",
        required=True,
        help="Path to an action-preflight-binding.v1 JSON file.",
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "--repo-path",
        required=True,
        help="Explicit path to the local git repository to pull in.",
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "--command-trace-out",
        required=True,
        help="Output path for command-trace.v1 JSON. Must not already exist.",
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "--run-result-out",
        required=True,
        help="Output path for run-result.v1 JSON. Must not already exist.",
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "--postcheck-out",
        required=True,
        help="Output path for run-postcheck.v1 JSON. Must not already exist.",
    )
    action_run_git_pull_ff_only_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit run-result.v1 JSON.",
    )

    action_run_switch_main_parser = action_subparsers.add_parser(
        "run-switch-main",
        help=(
            "Execute a Stage-D approved switch-main action. "
            "Requires a ready switch-main-readiness.v1 verdict and a binding-valid "
            "action-approval-validation.v1, both pinned to the supplied "
            "action-plan.v1. Re-derives the mutation-critical live state and then "
            "performs exactly one bounded branch switch to main. "
            "Writes command-trace.v1, run-result.v1, and run-postcheck.v1. "
            "No free shell. No fetch, pull, merge, rebase, reset, clean, or checkout."
        ),
    )
    action_run_switch_main_parser.add_argument(
        "action_plan_json",
        help="Path to an action-plan.v1 JSON file (action must be switch-main).",
    )
    action_run_switch_main_parser.add_argument(
        "--approval-validation",
        required=True,
        help="Path to an action-approval-validation.v1 JSON file (binding_valid, switch-main).",
    )
    action_run_switch_main_parser.add_argument(
        "--switch-main-readiness",
        required=True,
        help="Path to a ready switch-main-readiness.v1 JSON file for the same plan.",
    )
    action_run_switch_main_parser.add_argument(
        "--repo-path",
        required=True,
        help="Explicit path to the local git repository to switch in.",
    )
    action_run_switch_main_parser.add_argument(
        "--command-trace-out",
        required=True,
        help="Output path for command-trace.v1 JSON. Must not already exist.",
    )
    action_run_switch_main_parser.add_argument(
        "--run-result-out",
        required=True,
        help="Output path for run-result.v1 JSON. Must not already exist.",
    )
    action_run_switch_main_parser.add_argument(
        "--postcheck-out",
        required=True,
        help="Output path for run-postcheck.v1 JSON. Must not already exist.",
    )
    action_run_switch_main_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit run-result.v1 JSON.",
    )

    runbook_parser = subparsers.add_parser(
        "runbook",
        help="Read-only runbook runner commands.",
    )
    runbook_subparsers = runbook_parser.add_subparsers(dest="runbook_command", required=True)

    runbook_run_parser = runbook_subparsers.add_parser(
        "run",
        help=(
            "Execute a read-only runbook from a runbook-plan.v1 JSON file. "
            "Writes runbook-result.v1 and runbook-step-trace.v1 JSONL. "
            "No mutation, no fetch, no branch switch, no free shell."
        ),
    )
    runbook_run_parser.add_argument(
        "runbook_plan_json",
        help="Path to a runbook-plan.v1 JSON file.",
    )
    runbook_run_parser.add_argument(
        "--result-out",
        required=True,
        help="Output path for runbook-result.v1 JSON. Must not already exist.",
    )
    runbook_run_parser.add_argument(
        "--command-trace-out",
        required=True,
        help="Output path for runbook-step-trace.v1 JSONL. Must not already exist.",
    )
    runbook_run_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit runbook-result.v1 JSON.",
    )

    approval_parser = subparsers.add_parser(
        "approval",
        help="Pure artifact approval commands.",
    )
    approval_subparsers = approval_parser.add_subparsers(dest="approval_command", required=True)

    approval_validate_parser = approval_subparsers.add_parser(
        "validate",
        help=(
            "Validate that one action-approval.v1 artifact binds to one action-plan.v1 artifact. "
            "Pure artifact validation only — no pull, no execution, no mutation."
        ),
    )
    approval_validate_parser.add_argument(
        "approval_json",
        help="Path to an action-approval.v1 JSON file.",
    )
    approval_validate_parser.add_argument(
        "--plan",
        required=True,
        help="Path to an action-plan.v1 JSON file.",
    )
    approval_validate_parser.add_argument(
        "--checked-at",
        required=True,
        help="UTC date-time string (YYYY-MM-DDTHH:MM:SSZ) used as the validation reference time.",
    )
    approval_validate_parser.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit action-approval-validation.v1 JSON.",
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
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(duplicates, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "inventory" and args.inventory_command == "favorites":
        config_path = Path(args.config) if args.config else None
        try:
            favorites = build_favorites_report(config_path=config_path)
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(favorites, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "inventory":
        if not args.json:
            parser.error("the following arguments are required: --json")
        config_path = Path(args.config) if args.config else None
        try:
            inventory = build_inventory(config_path=config_path)
        except (FileNotFoundError, ValueError) as exc:
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

    if args.command == "plan" and args.plan_command == "git-pull-ff-only":
        try:
            with Path(args.assessment_json).open("r", encoding="utf-8") as handle:
                assessment = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"invalid assessment JSON: {exc}")

        remote_refresh_result = None
        if args.remote_refresh_result:
            try:
                with Path(args.remote_refresh_result).open("r", encoding="utf-8") as handle:
                    remote_refresh_result = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                parser.error(f"invalid remote-refresh-result JSON: {exc}")

        try:
            plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh_result)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "remote-refresh" and args.remote_refresh_command == "fetch-origin-prune":
        try:
            refresh_result = run_fetch_origin_prune(
                repo_path=args.repo_path,
                config_path=args.config,
                assessment_id=args.assessment_id,
                command_trace_out=args.command_trace_out,
            )
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(refresh_result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "scope" and args.scope_command == "explain":
        config_path = Path(args.config) if args.config else None
        try:
            explanation = explain_scope(Path(args.path), config_path=config_path)
        except (FileNotFoundError, ValueError) as exc:
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

    if args.command == "omnipull-report" and args.omnipull_report_command == "latest":
        try:
            index = load_omnipull_run_index(
                Path(args.run_index_json), source_path_ref=args.run_index_json
            )
            report_ref = select_latest_report(index)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(report_ref, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if (
        args.command == "omnipull-report"
        and args.omnipull_report_command == "recent-problems"
    ):
        try:
            reports = [
                load_omnipull_report(Path(path), source_path_ref=path)
                for path in args.report_json
            ]
            recent_problems = build_recent_problem_repos(reports, limit=args.limit)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(recent_problems, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "approval" and args.approval_command == "validate":
        try:
            with Path(args.approval_json).open("r", encoding="utf-8") as handle:
                approval = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"invalid approval JSON: {exc}")

        try:
            with Path(args.plan).open("r", encoding="utf-8") as handle:
                plan = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"invalid plan JSON: {exc}")

        try:
            result = validate_action_approval_binding(
                plan=plan,
                approval=approval,
                checked_at=args.checked_at,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "action" and args.action_command == "run-read-only":
        try:
            with Path(args.action_plan_json).open("r", encoding="utf-8") as handle:
                action_plan = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"invalid action-plan JSON: {exc}")

        preflight_for_action_plan: dict | None = None
        if args.preflight_for_action_plan is not None:
            try:
                with Path(args.preflight_for_action_plan).open("r", encoding="utf-8") as handle:
                    preflight_for_action_plan = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                print(
                    json.dumps(
                        {
                            "schema_version": "run-result.v1",
                            "run_id": "run-blocked-precondition",
                            "status": "blocked",
                            "redaction_verified": True,
                            "blocked_reasons": [f"invalid_preflight_for_action_plan_json: {exc}"],
                        },
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 1

        try:
            run_result = run_read_only_action(
                action_plan=action_plan,
                repo_path=args.repo_path,
                command_trace_out=args.command_trace_out,
                run_result_out=args.run_result_out,
                preflight_for_action_plan=preflight_for_action_plan,
            )
        except ValueError as exc:
            print(
                json.dumps(
                    {
                        "schema_version": "run-result.v1",
                        "run_id": "run-blocked-precondition",
                        "status": "blocked",
                        "redaction_verified": True,
                        "blocked_reasons": [str(exc)],
                    },
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(run_result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "action" and args.action_command == "postcheck-read-only":
        try:
            with Path(args.run_result_json).open("r", encoding="utf-8") as handle:
                run_result_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_postcheck_inconclusive(f"invalid_run_result_json: {exc}")

        try:
            with Path(args.command_trace).open("r", encoding="utf-8") as handle:
                command_trace_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_postcheck_inconclusive(f"invalid_command_trace_json: {exc}")

        try:
            postcheck = run_read_only_postcheck(
                run_result=run_result_data,
                command_trace=command_trace_data,
                repo_path=args.repo_path,
                postcheck_out=args.postcheck_out,
                command_trace_path=args.command_trace,
                run_result_path=args.run_result_json,
            )
        except ValueError as exc:
            return _emit_postcheck_inconclusive(str(exc))
        print(json.dumps(postcheck, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "action" and args.action_command == "validate-run-chain":
        try:
            with Path(args.action_plan_json).open("r", encoding="utf-8") as handle:
                action_plan_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_chain_inconclusive(
                f"invalid_action_plan_json: {exc}",
                action_plan_path=args.action_plan_json,
                command_trace_path=args.command_trace,
                run_result_path=args.run_result,
                run_postcheck_path=args.run_postcheck,
            )

        try:
            with Path(args.command_trace).open("r", encoding="utf-8") as handle:
                command_trace_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_chain_inconclusive(
                f"invalid_command_trace_json: {exc}",
                action_plan_path=args.action_plan_json,
                command_trace_path=args.command_trace,
                run_result_path=args.run_result,
                run_postcheck_path=args.run_postcheck,
            )

        try:
            with Path(args.run_result).open("r", encoding="utf-8") as handle:
                run_result_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_chain_inconclusive(
                f"invalid_run_result_json: {exc}",
                action_plan_path=args.action_plan_json,
                command_trace_path=args.command_trace,
                run_result_path=args.run_result,
                run_postcheck_path=args.run_postcheck,
            )

        try:
            with Path(args.run_postcheck).open("r", encoding="utf-8") as handle:
                run_postcheck_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_chain_inconclusive(
                f"invalid_run_postcheck_json: {exc}",
                action_plan_path=args.action_plan_json,
                command_trace_path=args.command_trace,
                run_result_path=args.run_result,
                run_postcheck_path=args.run_postcheck,
            )

        try:
            chain = validate_run_evidence_chain(
                action_plan=action_plan_data,
                command_trace=command_trace_data,
                run_result=run_result_data,
                run_postcheck=run_postcheck_data,
                action_plan_path=args.action_plan_json,
                command_trace_path=args.command_trace,
                run_result_path=args.run_result,
                run_postcheck_path=args.run_postcheck,
                chain_out=args.chain_out,
            )
        except ValueError as exc:
            return _emit_chain_inconclusive(
                str(exc),
                action_plan_path=args.action_plan_json,
                command_trace_path=args.command_trace,
                run_result_path=args.run_result,
                run_postcheck_path=args.run_postcheck,
            )
        print(json.dumps(chain, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "action" and args.action_command == "validate-execution-readiness":
        try:
            with Path(args.action_plan_json).open("r", encoding="utf-8") as handle:
                action_plan_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_readiness_inconclusive(
                f"invalid_action_plan_json: {exc}",
                action_plan_path=args.action_plan_json,
                approval_validation_path=args.approval_validation,
                run_evidence_chain_path=args.run_evidence_chain,
            )

        try:
            with Path(args.approval_validation).open("r", encoding="utf-8") as handle:
                approval_validation_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_readiness_inconclusive(
                f"invalid_approval_validation_json: {exc}",
                action_plan_path=args.action_plan_json,
                approval_validation_path=args.approval_validation,
                run_evidence_chain_path=args.run_evidence_chain,
            )

        try:
            with Path(args.run_evidence_chain).open("r", encoding="utf-8") as handle:
                run_evidence_chain_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_readiness_inconclusive(
                f"invalid_run_evidence_chain_json: {exc}",
                action_plan_path=args.action_plan_json,
                approval_validation_path=args.approval_validation,
                run_evidence_chain_path=args.run_evidence_chain,
            )

        preflight_binding_data: dict | None = None
        if args.preflight_binding is not None:
            try:
                with Path(args.preflight_binding).open("r", encoding="utf-8") as handle:
                    preflight_binding_data = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                return _emit_readiness_inconclusive(
                    f"invalid_preflight_binding_json: {exc}",
                    action_plan_path=args.action_plan_json,
                    approval_validation_path=args.approval_validation,
                    run_evidence_chain_path=args.run_evidence_chain,
                )

        try:
            readiness = validate_execution_readiness(
                action_plan=action_plan_data,
                approval_validation=approval_validation_data,
                run_evidence_chain=run_evidence_chain_data,
                readiness_out=args.readiness_out,
                preflight_binding=preflight_binding_data,
            )
        except ValueError as exc:
            return _emit_readiness_inconclusive(
                str(exc),
                action_plan_path=args.action_plan_json,
                approval_validation_path=args.approval_validation,
                run_evidence_chain_path=args.run_evidence_chain,
            )
        print(json.dumps(readiness, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "action" and args.action_command == "validate-switch-main-readiness":
        try:
            with Path(args.action_plan_json).open("r", encoding="utf-8") as handle:
                action_plan_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_switch_main_readiness_inconclusive(f"invalid_action_plan_json: {exc}")

        try:
            with Path(args.preflight_proof).open("r", encoding="utf-8") as handle:
                preflight_proof_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_switch_main_readiness_inconclusive(f"invalid_preflight_proof_json: {exc}")

        try:
            readiness = validate_switch_main_readiness(
                action_plan=action_plan_data,
                preflight_proof=preflight_proof_data,
                readiness_out=args.readiness_out,
            )
        except ValueError as exc:
            return _emit_switch_main_readiness_inconclusive(str(exc))
        print(json.dumps(readiness, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "action" and args.action_command == "run-git-pull-ff-only":
        try:
            with Path(args.action_plan_json).open("r", encoding="utf-8") as handle:
                action_plan_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_pull_blocked(f"invalid_action_plan_json: {exc}")

        try:
            with Path(args.approval_validation).open("r", encoding="utf-8") as handle:
                approval_validation_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_pull_blocked(f"invalid_approval_validation_json: {exc}")

        try:
            with Path(args.run_evidence_chain).open("r", encoding="utf-8") as handle:
                run_evidence_chain_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_pull_blocked(f"invalid_run_evidence_chain_json: {exc}")

        try:
            with Path(args.preflight_binding).open("r", encoding="utf-8") as handle:
                preflight_binding_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_pull_blocked(f"invalid_preflight_binding_json: {exc}")

        try:
            run_result = run_git_pull_ff_only(
                action_plan=action_plan_data,
                approval_validation=approval_validation_data,
                run_evidence_chain=run_evidence_chain_data,
                preflight_binding=preflight_binding_data,
                repo_path=args.repo_path,
                command_trace_out=args.command_trace_out,
                run_result_out=args.run_result_out,
                postcheck_out=args.postcheck_out,
            )
        except ValueError as exc:
            return _emit_pull_blocked(str(exc))
        print(json.dumps(run_result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "action" and args.action_command == "run-switch-main":
        try:
            with Path(args.action_plan_json).open("r", encoding="utf-8") as handle:
                action_plan_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_switch_main_blocked(f"invalid_action_plan_json: {exc}")

        try:
            with Path(args.approval_validation).open("r", encoding="utf-8") as handle:
                approval_validation_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_switch_main_blocked(f"invalid_approval_validation_json: {exc}")

        try:
            with Path(args.switch_main_readiness).open("r", encoding="utf-8") as handle:
                switch_main_readiness_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_switch_main_blocked(f"invalid_switch_main_readiness_json: {exc}")

        try:
            run_result = run_switch_main(
                action_plan=action_plan_data,
                approval_validation=approval_validation_data,
                switch_main_readiness=switch_main_readiness_data,
                repo_path=args.repo_path,
                command_trace_out=args.command_trace_out,
                run_result_out=args.run_result_out,
                postcheck_out=args.postcheck_out,
            )
        except ValueError as exc:
            return _emit_switch_main_blocked(str(exc))
        print(json.dumps(run_result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "action" and args.action_command == "bind-preflight-to-action":
        try:
            with Path(args.action_plan_json).open("r", encoding="utf-8") as handle:
                action_plan_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_preflight_binding_inconclusive(f"invalid_action_plan_json: {exc}")

        try:
            with Path(args.run_evidence_chain).open("r", encoding="utf-8") as handle:
                run_evidence_chain_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return _emit_preflight_binding_inconclusive(
                f"invalid_run_evidence_chain_json: {exc}"
            )

        try:
            binding = bind_preflight_to_action(
                action_plan=action_plan_data,
                run_evidence_chain=run_evidence_chain_data,
                binding_out=args.binding_out,
            )
        except ValueError as exc:
            return _emit_preflight_binding_inconclusive(str(exc))
        print(json.dumps(binding, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "runbook" and args.runbook_command == "run":
        try:
            with Path(args.runbook_plan_json).open("r", encoding="utf-8") as handle:
                runbook_plan_data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                json.dumps(
                    {
                        "schema_version": "runbook-result.v1",
                        "result_id": "rbresult-blocked-precondition",
                        "runbook_ref": "unknown",
                        "runbook_kind": "repo-sync-gate",
                        "status": "blocked",
                        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                        "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                        "repo_path": "unknown",
                        "short_assessment": (
                            f"diagnostic_sentinel_precondition: invalid_runbook_plan_json: {exc}; "
                            "runbook_kind is a schema-compatibility fallback and not validated input"
                        ),
                        "steps": [],
                        "evidence_paths": [],
                        "source_refs": [],
                        "redaction_verified": True,
                        "boundary": {
                            "does_not_execute_mutating_actions": True,
                            "does_not_mutate": True,
                            "does_not_authorise_actions": True,
                            "read_only_or_dry_run_only": True,
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1

        try:
            result = run_runbook(
                runbook_plan=runbook_plan_data,
                result_out=args.result_out,
                command_trace_out=args.command_trace_out,
            )
        except ValueError as exc:
            if isinstance(runbook_plan_data, dict):
                runbook_id_raw = runbook_plan_data.get("runbook_id")
                runbook_ref = (
                    runbook_id_raw.strip()
                    if isinstance(runbook_id_raw, str) and runbook_id_raw.strip()
                    else "unknown"
                )
                repo_path_raw = runbook_plan_data.get("repo_path")
                repo_path = (
                    repo_path_raw.strip()
                    if isinstance(repo_path_raw, str) and repo_path_raw.strip()
                    else "unknown"
                )
            else:
                runbook_ref = "unknown"
                repo_path = "unknown"
            print(
                json.dumps(
                    {
                        "schema_version": "runbook-result.v1",
                        "result_id": "rbresult-blocked-precondition",
                        "runbook_ref": runbook_ref,
                        "runbook_kind": "repo-sync-gate",
                        "status": "blocked",
                        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                        "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                        "repo_path": repo_path,
                        "short_assessment": (
                            f"diagnostic_sentinel_precondition: {exc}; "
                            "runbook_kind is a schema-compatibility fallback and not validated input"
                        ),
                        "steps": [],
                        "evidence_paths": [],
                        "source_refs": [],
                        "redaction_verified": True,
                        "boundary": {
                            "does_not_execute_mutating_actions": True,
                            "does_not_mutate": True,
                            "does_not_authorise_actions": True,
                            "read_only_or_dry_run_only": True,
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    parser.error("unsupported command")
    return 2
