"""Tests for Phase 9A: non-mutating Switch-main Execution Readiness.

These tests prove that switch-main readiness is a pure artifact/proof layer:
- it reaches ``ready`` only when the proof material is complete and consistent
  and content-bound to the exact switch-main plan;
- it ``blocked``s on hard contradictions (binding mismatch, dirty worktree,
  default branch not main, stale remote main, ownership/path split-brain,
  unsupported action);
- it is ``inconclusive`` when proof material is merely unknown;
- it never executes, never switches a branch, never mutates, never authorises;
- ``plan switch-main`` stays ``derivation_only``; the Phase 9A readiness layer
  itself introduces no runner. The bounded ``run-switch-main`` executor is the
  separate Phase 9B slice (tested in ``tests/test_action_switch_main.py``), and
  Stage D now holds exactly two ``mutating_stage_d`` commands.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

import steuerboard.action_switch_main_readiness as _mod
from scripts.docmeta import generate_cli_surface as surface
from scripts.validate_examples import (
    EXAMPLES_DIR,
    SCHEMAS_DIR,
    load_json,
    validate_instance,
)
from steuerboard.action_switch_main_readiness import validate_switch_main_readiness
from steuerboard.canonical_json import canonical_json_sha256
from steuerboard.cli import build_parser

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROOF_EXAMPLES = EXAMPLES_DIR / "switch-main-preflight-proofs"
_READINESS_EXAMPLES = EXAMPLES_DIR / "switch-main-readiness"
_PROOF_SCHEMA = SCHEMAS_DIR / "switch-main-preflight-proof.v1.schema.json"
_READINESS_SCHEMA = SCHEMAS_DIR / "switch-main-readiness.v1.schema.json"
_SWITCH_MAIN_PLAN_PATH = EXAMPLES_DIR / "action-plans" / "switch-main-blocked.json"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------
def _switch_main_plan() -> dict:
    return load_json(_SWITCH_MAIN_PLAN_PATH)


def _ready_proof(plan: dict | None = None) -> dict:
    plan = plan if plan is not None else _switch_main_plan()
    return {
        "schema_version": "switch-main-preflight-proof.v1",
        "proof_id": "switch-main-proof-test-ready",
        "checked_at": "2026-05-30T12:00:00Z",
        "plan_ref": plan["plan_id"],
        "plan_action": "switch-main",
        "plan_content_sha256": canonical_json_sha256(plan),
        "repo_toplevel": "/home/alex/code/heimgewebe/infra",
        "current_branch": "docs/runtime-refresh",
        "default_branch": "main",
        "branch_contains_origin_main_or_pr_merged": True,
        "worktree_clean": True,
        "remote_main_fresh": True,
        "ownership_ok": True,
        "source_refs": ["git.rev_parse.toplevel", "git.current_branch"],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }


def _run(plan: dict, proof: dict, tmp_path: Path) -> dict:
    out = tmp_path / "switch-main-readiness.json"
    return validate_switch_main_readiness(
        action_plan=plan, preflight_proof=proof, readiness_out=str(out)
    )


# ---------------------------------------------------------------------------
# ready
# ---------------------------------------------------------------------------
def test_ready_only_when_proof_complete_and_consistent(tmp_path):
    plan = _switch_main_plan()
    result = _run(plan, _ready_proof(plan), tmp_path)
    assert result["status"] == "ready"
    assert result["blocked_because"] == []
    assert "failure_reasons" not in result
    assert result["action"] == "switch-main"
    assert result["plan_ref"] == plan["plan_id"]
    assert result["proof_ref"] == "switch-main-proof-test-ready"
    assert result["repo_toplevel"] == "/home/alex/code/heimgewebe/infra"
    assert all(check["passed"] for check in result["checks"])


def test_ready_artifact_has_const_true_boundary(tmp_path):
    result = _run(_switch_main_plan(), _ready_proof(), tmp_path)
    assert result["boundary"] == {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }


def test_ready_is_not_authorisation_no_execution_fields(tmp_path):
    # A 'ready' verdict must not leak any execute/mutate/authorise affordance.
    result = _run(_switch_main_plan(), _ready_proof(), tmp_path)
    for forbidden in ("would_run", "would_switch", "command", "argv", "authorised"):
        assert forbidden not in result


# ---------------------------------------------------------------------------
# blocked — hard contradictions
# ---------------------------------------------------------------------------
def test_dirty_worktree_proof_blocks(tmp_path):
    proof = _ready_proof()
    proof["worktree_clean"] = False
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "worktree_not_clean" in result["blocked_because"]
    assert "worktree_not_clean" in result["failure_reasons"]


def test_plan_content_hash_mismatch_blocks(tmp_path):
    proof = _ready_proof()
    proof["plan_content_sha256"] = "0" * 64
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "plan_content_sha256_mismatch" in result["blocked_because"]


def test_plan_action_mismatch_blocks(tmp_path):
    proof = _ready_proof()
    proof["plan_action"] = "git-pull-ff-only"
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "plan_action_mismatch" in result["blocked_because"]


def test_plan_ref_mismatch_blocks(tmp_path):
    proof = _ready_proof()
    proof["plan_ref"] = "plan-some-other-switch-main"
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "plan_ref_mismatch" in result["blocked_because"]


def test_default_branch_not_main_blocks(tmp_path):
    proof = _ready_proof()
    proof["default_branch"] = "develop"
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "default_branch_not_main" in result["blocked_because"]


def test_stale_remote_main_blocks(tmp_path):
    proof = _ready_proof()
    proof["remote_main_fresh"] = False
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "remote_main_stale" in result["blocked_because"]


def test_ownership_split_brain_blocks(tmp_path):
    proof = _ready_proof()
    proof["ownership_ok"] = False
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "ownership_conflict" in result["blocked_because"]


def test_non_default_branch_with_lifecycle_false_blocks(tmp_path):
    proof = _ready_proof()
    proof["current_branch"] = "feature/experimental"
    proof["branch_contains_origin_main_or_pr_merged"] = False
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "branch_lifecycle_unproven" in result["blocked_because"]


def test_non_default_branch_without_lifecycle_proof_is_inconclusive(tmp_path):
    proof = _ready_proof()
    proof["current_branch"] = "feature/experimental"
    # branch_contains_origin_main_or_pr_merged is absent
    proof.pop("branch_contains_origin_main_or_pr_merged")
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "inconclusive"
    assert result["blocked_because"] == []
    assert "branch_lifecycle_unknown" in result["failure_reasons"]


def test_non_default_branch_with_lifecycle_true_can_be_ready(tmp_path):
    proof = _ready_proof()
    proof["current_branch"] = "feature/experimental"
    proof["branch_contains_origin_main_or_pr_merged"] = True
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "ready"
    assert result["blocked_because"] == []
    assert "failure_reasons" not in result


def test_current_main_does_not_require_branch_lifecycle_proof(tmp_path):
    proof = _ready_proof()
    proof["current_branch"] = "main"
    # branch_contains_origin_main_or_pr_merged is not provided (and not needed)
    proof.pop("branch_contains_origin_main_or_pr_merged")
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "ready"
    assert result["blocked_because"] == []
    # Check that we have a "branch_lifecycle_not_required" check that passed
    lifecycle_checks = [
        c for c in result["checks"] if "branch_lifecycle" in c["check"]
    ]
    assert len(lifecycle_checks) == 1
    assert lifecycle_checks[0]["check"] == "branch_lifecycle_not_required"
    assert lifecycle_checks[0]["passed"] is True


def test_non_switch_main_plan_is_unsupported_action(tmp_path):
    # Routing a git-pull-ff-only plan into the switch-main gate must block.
    pull_plan = load_json(
        EXAMPLES_DIR / "action-plans" / "git-pull-ff-only-blocked-dirty-worktree.json"
    )
    result = _run(pull_plan, _ready_proof(), tmp_path)
    assert result["status"] == "blocked"
    assert "unsupported_action" in result["blocked_because"]


def test_hard_failure_dominates_unknown_material(tmp_path):
    proof = _ready_proof()
    proof["worktree_clean"] = False  # hard
    proof.pop("remote_main_fresh")  # unknown
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "blocked"
    assert "worktree_not_clean" in result["blocked_because"]
    # The unknown is still surfaced in failure_reasons but does not soften status.
    assert "remote_freshness_unknown" in result["failure_reasons"]


# ---------------------------------------------------------------------------
# inconclusive — unknown proof material
# ---------------------------------------------------------------------------
def test_missing_repo_toplevel_is_inconclusive(tmp_path):
    proof = _ready_proof()
    proof.pop("repo_toplevel")
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "inconclusive"
    assert result["blocked_because"] == []
    assert "repo_toplevel_unknown" in result["failure_reasons"]
    assert "repo_toplevel" not in result


def test_unknown_default_branch_is_inconclusive(tmp_path):
    proof = _ready_proof()
    proof.pop("default_branch")
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "inconclusive"
    assert "default_branch_unknown" in result["failure_reasons"]


def test_unknown_current_branch_is_inconclusive(tmp_path):
    proof = _ready_proof()
    proof.pop("current_branch")
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "inconclusive"
    assert "current_branch_unknown" in result["failure_reasons"]


@pytest.mark.parametrize(
    "field,reason",
    [
        ("worktree_clean", "worktree_state_unknown"),
        ("remote_main_fresh", "remote_freshness_unknown"),
        ("ownership_ok", "ownership_unknown"),
    ],
)
def test_unknown_boolean_material_is_inconclusive(tmp_path, field, reason):
    proof = _ready_proof()
    proof.pop(field)
    result = _run(_switch_main_plan(), proof, tmp_path)
    assert result["status"] == "inconclusive"
    assert reason in result["failure_reasons"]


# ---------------------------------------------------------------------------
# output-path preconditions and disk behaviour
# ---------------------------------------------------------------------------
def test_artifact_written_to_disk_and_schema_valid(tmp_path):
    out = tmp_path / "readiness.json"
    result = validate_switch_main_readiness(
        action_plan=_switch_main_plan(),
        preflight_proof=_ready_proof(),
        readiness_out=str(out),
    )
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk == result
    validate_instance(on_disk, load_json(_READINESS_SCHEMA), out)


def test_output_path_must_not_pre_exist(tmp_path):
    out = tmp_path / "readiness.json"
    out.write_text("{}")
    with pytest.raises(ValueError):
        validate_switch_main_readiness(
            action_plan=_switch_main_plan(),
            preflight_proof=_ready_proof(),
            readiness_out=str(out),
        )


def test_output_parent_must_exist(tmp_path):
    out = tmp_path / "missing" / "readiness.json"
    with pytest.raises(ValueError):
        validate_switch_main_readiness(
            action_plan=_switch_main_plan(),
            preflight_proof=_ready_proof(),
            readiness_out=str(out),
        )


def test_schema_invalid_proof_raises_and_writes_nothing(tmp_path):
    out = tmp_path / "readiness.json"
    bad_proof = _ready_proof()
    del bad_proof["plan_ref"]  # required by the proof schema
    with pytest.raises(ValueError):
        validate_switch_main_readiness(
            action_plan=_switch_main_plan(),
            preflight_proof=bad_proof,
            readiness_out=str(out),
        )
    assert not out.exists()


def test_schema_invalid_plan_raises(tmp_path):
    out = tmp_path / "readiness.json"
    bad_plan = _switch_main_plan()
    del bad_plan["boundary"]
    with pytest.raises(ValueError):
        validate_switch_main_readiness(
            action_plan=bad_plan,
            preflight_proof=_ready_proof(),
            readiness_out=str(out),
        )
    assert not out.exists()


def test_readiness_id_is_deterministic_and_excludes_checked_at(tmp_path):
    plan = _switch_main_plan()
    first = validate_switch_main_readiness(
        action_plan=plan, preflight_proof=_ready_proof(plan), readiness_out=str(tmp_path / "a.json")
    )
    second = validate_switch_main_readiness(
        action_plan=plan, preflight_proof=_ready_proof(plan), readiness_out=str(tmp_path / "b.json")
    )
    assert first["readiness_id"] == second["readiness_id"]


def test_different_repo_toplevel_yields_different_readiness_id(tmp_path):
    plan = _switch_main_plan()
    proof_a = _ready_proof(plan)
    proof_a["repo_toplevel"] = "/repo/path/alpha"
    proof_b = _ready_proof(plan)
    proof_b["repo_toplevel"] = "/repo/path/beta"
    result_a = validate_switch_main_readiness(
        action_plan=plan, preflight_proof=proof_a, readiness_out=str(tmp_path / "a.json")
    )
    result_b = validate_switch_main_readiness(
        action_plan=plan, preflight_proof=proof_b, readiness_out=str(tmp_path / "b.json")
    )
    assert result_a["readiness_id"] != result_b["readiness_id"]


def test_different_proof_content_yields_different_readiness_id(tmp_path):
    # Two proofs with the same proof_id but different content must produce
    # different readiness_ids — the ID must bind to proof content, not just ref.
    plan = _switch_main_plan()
    proof_clean = _ready_proof(plan)
    proof_clean["proof_id"] = "same-proof-id"
    proof_dirty = _ready_proof(plan)
    proof_dirty["proof_id"] = "same-proof-id"
    proof_dirty["worktree_clean"] = False
    result_clean = validate_switch_main_readiness(
        action_plan=plan, preflight_proof=proof_clean, readiness_out=str(tmp_path / "clean.json")
    )
    result_dirty = validate_switch_main_readiness(
        action_plan=plan, preflight_proof=proof_dirty, readiness_out=str(tmp_path / "dirty.json")
    )
    assert result_clean["readiness_id"] != result_dirty["readiness_id"]


# ---------------------------------------------------------------------------
# boundary guard — the module is pure (no subprocess / no git invocation)
# ---------------------------------------------------------------------------
def test_module_has_no_subprocess_surface():
    # The non-mutating proof layer must never call out to git. The strongest
    # guarantee is structural: the module does not import or reference any
    # subprocess/exec surface at all, so it cannot run switch/checkout/merge/
    # rebase/reset/clean/pull.
    assert not hasattr(_mod, "subprocess")
    source = inspect.getsource(_mod)
    for forbidden in (
        "subprocess.run",
        "subprocess.Popen",
        "Popen(",
        "os.system",
        "shell=True",
        "check_output",
    ):
        assert forbidden not in source, f"forbidden exec surface present: {forbidden!r}"


def test_supported_actions_is_exactly_switch_main():
    assert _mod._SUPPORTED_ACTIONS == frozenset({"switch-main"})


# ---------------------------------------------------------------------------
# example coherence
# ---------------------------------------------------------------------------
def test_proof_examples_validate_against_schema():
    schema = load_json(_PROOF_SCHEMA)
    examples = sorted(_PROOF_EXAMPLES.glob("*.json"))
    assert examples
    for example_path in examples:
        validate_instance(load_json(example_path), schema, example_path)


def test_readiness_examples_validate_against_schema():
    schema = load_json(_READINESS_SCHEMA)
    examples = sorted(_READINESS_EXAMPLES.glob("*.json"))
    assert examples
    for example_path in examples:
        validate_instance(load_json(example_path), schema, example_path)


@pytest.mark.parametrize(
    "proof_name,readiness_name,expected_status",
    [
        ("ready.json", "ready.json", "ready"),
        ("blocked-dirty-worktree.json", "blocked-dirty-worktree.json", "blocked"),
        (
            "inconclusive-default-branch-unknown.json",
            "inconclusive-default-branch-unknown.json",
            "inconclusive",
        ),
    ],
)
def test_readiness_examples_match_function_output(
    tmp_path, proof_name, readiness_name, expected_status
):
    plan = _switch_main_plan()
    proof = load_json(_PROOF_EXAMPLES / proof_name)
    recomputed = _run(plan, proof, tmp_path)
    stored = load_json(_READINESS_EXAMPLES / readiness_name)
    assert recomputed["status"] == expected_status
    # checked_at is wall-clock; everything else (incl. readiness_id) is stable.
    recomputed.pop("checked_at")
    stored.pop("checked_at")
    assert recomputed == stored


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------
def _cli(args, tmp_path):
    return subprocess.run(
        [sys.executable, "-m", "steuerboard", *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )


def test_cli_ready_exit_zero(tmp_path):
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(_ready_proof()))
    out = tmp_path / "readiness.json"
    proc = _cli(
        [
            "action",
            "validate-switch-main-readiness",
            str(_SWITCH_MAIN_PLAN_PATH),
            "--preflight-proof",
            str(proof_path),
            "--readiness-out",
            str(out),
            "--json",
        ],
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "ready"
    assert out.exists()


def test_cli_blocked_exit_zero(tmp_path):
    proof = _ready_proof()
    proof["worktree_clean"] = False
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(proof))
    out = tmp_path / "readiness.json"
    proc = _cli(
        [
            "action",
            "validate-switch-main-readiness",
            str(_SWITCH_MAIN_PLAN_PATH),
            "--preflight-proof",
            str(proof_path),
            "--readiness-out",
            str(out),
            "--json",
        ],
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "blocked"
    assert "worktree_not_clean" in result["blocked_because"]


def test_cli_precondition_emits_sentinel_writes_no_file(tmp_path):
    out = tmp_path / "readiness.json"
    proc = _cli(
        [
            "action",
            "validate-switch-main-readiness",
            str(_SWITCH_MAIN_PLAN_PATH),
            "--preflight-proof",
            str(tmp_path / "does-not-exist.json"),
            "--readiness-out",
            str(out),
            "--json",
        ],
        tmp_path,
    )
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["status"] == "inconclusive"
    assert result["schema_version"] == "switch-main-readiness.v1"
    assert not out.exists()


# ---------------------------------------------------------------------------
# cross-cutting capability guards — no new mutating surface
# ---------------------------------------------------------------------------
def test_validate_switch_main_readiness_is_derivation_only():
    by_command = {command: klass for command, klass, _ in surface.collect_surface()[1]}
    assert by_command["action validate-switch-main-readiness"] == "derivation_only"


def test_stage_d_has_exactly_two_mutating_executors():
    # Phase 9B added the switch-main executor; Stage D now holds exactly two
    # bounded mutating commands and no more.
    by_command = {command: klass for command, klass, _ in surface.collect_surface()[1]}
    mutating = sorted(c for c, k in by_command.items() if k == "mutating_stage_d")
    assert mutating == ["action run-git-pull-ff-only", "action run-switch-main"]


def test_switch_main_runner_command_exists_and_is_mutating():
    parser_commands = {
        " ".join(path) for path, _ in surface._iter_leaf_commands(build_parser())
    }
    assert "action run-switch-main" in parser_commands
    by_command = {command: klass for command, klass, _ in surface.collect_surface()[1]}
    assert by_command["action run-switch-main"] == "mutating_stage_d"


def test_plan_switch_main_stays_derivation_only():
    by_command = {command: klass for command, klass, _ in surface.collect_surface()[1]}
    assert by_command["plan switch-main"] == "derivation_only"
