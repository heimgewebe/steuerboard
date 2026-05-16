from __future__ import annotations

from typing import Any

FORBIDDEN_PLAN_INPUT_FIELDS = {
    "action",
    "plan_id",
    "would_run",
    "would_mutate",
    "safe_alternatives",
    "required_evidence",
    "command_trace",
    "run_result",
}

KNOWN_SWITCH_MAIN_STATUSES = {
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

BLOCKING_SWITCH_MAIN_STATUSES = {
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

NOT_APPLICABLE_SWITCH_MAIN_STATUSES = {"clean_default_current"}

VALID_ASSESSMENT_DECISION_STATES = {
    "action_blocked",
    "evidence_missing",
    "assessment_clear",
}


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list[str]")
    return value


def _require_non_empty_string_list(value: Any, field_name: str) -> list[str]:
    items = _require_string_list(value, field_name)
    if not items:
        raise ValueError(f"{field_name} must be a non-empty list[str]")
    return items


def plan_switch_main(assessment: dict[str, Any]) -> dict[str, Any]:
    """Derive a preview-only action-plan.v1 from an existing repo-assessment.v1 object.

    This function never executes commands, never mutates repositories, and never
    authorises action execution.
    """
    if not isinstance(assessment, dict):
        raise ValueError("assessment must be an object")

    forbidden_present = sorted(FORBIDDEN_PLAN_INPUT_FIELDS & set(assessment))
    if forbidden_present:
        raise ValueError(f"assessment contains forbidden plan/executor fields: {forbidden_present}")

    schema_version = assessment.get("schema_version")
    if schema_version != "repo-assessment.v1":
        raise ValueError("schema_version must be exactly 'repo-assessment.v1'")

    assessment_id = _require_non_empty_string(assessment.get("assessment_id"), "assessment_id")
    _require_non_empty_string(assessment.get("observation_ref"), "observation_ref")
    decision_state = _require_non_empty_string(assessment.get("decision_state"), "decision_state")
    if decision_state not in VALID_ASSESSMENT_DECISION_STATES:
        allowed_decision_states = sorted(VALID_ASSESSMENT_DECISION_STATES)
        raise ValueError(f"decision_state must be one of {allowed_decision_states}")

    derived_status = _require_string_list(assessment.get("derived_status"), "derived_status")
    if not derived_status:
        raise ValueError("derived_status must not be empty")

    unknown_statuses = [status for status in derived_status if status not in KNOWN_SWITCH_MAIN_STATUSES]
    if unknown_statuses:
        raise ValueError(f"unknown derived_status value(s): {unknown_statuses}")

    source_refs = _require_non_empty_string_list(assessment.get("source_refs"), "source_refs")
    missing_evidence = _require_string_list(assessment.get("missing_evidence"), "missing_evidence")
    rule_refs = _require_string_list(assessment.get("rule_refs"), "rule_refs")
    freshness_refs = _require_string_list(assessment.get("freshness_refs"), "freshness_refs")
    falsification_refs = _require_string_list(
        assessment.get("falsification_refs"), "falsification_refs"
    )

    blocking_reasons = [status for status in derived_status if status in BLOCKING_SWITCH_MAIN_STATUSES]
    not_applicable_reasons = [
        status for status in derived_status if status in NOT_APPLICABLE_SWITCH_MAIN_STATUSES
    ]

    if blocking_reasons and not_applicable_reasons:
        raise ValueError(
            "derived_status contains contradictory switch-main outcomes: "
            f"blocked={blocking_reasons}, not_applicable={not_applicable_reasons}"
        )

    if blocking_reasons and decision_state == "assessment_clear":
        raise ValueError(
            "decision_state must not be 'assessment_clear' when derived_status contains blocking reasons"
        )
    if not_applicable_reasons and decision_state != "assessment_clear":
        raise ValueError(
            "decision_state must be 'assessment_clear' when derived_status indicates clean_default_current"
        )

    if blocking_reasons:
        decision = "blocked"
    elif not_applicable_reasons:
        decision = "not_applicable"
    else:
        raise ValueError(
            "derived_status does not contain a supported switch-main planning status"
        )

    plan: dict[str, Any] = {
        "schema_version": "action-plan.v1",
        "plan_id": f"plan-{assessment_id}-switch-main",
        "action": "switch-main",
        "assessment_ref": assessment_id,
        "decision": decision,
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
        "source_refs": source_refs,
        "rule_refs": rule_refs,
        "freshness_refs": freshness_refs,
        "falsification_refs": falsification_refs,
        "missing_evidence": missing_evidence,
    }

    if blocking_reasons:
        plan["blocked_because"] = blocking_reasons

    return plan
