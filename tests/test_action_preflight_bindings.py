"""Tests for Phase 8D.1: Action Preflight Binding (action_preflight_bindings)."""
from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import steuerboard.action_preflight_bindings as _mod
from scripts.validate_examples import (
    EXAMPLES_DIR,
    SCHEMAS_DIR,
    load_json,
    validate_instance,
)
from steuerboard.action_preflight_bindings import bind_preflight_to_action
from steuerboard.canonical_json import canonical_json_sha256

_EXAMPLES = EXAMPLES_DIR / "action-preflight-bindings"
_SCHEMA = SCHEMAS_DIR / "action-preflight-binding.v1.schema.json"
_REPO_ROOT = Path(__file__).resolve().parent.parent

_SCHEMA_SAFE_LINE_RE = re.compile(r"^\S(?:.*\S)?$")


# ---------------------------------------------------------------------------
# Shared base fixtures
# ---------------------------------------------------------------------------

_PULL_PLAN = {
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

_SWITCH_MAIN_PLAN = {
    "schema_version": "action-plan.v1",
    "plan_id": "plan-switch-main-2026-05-23-001",
    "action": "switch-main",
    "assessment_ref": "assess-example-001",
    "decision": "blocked",
    "blocked_because": ["dirty_worktree"],
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
    "git-pull-ff-only-binding-inconclusive.json",
    "git-pull-ff-only-binding-blocked-invalid-chain.json",
    "git-pull-ff-only-binding-blocked-redaction-unverified.json",
    "git-pull-ff-only-binding-blocked-unsupported-plan-action.json",
    "git-pull-ff-only-binding-valid.json",
    "git-pull-ff-only-binding-invalid-plan-ref-mismatch.json",
    "git-pull-ff-only-binding-invalid-plan-content-sha256-mismatch.json",
    "git-pull-ff-only-binding-invalid-plan-action-wrong.json",
]


@pytest.mark.parametrize("filename", _EXAMPLE_FILES)
def test_schema_examples_validate(filename):
    schema = load_json(_SCHEMA)
    instance = load_json(_EXAMPLES / filename)
    validate_instance(instance, schema, _EXAMPLES / filename)


@pytest.mark.parametrize("filename", _EXAMPLE_FILES)
def test_schema_examples_binding_id_matches_binding_material(filename):
    instance = load_json(_EXAMPLES / filename)
    binding_material = {
        "plan_ref": instance["plan_ref"],
        "plan_action": instance["plan_action"],
        "chain_ref": instance["chain_ref"],
        "chain_action": instance["chain_action"],
        "binding_state": instance["binding_state"],
        "blocked_because": list(instance.get("blocked_because", [])),
        "failure_reasons": list(instance.get("failure_reasons", [])),
    }
    if "preflight_for_action_plan" in instance:
        binding_material["preflight_for_action_plan"] = dict(
            instance["preflight_for_action_plan"]
        )
    expected = f"preflight-binding-{canonical_json_sha256(binding_material)}"
    assert instance["binding_id"] == expected


# ---------------------------------------------------------------------------
# Core logic tests (pure function)
# ---------------------------------------------------------------------------


def test_inconclusive_when_binding_material_missing(tmp_path):
    """Standard git-pull-ff-only plan + valid git-status-read-only chain.

    Honest result: inconclusive because the chain artifact does not expose any
    field that ties it to the pull plan.
    """
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_CHAIN_VALID,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_inconclusive"
    assert result["blocked_because"] == []
    assert "binding_cannot_be_proven_from_supplied_artifacts" in result["failure_reasons"]
    assert result["plan_ref"] == _PULL_PLAN["plan_id"]
    assert result["plan_action"] == "git-pull-ff-only"
    assert result["chain_ref"] == _CHAIN_VALID["chain_id"]
    assert result["chain_action"] == "git-status-read-only"
    assert result["boundary"]["does_not_execute"] is True
    assert result["boundary"]["does_not_mutate"] is True
    assert result["boundary"]["does_not_authorise_actions"] is True


def test_blocked_unsupported_plan_action(tmp_path):
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_SWITCH_MAIN_PLAN,
        run_evidence_chain=_CHAIN_VALID,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_invalid"
    assert "unsupported_plan_action" in result["blocked_because"]
    assert "unsupported_plan_action" in result["failure_reasons"]


def test_blocked_chain_invalid(tmp_path):
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_CHAIN_INVALID,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_invalid"
    assert "chain_invalid" in result["blocked_because"]
    assert "chain_invalid" in result["failure_reasons"]


def test_blocked_chain_redaction_unverified(tmp_path):
    """If the chain has redaction_verified=false, the binding is blocked.

    The chain schema forbids redaction_verified=false for status=valid via an
    if/then rule, so we use status=inconclusive to construct a chain that is
    schema-valid but fails the redaction gate.
    """
    chain = {**_CHAIN_INCONCLUSIVE, "redaction_verified": False}
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=chain,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_invalid"
    assert "chain_redaction_unverified" in result["blocked_because"]
    assert "chain_redaction_unverified" in result["failure_reasons"]


def test_inconclusive_chain_yields_inconclusive_binding(tmp_path):
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_CHAIN_INCONCLUSIVE,
        binding_out=out,
    )
    # chain status inconclusive is recorded as a soft reason, not a hard block.
    # The natural binding remains inconclusive.
    assert result["binding_state"] == "binding_inconclusive"
    assert result["blocked_because"] == []
    assert "chain_inconclusive" in result["failure_reasons"]


def test_output_parent_must_exist(tmp_path):
    out = tmp_path / "no_such_dir" / "binding.json"
    with pytest.raises(ValueError, match="parent directory does not exist"):
        bind_preflight_to_action(
            action_plan=_PULL_PLAN,
            run_evidence_chain=_CHAIN_VALID,
            binding_out=str(out),
        )


def test_output_must_not_pre_exist(tmp_path):
    out = tmp_path / "binding.json"
    out.write_text("{}")
    with pytest.raises(ValueError, match="output file already exists"):
        bind_preflight_to_action(
            action_plan=_PULL_PLAN,
            run_evidence_chain=_CHAIN_VALID,
            binding_out=str(out),
        )


def test_artifact_written_to_disk(tmp_path):
    out = tmp_path / "binding.json"
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_CHAIN_VALID,
        binding_out=str(out),
    )
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["binding_id"] == result["binding_id"]
    assert written["binding_state"] == result["binding_state"]
    assert written["schema_version"] == "action-preflight-binding.v1"


def test_invalid_action_plan_raises_value_error(tmp_path):
    out = str(tmp_path / "binding.json")
    bad_plan = {"schema_version": "action-plan.v1"}  # missing required fields
    with pytest.raises(ValueError, match="action-plan.v1 does not validate"):
        bind_preflight_to_action(
            action_plan=bad_plan,
            run_evidence_chain=_CHAIN_VALID,
            binding_out=out,
        )


def test_invalid_chain_raises_value_error(tmp_path):
    out = str(tmp_path / "binding.json")
    bad_chain = {"schema_version": "run-evidence-chain.v1"}  # missing required fields
    with pytest.raises(ValueError, match="run-evidence-chain.v1 does not validate"):
        bind_preflight_to_action(
            action_plan=_PULL_PLAN,
            run_evidence_chain=bad_chain,
            binding_out=out,
        )


def test_artifact_validates_against_schema(tmp_path):
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_CHAIN_VALID,
        binding_out=out,
    )
    schema = load_json(_SCHEMA)
    validate_instance(result, schema, Path(out))


def test_failure_reasons_are_schema_safe(tmp_path):
    """All emitted failure_reasons must satisfy the schema pattern ^\\S(?:.*\\S)?$."""
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_CHAIN_VALID,
        binding_out=out,
    )
    for reason in result.get("failure_reasons", []):
        assert "\n" not in reason, f"Reason contains newline: {reason!r}"
        assert _SCHEMA_SAFE_LINE_RE.fullmatch(reason), f"Reason not schema-safe: {reason!r}"


def test_no_subprocess_in_module():
    source = inspect.getsource(_mod)
    assert "import subprocess" not in source, (
        "action_preflight_bindings.py must not import subprocess"
    )


def test_no_socket_in_module():
    source = inspect.getsource(_mod)
    assert "import socket" not in source, (
        "action_preflight_bindings.py must not import socket"
    )


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_cli_happy_path_inconclusive(tmp_path):
    plan_path = tmp_path / "plan.json"
    chain_path = tmp_path / "chain.json"
    binding_out = tmp_path / "binding.json"

    plan_path.write_text(json.dumps(_PULL_PLAN))
    chain_path.write_text(json.dumps(_CHAIN_VALID))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "bind-preflight-to-action",
            str(plan_path),
            "--run-evidence-chain",
            str(chain_path),
            "--binding-out",
            str(binding_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr  # inconclusive exits 0
    result = json.loads(proc.stdout)
    assert result["binding_state"] == "binding_inconclusive"
    assert "binding_cannot_be_proven_from_supplied_artifacts" in result["failure_reasons"]
    assert binding_out.exists()


def test_cli_blocked_unsupported_plan_action(tmp_path):
    plan_path = tmp_path / "plan.json"
    chain_path = tmp_path / "chain.json"
    binding_out = tmp_path / "binding.json"

    plan_path.write_text(json.dumps(_SWITCH_MAIN_PLAN))
    chain_path.write_text(json.dumps(_CHAIN_VALID))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "bind-preflight-to-action",
            str(plan_path),
            "--run-evidence-chain",
            str(chain_path),
            "--binding-out",
            str(binding_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr  # binding_invalid still exits 0
    result = json.loads(proc.stdout)
    assert result["binding_state"] == "binding_invalid"
    assert "unsupported_plan_action" in result["blocked_because"]


def test_cli_invalid_json_emits_schema_safe_sentinel(tmp_path):
    plan_path = tmp_path / "plan.json"
    chain_path = tmp_path / "chain.json"
    binding_out = tmp_path / "binding.json"

    plan_path.write_text("{")  # malformed JSON
    chain_path.write_text(json.dumps(_CHAIN_VALID))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "bind-preflight-to-action",
            str(plan_path),
            "--run-evidence-chain",
            str(chain_path),
            "--binding-out",
            str(binding_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    # Validate sentinel against schema
    schema = load_json(_SCHEMA)
    validate_instance(payload, schema, _EXAMPLES / "sentinel.json")
    assert payload["binding_state"] == "binding_inconclusive"
    assert payload["plan_ref"] == "unknown"
    assert any("invalid_action_plan_json" in reason for reason in payload["failure_reasons"])
    # Reasons must be schema-safe (single line, no whitespace padding)
    for reason in payload["failure_reasons"]:
        assert "\n" not in reason
        assert _SCHEMA_SAFE_LINE_RE.fullmatch(reason), f"Not schema-safe: {reason!r}"
    # checks[0].actual must also be schema-safe
    assert payload["checks"][0]["actual"] == payload["failure_reasons"][0]


def test_cli_schema_invalid_plan_emits_schema_safe_sentinel(tmp_path):
    plan_path = tmp_path / "plan.json"
    chain_path = tmp_path / "chain.json"
    binding_out = tmp_path / "binding.json"

    plan_path.write_text(json.dumps({"schema_version": "action-plan.v1"}))
    chain_path.write_text(json.dumps(_CHAIN_VALID))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "bind-preflight-to-action",
            str(plan_path),
            "--run-evidence-chain",
            str(chain_path),
            "--binding-out",
            str(binding_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    schema = load_json(_SCHEMA)
    validate_instance(payload, schema, _EXAMPLES / "sentinel.json")
    assert payload["binding_state"] == "binding_inconclusive"
    for reason in payload["failure_reasons"]:
        assert "\n" not in reason
        assert _SCHEMA_SAFE_LINE_RE.fullmatch(reason), f"Not schema-safe: {reason!r}"


# ---------------------------------------------------------------------------
# Phase 8D.2 — contract-defined preflight proof material
# ---------------------------------------------------------------------------


def _pull_plan_proof_material(pull_plan: dict) -> dict:
    return {
        "plan_ref": pull_plan["plan_id"],
        "plan_action": "git-pull-ff-only",
        "plan_content_sha256": canonical_json_sha256(pull_plan),
        "repo_toplevel": "/home/user/steuerboard",
    }


def _chain_with_proof(pull_plan: dict) -> dict:
    chain = json.loads(json.dumps(_CHAIN_VALID))
    chain["preflight_for_action_plan"] = _pull_plan_proof_material(pull_plan)
    return chain


def test_binding_valid_when_proof_matches(tmp_path):
    """Phase 8D.2: chain carries proof matching the pull plan → binding_valid."""
    chain = _chain_with_proof(_PULL_PLAN)
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=chain,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_valid"
    assert result["blocked_because"] == []
    assert "failure_reasons" not in result
    assert "preflight_for_action_plan" in result
    assert result["preflight_for_action_plan"]["plan_ref"] == _PULL_PLAN["plan_id"]
    assert result["preflight_for_action_plan"]["plan_action"] == "git-pull-ff-only"
    assert result["preflight_for_action_plan"]["plan_content_sha256"] == (
        canonical_json_sha256(_PULL_PLAN)
    )


def test_binding_inconclusive_when_proof_absent(tmp_path):
    """Phase 8D.2: chain has no proof object → binding stays inconclusive.

    Preserves pre-8D.2 behaviour for artifacts produced before Phase 8D.2.
    """
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_CHAIN_VALID,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_inconclusive"
    assert result["blocked_because"] == []
    assert "binding_cannot_be_proven_from_supplied_artifacts" in result["failure_reasons"]
    assert "preflight_for_action_plan" not in result


def test_binding_invalid_when_proof_plan_ref_mismatches(tmp_path):
    """Phase 8D.2: chain proof references a different plan_id → binding_invalid."""
    chain = _chain_with_proof(_PULL_PLAN)
    chain["preflight_for_action_plan"]["plan_ref"] = "plan-git-pull-ff-only-OTHER-001"
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=chain,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_invalid"
    assert "binding_mismatch" in result["blocked_because"]
    assert "binding_mismatch" in result["failure_reasons"]


def test_binding_invalid_when_proof_plan_content_sha256_mismatches(tmp_path):
    """Phase 8D.2: chain proof carries wrong content hash → binding_invalid."""
    chain = _chain_with_proof(_PULL_PLAN)
    chain["preflight_for_action_plan"]["plan_content_sha256"] = "0" * 64
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=chain,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_invalid"
    assert "binding_mismatch" in result["blocked_because"]
    assert "binding_mismatch" in result["failure_reasons"]


def test_binding_invalid_when_proof_plan_action_is_not_git_pull_ff_only(tmp_path):
    """Phase 8D.2: chain proof plan_action != git-pull-ff-only → binding_invalid."""
    chain = _chain_with_proof(_PULL_PLAN)
    chain["preflight_for_action_plan"]["plan_action"] = "switch-main"
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=chain,
        binding_out=out,
    )
    assert result["binding_state"] == "binding_invalid"
    assert "binding_mismatch" in result["blocked_because"]
    assert "binding_mismatch" in result["failure_reasons"]


def test_binding_rejects_schema_invalid_proof_repo_toplevel_missing(tmp_path):
    """Phase 8D.2/8E: proof without repo_toplevel is rejected at schema gate."""
    chain = _chain_with_proof(_PULL_PLAN)
    chain["preflight_for_action_plan"].pop("repo_toplevel")

    out = str(tmp_path / "binding.json")
    with pytest.raises(ValueError, match="repo_toplevel"):
        bind_preflight_to_action(
            action_plan=_PULL_PLAN,
            run_evidence_chain=chain,
            binding_out=out,
        )

    assert not Path(out).exists()


def test_binding_valid_artifact_records_proof_material(tmp_path):
    """The binding artifact carries the proof object it found in the chain."""
    chain = _chain_with_proof(_PULL_PLAN)
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=chain,
        binding_out=out,
    )
    assert result["preflight_for_action_plan"] == chain["preflight_for_action_plan"]


def test_binding_id_includes_proof_in_material(tmp_path):
    """binding_id must change when proof material is part of the binding."""
    out_with_proof = str(tmp_path / "binding-with-proof.json")
    out_without_proof = str(tmp_path / "binding-without-proof.json")
    with_proof = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_chain_with_proof(_PULL_PLAN),
        binding_out=out_with_proof,
    )
    without_proof = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_CHAIN_VALID,
        binding_out=out_without_proof,
    )
    # Different binding_state and proof presence => different binding_id
    assert with_proof["binding_id"] != without_proof["binding_id"]


def test_binding_valid_artifact_validates_against_schema(tmp_path):
    out = str(tmp_path / "binding.json")
    result = bind_preflight_to_action(
        action_plan=_PULL_PLAN,
        run_evidence_chain=_chain_with_proof(_PULL_PLAN),
        binding_out=out,
    )
    schema = load_json(_SCHEMA)
    validate_instance(result, schema, Path(out))
    assert result["binding_state"] == "binding_valid"
