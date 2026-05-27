from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .canonical_json import canonical_json_sha256

_NONEMPTY_NONPADDED_RE = re.compile(r"^\S(?:.*\S)?$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _validate_nonempty_string(value: Any, field_name: str) -> str | None:
    if not isinstance(value, str) or not _NONEMPTY_NONPADDED_RE.fullmatch(value):
        return f"{field_name} must be a non-empty non-whitespace-padded string"
    return None


def _validate_string_array(value: Any, field_name: str, *, min_items: int = 0) -> str | None:
    if not isinstance(value, list):
        return f"{field_name} must be an array"
    if len(value) < min_items:
        return f"{field_name} must contain at least {min_items} item(s)"
    for index, item in enumerate(value):
        if _validate_nonempty_string(item, f"{field_name}[{index}]") is not None:
            return f"{field_name}[{index}] must be a non-empty non-whitespace-padded string"
    return None


def _validate_const_true_object(value: Any, field_name: str, required_keys: set[str]) -> str | None:
    if not isinstance(value, dict):
        return f"{field_name} must be an object"
    keys = set(value.keys())
    missing = sorted(required_keys - keys)
    if missing:
        return f"{field_name} is missing required field(s): {', '.join(missing)}"
    extra = sorted(keys - required_keys)
    if extra:
        return f"{field_name} has unexpected field(s): {', '.join(extra)}"
    for key in required_keys:
        if value.get(key) is not True:
            return f"{field_name}.{key} must be true"
    return None


def _parse_dt(value: str, field_name: str) -> datetime:
    """Parse a canonical UTC date-time string into a timezone-aware datetime.

    Only the exact shape ``YYYY-MM-DDTHH:MM:SSZ`` is accepted.  Fractional
    seconds, non-UTC offsets (``+02:00``), explicit UTC offset (``+00:00``),
    space separators, and naive timestamps are all rejected as invalid input.
    This keeps ``validation_id`` deterministic: equal inputs always produce
    equal outputs because there is exactly one valid representation of any
    given UTC instant.
    """
    if not isinstance(value, str) or _UTC_RFC3339_RE.fullmatch(value) is None:
        raise ValueError(
            f"{field_name}: {value!r} is not a valid UTC date-time (expected YYYY-MM-DDTHH:MM:SSZ)"
        )
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field_name}: cannot parse date-time {value!r}: {exc}") from exc
    return dt


def _schema_valid_plan(plan: Any) -> str | None:
    """Return None if plan is schema-valid action-plan.v1, or an error string."""
    if not isinstance(plan, dict):
        return "plan is not a JSON object"

    required = {
        "schema_version",
        "plan_id",
        "action",
        "decision",
        "assessment_ref",
        "source_refs",
        "rule_refs",
        "freshness_refs",
        "falsification_refs",
        "missing_evidence",
        "boundary",
    }
    keys = set(plan.keys())
    missing = sorted(required - keys)
    if missing:
        return f"plan is missing required field(s): {', '.join(missing)}"
    extra = sorted(keys - (required | {"blocked_because"}))
    if extra:
        return f"plan has unexpected field(s): {', '.join(extra)}"

    if plan.get("schema_version") != "action-plan.v1":
        return "plan.schema_version must be 'action-plan.v1'"
    if _validate_nonempty_string(plan.get("plan_id"), "plan.plan_id") is not None:
        return "plan.plan_id must be a non-empty non-whitespace-padded string"
    if plan.get("action") not in {"switch-main", "git-pull-ff-only"}:
        return "plan.action must be one of: switch-main, git-pull-ff-only"
    if _validate_nonempty_string(plan.get("assessment_ref"), "plan.assessment_ref") is not None:
        return "plan.assessment_ref must be a non-empty non-whitespace-padded string"
    if plan.get("decision") not in {"blocked", "not_applicable"}:
        return "plan.decision must be one of: blocked, not_applicable"

    for field_name, min_items in (
        ("source_refs", 1),
        ("rule_refs", 0),
        ("freshness_refs", 0),
        ("falsification_refs", 0),
        ("missing_evidence", 0),
    ):
        error = _validate_string_array(plan.get(field_name), f"plan.{field_name}", min_items=min_items)
        if error is not None:
            return error

    if plan.get("decision") == "blocked":
        if "blocked_because" not in plan:
            return "plan.blocked_because is required when plan.decision is 'blocked'"
        blocked_error = _validate_string_array(
            plan.get("blocked_because"),
            "plan.blocked_because",
            min_items=1,
        )
        if blocked_error is not None:
            return blocked_error
    elif "blocked_because" in plan:
        return "plan.blocked_because is not allowed when plan.decision is 'not_applicable'"

    boundary_error = _validate_const_true_object(
        plan.get("boundary"),
        "plan.boundary",
        {"does_not_execute", "does_not_mutate", "does_not_authorise_actions"},
    )
    if boundary_error is not None:
        return boundary_error

    return None


def _schema_valid_approval(approval: Any) -> str | None:
    """Return None if approval is schema-valid action-approval.v1, or an error string."""
    if not isinstance(approval, dict):
        return "approval is not a JSON object"

    required = {
        "schema_version",
        "approval_id",
        "plan_ref",
        "plan_content_sha256",
        "action",
        "decision",
        "decided_at",
        "approver_ref",
        "approval_scope",
        "expires_at",
        "constraints",
        "boundary",
    }
    keys = set(approval.keys())
    missing = sorted(required - keys)
    if missing:
        return f"approval is missing required field(s): {', '.join(missing)}"
    extra = sorted(keys - (required | {"reason", "source_refs"}))
    if extra:
        return f"approval has unexpected field(s): {', '.join(extra)}"

    if approval.get("schema_version") != "action-approval.v1":
        return "approval.schema_version must be 'action-approval.v1'"
    if _validate_nonempty_string(approval.get("approval_id"), "approval.approval_id") is not None:
        return "approval.approval_id must be a non-empty non-whitespace-padded string"
    if _validate_nonempty_string(approval.get("plan_ref"), "approval.plan_ref") is not None:
        return "approval.plan_ref must be a non-empty non-whitespace-padded string"
    if not isinstance(approval.get("plan_content_sha256"), str) or _SHA256_HEX_RE.fullmatch(
        approval["plan_content_sha256"]
    ) is None:
        return "approval.plan_content_sha256 must be a lowercase sha256 hex string"
    # action-approval.v1 is intentionally narrower in this phase than action-plan.v1.
    if approval.get("action") != "git-pull-ff-only":
        return "approval.action must be 'git-pull-ff-only' (only approved action in action-approval.v1)"
    if approval.get("decision") not in {"approved", "rejected"}:
        return "approval.decision must be one of: approved, rejected"
    if _validate_nonempty_string(approval.get("approver_ref"), "approval.approver_ref") is not None:
        return "approval.approver_ref must be a non-empty non-whitespace-padded string"

    if "source_refs" in approval:
        source_refs_error = _validate_string_array(approval["source_refs"], "approval.source_refs")
        if source_refs_error is not None:
            return source_refs_error

    if approval.get("decision") == "rejected":
        if _validate_nonempty_string(approval.get("reason"), "approval.reason") is not None:
            return "approval.reason is required and must be non-empty when decision is 'rejected'"

    try:
        _parse_dt(approval.get("decided_at"), "approval.decided_at")
        _parse_dt(approval.get("expires_at"), "approval.expires_at")
    except ValueError as exc:
        return str(exc)

    scope_error = _validate_const_true_object(
        approval.get("approval_scope"),
        "approval.approval_scope",
        {"single_plan_only", "no_plan_substitution", "no_command_substitution"},
    )
    if scope_error is not None:
        return scope_error

    constraints_error = _validate_const_true_object(
        approval.get("constraints"),
        "approval.constraints",
        {
            "requires_same_plan_id",
            "requires_same_action",
            "requires_revalidation_before_execution",
            "requires_runner_contract",
            "requires_postcheck",
        },
    )
    if constraints_error is not None:
        return constraints_error

    boundary_error = _validate_const_true_object(
        approval.get("boundary"),
        "approval.boundary",
        {
            "does_not_execute",
            "does_not_mutate",
            "does_not_authorise_unplanned_action",
            "does_not_create_runner",
        },
    )
    if boundary_error is not None:
        return boundary_error

    return None


def validate_action_approval_binding(
    plan: dict,
    approval: dict,
    checked_at: str,
) -> dict:
    """Validate that an action-approval.v1 artifact binds to an action-plan.v1 artifact.

    This function:
    - reads no files
    - runs no subprocesses
    - makes no network calls
    - mutates no repository
    - emits only action-approval-validation.v1 data

    Parameters
    ----------
    plan:
        A dict representing a schema-valid action-plan.v1 object.
    approval:
        A dict representing a schema-valid action-approval.v1 object.
    checked_at:
        Canonical UTC date-time string (``YYYY-MM-DDTHH:MM:SSZ``) used as
        the validation reference time.

    Returns
    -------
    dict
        An action-approval-validation.v1 artifact.

    Raises
    ------
    ValueError
        If either plan or approval is schema-invalid, or if checked_at cannot
        be parsed.
    """
    plan_err = _schema_valid_plan(plan)
    if plan_err is not None:
        raise ValueError(f"invalid action-plan.v1 input: {plan_err}")

    approval_err = _schema_valid_approval(approval)
    if approval_err is not None:
        raise ValueError(f"invalid action-approval.v1 input: {approval_err}")

    checked_at_dt = _parse_dt(checked_at, "checked_at")
    plan_content_sha256 = canonical_json_sha256(plan)

    blocked_because: list[str] = []

    # --- semantic checks ---

    if approval.get("decision") != "approved":
        blocked_because.append("approval_rejected")

    if approval.get("plan_ref") != plan.get("plan_id"):
        blocked_because.append("plan_ref_mismatch")

    if approval.get("action") != plan.get("action"):
        blocked_because.append("action_mismatch")

    if approval.get("plan_content_sha256") != plan_content_sha256:
        blocked_because.append("plan_content_sha256_mismatch")

    decided_at_dt = _parse_dt(approval["decided_at"], "approval.decided_at")
    expires_at_dt = _parse_dt(approval["expires_at"], "approval.expires_at")

    if expires_at_dt <= decided_at_dt:
        blocked_because.append("approval_expires_before_decided_at")

    if decided_at_dt > checked_at_dt:
        blocked_because.append("approval_decided_in_future")

    if checked_at_dt >= expires_at_dt:
        blocked_because.append("approval_expired")

    binding_state = "binding_valid" if not blocked_because else "binding_invalid"
    validation_material = {
        "plan_id": plan["plan_id"],
        "approval_id": approval["approval_id"],
        "plan_ref": approval["plan_ref"],
        "plan_action": plan["action"],
        "approval_action": approval["action"],
        "checked_at": checked_at,
        "plan_content_sha256": plan_content_sha256,
        "blocked_because": blocked_because,
    }
    validation_id = f"validation-{canonical_json_sha256(validation_material)}"

    return {
        "schema_version": "action-approval-validation.v1",
        "validation_id": validation_id,
        "plan_ref": plan["plan_id"],
        "approval_ref": approval["approval_id"],
        "action": approval["action"],
        "checked_at": checked_at,
        "binding_state": binding_state,
        "blocked_because": blocked_because,
        "source_refs": [],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_execution": True,
            "does_not_create_runner": True,
        },
    }
