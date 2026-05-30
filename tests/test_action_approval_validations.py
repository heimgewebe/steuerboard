from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.action_approval_validations import validate_action_approval_binding
from steuerboard.canonical_json import canonical_json_sha256


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
_PLAN_SHA256 = canonical_json_sha256(_PLAN)

_APPROVAL_APPROVED = {
    "schema_version": "action-approval.v1",
    "approval_id": "approval-2026-05-23-git-pull-ff-only-approved-001",
    "plan_ref": "plan-git-pull-ff-only-2026-05-23-001",
    "plan_content_sha256": _PLAN_SHA256,
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
_EXAMPLES_DIR = ROOT / "examples"


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_binding_valid_approved_unexpired():
    result = validate_action_approval_binding(_PLAN, _APPROVAL_APPROVED, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_valid"
    assert result["blocked_because"] == []


def test_binding_invalid_rejected():
    approval = {
        **_APPROVAL_APPROVED,
        "decision": "rejected",
        "reason": "Approval withheld pending execution-runner contract.",
    }
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
    approval = dict(_APPROVAL_APPROVED)
    plan = {**_PLAN, "action": "switch-main"}
    result = validate_action_approval_binding(plan, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "action_mismatch" in result["blocked_because"]


def test_binding_invalid_action_mismatch_output_stays_schema_valid():
    approval = dict(_APPROVAL_APPROVED)
    plan = {**_PLAN, "action": "switch-main"}
    result = validate_action_approval_binding(plan, approval, _CHECKED_AT_VALID)
    schema = load_json(SCHEMAS_DIR / "action-approval-validation.v1.schema.json")
    validate_instance(result, schema, Path("action-mismatch-output"))


def test_binding_invalid_plan_content_sha256_mismatch():
    approval = {**_APPROVAL_APPROVED, "plan_content_sha256": "0" * 64}
    result = validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)
    assert result["binding_state"] == "binding_invalid"
    assert "plan_content_sha256_mismatch" in result["blocked_because"]


def test_binding_validation_id_is_deterministic():
    first = validate_action_approval_binding(_PLAN, _APPROVAL_APPROVED, _CHECKED_AT_VALID)
    second = validate_action_approval_binding(_PLAN, _APPROVAL_APPROVED, _CHECKED_AT_VALID)
    assert first["validation_id"] == second["validation_id"]


def test_invalid_approval_scope_false_raises_value_error():
    approval = {
        **_APPROVAL_APPROVED,
        "approval_scope": {
            "single_plan_only": False,
            "no_plan_substitution": True,
            "no_command_substitution": True,
        },
    }
    with pytest.raises(ValueError, match="invalid action-approval.v1 input"):
        validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)


def test_invalid_constraints_false_raises_value_error():
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
    with pytest.raises(ValueError, match="invalid action-approval.v1 input"):
        validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)


def test_invalid_boundary_false_raises_value_error():
    approval = {
        **_APPROVAL_APPROVED,
        "boundary": {
            "does_not_execute": False,
            "does_not_mutate": True,
            "does_not_authorise_unplanned_action": True,
            "does_not_create_runner": True,
        },
    }
    with pytest.raises(ValueError, match="invalid action-approval.v1 input"):
        validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)


def test_invalid_approval_timestamp_raises_value_error():
    approval = {**_APPROVAL_APPROVED, "decided_at": "2026-13-40"}
    with pytest.raises(ValueError, match="invalid action-approval.v1 input"):
        validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)


@pytest.mark.parametrize(
    "bad_ts",
    [
        "2026-05-23 12:00:00Z",         # space separator — not RFC 3339
        "2026-05-23T12:00:00",          # naive timestamp — no offset
        "2026-05-23",                   # date only
        "not-a-date",                   # garbage
        "",                             # empty string
        "2026-05-23T10:40Z",            # missing seconds
        "2026-05-23T10:40:00.000Z",     # fractional seconds — not canonical
        "2026-05-23T10:40:00+00:00",    # explicit UTC offset — only Z is accepted
        "2026-05-23T10:40:00+02:00",    # non-UTC offset
    ],
)
def test_non_rfc3339_approval_decided_at_raises_value_error(bad_ts: str):
    """Malformed timestamps must be rejected as invalid input, not semanticized."""
    approval = {**_APPROVAL_APPROVED, "decided_at": bad_ts}
    with pytest.raises(ValueError, match="invalid action-approval.v1 input"):
        validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)


@pytest.mark.parametrize(
    "bad_ts",
    [
        "2026-05-23 18:40:00Z",         # space separator — not RFC 3339
        "2026-05-23T18:40:00",          # naive timestamp — no offset
        "not-a-date",                   # garbage
        "2026-05-23T18:40Z",            # missing seconds
        "2026-05-23T18:40:00.000Z",     # fractional seconds — not canonical
        "2026-05-23T18:40:00+00:00",    # explicit UTC offset — only Z is accepted
        "2026-05-23T18:40:00+02:00",    # non-UTC offset
    ],
)
def test_non_rfc3339_approval_expires_at_raises_value_error(bad_ts: str):
    """Malformed expires_at must be rejected as invalid input."""
    approval = {**_APPROVAL_APPROVED, "expires_at": bad_ts}
    with pytest.raises(ValueError, match="invalid action-approval.v1 input"):
        validate_action_approval_binding(_PLAN, approval, _CHECKED_AT_VALID)


@pytest.mark.parametrize(
    "bad_ts",
    [
        "2026-05-23 12:00:00Z",         # space separator — not RFC 3339
        "2026-05-23T12:00:00",          # naive timestamp — no offset
        "not-a-date",                   # garbage
        "2026-05-23T12:00Z",            # missing seconds
        "2026-05-23T12:00:00.000Z",     # fractional seconds — not canonical
        "2026-05-23T12:00:00+00:00",    # explicit UTC offset — only Z is accepted
        "2026-05-23T14:00:00+02:00",    # non-UTC offset (even if semantically UTC)
    ],
)
def test_non_canonical_utc_checked_at_raises_value_error(bad_ts: str):
    """Only YYYY-MM-DDTHH:MM:SSZ is accepted; all other forms are invalid input."""
    with pytest.raises(ValueError, match="checked_at"):
        validate_action_approval_binding(_PLAN, _APPROVAL_APPROVED, bad_ts)


def test_non_utc_offset_checked_at_is_rejected():
    """Non-UTC offsets must be rejected; only the Z suffix is canonical."""
    with pytest.raises(ValueError, match="checked_at"):
        validate_action_approval_binding(
            _PLAN, _APPROVAL_APPROVED, "2026-05-23T14:00:00+02:00"
        )


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


def test_cli_rejects_approval_with_extra_top_level_field(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    bad_approval_path = tmp_path / "bad_approval.json"
    bad_approval = {**_APPROVAL_APPROVED, "execution_allowed": True}
    plan_path.write_text(json.dumps(_PLAN), encoding="utf-8")
    bad_approval_path.write_text(json.dumps(bad_approval), encoding="utf-8")

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
    assert "invalid action-approval.v1 input" in proc.stderr
    assert "action-approval-validation.v1" not in proc.stdout


def test_cli_rejects_plan_with_invalid_boundary_value(tmp_path: Path):
    bad_plan_path = tmp_path / "bad_plan.json"
    approval_path = tmp_path / "approval.json"
    bad_plan = {
        **_PLAN,
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": False,
        },
    }
    bad_plan_path.write_text(json.dumps(bad_plan), encoding="utf-8")
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
    assert "invalid action-plan.v1 input" in proc.stderr
    assert "action-approval-validation.v1" not in proc.stdout


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


def test_validation_examples_match_runtime_outputs():
    plan = load_json(_EXAMPLES_DIR / "action-plans/git-pull-ff-only-approval-binding-base.json")
    approved = load_json(_EXAMPLES_DIR / "action-approvals/git-pull-ff-only-approved.json")
    rejected = load_json(_EXAMPLES_DIR / "action-approvals/git-pull-ff-only-rejected.json")
    mismatch = load_json(_EXAMPLES_DIR / "action-approvals/git-pull-ff-only-approved-plan-mismatch.json")

    scenarios = [
        (approved, "2026-05-23T12:00:00Z", "git-pull-ff-only-binding-valid.json"),
        (rejected, "2026-05-23T12:00:00Z", "git-pull-ff-only-rejected.json"),
        (approved, "2026-05-23T20:00:00Z", "git-pull-ff-only-expired.json"),
        (mismatch, "2026-05-23T12:00:00Z", "git-pull-ff-only-plan-mismatch.json"),
    ]

    for approval, checked_at, fixture_name in scenarios:
        expected = load_json(_EXAMPLES_DIR / "action-approval-validations" / fixture_name)
        actual = validate_action_approval_binding(plan, approval, checked_at)
        assert actual == expected


# ---------------------------------------------------------------------------
# switch-main approval tests
# ---------------------------------------------------------------------------

_SWITCH_MAIN_PLAN = {
    "schema_version": "action-plan.v1",
    "plan_id": "plan-example-switch-main-blocked",
    "action": "switch-main",
    "assessment_ref": "assess-example-non-default-branch-evidence-missing",
    "decision": "blocked",
    "blocked_because": ["non_default_branch"],
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
_SWITCH_MAIN_PLAN_SHA256 = canonical_json_sha256(_SWITCH_MAIN_PLAN)

_SWITCH_MAIN_APPROVAL_APPROVED = {
    "schema_version": "action-approval.v1",
    "approval_id": "approval-2026-05-30-switch-main-approved-001",
    "plan_ref": "plan-example-switch-main-blocked",
    "plan_content_sha256": _SWITCH_MAIN_PLAN_SHA256,
    "action": "switch-main",
    "decision": "approved",
    "decided_at": "2026-05-30T10:00:00Z",
    "approver_ref": "user:alex",
    "source_refs": [],
    "approval_scope": {
        "single_plan_only": True,
        "no_plan_substitution": True,
        "no_command_substitution": True,
    },
    "expires_at": "2026-05-30T18:00:00Z",
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


def test_switch_main_approval_schema_valid():
    """_schema_valid_approval accepts action == 'switch-main'."""
    from steuerboard.action_approval_validations import _schema_valid_approval

    err = _schema_valid_approval(_SWITCH_MAIN_APPROVAL_APPROVED)
    assert err is None, f"Expected no error, got: {err}"


def test_switch_main_approval_binding_valid():
    """validate_action_approval_binding returns binding_valid for a matched switch-main pair."""
    result = validate_action_approval_binding(
        _SWITCH_MAIN_PLAN, _SWITCH_MAIN_APPROVAL_APPROVED, "2026-05-30T12:00:00Z"
    )
    assert result["binding_state"] == "binding_valid"
    assert result["blocked_because"] == []
    assert result["action"] == "switch-main"
    assert result["plan_ref"] == "plan-example-switch-main-blocked"
    assert result["approval_ref"] == "approval-2026-05-30-switch-main-approved-001"


def test_switch_main_approval_binding_invalid_action_mismatch():
    """binding_invalid when approval action is git-pull-ff-only but plan action is switch-main."""
    mismatched_approval = {**_SWITCH_MAIN_APPROVAL_APPROVED, "action": "git-pull-ff-only"}
    # Recompute plan_content_sha256 so the only mismatch is action
    mismatched_approval["plan_content_sha256"] = _SWITCH_MAIN_PLAN_SHA256
    result = validate_action_approval_binding(
        _SWITCH_MAIN_PLAN, mismatched_approval, "2026-05-30T12:00:00Z"
    )
    assert result["binding_state"] == "binding_invalid"
    assert "action_mismatch" in result["blocked_because"]


def test_switch_main_approval_schema_example_validates():
    """examples/action-approvals/switch-main-approved.json validates against action-approval.v1 schema."""
    schema = load_json(SCHEMAS_DIR / "action-approval.v1.schema.json")
    example = load_json(_EXAMPLES_DIR / "action-approvals" / "switch-main-approved.json")
    validate_instance(example, schema, Path("switch-main-approved"))


def test_switch_main_approval_validation_example_matches_runtime():
    """examples/action-approval-validations/switch-main-binding-valid.json matches runtime output."""
    plan = load_json(_EXAMPLES_DIR / "action-plans" / "switch-main-blocked.json")
    approval = load_json(_EXAMPLES_DIR / "action-approvals" / "switch-main-approved.json")
    expected = load_json(
        _EXAMPLES_DIR / "action-approval-validations" / "switch-main-binding-valid.json"
    )
    actual = validate_action_approval_binding(plan, approval, "2026-05-30T12:00:00Z")
    assert actual == expected


def test_cli_approval_validate_switch_main_binding_valid(tmp_path: Path):
    """CLI 'approval validate' produces binding_valid for a switch-main approval."""
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    plan_path.write_text(json.dumps(_SWITCH_MAIN_PLAN), encoding="utf-8")
    approval_path.write_text(json.dumps(_SWITCH_MAIN_APPROVAL_APPROVED), encoding="utf-8")

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
            "2026-05-30T12:00:00Z",
            "--json",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["schema_version"] == "action-approval-validation.v1"
    assert result["binding_state"] == "binding_valid"
    assert result["action"] == "switch-main"

    schema = load_json(SCHEMAS_DIR / "action-approval-validation.v1.schema.json")
    validate_instance(result, schema, Path("cli-switch-main-output"))
