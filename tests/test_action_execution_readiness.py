"""Tests for Phase 8D.0: Stage-D Execution Readiness (action_execution_readiness)."""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

import steuerboard.action_execution_readiness as _mod
from scripts.validate_examples import EXAMPLES_DIR, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.action_execution_readiness import validate_execution_readiness
from steuerboard.canonical_json import canonical_json_sha256

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


# ---------------------------------------------------------------------------
# Boundary: no subprocess import in the module
# ---------------------------------------------------------------------------

def test_no_subprocess_in_module():
    source = inspect.getsource(_mod)
    assert "import subprocess" not in source, (
        "action_execution_readiness.py must not import subprocess"
    )
