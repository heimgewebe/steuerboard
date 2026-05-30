"""Tests for Phase 9B: Stage-D switch-main executor (action_switch_main).

These tests prove the bounded switch-main executor is tightly gated:
- it runs only for ``action == "switch-main"``;
- it refuses unless a ``ready`` switch-main-readiness, a ``binding_valid``
  approval validation, the repo path, and the output preconditions all pass;
- it reproduces the mutation-critical live state immediately before mutation;
- it performs exactly one allowed mutating command (``git switch main``) and is
  structurally incapable of running arbitrary Git commands;
- it emits command-trace, run-result, and postcheck artifacts;
- ``run-git-pull-ff-only`` and ``run-switch-main`` are the only mutating
  Stage-D commands.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import steuerboard.action_switch_main as _mod
from scripts.docmeta import generate_cli_surface as surface
from scripts.validate_examples import (
    EXAMPLES_DIR,
    SCHEMAS_DIR,
    load_json,
    validate_instance,
)
from steuerboard.action_switch_main import (
    _GIT_SWITCH_MAIN_ARGV,
    _resolve_git_toplevel,
    run_switch_main,
)
from steuerboard.action_switch_main_readiness import validate_switch_main_readiness
from steuerboard.canonical_json import canonical_json_sha256
from steuerboard.cli import build_parser

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SWITCH_MAIN_PLAN_PATH = EXAMPLES_DIR / "action-plans" / "switch-main-blocked.json"

# Git subcommands this executor must never contain as command tokens.
_FORBIDDEN_GIT_SUBCOMMANDS = {
    "pull",
    "fetch",
    "push",
    "merge",
    "rebase",
    "reset",
    "clean",
    "checkout",
    "cherry-pick",
    "revert",
    "stash",
}


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _init_repo(path: Path, initial_branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", initial_branch], path)
    _run(["git", "config", "user.email", "test@example.invalid"], path)
    _run(["git", "config", "user.name", "Test User"], path)
    _run(["git", "config", "commit.gpgsign", "false"], path)
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    _run(["git", "add", "README.md"], path)
    _run(["git", "commit", "-m", "init"], path)
    return path


def _repo_on_feature(path: Path, branch: str = "feature/x") -> Path:
    """A repo where ``main`` exists and HEAD is on a feature branch."""
    _init_repo(path, "main")
    _run(["git", "switch", "-c", branch], path)
    return path


def _toplevel(repo: Path) -> str:
    return str(_resolve_git_toplevel(str(repo)))


def _live_branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Artifact builders
# ---------------------------------------------------------------------------
def _switch_main_plan() -> dict:
    return load_json(_SWITCH_MAIN_PLAN_PATH)


def _ready_proof(plan: dict, *, repo_toplevel: str, current_branch: str = "feature/x", **overrides) -> dict:
    proof = {
        "schema_version": "switch-main-preflight-proof.v1",
        "proof_id": "switch-main-proof-test",
        "checked_at": "2026-05-30T12:00:00Z",
        "plan_ref": plan["plan_id"],
        "plan_action": "switch-main",
        "plan_content_sha256": canonical_json_sha256(plan),
        "repo_toplevel": repo_toplevel,
        "current_branch": current_branch,
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
    if current_branch == "main":
        # On main the lifecycle proof is not required (and absent in the proof).
        proof.pop("branch_contains_origin_main_or_pr_merged", None)
    proof.update(overrides)
    return proof


def _make_readiness(tmp_path: Path, plan: dict, proof: dict) -> dict:
    out = tmp_path / f"readiness-{uuid.uuid4().hex}.json"
    return validate_switch_main_readiness(
        action_plan=plan, preflight_proof=proof, readiness_out=str(out)
    )


def _approval_validation(plan: dict, **overrides) -> dict:
    approval = {
        "schema_version": "action-approval-validation.v1",
        "validation_id": "validation-switch-main-test-001",
        "plan_ref": plan["plan_id"],
        "plan_content_sha256": canonical_json_sha256(plan),
        "approval_ref": "approval-switch-main-test-001",
        "action": "switch-main",
        "checked_at": "2026-05-30T12:00:00Z",
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
    approval.update(overrides)
    return approval


def _call_run(
    tmp_path: Path,
    *,
    repo: Path,
    plan: dict | None = None,
    approval: dict | None = None,
    readiness: dict | None = None,
    current_branch: str = "feature/x",
    trace_out: str | None = None,
    result_out: str | None = None,
    postcheck_out: str | None = None,
) -> dict:
    plan = plan if plan is not None else _switch_main_plan()
    if readiness is None:
        proof = _ready_proof(plan, repo_toplevel=_toplevel(repo), current_branch=current_branch)
        readiness = _make_readiness(tmp_path, plan, proof)
    approval = approval if approval is not None else _approval_validation(plan)
    return run_switch_main(
        action_plan=plan,
        approval_validation=approval,
        switch_main_readiness=readiness,
        repo_path=str(repo),
        command_trace_out=trace_out or str(tmp_path / "trace.json"),
        run_result_out=result_out or str(tmp_path / "result.json"),
        postcheck_out=postcheck_out or str(tmp_path / "postcheck.json"),
    )


# ---------------------------------------------------------------------------
# Static guard tests — no free shell, exact argv, no forbidden commands
# ---------------------------------------------------------------------------
def test_no_shell_true_in_source():
    """run_switch_main must never pass shell=True in code (not comments/docstrings)."""
    tree = ast.parse(inspect.getsource(_mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant):
                    assert kw.value.value is not True, "shell=True found in action_switch_main.py"


def test_no_generic_command_runner_surface():
    """No os.system / Popen / check_output / check_call free-command surface."""
    src = inspect.getsource(_mod)
    for forbidden in ("os.system", "subprocess.Popen", "Popen(", "check_output", "check_call", "shell=True,"):
        assert forbidden not in src, f"forbidden command surface present: {forbidden!r}"


def test_switch_main_argv_is_exact_bounded_switch():
    """The single mutating argv must be exactly the bounded switch to main."""
    assert _GIT_SWITCH_MAIN_ARGV == ("--no-optional-locks", "switch", "main")
    joined = " ".join(_GIT_SWITCH_MAIN_ARGV)
    for forbidden in _FORBIDDEN_GIT_SUBCOMMANDS:
        assert forbidden not in joined


def test_no_forbidden_git_subcommand_literals():
    """No string literal in the module equals a forbidden git subcommand token.

    Docstrings/comments may *mention* git verbs in prose, but no individual
    command token may be one of the forbidden mutating subcommands.
    """
    tree = ast.parse(inspect.getsource(_mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in _FORBIDDEN_GIT_SUBCOMMANDS, (
                f"forbidden git subcommand literal: {node.value!r}"
            )


# ---------------------------------------------------------------------------
# Precondition rejection tests
# ---------------------------------------------------------------------------
def test_rejects_wrong_plan_action(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    bad_plan = copy.deepcopy(_switch_main_plan())
    bad_plan["action"] = "git-pull-ff-only"
    bad_plan["plan_id"] = "plan-wrong-action"
    with pytest.raises(ValueError, match="action_plan.action"):
        # readiness/approval built for the real switch-main plan; the wrong plan
        # is rejected on the action gate first.
        _call_run(tmp_path, repo=repo, plan=bad_plan,
                  approval=_approval_validation(_switch_main_plan()),
                  readiness=_make_readiness(
                      tmp_path, _switch_main_plan(),
                      _ready_proof(_switch_main_plan(), repo_toplevel=_toplevel(repo))))


def test_rejects_approval_not_binding_valid(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    bad_approval = _approval_validation(_switch_main_plan(), binding_state="binding_invalid",
                                        blocked_because=["approval_rejected"])
    with pytest.raises(ValueError, match="binding_state"):
        _call_run(tmp_path, repo=repo, approval=bad_approval)


def test_rejects_approval_plan_ref_mismatch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    bad_approval = _approval_validation(_switch_main_plan(), plan_ref="plan-some-other")
    with pytest.raises(ValueError, match="plan_ref"):
        _call_run(tmp_path, repo=repo, approval=bad_approval)


def test_rejects_approval_action_mismatch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    bad_approval = _approval_validation(_switch_main_plan(), action="git-pull-ff-only")
    with pytest.raises(ValueError, match="approval_validation.action"):
        _call_run(tmp_path, repo=repo, approval=bad_approval)


def test_rejects_approval_plan_content_sha256_mismatch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    bad_approval = _approval_validation(_switch_main_plan(), plan_content_sha256="0" * 64)
    with pytest.raises(ValueError, match="approval_validation_plan_content_sha256_mismatch"):
        _call_run(tmp_path, repo=repo, approval=bad_approval)


def test_rejects_readiness_not_ready(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    plan = _switch_main_plan()
    # A dirty-worktree proof yields a blocked readiness verdict.
    proof = _ready_proof(plan, repo_toplevel=_toplevel(repo), worktree_clean=False)
    readiness = _make_readiness(tmp_path, plan, proof)
    assert readiness["status"] == "blocked"
    with pytest.raises(ValueError, match="readiness gate not satisfied"):
        _call_run(tmp_path, repo=repo, readiness=readiness)


def test_rejects_readiness_action_mismatch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    plan = _switch_main_plan()
    readiness = _make_readiness(
        tmp_path, plan, _ready_proof(plan, repo_toplevel=_toplevel(repo))
    )
    readiness["action"] = "git-pull-ff-only"
    with pytest.raises(ValueError, match="switch_main_readiness.action"):
        _call_run(tmp_path, repo=repo, readiness=readiness)


def test_rejects_readiness_plan_ref_mismatch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    plan = _switch_main_plan()
    readiness = _make_readiness(
        tmp_path, plan, _ready_proof(plan, repo_toplevel=_toplevel(repo))
    )
    readiness["plan_ref"] = "plan-some-other-switch-main"
    with pytest.raises(ValueError, match="switch_main_readiness.plan_ref"):
        _call_run(tmp_path, repo=repo, readiness=readiness)


def test_rejects_readiness_content_hash_mismatch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    plan = _switch_main_plan()
    readiness = _make_readiness(
        tmp_path, plan, _ready_proof(plan, repo_toplevel=_toplevel(repo))
    )
    # Tamper the recorded plan-content hash so it no longer matches this plan.
    for check in readiness["checks"]:
        if check["check"] == "proof_plan_content_sha256_matches_plan":
            check["expected"] = "0" * 64
    with pytest.raises(ValueError, match="plan_content_sha256_mismatch"):
        _call_run(tmp_path, repo=repo, readiness=readiness)


def test_rejects_repo_toplevel_mismatch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    plan = _switch_main_plan()
    readiness = _make_readiness(
        tmp_path, plan, _ready_proof(plan, repo_toplevel="/wrong/path")
    )
    assert readiness["status"] == "ready"
    with pytest.raises(ValueError, match="repo_toplevel_mismatch"):
        _call_run(tmp_path, repo=repo, readiness=readiness)


def test_rejects_existing_output_file_trace(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    pre = tmp_path / "trace.json"
    pre.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already exist"):
        _call_run(tmp_path, repo=repo, trace_out=str(pre))


def test_rejects_existing_output_file_run_result(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    pre = tmp_path / "result.json"
    pre.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already exist"):
        _call_run(tmp_path, repo=repo, result_out=str(pre))


def test_rejects_existing_output_file_postcheck(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    pre = tmp_path / "postcheck.json"
    pre.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already exist"):
        _call_run(tmp_path, repo=repo, postcheck_out=str(pre))


def test_rejects_output_inside_repo_worktree(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    with pytest.raises(ValueError, match="inside the repository worktree"):
        _call_run(tmp_path, repo=repo, trace_out=str(repo / "trace.json"))


def test_rejects_duplicate_output_path_trace_equals_result(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    shared = str(tmp_path / "shared.json")
    with pytest.raises(ValueError, match="same file"):
        _call_run(tmp_path, repo=repo, trace_out=shared, result_out=shared)


def test_rejects_duplicate_output_path_trace_equals_postcheck(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    shared = str(tmp_path / "shared.json")
    with pytest.raises(ValueError, match="same file"):
        _call_run(tmp_path, repo=repo, trace_out=shared, postcheck_out=shared)


def test_rejects_duplicate_output_path_result_equals_postcheck(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    shared = str(tmp_path / "shared.json")
    with pytest.raises(ValueError, match="same file"):
        _call_run(tmp_path, repo=repo, result_out=shared, postcheck_out=shared)


def test_rejects_dirty_worktree_before_switch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    with pytest.raises(ValueError, match="worktree is not clean"):
        _call_run(tmp_path, repo=repo)
    assert not (tmp_path / "trace.json").exists()
    assert not (tmp_path / "result.json").exists()
    assert not (tmp_path / "postcheck.json").exists()


def test_rejects_detached_head_before_switch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()
    _run(["git", "switch", "--detach", head], repo)
    with pytest.raises(ValueError, match="detached HEAD"):
        _call_run(tmp_path, repo=repo)


def test_rejects_non_main_branch_without_lifecycle_proof(tmp_path):
    """Readiness computed while on main cannot authorise leaving a live non-main branch.

    After current_branch binding: readiness.current_branch == 'main' != live 'feature/x',
    so branch_current_mismatch fires before the lifecycle proof check.
    """
    repo = _repo_on_feature(tmp_path / "repo")  # live HEAD = feature/x
    plan = _switch_main_plan()
    # Readiness proof claims current_branch == main → no branch_lifecycle_proof check.
    readiness = _make_readiness(
        tmp_path, plan, _ready_proof(plan, repo_toplevel=_toplevel(repo), current_branch="main")
    )
    assert readiness["status"] == "ready"
    assert readiness.get("current_branch") == "main"
    assert not any(c["check"] == "branch_lifecycle_proof" for c in readiness["checks"])
    with pytest.raises(ValueError, match="branch_current_mismatch"):
        _call_run(tmp_path, repo=repo, readiness=readiness)
    assert not (tmp_path / "trace.json").exists()


def test_rejects_readiness_for_different_branch(tmp_path):
    """Readiness attested for feature/a but live repo is on feature/b → blocked, no mutation."""
    repo = _repo_on_feature(tmp_path / "repo", branch="feature/b")
    plan = _switch_main_plan()
    # Proof (and therefore readiness) claims current_branch == "feature/a";
    # the live repository is on "feature/b".
    proof = _ready_proof(plan, repo_toplevel=_toplevel(repo), current_branch="feature/a")
    readiness = _make_readiness(tmp_path, plan, proof)
    assert readiness["status"] == "ready"
    assert readiness.get("current_branch") == "feature/a"
    with pytest.raises(ValueError, match="branch_current_mismatch"):
        _call_run(tmp_path, repo=repo, readiness=readiness)
    assert not (tmp_path / "trace.json").exists()
    assert not (tmp_path / "result.json").exists()
    assert not (tmp_path / "postcheck.json").exists()
    assert _live_branch(repo) == "feature/b"  # no mutation occurred


def test_no_output_on_precondition_failure(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    bad_approval = _approval_validation(_switch_main_plan(), binding_state="binding_invalid",
                                        blocked_because=["approval_rejected"])
    with pytest.raises(ValueError):
        _call_run(tmp_path, repo=repo, approval=bad_approval)
    assert not (tmp_path / "trace.json").exists()
    assert not (tmp_path / "result.json").exists()
    assert not (tmp_path / "postcheck.json").exists()


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------
def test_executes_exactly_one_switch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy_run(args, **kwargs):
        if isinstance(args, (list, tuple)) and "switch" in args:
            calls.append(list(args))
        return real_run(args, **kwargs)

    with patch("steuerboard.action_switch_main.subprocess.run", side_effect=spy_run):
        _call_run(tmp_path, repo=repo)

    assert len(calls) == 1, f"expected exactly one switch call, got: {calls}"
    assert calls[0] == ["git", "--no-optional-locks", "-C", _toplevel(repo), "switch", "main"]


def test_happy_path_switch_produces_valid_artifacts(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    assert _live_branch(repo) == "feature/x"

    result = _call_run(tmp_path, repo=repo)

    trace = json.loads((tmp_path / "trace.json").read_text(encoding="utf-8"))
    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))

    validate_instance(trace, load_json(SCHEMAS_DIR / "command-trace.v1.schema.json"), tmp_path / "trace.json")
    validate_instance(run_res, load_json(SCHEMAS_DIR / "run-result.v1.schema.json"), tmp_path / "result.json")
    validate_instance(postcheck, load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json"), tmp_path / "postcheck.json")

    assert result == run_res
    assert run_res["status"] == "success"
    assert run_res["action"] == "switch-main"
    assert run_res["plan_ref"] == _switch_main_plan()["plan_id"]
    assert postcheck["status"] == "passed"
    assert postcheck["action"] == "switch-main"
    assert trace["command"] == ["git", "--no-optional-locks", "-C", _toplevel(repo), "switch", "main"]
    # Branch actually changed to main.
    assert _live_branch(repo) == "main"
    obs = postcheck["observations"]
    assert any("feature/x" in o for o in obs)
    assert any("main" in o for o in obs)


def test_allows_switch_with_lifecycle_proof_from_non_main(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    plan = _switch_main_plan()
    readiness = _make_readiness(
        tmp_path, plan,
        _ready_proof(plan, repo_toplevel=_toplevel(repo), current_branch="feature/x"),
    )
    assert any(
        c["check"] == "branch_lifecycle_proof" and c["passed"] for c in readiness["checks"]
    )
    result = _call_run(tmp_path, repo=repo, readiness=readiness)
    assert result["status"] == "success"
    assert _live_branch(repo) == "main"


def test_switch_already_on_main_is_passed(tmp_path):
    repo = _init_repo(tmp_path / "repo", "main")  # HEAD already on main
    plan = _switch_main_plan()
    readiness = _make_readiness(
        tmp_path, plan,
        _ready_proof(plan, repo_toplevel=_toplevel(repo), current_branch="main"),
    )
    result = _call_run(tmp_path, repo=repo, readiness=readiness)
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert result["status"] == "success"
    assert postcheck["status"] == "passed"
    assert _live_branch(repo) == "main"


def test_switch_failure_records_failure_not_blocked(tmp_path):
    """If ``git switch main`` fails (no main branch), status is failure, not blocked."""
    repo = _init_repo(tmp_path / "repo", "feature/x")  # no main branch exists
    assert _live_branch(repo) == "feature/x"
    result = _call_run(tmp_path, repo=repo)
    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert result["status"] == "failure"
    assert "blocked_reasons" not in run_res
    assert postcheck["status"] == "failed"
    assert "switch_exit_code_nonzero" in postcheck["failure_reasons"]


def test_postcheck_failed_when_not_on_main_after_switch(tmp_path):
    """Switch reports success but HEAD did not move to main → failed."""
    repo = _repo_on_feature(tmp_path / "repo")
    real_run = subprocess.run

    def mock_noop_switch(args, **kwargs):
        if isinstance(args, (list, tuple)) and "switch" in args and "main" in args:
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        return real_run(args, **kwargs)

    with patch("steuerboard.action_switch_main.subprocess.run", side_effect=mock_noop_switch):
        _call_run(tmp_path, repo=repo)

    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert run_res["status"] == "failure"
    assert postcheck["status"] == "failed"
    assert "not_on_main_after_switch" in postcheck["failure_reasons"]


def test_postcheck_failed_dirty_after_switch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    real_run = subprocess.run
    status_calls: list[int] = []

    def mock_dirty_post_status(args, **kwargs):
        if isinstance(args, (list, tuple)) and "status" in args and "--porcelain=v1" in args:
            status_calls.append(1)
            if len(status_calls) >= 2:  # post-switch status → simulate dirty
                return SimpleNamespace(returncode=0, stdout=b" M README.md\n", stderr=b"")
        return real_run(args, **kwargs)

    with patch("steuerboard.action_switch_main.subprocess.run", side_effect=mock_dirty_post_status):
        _call_run(tmp_path, repo=repo)

    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert run_res["status"] == "failure"
    assert postcheck["status"] == "failed"
    assert "worktree_not_clean_after_switch" in postcheck["failure_reasons"]


def test_postcheck_inconclusive_when_branch_unreadable_after_switch(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    real_run = subprocess.run
    abbrev_calls = {"count": 0}

    def mock_branch_unreadable(args, **kwargs):
        if isinstance(args, (list, tuple)) and "--abbrev-ref" in args and "HEAD" in args:
            abbrev_calls["count"] += 1
            if abbrev_calls["count"] >= 2:  # post-switch branch read → fail
                return SimpleNamespace(returncode=128, stdout=b"", stderr=b"fatal")
        return real_run(args, **kwargs)

    with patch("steuerboard.action_switch_main.subprocess.run", side_effect=mock_branch_unreadable):
        _call_run(tmp_path, repo=repo)

    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert run_res["status"] == "success"
    assert postcheck["status"] == "inconclusive"
    assert "branch_unreadable_after_switch" in postcheck["failure_reasons"]


def test_trace_redacted_and_run_result_redaction_verified(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    _call_run(tmp_path, repo=repo)
    trace = json.loads((tmp_path / "trace.json").read_text(encoding="utf-8"))
    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert trace["redacted"] is True
    assert run_res["redaction_verified"] is True


# ---------------------------------------------------------------------------
# Example artifact validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("filename", [
    "run-switch-main-success.json",
    "run-switch-main-blocked-not-ready.json",
])
def test_run_result_switch_main_examples_validate(filename):
    schema = load_json(SCHEMAS_DIR / "run-result.v1.schema.json")
    path = EXAMPLES_DIR / "run-results" / filename
    validate_instance(load_json(path), schema, path)


def test_postcheck_switch_main_example_validates():
    schema = load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json")
    path = EXAMPLES_DIR / "run-postchecks" / "switch-main-passed.json"
    validate_instance(load_json(path), schema, path)


def test_trace_switch_main_example_validates():
    schema = load_json(SCHEMAS_DIR / "command-trace.v1.schema.json")
    path = EXAMPLES_DIR / "evidence" / "command-trace-switch-main-success.json"
    validate_instance(load_json(path), schema, path)


def test_approval_validation_switch_main_example_validates():
    schema = load_json(SCHEMAS_DIR / "action-approval-validation.v1.schema.json")
    path = EXAMPLES_DIR / "action-approval-validations" / "switch-main-binding-valid.json"
    validate_instance(load_json(path), schema, path)


def test_switch_main_success_example_matches_plan_hash():
    """The example run-result plan hash must equal the canonical hash of the plan."""
    plan = _switch_main_plan()
    run_res = load_json(EXAMPLES_DIR / "run-results" / "run-switch-main-success.json")
    assert run_res["plan_content_sha256"] == canonical_json_sha256(plan)


# ---------------------------------------------------------------------------
# CLI surface guards
# ---------------------------------------------------------------------------
def test_run_switch_main_is_mutating_stage_d():
    by_command = {command: klass for command, klass, _ in surface.collect_surface()[1]}
    assert by_command["action run-switch-main"] == "mutating_stage_d"


def test_exactly_two_mutating_stage_d_executors():
    by_command = {command: klass for command, klass, _ in surface.collect_surface()[1]}
    mutating = sorted(c for c, k in by_command.items() if k == "mutating_stage_d")
    assert mutating == ["action run-git-pull-ff-only", "action run-switch-main"]


def test_run_switch_main_command_exists_in_parser():
    parser_commands = {" ".join(path) for path, _ in surface._iter_leaf_commands(build_parser())}
    assert "action run-switch-main" in parser_commands


# ---------------------------------------------------------------------------
# CLI behaviour (subprocess)
# ---------------------------------------------------------------------------
def _cli(args: list[str]):
    return subprocess.run(
        [sys.executable, "-m", "steuerboard", *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )


def test_cli_run_switch_main_success(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    plan = _switch_main_plan()
    readiness = _make_readiness(
        tmp_path, plan, _ready_proof(plan, repo_toplevel=_toplevel(repo))
    )
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(_approval_validation(plan)), encoding="utf-8")

    trace_out = tmp_path / "trace.json"
    result_out = tmp_path / "result.json"
    postcheck_out = tmp_path / "postcheck.json"

    proc = _cli([
        "action", "run-switch-main", str(_SWITCH_MAIN_PLAN_PATH),
        "--approval-validation", str(approval_path),
        "--switch-main-readiness", str(readiness_path),
        "--repo-path", str(repo),
        "--command-trace-out", str(trace_out),
        "--run-result-out", str(result_out),
        "--postcheck-out", str(postcheck_out),
        "--json",
    ])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "success"
    assert result["action"] == "switch-main"
    assert trace_out.exists() and result_out.exists() and postcheck_out.exists()
    assert _live_branch(repo) == "main"


def test_cli_run_switch_main_blocked_sentinel_writes_no_files(tmp_path):
    repo = _repo_on_feature(tmp_path / "repo")
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(_approval_validation(_switch_main_plan())), encoding="utf-8")
    trace_out = tmp_path / "trace.json"
    result_out = tmp_path / "result.json"
    postcheck_out = tmp_path / "postcheck.json"

    proc = _cli([
        "action", "run-switch-main", str(_SWITCH_MAIN_PLAN_PATH),
        "--approval-validation", str(approval_path),
        "--switch-main-readiness", str(tmp_path / "does-not-exist.json"),
        "--repo-path", str(repo),
        "--command-trace-out", str(trace_out),
        "--run-result-out", str(result_out),
        "--postcheck-out", str(postcheck_out),
        "--json",
    ])
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["schema_version"] == "run-result.v1"
    assert result["status"] == "blocked"
    assert result["action"] == "switch-main"
    assert not trace_out.exists()
    assert not result_out.exists()
    assert not postcheck_out.exists()
    assert _live_branch(repo) == "feature/x"  # no mutation occurred


def test_cli_run_switch_main_via_real_approval_validate_path(tmp_path):
    """run-switch-main succeeds when the approval_validation comes from the real 'approval validate' CLI.

    This test exercises the full approval chain:
      action-approval.v1 → approval validate → action-approval-validation.v1 → run-switch-main
    ensuring the official approval producer path works end-to-end for switch-main.
    """
    repo = _repo_on_feature(tmp_path / "repo")
    plan = _switch_main_plan()

    # Build an action-approval.v1 for switch-main against the example plan.
    approval = {
        "schema_version": "action-approval.v1",
        "approval_id": "approval-test-switch-main-real-path-001",
        "plan_ref": plan["plan_id"],
        "plan_content_sha256": canonical_json_sha256(plan),
        "action": "switch-main",
        "decision": "approved",
        "decided_at": "2026-05-30T10:00:00Z",
        "approver_ref": "user:test",
        "source_refs": [],
        "approval_scope": {
            "single_plan_only": True,
            "no_plan_substitution": True,
            "no_command_substitution": True,
        },
        "expires_at": "2026-05-30T23:59:59Z",
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

    approval_file = tmp_path / "approval.json"
    approval_file.write_text(json.dumps(approval), encoding="utf-8")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")

    # Run the real approval validate CLI to produce action-approval-validation.v1.
    approval_validation_file = tmp_path / "approval-validation.json"
    validate_proc = _cli([
        "approval", "validate",
        str(approval_file),
        "--plan", str(plan_file),
        "--checked-at", "2026-05-30T12:00:00Z",
        "--json",
    ])
    assert validate_proc.returncode == 0, validate_proc.stderr
    approval_validation = json.loads(validate_proc.stdout)
    assert approval_validation["binding_state"] == "binding_valid", (
        f"Expected binding_valid but got: {approval_validation}"
    )
    assert approval_validation["plan_content_sha256"] == canonical_json_sha256(plan)
    approval_validation_file.write_text(json.dumps(approval_validation), encoding="utf-8")

    # Build readiness and run run-switch-main with the real approval validation.
    readiness = _make_readiness(
        tmp_path, plan, _ready_proof(plan, repo_toplevel=_toplevel(repo))
    )
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")

    trace_out = tmp_path / "trace.json"
    result_out = tmp_path / "result.json"
    postcheck_out = tmp_path / "postcheck.json"

    proc = _cli([
        "action", "run-switch-main", str(_SWITCH_MAIN_PLAN_PATH),
        "--approval-validation", str(approval_validation_file),
        "--switch-main-readiness", str(readiness_path),
        "--repo-path", str(repo),
        "--command-trace-out", str(trace_out),
        "--run-result-out", str(result_out),
        "--postcheck-out", str(postcheck_out),
        "--json",
    ])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "success"
    assert result["action"] == "switch-main"
    assert _live_branch(repo) == "main"
