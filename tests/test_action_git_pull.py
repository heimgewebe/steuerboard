"""Tests for Phase 8E: Stage-D git-pull-ff-only executor (action_git_pull)."""
from __future__ import annotations

import ast
import copy
import inspect
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import steuerboard.action_git_pull as _mod
from scripts.validate_examples import (
    EXAMPLES_DIR,
    ROOT,
    SCHEMAS_DIR,
    load_json,
    validate_instance,
)
from steuerboard.action_git_pull import (
    _GIT_PULL_FF_ONLY_ARGV,
    run_git_pull_ff_only,
)
from steuerboard.canonical_json import canonical_json_sha256

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_PLAN = load_json(EXAMPLES_DIR / "action-plans" / "git-pull-ff-only-approval-binding-base.json")
_APPROVAL_VALIDATION = {
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
    EXAMPLES_DIR / "run-evidence-chains" / "git-status-read-only-valid-with-preflight-proof.json"
)
_BINDING_VALID = load_json(
    EXAMPLES_DIR / "action-preflight-bindings" / "git-pull-ff-only-binding-valid.json"
)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _init_repo(path: Path) -> None:
    """Create a minimal local git repository."""
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.email", "test@example.invalid"], path)
    _run(["git", "config", "user.name", "Test User"], path)
    _run(["git", "config", "commit.gpgsign", "false"], path)
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    _run(["git", "add", "README.md"], path)
    _run(["git", "commit", "-m", "init"], path)


def _clone_from(source: Path, dest: Path) -> None:
    """Clone source into dest so that dest has origin and can pull."""
    subprocess.run(
        ["git", "clone", str(source), str(dest)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _run(["git", "config", "user.email", "test@example.invalid"], dest)
    _run(["git", "config", "user.name", "Test User"], dest)
    _run(["git", "config", "commit.gpgsign", "false"], dest)


def _add_commit(repo: Path, filename: str = "extra.txt", content: str = "extra\n") -> None:
    """Add a new file + commit to repo."""
    (repo / filename).write_text(content, encoding="utf-8")
    _run(["git", "add", filename], repo)
    _run(["git", "commit", "-m", f"add {filename}"], repo)


def _get_head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Helper that builds the chain with preflight_for_action_plan referencing
# the canonical _PLAN content sha256
# ---------------------------------------------------------------------------

def _chain_with_preflight(base_chain: dict | None = None) -> dict:
    chain = copy.deepcopy(base_chain or _CHAIN_VALID)
    plan_sha = canonical_json_sha256(_PLAN)
    chain["preflight_for_action_plan"] = {
        "plan_ref": _PLAN["plan_id"],
        "plan_action": "git-pull-ff-only",
        "plan_content_sha256": plan_sha,
    }
    return chain


# ---------------------------------------------------------------------------
# Helpers to call run_git_pull_ff_only with pre-arranged file paths
# ---------------------------------------------------------------------------


def _call_run(
    tmp_path: Path,
    *,
    repo: Path | None = None,
    action_plan: dict | None = None,
    approval_validation: dict | None = None,
    run_evidence_chain: dict | None = None,
    preflight_binding: dict | None = None,
) -> dict:
    if repo is None:
        repo = tmp_path / "repo"
        _init_repo(repo)
    return run_git_pull_ff_only(
        action_plan=action_plan or _PLAN,
        approval_validation=approval_validation or _APPROVAL_VALIDATION,
        run_evidence_chain=run_evidence_chain if run_evidence_chain is not None else _chain_with_preflight(),
        preflight_binding=preflight_binding or _BINDING_VALID,
        repo_path=str(repo),
        command_trace_out=str(tmp_path / "trace.json"),
        run_result_out=str(tmp_path / "result.json"),
        postcheck_out=str(tmp_path / "postcheck.json"),
    )


# ---------------------------------------------------------------------------
# Static guard tests
# ---------------------------------------------------------------------------


def test_no_shell_true_in_source():
    """run_git_pull_ff_only must never pass shell=True in code (not comments/docstrings)."""
    src = inspect.getsource(_mod)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "shell":
                    # Check if the value is True literal
                    if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        pytest.fail("shell=True found in a subprocess call in action_git_pull.py")


def test_no_generic_subprocess_run_call():
    """No subprocess.run call in action_git_pull must pass shell=True."""
    src = inspect.getsource(_mod)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                for kw in node.keywords:
                    if kw.arg == "shell":
                        assert not (
                            isinstance(kw.value, ast.Constant) and kw.value.value is True
                        ), "shell=True found in subprocess.run call in action_git_pull.py"


def test_git_pull_argv_no_merge_or_rebase():
    """The hard-coded git pull argv must be --ff-only only."""
    args_str = " ".join(_GIT_PULL_FF_ONLY_ARGV)
    assert "--ff-only" in args_str
    assert "--no-ff" not in args_str
    assert "merge" not in args_str.lower()
    assert "rebase" not in args_str.lower()
    assert "reset" not in args_str.lower()
    assert "clean" not in args_str.lower()


# ---------------------------------------------------------------------------
# Precondition rejection tests (no git repo needed for most)
# ---------------------------------------------------------------------------


def test_rejects_wrong_plan_action(tmp_path):
    """action_plan.action != git-pull-ff-only must raise ValueError."""
    bad_plan = copy.deepcopy(_PLAN)
    bad_plan["action"] = "git-status-read-only"
    with pytest.raises(ValueError, match="action_plan.action"):
        _call_run(tmp_path, action_plan=bad_plan)


def test_rejects_binding_state_not_binding_valid(tmp_path):
    """preflight_binding.binding_state != binding_valid must raise ValueError."""
    bad_binding = copy.deepcopy(_BINDING_VALID)
    bad_binding["binding_state"] = "blocked"
    with pytest.raises(ValueError, match="binding_state"):
        _call_run(tmp_path, preflight_binding=bad_binding)


def test_rejects_binding_without_preflight_proof(tmp_path):
    """preflight_binding missing preflight_for_action_plan proof must raise ValueError."""
    bad_binding = copy.deepcopy(_BINDING_VALID)
    bad_binding.pop("preflight_for_action_plan", None)
    bad_binding["binding_state"] = "binding_valid"
    with pytest.raises(ValueError, match="preflight_for_action_plan"):
        _call_run(tmp_path, preflight_binding=bad_binding)


def test_rejects_existing_output_file_trace(tmp_path):
    """Raises ValueError if command_trace_out already exists."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    pre = tmp_path / "trace.json"
    pre.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        run_git_pull_ff_only(
            action_plan=_PLAN,
            approval_validation=_APPROVAL_VALIDATION,
            run_evidence_chain=_chain_with_preflight(),
            preflight_binding=_BINDING_VALID,
            repo_path=str(repo),
            command_trace_out=str(pre),
            run_result_out=str(tmp_path / "result.json"),
            postcheck_out=str(tmp_path / "postcheck.json"),
        )


def test_rejects_existing_output_file_run_result(tmp_path):
    """Raises ValueError if run_result_out already exists."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    pre = tmp_path / "result.json"
    pre.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        run_git_pull_ff_only(
            action_plan=_PLAN,
            approval_validation=_APPROVAL_VALIDATION,
            run_evidence_chain=_chain_with_preflight(),
            preflight_binding=_BINDING_VALID,
            repo_path=str(repo),
            command_trace_out=str(tmp_path / "trace.json"),
            run_result_out=str(pre),
            postcheck_out=str(tmp_path / "postcheck.json"),
        )


def test_rejects_output_inside_repo_worktree(tmp_path):
    """Output paths inside the repo worktree must raise ValueError."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    with pytest.raises(ValueError, match="inside.*repo"):
        run_git_pull_ff_only(
            action_plan=_PLAN,
            approval_validation=_APPROVAL_VALIDATION,
            run_evidence_chain=_chain_with_preflight(),
            preflight_binding=_BINDING_VALID,
            repo_path=str(repo),
            command_trace_out=str(repo / "trace.json"),
            run_result_out=str(tmp_path / "result.json"),
            postcheck_out=str(tmp_path / "postcheck.json"),
        )


def test_no_output_on_precondition_failure(tmp_path):
    """When a precondition fails, no output files must be created."""
    bad_plan = copy.deepcopy(_PLAN)
    bad_plan["action"] = "git-status-read-only"
    with pytest.raises(ValueError):
        _call_run(tmp_path, action_plan=bad_plan)
    assert not (tmp_path / "trace.json").exists()
    assert not (tmp_path / "result.json").exists()
    assert not (tmp_path / "postcheck.json").exists()


# ---------------------------------------------------------------------------
# Readiness-gate enforcement
# ---------------------------------------------------------------------------


def test_rejects_when_readiness_not_ready(tmp_path):
    """Runner must call validate_execution_readiness and reject if status != ready."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    # Use a rejected approval → readiness will be blocked
    rejected_approval = copy.deepcopy(_APPROVAL_VALIDATION)
    rejected_approval["binding_state"] = "rejected"
    rejected_approval.pop("blocked_because", None)
    with pytest.raises(ValueError):
        _call_run(tmp_path, repo=repo, approval_validation=rejected_approval)


def test_rejects_binding_state_not_valid_in_preflight(tmp_path):
    """Binding with binding_state != binding_valid must raise before readiness gate."""
    bad_binding = copy.deepcopy(_BINDING_VALID)
    bad_binding["binding_state"] = "inconclusive"
    with pytest.raises(ValueError, match="binding_state"):
        _call_run(tmp_path, preflight_binding=bad_binding)


# ---------------------------------------------------------------------------
# Execution tests (require a two-repo setup with origin)
# ---------------------------------------------------------------------------


def _setup_pull_repos(tmp_path: Path):
    """Set up an upstream repo with one commit ahead of local clone."""
    upstream = tmp_path / "upstream"
    local = tmp_path / "local"
    _init_repo(upstream)
    _clone_from(upstream, local)
    # Advance upstream by one commit
    _add_commit(upstream, "new.txt", "new\n")
    return upstream, local


def test_executes_exactly_one_pull_ff_only(tmp_path):
    """Run must issue exactly one git pull --ff-only subprocess call."""
    _, local = _setup_pull_repos(tmp_path)

    calls = []
    real_run = subprocess.run

    def spy_run(args, **kwargs):
        if isinstance(args, (list, tuple)) and "pull" in args:
            calls.append(list(args))
        return real_run(args, **kwargs)

    with patch("steuerboard.action_git_pull.subprocess.run", side_effect=spy_run):
        _call_run(tmp_path, repo=local)

    pull_calls = [c for c in calls if "--ff-only" in c]
    assert len(pull_calls) == 1, f"Expected exactly 1 pull --ff-only call, got: {calls}"


def test_happy_path_fast_forward_produces_valid_artifacts(tmp_path):
    """Successful ff-only pull produces schema-valid trace, result, postcheck."""
    _, local = _setup_pull_repos(tmp_path)
    head_before = _get_head(local)

    result = _call_run(tmp_path, repo=local)

    trace_schema = load_json(SCHEMAS_DIR / "command-trace.v1.schema.json")
    result_schema = load_json(SCHEMAS_DIR / "run-result.v1.schema.json")
    postcheck_schema = load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json")

    trace = json.loads((tmp_path / "trace.json").read_text(encoding="utf-8"))
    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))

    validate_instance(trace, trace_schema, tmp_path / "trace.json")
    validate_instance(run_res, result_schema, tmp_path / "result.json")
    validate_instance(postcheck, postcheck_schema, tmp_path / "postcheck.json")

    assert run_res["status"] == "success"
    assert run_res["action"] == "git-pull-ff-only"
    assert postcheck["status"] == "passed"
    assert postcheck["action"] == "git-pull-ff-only"

    # HEAD must have advanced
    head_after = _get_head(local)
    assert head_before != head_after

    # Observations in postcheck must record both HEAD values
    obs_strs = postcheck.get("observations", [])
    assert any(head_before in o for o in obs_strs), f"head_before not in observations: {obs_strs}"
    assert any(head_after in o for o in obs_strs), f"head_after not in observations: {obs_strs}"


def test_postcheck_passed_after_fast_forward(tmp_path):
    """Postcheck must be passed when FF pull advances HEAD."""
    _, local = _setup_pull_repos(tmp_path)
    _call_run(tmp_path, repo=local)
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert postcheck["status"] == "passed"


def test_already_up_to_date_produces_inconclusive_postcheck(tmp_path):
    """When already up to date, postcheck must be inconclusive (not success)."""
    _, local = _setup_pull_repos(tmp_path)
    # Pull first to advance local to same as upstream
    subprocess.run(["git", "-C", str(local), "pull", "--ff-only"], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    result = _call_run(tmp_path, repo=local)
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert postcheck["status"] == "inconclusive"
    failure_reasons = postcheck.get("failure_reasons", [])
    # HEAD didn't change → either already_up_to_date or head_unchanged_after_pull
    assert any(
        r in ("already_up_to_date", "head_unchanged_after_pull")
        or "already_up_to_date" in r
        or "head_unchanged" in r
        for r in failure_reasons
    ), f"Expected up-to-date inconclusive reason, got: {failure_reasons}"


def test_failed_ff_only_not_possible(tmp_path):
    """If git pull --ff-only fails (non-zero), run_result.status == failure."""
    upstream = tmp_path / "upstream"
    local = tmp_path / "local"
    _init_repo(upstream)
    _clone_from(upstream, local)

    # Diverge local and upstream (both add different commits on main)
    _add_commit(upstream, "upstream.txt", "upstream\n")
    _add_commit(local, "local.txt", "local\n")

    result = _call_run(tmp_path, repo=local)

    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))

    assert run_res["status"] == "failure"
    assert postcheck["status"] == "failed"
    assert any("pull_exit_code_nonzero" in r for r in postcheck.get("failure_reasons", []))


def test_postcheck_failed_dirty_after_pull(tmp_path):
    """If worktree is unclean after pull, run_result=failure, postcheck=failed."""
    _, local = _setup_pull_repos(tmp_path)

    # We mock the post-pull status check to return dirty output on second call
    real_run = subprocess.run
    _status_calls: list[int] = []

    def mock_dirty_status(args, **kwargs):
        if (
            isinstance(args, (list, tuple))
            and "status" in args
            and "--porcelain=v1" in args
        ):
            _status_calls.append(1)
            if len(_status_calls) >= 2:
                # Second status call (post-pull): simulate dirty
                from types import SimpleNamespace
                return SimpleNamespace(returncode=0, stdout=b" M README.md\n", stderr=b"")
        return real_run(args, **kwargs)

    with patch("steuerboard.action_git_pull.subprocess.run", side_effect=mock_dirty_status):
        _call_run(tmp_path, repo=local)

    run_res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert run_res["status"] == "failure"
    assert postcheck["status"] == "failed"
    failure_reasons = postcheck.get("failure_reasons", [])
    assert any("worktree_not_clean_after_pull" in r for r in failure_reasons)


def test_postcheck_inconclusive_when_head_unreadable(tmp_path):
    """If HEAD is unreadable after pull, postcheck must be inconclusive."""
    _, local = _setup_pull_repos(tmp_path)

    real_run = subprocess.run
    calls = {"count": 0}

    def mock_head_unreadable(args, **kwargs):
        if isinstance(args, (list, tuple)) and "rev-parse" in args and "HEAD" in args:
            calls["count"] += 1
            if calls["count"] >= 2:
                # Second rev-parse HEAD call (after pull) → fail
                from types import SimpleNamespace
                return SimpleNamespace(returncode=128, stdout=b"", stderr=b"fatal: not a git repo")
        return real_run(args, **kwargs)

    with patch("steuerboard.action_git_pull.subprocess.run", side_effect=mock_head_unreadable):
        _call_run(tmp_path, repo=local)

    postcheck = json.loads((tmp_path / "postcheck.json").read_text(encoding="utf-8"))
    assert postcheck["status"] == "inconclusive"
    failure_reasons = postcheck.get("failure_reasons", [])
    assert any("head_unreadable_after_pull" in r for r in failure_reasons)


# ---------------------------------------------------------------------------
# Schema validation of new example artifacts
# ---------------------------------------------------------------------------


def _postcheck_schema():
    return load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json")


def _run_result_schema():
    return load_json(SCHEMAS_DIR / "run-result.v1.schema.json")


def _trace_schema():
    return load_json(SCHEMAS_DIR / "command-trace.v1.schema.json")


def _readiness_schema():
    return load_json(SCHEMAS_DIR / "action-execution-readiness.v1.schema.json")


@pytest.mark.parametrize("filename", [
    "git-pull-ff-only-passed.json",
    "git-pull-ff-only-failed.json",
    "git-pull-ff-only-inconclusive.json",
])
def test_postcheck_examples_validate(filename):
    schema = _postcheck_schema()
    instance = load_json(EXAMPLES_DIR / "run-postchecks" / filename)
    validate_instance(instance, schema, EXAMPLES_DIR / "run-postchecks" / filename)


@pytest.mark.parametrize("filename", [
    "run-git-pull-ff-only-success.json",
    "run-git-pull-ff-only-blocked-not-ready.json",
])
def test_run_result_examples_validate(filename):
    schema = _run_result_schema()
    instance = load_json(EXAMPLES_DIR / "run-results" / filename)
    validate_instance(instance, schema, EXAMPLES_DIR / "run-results" / filename)


def test_trace_example_validates():
    schema = _trace_schema()
    instance = load_json(EXAMPLES_DIR / "evidence" / "command-trace-git-pull-ff-only-success.json")
    validate_instance(instance, schema, EXAMPLES_DIR / "evidence" / "command-trace-git-pull-ff-only-success.json")


def test_readiness_example_validates():
    schema = _readiness_schema()
    instance = load_json(EXAMPLES_DIR / "action-execution-readiness" / "git-pull-ff-only-ready.json")
    validate_instance(instance, schema, EXAMPLES_DIR / "action-execution-readiness" / "git-pull-ff-only-ready.json")
