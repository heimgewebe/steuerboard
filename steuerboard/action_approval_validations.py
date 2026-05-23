from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _parse_dt(value: str, field_name: str) -> datetime:
    """Parse an ISO 8601 / RFC 3339 date-time string into a timezone-aware datetime."""
    # Try common suffixes accepted by fromisoformat (Python 3.11+) and a manual Z path.
    if isinstance(value, str) and value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field_name}: cannot parse date-time {value!r}: {exc}") from exc
    if dt.tzinfo is None:
        raise ValueError(
            f"{field_name}: naive timestamp {value!r} is not accepted; "
            "provide an explicit UTC offset or Z suffix"
        )
    return dt


def _schema_valid_plan(plan: Any) -> str | None:
    """Return None if plan looks structurally usable, or an error string."""
    if not isinstance(plan, dict):
        return "plan is not a JSON object"
    if plan.get("schema_version") != "action-plan.v1":
        return f"plan schema_version is not 'action-plan.v1' (got {plan.get('schema_version')!r})"
    if not isinstance(plan.get("plan_id"), str) or not plan["plan_id"].strip():
        return "plan.plan_id is missing or blank"
    if not isinstance(plan.get("action"), str) or not plan["action"].strip():
        return "plan.action is missing or blank"
    return None


def _schema_valid_approval(approval: Any) -> str | None:
    """Return None if approval looks structurally usable, or an error string."""
    if not isinstance(approval, dict):
        return "approval is not a JSON object"
    if approval.get("schema_version") != "action-approval.v1":
        return (
            f"approval schema_version is not 'action-approval.v1' "
            f"(got {approval.get('schema_version')!r})"
        )
    if not isinstance(approval.get("approval_id"), str) or not approval["approval_id"].strip():
        return "approval.approval_id is missing or blank"
    if not isinstance(approval.get("plan_ref"), str) or not approval["plan_ref"].strip():
        return "approval.plan_ref is missing or blank"
    if not isinstance(approval.get("action"), str) or not approval["action"].strip():
        return "approval.action is missing or blank"
    if approval.get("decision") not in ("approved", "rejected"):
        return f"approval.decision is not 'approved' or 'rejected' (got {approval.get('decision')!r})"
    if not isinstance(approval.get("decided_at"), str):
        return "approval.decided_at is missing or not a string"
    if not isinstance(approval.get("expires_at"), str):
        return "approval.expires_at is missing or not a string"
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
        An explicit UTC-aware date-time string (RFC 3339).

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

    blocked_because: list[str] = []

    # --- semantic checks ---

    if approval.get("decision") != "approved":
        blocked_because.append("approval_rejected")

    if approval.get("plan_ref") != plan.get("plan_id"):
        blocked_because.append("plan_ref_mismatch")

    if approval.get("action") != plan.get("action"):
        blocked_because.append("action_mismatch")

    decided_at_dt: datetime | None = None
    expires_at_dt: datetime | None = None

    try:
        decided_at_dt = _parse_dt(approval["decided_at"], "approval.decided_at")
    except ValueError:
        blocked_because.append("approval_decided_in_future")  # malformed = treat as invalid

    try:
        expires_at_dt = _parse_dt(approval["expires_at"], "approval.expires_at")
    except ValueError:
        blocked_because.append("approval_expired")  # malformed = treat as invalid

    if decided_at_dt is not None and expires_at_dt is not None:
        if expires_at_dt <= decided_at_dt:
            blocked_because.append("approval_expires_before_decided_at")

    if decided_at_dt is not None:
        if decided_at_dt > checked_at_dt:
            blocked_because.append("approval_decided_in_future")

    if expires_at_dt is not None:
        if checked_at_dt >= expires_at_dt:
            blocked_because.append("approval_expired")

    # approval_scope checks
    scope = approval.get("approval_scope") or {}
    scope_ok = (
        scope.get("single_plan_only") is True
        and scope.get("no_plan_substitution") is True
        and scope.get("no_command_substitution") is True
    )
    if not scope_ok:
        blocked_because.append("approval_scope_invalid")

    # constraints checks
    constraints = approval.get("constraints") or {}
    constraints_ok = (
        constraints.get("requires_same_plan_id") is True
        and constraints.get("requires_same_action") is True
        and constraints.get("requires_revalidation_before_execution") is True
        and constraints.get("requires_runner_contract") is True
        and constraints.get("requires_postcheck") is True
    )
    if not constraints_ok:
        blocked_because.append("constraints_invalid")

    # boundary checks
    boundary = approval.get("boundary") or {}
    boundary_ok = (
        boundary.get("does_not_execute") is True
        and boundary.get("does_not_mutate") is True
        and boundary.get("does_not_authorise_unplanned_action") is True
        and boundary.get("does_not_create_runner") is True
    )
    if not boundary_ok:
        blocked_because.append("approval_boundary_invalid")

    binding_state = "binding_valid" if not blocked_because else "binding_invalid"

    validation_id = f"validation-{uuid.uuid4()}"

    return {
        "schema_version": "action-approval-validation.v1",
        "validation_id": validation_id,
        "plan_ref": plan["plan_id"],
        "approval_ref": approval["approval_id"],
        "action": plan["action"],
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
