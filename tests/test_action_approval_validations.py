from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.action_approval_validations import validate_action_approval_binding


FORBIDDEN_OUTPUT_FIELDS = {
    "would_run",
    "would_mutate",
    "command_trace",
    "run_result",
    "execution_allowed",
    "safe_alternatives",
    "required_evidence",
}

_PLAN = {
    "schema_version": "action-plan.v1",
    "plan_id": "plan-git-pull-ff-only-2026-05-23-001",
    "action": "git-pull-ff-only",
    "assessment_ref": "assess-example-001",
    "decision": "blocked",
    "blocked_because": ["git_pull_ff_only_evidence_missing_remote_freshness"],
    "source_refs": ["git.current_branch"],
    "rule_refs": [],
    "freshness_refs": [],
    "falsification_refs": [],
    "missing_evidence": [],
    "boundary": {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    },
}

_APPROVAL_APPROVED = {
    "schema_version": "action-approval.v1",
    "approval_id": "approval-2026-05-23-git-pull-ff-only-approved-001",
    "plan_ref": "plan-git-pull-ff-only-2026-05-23-001",
    "action": "git-pull-ff-only",
    "decision": "approved",
    "decided_at": "2026-05-23T10:40:00Z",
    "approver_ref": "user:alex",
    "source_refs": [],
    "approval_scope": {
        "single_plan_only": True,
        "no_plan_substitution": True,
        "no_command_substitution": True,
    },
    "expires_at": "2026-05-23T18:40:00Z",
    "constraints": {
        "requires_same_plan_id": True,
        "requires_same_action": True,
        "requires_revalidation_before_execution": True,
        "requires_runner_contract": True,
        "requires_postcheck": True,
    },
    "boundary": {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_unplanned_action": True,
        "does_not_create_runner": True,
    },
}

_CHECKED_AT_VALID = "2026-05-23T12:00:00Z"
_CHECKED_AT_AFTER_EXPIRY = "2026-05-23T20:00:00Z"


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_binding_valid_approved_unexpired():
    result = validate_action_approval_binding(_PLAN, _APPROVAL_APPROVED, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_valid"
    assert result["blocked_because"] == []


def test_binding_invalid_rejected():
    approval = {**_APPROVAL_APPROVED, "decision": "rejected"}
    result = validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "approval_rejected" in result["blocked_because"]


def test_binding_invalid_expired():
    result = validate_action_approval_binding(
        _PLAN, _APPROVAL_APPROVED, _CHECKED_AT_AFTER_EXPIRY
    )
    assert result["binding_state"] == "binding_invalid"
    assert "approval_expired" in result["blocked_because"]


def test_binding_invalid_decided_in_future():
    approval = {**_APPROVAL_APPROVED, "decided_at": "2026-05-23T14:00:00Z"}
    result = validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "approval_decided_in_future" in result["blocked_because"]


def test_binding_invalid_expires_before_decided_at():
    approval = {
        **_APPROVAL_APPROVED,
        "decided_at": "2026-05-23T10:40:00Z",
        "expires_at": "2026-05-23T10:40:00Z",  # equal → invalid
    }
    result = validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "approval_expires_before_decided_at" in result["blocked_because"]


def test_binding_invalid_plan_ref_mismatch():
    plan = {**_PLAN, "plan_id": "plan-different-id"}
    result = validate_action_approval_binding(plan, _APPROVAL_APPROVED, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "plan_ref_mismatch" in result["blocked_because"]


def test_binding_invalid_action_mismatch():
    # approval action differs from plan action
    approval = {**_APPROVAL_APPROVED, "action": "switch-main"}
    # plan also uses switch-main to avoid triggering the plan schema check on the action enum
    plan = {
        **_PLAN,
        "action": "git-pull-ff-only",
    }
    result = validate_action_approval_binding(plan, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "action_mismatch" in result["blocked_because"]


def test_binding_invalid_approval_scope_false():
    approval = {
        **_APPROVAL_APPROVED,
        "approval_scope": {
            "single_plan_only": False,
            "no_plan_substitution": True,
            "no_command_substitution": True,
        },
    }
    result = validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "approval_scope_invalid" in result["blocked_because"]


def test_binding_invalid_constraints_false():
    approval = {
        **_APPROVAL_APPROVED,
        "constraints": {
            "requires_same_plan_id": True,
            "requires_same_action": True,
            "requires_revalidation_before_execution": False,
            "requires_runner_contract": True,
            "requires_postcheck": True,
        },
    }
    result = validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "constraints_invalid" in result["blocked_because"]


def test_binding_invalid_boundary_false():
    approval = {
        **_APPROVAL_APPROVED,
        "boundary": {
            "does_not_execute": False,
            "does_not_mutate": True,
            "does_not_authorise_unplanned_action": True,
            "does_not_create_runner": True,
        },
    }
    result = validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "approval_boundary_invalid" in result["blocked_because"]


def test_invalid_plan_raises_value_error():
    bad_plan = {"schema_version": "action-plan.v1"}  # missing plan_id
    with pytest.raises(ValueError, match="action-plan.v1"):
        validate_action_approval_binding(bad_plan, _APPROVAL_APPROVED, _CHECKED_AT_VALID)


def test_invalid_approval_raises_value_error():
    bad_approval = {"schema_version": "action-approval.v1"}  # missing approval_id
    with pytest.raises(ValueError, match="action-approval.v1"):
        validate_action_approval_binding(_PLAN, bad_approval, _CHECKED_AT_VALID)


def test_output_schema_valid():
    schema = load_json(SCHEMAS_DIR / "action-approval-validation.v1.schema.json")
    result = validate_action_approval_binding(_PLAN, _APPROVAL_APPROVED, _CHECKED_AT_VALID)
    from scripts.validate_examples import validate_instance, ValidationError

    validate_instance(result, schema, Path("in-memory"))


def test_output_never_contains_forbidden_fields():
    result = validate_action_approval_binding(_PLAN, _APPROVAL_APPROVED, _CHECKED_AT_VALID)
    for field in FORBIDDEN_OUTPUT_FIELDS:
        assert field not in result, f"Forbidden field present in output: {field}"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def _cli(command: list[str]) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}:{existing}"
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def test_cli_emits_schema_valid_result(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    plan_path.write_text(json.dumps(_PLAN), encoding="utf-8")
    approval_path.write_text(json.dumps(_APPROVAL_APPROVED), encoding="utf-8")

    proc = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "approval",
            "validate",
            str(approval_path),
            "--plan",
            str(plan_path),
            "--checked-at",
            _CHECKED_AT_VALID,
            "--json",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["schema_version"] == "action-approval-validation.v1"

    schema = load_json(SCHEMAS_DIR / "action-approval-validation.v1.schema.json")
    from scripts.validate_examples import validate_instance

    validate_instance(result, schema, Path("cli-output"))


def test_cli_invalid_plan_fails_cleanly(tmp_path: Path):
    bad_plan_path = tmp_path / "bad_plan.json"
    approval_path = tmp_path / "approval.json"
    bad_plan_path.write_text('{"not": "valid"}', encoding="utf-8")
    approval_path.write_text(json.dumps(_APPROVAL_APPROVED), encoding="utf-8")

    proc = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "approval",
            "validate",
            str(approval_path),
            "--plan",
            str(bad_plan_path),
            "--checked-at",
            _CHECKED_AT_VALID,
            "--json",
        ]
    )
    assert proc.returncode != 0
    assert "plan" in proc.stderr.lower() or "action-plan" in proc.stderr.lower()


def test_cli_invalid_approval_fails_cleanly(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    bad_approval_path = tmp_path / "bad_approval.json"
    plan_path.write_text(json.dumps(_PLAN), encoding="utf-8")
    bad_approval_path.write_text('{"not": "valid"}', encoding="utf-8")

    proc = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "approval",
            "validate",
            str(bad_approval_path),
            "--plan",
            str(plan_path),
            "--checked-at",
            _CHECKED_AT_VALID,
            "--json",
        ]
    )
    assert proc.returncode != 0
    assert "approval" in proc.stderr.lower() or "action-approval" in proc.stderr.lower()


def test_cli_output_never_contains_forbidden_fields(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    plan_path.write_text(json.dumps(_PLAN), encoding="utf-8")
    approval_path.write_text(json.dumps(_APPROVAL_APPROVED), encoding="utf-8")

    proc = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "approval",
            "validate",
            str(approval_path),
            "--plan",
            str(plan_path),
            "--checked-at",
            _CHECKED_AT_VALID,
            "--json",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    for field in FORBIDDEN_OUTPUT_FIELDS:
        assert field not in result, f"Forbidden field present in CLI output: {field}"
