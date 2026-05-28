"""Tests for Phase 8D.0: Stage-D Execution Readiness (action_execution_readiness)."""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

import steuerboard.action_execution_readiness as _mod
from scripts.validate_examples import (
    EXAMPLES_DIR,
    SCHEMAS_DIR,
    ValidationError,
    load_json,
    validate_instance,
)
from steuerboard.action_execution_readiness import validate_execution_readiness

_EXAMPLES = EXAMPLES_DIR / "action-execution-readiness"
_SCHEMA = SCHEMAS_DIR / "action-execution-readiness.v1.schema.json"
_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Shared base fixtures
# ---------------------------------------------------------------------------

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

_APPROVAL_VALIDATION_BINDING_VALID = {
    "schema_version": "action-approval-validation.v1",
    "validation_id": "validation-d57efbd94539cd086dfe836cd54c089c74debd43d1d00fbfb8a4cd12d31d53c3",
    "plan_ref": "plan-git-pull-ff-only-2026-05-23-001",
    "approval_ref": "approval-2026-05-23-git-pull-ff-only-approved-001",
    "action": "git-pull-ff-only",
    "checked_at": "2026-05-27T09:00:00Z",
    "binding_state": "binding_valid",
    "blocked_because": [],
    "source_refs": [],
    "boundary": {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_execution": True,
        "does_not_create_runner": True,
    },
}

_CHAIN_VALID = load_json(
    EXAMPLES_DIR / "run-evidence-chains" / "git-status-read-only-valid.json"
)
_CHAIN_INCONCLUSIVE = load_json(
    EXAMPLES_DIR / "run-evidence-chains" / "git-status-read-only-inconclusive.json"
)
_CHAIN_INVALID = load_json(
    EXAMPLES_DIR / "run-evidence-chains" / "git-status-read-only-invalid-postcheck-failed.json"
)


# ---------------------------------------------------------------------------
# Schema validation of example artifacts
# ---------------------------------------------------------------------------

_EXAMPLE_FILES = [
    "git-pull-ff-only-inconclusive-binding-unproven.json",
    "git-pull-ff-only-blocked-rejected-approval.json",
    "git-pull-ff-only-blocked-expired-approval.json",
    "git-pull-ff-only-inconclusive-chain.json",
    "git-pull-ff-only-blocked-invalid-chain.json",
]


@pytest.mark.parametrize("filename", _EXAMPLE_FILES)
def test_schema_examples_validate(filename):
    schema = load_json(_SCHEMA)
    instance = load_json(_EXAMPLES / filename)
    validate_instance(instance, schema, _EXAMPLES / filename)


# ---------------------------------------------------------------------------
# Core logic tests (pure function)
# ---------------------------------------------------------------------------

def test_inconclusive_when_no_hard_failures(tmp_path):
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
    )
    assert result["status"] == "inconclusive"
    assert "preflight_chain_plan_binding_unproven" in result["failure_reasons"]
    assert result["blocked_because"] == []
    assert result["boundary"]["does_not_execute"] is True
    assert result["boundary"]["does_not_mutate"] is True
    assert result["boundary"]["does_not_authorise_actions"] is True


def test_rejected_approval_blocked(tmp_path):
    approval = {
        **_APPROVAL_VALIDATION_BINDING_VALID,
        "binding_state": "binding_invalid",
        "blocked_because": ["approval_rejected"],
    }
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=approval,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
    )
    assert result["status"] == "blocked"
    assert "approval_not_binding_valid" in result["blocked_because"]
    assert "approval_not_binding_valid" in result["failure_reasons"]


def test_expired_approval_blocked(tmp_path):
    approval = {
        **_APPROVAL_VALIDATION_BINDING_VALID,
        "binding_state": "binding_invalid",
        "blocked_because": ["approval_expired"],
    }
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=approval,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
    )
    assert result["status"] == "blocked"
    assert "approval_not_binding_valid" in result["blocked_because"]


def test_invalid_chain_blocked(tmp_path):
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_INVALID,
        readiness_out=out,
    )
    assert result["status"] == "blocked"
    assert "chain_invalid" in result["blocked_because"]
    assert "chain_invalid" in result["failure_reasons"]


def test_inconclusive_chain_remains_inconclusive(tmp_path):
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_INCONCLUSIVE,
        readiness_out=out,
    )
    assert result["status"] == "inconclusive"
    assert "chain_inconclusive" in result["failure_reasons"]
    assert result["blocked_because"] == []


def test_unsupported_action_is_blocked_and_preserves_actual_action(tmp_path):
    plan = {
        **_PLAN,
        "action": "switch-main",
    }
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=plan,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
    )
    assert result["status"] == "blocked"
    assert result["action"] == "switch-main"
    assert "unsupported_action" in result["blocked_because"]
    assert "unsupported_action" in result["failure_reasons"]


def test_artifact_written_to_disk(tmp_path):
    out = tmp_path / "readiness.json"
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=str(out),
    )
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["readiness_id"] == result["readiness_id"]
    assert written["status"] == result["status"]


# ---------------------------------------------------------------------------
# CLI integration test
# ---------------------------------------------------------------------------

def test_cli_happy_path_inconclusive(tmp_path):
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    chain_path = tmp_path / "chain.json"
    readiness_out = tmp_path / "readiness.json"

    plan_path.write_text(json.dumps(_PLAN))
    approval_path.write_text(json.dumps(_APPROVAL_VALIDATION_BINDING_VALID))
    chain_path.write_text(json.dumps(_CHAIN_VALID))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "validate-execution-readiness",
            str(plan_path),
            "--approval-validation",
            str(approval_path),
            "--run-evidence-chain",
            str(chain_path),
            "--readiness-out",
            str(readiness_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr  # inconclusive exits 0
    result = json.loads(proc.stdout)
    assert result["status"] == "inconclusive"
    assert "preflight_chain_plan_binding_unproven" in result["failure_reasons"]
    assert readiness_out.exists()


def test_cli_invalid_action_plan_json_sentinel_uses_unknown_action(tmp_path):
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    chain_path = tmp_path / "chain.json"
    readiness_out = tmp_path / "readiness.json"

    plan_path.write_text("{")
    approval_path.write_text(json.dumps(_APPROVAL_VALIDATION_BINDING_VALID))
    chain_path.write_text(json.dumps(_CHAIN_VALID))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "validate-execution-readiness",
            str(plan_path),
            "--approval-validation",
            str(approval_path),
            "--run-evidence-chain",
            str(chain_path),
            "--readiness-out",
            str(readiness_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    validate_instance(payload, load_json(_SCHEMA), _EXAMPLES / "invalid-action-plan-json-sentinel.json")
    assert payload["status"] == "inconclusive"
    assert payload["action"] == "unknown"
    assert payload["plan_ref"] == "unknown"
    assert payload["approval_validation_ref"] == "unknown"
    assert payload["chain_ref"] == "unknown"
    assert any("invalid_action_plan_json" in reason for reason in payload["failure_reasons"])


def test_cli_schema_invalid_json_sentinel_reason_sanitized(tmp_path):
    """Test that multi-line ValidationError strings are sanitized in sentinel output."""
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    chain_path = tmp_path / "chain.json"
    readiness_out = tmp_path / "readiness.json"

    # Valid JSON but missing required schema fields for action-plan.v1
    invalid_plan = {
        "schema_version": "action-plan.v1",
        # missing required fields like action, plan_id, etc.
    }
    plan_path.write_text(json.dumps(invalid_plan))
    approval_path.write_text(json.dumps(_APPROVAL_VALIDATION_BINDING_VALID))
    chain_path.write_text(json.dumps(_CHAIN_VALID))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "validate-execution-readiness",
            str(plan_path),
            "--approval-validation",
            str(approval_path),
            "--run-evidence-chain",
            str(chain_path),
            "--readiness-out",
            str(readiness_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    # Validate that the sentinel output is schema-valid
    validate_instance(payload, load_json(_SCHEMA), _EXAMPLES / "invalid-action-plan-json-sentinel.json")
    assert payload["status"] == "inconclusive"
    assert payload["action"] == "unknown"
    # The reason should be sanitized (single-line, no embedded newlines)
    for reason in payload["failure_reasons"]:
        # Pattern from schema: ^\S(?:.*\S)?$
        # No newlines, starts with non-ws, ends with non-ws (or single char)
        assert "\n" not in reason, f"Reason contains newline: {reason!r}"
        assert reason[0] != " ", f"Reason starts with whitespace: {reason!r}"
        if len(reason) > 1:
            assert reason[-1] != " ", f"Reason ends with whitespace: {reason!r}"

    # Verify both failure_reasons and checks[0].actual are sanitized identically
    assert payload["checks"][0]["actual"] == payload["failure_reasons"][0]
    assert "\n" not in payload["checks"][0]["actual"]
    assert payload["checks"][0]["actual"][0] != " "
    if len(payload["checks"][0]["actual"]) > 1:
        assert payload["checks"][0]["actual"][-1] != " "


def test_no_subprocess_in_module():
    source = inspect.getsource(_mod)
    assert "import subprocess" not in source, (
        "action_execution_readiness.py must not import subprocess"
    )


def _valid_readiness_ready() -> dict:
    return {
        "schema_version": "action-execution-readiness.v1",
        "readiness_id": "readiness-example",
        "checked_at": "2026-05-27T10:00:00Z",
        "action": "git-pull-ff-only",
        "plan_ref": "plan-git-pull-ff-only-2026-05-23-001",
        "approval_validation_ref": "validation-example",
        "chain_ref": "chain-example",
        "status": "ready",
        "blocked_because": [],
        "checks": [{"check": "example", "passed": True}],
        "source_refs": ["action-plan.v1"],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }


def test_schema_rejects_ready_with_failure_reasons():
    invalid = _valid_readiness_ready()
    invalid["failure_reasons"] = ["unexpected"]
    with pytest.raises(ValidationError):
        validate_instance(invalid, load_json(_SCHEMA), _EXAMPLES / "invalid-ready-failure-reasons.json")


def test_schema_rejects_blocked_with_empty_blocked_because():
    invalid = _valid_readiness_ready()
    invalid["status"] = "blocked"
    invalid["failure_reasons"] = ["unsupported_action"]
    with pytest.raises(ValidationError):
        validate_instance(invalid, load_json(_SCHEMA), _EXAMPLES / "invalid-blocked-empty-blocked-because.json")


def test_schema_rejects_inconclusive_with_nonempty_blocked_because():
    invalid = _valid_readiness_ready()
    invalid["status"] = "inconclusive"
    invalid["blocked_because"] = ["chain_invalid"]
    invalid["failure_reasons"] = ["preflight_chain_plan_binding_unproven"]
    with pytest.raises(ValidationError):
        validate_instance(
            invalid,
            load_json(_SCHEMA),
            _EXAMPLES / "invalid-inconclusive-nonempty-blocked-because.json",
        )


# ---------------------------------------------------------------------------
# Phase 8D.1: --preflight-binding integration tests
# ---------------------------------------------------------------------------


def _hand_crafted_binding(
    *,
    binding_state: str,
    plan_ref: str = "plan-git-pull-ff-only-2026-05-23-001",
    plan_action: str = "git-pull-ff-only",
    chain_ref: str | None = None,
    chain_action: str = "git-status-read-only",
) -> dict:
    """Construct an action-preflight-binding.v1 with the requested binding_state.

    binding_valid is not achievable from current artifacts in the production
    binding function; we hand-craft one to exercise the readiness integration
    path that consumes a supplied binding.
    """
    if chain_ref is None:
        chain_ref = _CHAIN_VALID["chain_id"]
    artifact: dict = {
        "schema_version": "action-preflight-binding.v1",
        "binding_id": "preflight-binding-test",
        "checked_at": "2026-05-28T09:00:00Z",
        "plan_ref": plan_ref,
        "plan_action": plan_action,
        "chain_ref": chain_ref,
        "chain_action": chain_action,
        "binding_state": binding_state,
        "blocked_because": [],
        "checks": [{"check": "example", "passed": True}],
        "source_refs": ["action-plan.v1", "run-evidence-chain.v1"],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }
    if binding_state == "binding_invalid":
        artifact["blocked_because"] = ["chain_invalid"]
        artifact["failure_reasons"] = ["chain_invalid"]
    elif binding_state == "binding_inconclusive":
        artifact["failure_reasons"] = ["binding_cannot_be_proven_from_supplied_artifacts"]
    return artifact


def test_readiness_without_preflight_binding_remains_inconclusive(tmp_path):
    """Phase 8D.0 behavior unchanged when --preflight-binding is omitted."""
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
    )
    assert result["status"] == "inconclusive"
    assert "preflight_binding_ref" not in result
    assert "preflight_chain_plan_binding_unproven" in result["failure_reasons"]
    assert result["boundary"]["does_not_execute"] is True
    assert result["boundary"]["does_not_mutate"] is True
    assert result["boundary"]["does_not_authorise_actions"] is True


def test_readiness_with_binding_valid_still_inconclusive_without_proof(tmp_path):
    binding = _hand_crafted_binding(binding_state="binding_valid")
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
        preflight_binding=binding,
    )
    assert result["status"] == "inconclusive"
    assert result["blocked_because"] == []
    assert "preflight_chain_plan_binding_unproven" in result["failure_reasons"]
    assert result["preflight_binding_ref"] == "preflight-binding-test"
    assert result["boundary"]["does_not_execute"] is True
    assert result["boundary"]["does_not_mutate"] is True
    assert result["boundary"]["does_not_authorise_actions"] is True


def test_readiness_blocked_with_invalid_preflight_binding(tmp_path):
    binding = _hand_crafted_binding(binding_state="binding_invalid")
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
        preflight_binding=binding,
    )
    assert result["status"] == "blocked"
    assert result["preflight_binding_ref"] == "preflight-binding-test"
    assert "preflight_binding_invalid" in result["blocked_because"]
    assert "preflight_binding_invalid" in result["failure_reasons"]


def test_readiness_inconclusive_with_inconclusive_preflight_binding(tmp_path):
    binding = _hand_crafted_binding(binding_state="binding_inconclusive")
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
        preflight_binding=binding,
    )
    assert result["status"] == "inconclusive"
    assert result["preflight_binding_ref"] == "preflight-binding-test"
    assert "preflight_chain_plan_binding_unproven" in result["failure_reasons"]
    assert result["blocked_because"] == []


def test_readiness_rejects_binding_plan_ref_mismatch(tmp_path):
    binding = _hand_crafted_binding(
        binding_state="binding_valid",
        plan_ref="plan-some-other-plan-001",
    )
    out = str(tmp_path / "readiness.json")
    with pytest.raises(ValueError, match="preflight_binding.plan_ref"):
        validate_execution_readiness(
            action_plan=_PLAN,
            approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
            run_evidence_chain=_CHAIN_VALID,
            readiness_out=out,
            preflight_binding=binding,
        )


def test_readiness_rejects_binding_chain_ref_mismatch(tmp_path):
    binding = _hand_crafted_binding(
        binding_state="binding_valid",
        chain_ref="chain-some-other-chain-001",
    )
    out = str(tmp_path / "readiness.json")
    with pytest.raises(ValueError, match="preflight_binding.chain_ref"):
        validate_execution_readiness(
            action_plan=_PLAN,
            approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
            run_evidence_chain=_CHAIN_VALID,
            readiness_out=out,
            preflight_binding=binding,
        )


def test_readiness_rejects_binding_plan_action_mismatch(tmp_path):
    binding = _hand_crafted_binding(
        binding_state="binding_valid",
        plan_action="switch-main",
    )
    out = str(tmp_path / "readiness.json")
    with pytest.raises(ValueError, match="preflight_binding.plan_action"):
        validate_execution_readiness(
            action_plan=_PLAN,
            approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
            run_evidence_chain=_CHAIN_VALID,
            readiness_out=out,
            preflight_binding=binding,
        )


def test_readiness_rejects_binding_chain_action_mismatch(tmp_path):
    binding = _hand_crafted_binding(
        binding_state="binding_valid",
        chain_action="git-pull-ff-only",
    )
    out = str(tmp_path / "readiness.json")
    with pytest.raises(ValueError, match="preflight_binding.chain_action"):
        validate_execution_readiness(
            action_plan=_PLAN,
            approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
            run_evidence_chain=_CHAIN_VALID,
            readiness_out=out,
            preflight_binding=binding,
        )


def test_readiness_different_binding_state_produces_different_readiness_id(tmp_path):
    """Prove that different binding_state values produce different readiness_id.

    Two bindings with same binding_id but different binding_state should
    produce different readiness_id because binding_state is included in
    readiness_material, which is hashed to compute readiness_id.
    """
    binding_valid = _hand_crafted_binding(binding_state="binding_valid")
    binding_inconclusive = _hand_crafted_binding(binding_state="binding_inconclusive")

    # Verify they have the same binding_id
    assert binding_valid["binding_id"] == binding_inconclusive["binding_id"]
    assert binding_valid["binding_id"] == "preflight-binding-test"

    out_valid = str(tmp_path / "readiness_valid.json")
    result_valid = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out_valid,
        preflight_binding=binding_valid,
    )

    out_inconclusive = str(tmp_path / "readiness_inconclusive.json")
    result_inconclusive = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out_inconclusive,
        preflight_binding=binding_inconclusive,
    )

    # Different binding_state should produce different readiness_id
    assert result_valid["readiness_id"] != result_inconclusive["readiness_id"]
    # Both should record preflight_binding_ref and preflight_binding_state
    assert result_valid["preflight_binding_ref"] == "preflight-binding-test"
    assert result_inconclusive["preflight_binding_ref"] == "preflight-binding-test"
    # But the binding_state should differ in the id calculation
    assert result_valid["status"] == "inconclusive"
    assert result_inconclusive["status"] == "inconclusive"


def test_readiness_preserves_boundary_with_invalid_binding(tmp_path):
    binding = _hand_crafted_binding(binding_state="binding_invalid")
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
        preflight_binding=binding,
    )
    assert result["boundary"]["does_not_execute"] is True
    assert result["boundary"]["does_not_mutate"] is True
    assert result["boundary"]["does_not_authorise_actions"] is True


def test_readiness_cli_with_preflight_binding_valid_remains_inconclusive(tmp_path):
    """End-to-end CLI test: binding_valid remains inconclusive in current slice."""
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    chain_path = tmp_path / "chain.json"
    binding_path = tmp_path / "binding.json"
    readiness_out = tmp_path / "readiness.json"

    plan_path.write_text(json.dumps(_PLAN))
    approval_path.write_text(json.dumps(_APPROVAL_VALIDATION_BINDING_VALID))
    chain_path.write_text(json.dumps(_CHAIN_VALID))
    binding_path.write_text(json.dumps(_hand_crafted_binding(binding_state="binding_valid")))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "validate-execution-readiness",
            str(plan_path),
            "--approval-validation",
            str(approval_path),
            "--run-evidence-chain",
            str(chain_path),
            "--readiness-out",
            str(readiness_out),
            "--preflight-binding",
            str(binding_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "inconclusive"
    assert result["preflight_binding_ref"] == "preflight-binding-test"
    assert result["blocked_because"] == []
    assert "preflight_chain_plan_binding_unproven" in result["failure_reasons"]


# ---------------------------------------------------------------------------
# Phase 8D.2 — readiness with contract-defined preflight proof material
# ---------------------------------------------------------------------------


def _hand_crafted_binding_with_proof(
    *,
    plan_ref: str = "plan-git-pull-ff-only-2026-05-23-001",
    plan_action: str = "git-pull-ff-only",
    chain_ref: str | None = None,
    chain_action: str = "git-status-read-only",
    proof: dict | None = None,
) -> dict:
    if chain_ref is None:
        chain_ref = _CHAIN_VALID["chain_id"]
    if proof is None:
        from steuerboard.canonical_json import canonical_json_sha256
        proof = {
            "plan_ref": plan_ref,
            "plan_action": plan_action,
            "plan_content_sha256": canonical_json_sha256(_PLAN),
        }
    return {
        "schema_version": "action-preflight-binding.v1",
        "binding_id": "preflight-binding-test-proven",
        "checked_at": "2026-05-28T09:00:00Z",
        "plan_ref": plan_ref,
        "plan_action": plan_action,
        "chain_ref": chain_ref,
        "chain_action": chain_action,
        "binding_state": "binding_valid",
        "blocked_because": [],
        "checks": [{"check": "example", "passed": True}],
        "preflight_for_action_plan": dict(proof),
        "source_refs": ["action-plan.v1", "run-evidence-chain.v1"],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }


def test_readiness_ready_with_binding_valid_carrying_proof(tmp_path):
    """Phase 8D.2: readiness is ready when binding_valid carries proof material."""
    binding = _hand_crafted_binding_with_proof()
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
        preflight_binding=binding,
    )
    assert result["status"] == "ready"
    assert result["blocked_because"] == []
    assert "failure_reasons" not in result
    assert result["preflight_binding_ref"] == "preflight-binding-test-proven"


def test_readiness_inconclusive_when_binding_valid_lacks_proof(tmp_path):
    """Phase 8D.2: binding_valid without proof keeps readiness inconclusive.

    Conservative consumption: readiness must not elevate without explicit proof.
    """
    binding = _hand_crafted_binding(binding_state="binding_valid")
    # Sanity: this binding does not have a proof object.
    assert "preflight_for_action_plan" not in binding
    out = str(tmp_path / "readiness.json")
    result = validate_execution_readiness(
        action_plan=_PLAN,
        approval_validation=_APPROVAL_VALIDATION_BINDING_VALID,
        run_evidence_chain=_CHAIN_VALID,
        readiness_out=out,
        preflight_binding=binding,
    )
    assert result["status"] == "inconclusive"
    assert "preflight_chain_plan_binding_unproven" in result["failure_reasons"]
    assert result["preflight_binding_ref"] == "preflight-binding-test"
