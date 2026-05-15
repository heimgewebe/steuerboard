"""Plan Preview generation for the switch-main action.

This module derives an ``action-plan.v1`` JSON object from a previously
recorded ``repo-assessment.v1`` JSON object. It is a hypothetical preview:

- It does not execute anything.
- It does not mutate any repository.
- It does not authorise any action.
- It does not read configuration.
- It does not run Git or network commands.
- It does not start a new observation.

The plan is a Plan-Ergebnis, not an Action-Freigabe. ``not_applicable``
means no switch is required. ``blocked`` means the plan must not suggest
a way to bypass the blocker.
"""
from __future__ import annotations

import hashlib
from typing import Any

_KNOWN_STATUSES: frozenset[str] = frozenset(
    {
        "not_git_repo",
        "scope_backup",
        "scope_gdrive",
        "scope_excluded",
        "scope_unknown",
        "scope_shadow",
        "dirty_worktree",
        "detached_head",
        "default_branch_unknown",
        "non_default_branch",
        "clean_default_current",
    }
)

_BLOCKING_STATUSES: frozenset[str] = frozenset(
    {
        "not_git_repo",
        "scope_backup",
        "scope_gdrive",
        "scope_excluded",
        "scope_unknown",
        "scope_shadow",
        "dirty_worktree",
        "detached_head",
        "default_branch_unknown",
        "non_default_branch",
    }
)

_NOT_APPLICABLE_STATUSES: frozenset[str] = frozenset({"clean_default_current"})


def _string_list_field(
    assessment: dict[str, Any],
    key: str,
    *,
    required: bool = False,
) -> list[str]:
    if key not in assessment:
        if required:
            raise ValueError(f"{key} must be a list of strings")
        return []

    value = assessment[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of strings")
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} must be a list of strings")
    return value


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _build_plan_id(assessment_id: str, decision: str) -> str:
    material = f"switch-main|{decision}|{assessment_id}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"plan-switch-main-{digest}"


def plan_switch_main(assessment: dict[str, Any]) -> dict[str, Any]:
    """Derive an ``action-plan.v1`` preview for ``switch-main`` from an assessment.

    The function never returns ``decision == "allowed"``. switch-main is a
    mutating action, and this read-only preview slice deliberately does not
    authorise it. The plan only states whether the action is blocked or not
    applicable, why, and what evidence would be required.
    """
    if not isinstance(assessment, dict):
        raise ValueError("assessment must be an object")

    schema_version = assessment.get("schema_version")
    if schema_version != "repo-assessment.v1":
        raise ValueError("schema_version must be repo-assessment.v1")

    assessment_id = assessment.get("assessment_id")
    if not isinstance(assessment_id, str) or not assessment_id:
        raise ValueError("assessment_id must be a non-empty string")

    derived_status = assessment.get("derived_status")
    if not isinstance(derived_status, list) or not derived_status:
        raise ValueError("derived_status must be a non-empty list")
    for status in derived_status:
        if not isinstance(status, str) or not status:
            raise ValueError("derived_status must contain non-empty strings")
        if status not in _KNOWN_STATUSES:
            raise ValueError(f"Unsupported derived_status: {status!r}")

    source_refs = _string_list_field(assessment, "source_refs", required=True)
    missing_evidence = _string_list_field(assessment, "missing_evidence")
    rule_refs = _string_list_field(assessment, "rule_refs")
    freshness_refs = _string_list_field(assessment, "freshness_refs")
    falsification_refs = _string_list_field(assessment, "falsification_refs")

    blocking = [status for status in derived_status if status in _BLOCKING_STATUSES]
    not_applicable = [
        status for status in derived_status if status in _NOT_APPLICABLE_STATUSES
    ]

    if blocking and not_applicable:
        raise ValueError(
            "derived_status mixes blocking and not_applicable statuses; "
            "cannot derive a switch-main plan without contract violation"
        )

    if blocking:
        decision = "blocked"
        blocked_because = _dedupe_keep_order(blocking)
        would_run = ["git switch main"]
        would_mutate = ["current_branch"]
        required_evidence = list(missing_evidence)
    elif not_applicable:
        decision = "not_applicable"
        blocked_because = []
        would_run = []
        would_mutate = []
        required_evidence = []
    else:
        # No mapping found for any derived_status: should not happen because
        # all statuses pass _KNOWN_STATUSES, but keep this explicit so the
        # contract cannot silently widen in the future.
        raise ValueError(
            "derived_status contains no statuses that map to a switch-main plan"
        )

    plan: dict[str, Any] = {
        "schema_version": "action-plan.v1",
        "plan_id": _build_plan_id(assessment_id, decision),
        "action": "switch-main",
        "assessment_ref": assessment_id,
        "decision": decision,
        "would_run": would_run,
        "would_mutate": would_mutate,
        "blocked_because": blocked_because,
        "required_evidence": required_evidence,
        "safe_alternatives": [],
        "source_refs": list(source_refs),
        "rule_refs": list(rule_refs),
        "freshness_refs": list(freshness_refs),
        "falsification_refs": list(falsification_refs),
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    return plan
