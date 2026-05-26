"""Tests for Phase 8B: run_postchecks.py — read-only postcheck for git-status-read-only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.action_runs import run_read_only_action
from steuerboard.run_postchecks import (
    _EXCERPT_LIMIT,
    _HARDENED_COMMAND_FIXED,
    _HARDENED_COMMAND_LEN,
    _validate_trace_command,
    run_read_only_postcheck,
)


# ---------------------------------------------------------------------------
# Helpers shared with action_runs tests
# ---------------------------------------------------------------------------


def _run(command: list[str], cwd: Path) -> None:
    import subprocess

    subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.email", "test@example.invalid"], path)
    _run(["git", "config", "user.name", "Test User"], path)
    _run(["git", "config", "commit.gpgsign", "false"], path)
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    _run(["git", "add", "README.md"], path)
    _run(["git", "commit", "-m", "init"], path)


def _pilot_plan(action: str = "git-status-read-only") -> dict:
    return {
        "schema_version": "action-plan.v1",
        "plan_id": f"plan-{action}-test-001",
        "action": action,
        "assessment_ref": "assess-test-001",
        "decision": "not_applicable",
        "source_refs": ["git.status_porcelain"],
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


def _run_action_and_get_artifacts(
    repo: Path, artifacts_dir: Path
) -> tuple[dict, dict, Path, Path]:
    """Run the Phase 8A action runner and return (run_result, trace, trace_path, result_path)."""
    trace_path = artifacts_dir / "trace.json"
    result_path = artifacts_dir / "run-result.json"
    run_read_only_action(
        action_plan=_pilot_plan(),
        repo_path=str(repo),
        command_trace_out=str(trace_path),
        run_result_out=str(result_path),
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    run_result = json.loads(result_path.read_text(encoding="utf-8"))
    return run_result, trace, trace_path, result_path


def _postcheck_schema() -> dict:
    return load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json")


def _cli(args: list[str], cwd: Path):
    import os
    import subprocess

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}:{existing}"
    return subprocess.run(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )


# ---------------------------------------------------------------------------
# Unit: _validate_trace_command
# ---------------------------------------------------------------------------


def test_validate_trace_command_happy_path():
    cmd = ["git", "--no-optional-locks", "-C", "/some/repo", "status", "--porcelain=v1"]
    toplevel = _validate_trace_command(cmd)
    assert toplevel == "/some/repo"


def test_validate_trace_command_wrong_length():
    with pytest.raises(ValueError, match="exactly"):
        _validate_trace_command(["git", "status"])


def test_validate_trace_command_wrong_subcommand():
    cmd = ["git", "--no-optional-locks", "-C", "/repo", "fetch", "--porcelain=v1"]
    with pytest.raises(ValueError, match="command\\[4\\]"):
        _validate_trace_command(cmd)


def test_validate_trace_command_wrong_format_flag():
    cmd = ["git", "--no-optional-locks", "-C", "/repo", "status", "--short"]
    with pytest.raises(ValueError, match="command\\[5\\]"):
        _validate_trace_command(cmd)


def test_validate_trace_command_empty_toplevel():
    cmd = ["git", "--no-optional-locks", "-C", "", "status", "--porcelain=v1"]
    with pytest.raises(ValueError, match="non-empty"):
        _validate_trace_command(cmd)


def test_hardened_command_constants_are_stable():
    """The hardened command structure constants must not be changed without a phase review."""
    assert _HARDENED_COMMAND_LEN == 6
    assert _HARDENED_COMMAND_FIXED[0] == "git"
    assert _HARDENED_COMMAND_FIXED[1] == "--no-optional-locks"
    assert _HARDENED_COMMAND_FIXED[2] == "-C"
    assert _HARDENED_COMMAND_FIXED[4] == "status"
    assert _HARDENED_COMMAND_FIXED[5] == "--porcelain=v1"


# ---------------------------------------------------------------------------
# Happy path: passing run + trace + same status → run-postcheck.v1 passed
# ---------------------------------------------------------------------------


def test_happy_path_produces_valid_postcheck_passed(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    postcheck_path = postchecks / "postcheck.json"
    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postcheck_path),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck_path.exists(), "postcheck output was not written"
    written = json.loads(postcheck_path.read_text(encoding="utf-8"))

    # Schema validation
    validate_instance(postcheck, _postcheck_schema(), Path("postcheck.json"))
    validate_instance(written, _postcheck_schema(), Path("postcheck-written.json"))

    # Structural assertions
    assert postcheck["schema_version"] == "run-postcheck.v1"
    assert postcheck["status"] == "passed"
    assert postcheck["action"] == "git-status-read-only"
    assert postcheck["run_id"] == run_result["run_id"]
    assert postcheck["trace_ref"] == trace["trace_id"]
    assert postcheck["redaction_verified"] is True
    assert "run-result.v1" in postcheck["source_refs"]
    assert "command-trace.v1" in postcheck["source_refs"]
    assert str(trace_path) in postcheck["evidence_paths"]
    assert str(result_path) in postcheck["evidence_paths"]

    # Returned dict must match written file
    assert postcheck == written


def test_happy_path_repo_toplevel_matches_trace(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postchecks / "postcheck.json"),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck["repo_toplevel"] == str(repo.resolve())


# ---------------------------------------------------------------------------
# Blocked: postcheck_out lies inside the inspected repository
# ---------------------------------------------------------------------------


def test_blocked_postcheck_out_inside_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    with pytest.raises(ValueError, match="must not be inside the inspected repository"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(repo / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )

    # No file written inside the repo
    assert not (repo / "postcheck.json").exists()


# ---------------------------------------------------------------------------
# Blocked: postcheck_out already exists
# ---------------------------------------------------------------------------


def test_blocked_postcheck_out_already_exists(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    existing = postchecks / "postcheck.json"
    existing.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="must not already exist"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(existing),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )

    # Pre-existing file must not be mutated
    assert existing.read_text(encoding="utf-8") == "{}"


# ---------------------------------------------------------------------------
# Blocked: run-result.v1 schema-invalid
# ---------------------------------------------------------------------------


def test_blocked_run_result_schema_invalid(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    _run_action_and_get_artifacts(repo, artifacts)
    trace_path = artifacts / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    # Missing required fields
    bad_run_result = {"schema_version": "run-result.v1"}

    with pytest.raises(ValueError, match="run-result.v1"):
        run_read_only_postcheck(
            run_result=bad_run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(artifacts / "run-result.json"),
        )

    assert not (postchecks / "postcheck.json").exists()


def test_blocked_run_result_status_not_success(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    run_result["status"] = "failure"

    with pytest.raises(ValueError, match="status must be 'success'"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )

    assert not (postchecks / "postcheck.json").exists()


def test_blocked_run_result_missing_trace_evidence_path(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    run_result["evidence_paths"] = [str(result_path)]

    with pytest.raises(ValueError, match="evidence_paths must include"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )

    assert not (postchecks / "postcheck.json").exists()


# ---------------------------------------------------------------------------
# Blocked: command-trace.v1 schema-invalid
# ---------------------------------------------------------------------------


def test_blocked_command_trace_schema_invalid(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    _, _, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    run_result = json.loads(result_path.read_text(encoding="utf-8"))

    # Missing required fields
    bad_trace = {"schema_version": "command-trace.v1"}

    with pytest.raises(ValueError, match="command-trace.v1"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=bad_trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )

    assert not (postchecks / "postcheck.json").exists()


def test_blocked_command_trace_exit_code_nonzero(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    trace["exit_code"] = 1

    with pytest.raises(ValueError, match="exit_code must be 0"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )

    assert not (postchecks / "postcheck.json").exists()


def test_blocked_command_trace_missing_stdout_excerpt(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    trace.pop("stdout_excerpt", None)

    with pytest.raises(ValueError, match="stdout_excerpt is required"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )

    assert not (postchecks / "postcheck.json").exists()


# ---------------------------------------------------------------------------
# Blocked: trace command is not the hardened command
# ---------------------------------------------------------------------------


def test_blocked_trace_command_is_not_hardened(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    _, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    run_result = json.loads(result_path.read_text(encoding="utf-8"))

    # Replace the hardened command with an arbitrary one
    bad_trace = dict(trace)
    bad_trace["command"] = ["git", "-C", str(repo.resolve()), "fetch", "origin"]

    with pytest.raises(ValueError, match="command"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=bad_trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )

    assert not (postchecks / "postcheck.json").exists()


def test_blocked_trace_command_uses_pull(tmp_path: Path):
    """A trace command containing pull must be rejected."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    _, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    run_result = json.loads(result_path.read_text(encoding="utf-8"))

    bad_trace = dict(trace)
    bad_trace["command"] = [
        "git",
        "--no-optional-locks",
        "-C",
        str(repo.resolve()),
        "pull",
        "--ff-only",
    ]

    with pytest.raises(ValueError, match="command"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=bad_trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )


# ---------------------------------------------------------------------------
# Status: failed/inconclusive when re-run status differs from trace excerpt
# ---------------------------------------------------------------------------


def test_failed_when_worktree_changes_after_run(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    # Mutate the worktree AFTER the original run to force a mismatch
    (repo / "newfile.txt").write_text("untracked change\n", encoding="utf-8")

    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postchecks / "postcheck.json"),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck["status"] == "failed"
    assert "worktree_changed_after_run" in postcheck.get("failure_reasons", [])

    # Must still be schema-valid
    validate_instance(postcheck, _postcheck_schema(), Path("postcheck-failed.json"))


def test_inconclusive_when_recheck_git_status_fails(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    import steuerboard.run_postchecks as _module

    original_run = _module.subprocess.run

    class _ProcResult:
        def __init__(self, returncode: int, stdout: str, stderr: str):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def patched_run(args, **kwargs):
        if args[:3] == ["git", "--no-optional-locks", "-C"] and "status" in args:
            return _ProcResult(1, "", "fatal: status failed")
        return original_run(args, **kwargs)

    monkeypatch.setattr(_module.subprocess, "run", patched_run)

    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postchecks / "postcheck.json"),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck["status"] == "inconclusive"
    assert "postcheck_command_failed" in postcheck.get("failure_reasons", [])
    validate_instance(postcheck, _postcheck_schema(), Path("postcheck-inconclusive.json"))


def test_inconclusive_when_new_status_output_is_truncated(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    import steuerboard.run_postchecks as _module

    original_run = _module.subprocess.run

    class _ProcResult:
        def __init__(self, returncode: int, stdout: str, stderr: str):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    # Force a truncated recheck output while keeping command success.
    truncated_stdout = "x" * (_EXCERPT_LIMIT + 1)

    def patched_run(args, **kwargs):
        if args[:3] == ["git", "--no-optional-locks", "-C"] and "status" in args:
            return _ProcResult(0, truncated_stdout, "")
        return original_run(args, **kwargs)

    monkeypatch.setattr(_module.subprocess, "run", patched_run)

    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postchecks / "postcheck.json"),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck["status"] == "inconclusive"
    assert "stdout_excerpt_truncated" in postcheck.get("failure_reasons", [])
    validate_instance(postcheck, _postcheck_schema(), Path("postcheck-truncated-recheck.json"))


def test_inconclusive_when_original_trace_excerpt_reaches_limit(
    tmp_path: Path, monkeypatch
):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    trace["stdout_excerpt"] = "x" * _EXCERPT_LIMIT

    import steuerboard.run_postchecks as _module

    original_run = _module.subprocess.run

    class _ProcResult:
        def __init__(self, returncode: int, stdout: str, stderr: str):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def patched_run(args, **kwargs):
        if args[:3] == ["git", "--no-optional-locks", "-C"] and "status" in args:
            return _ProcResult(0, "x" * _EXCERPT_LIMIT, "")
        return original_run(args, **kwargs)

    monkeypatch.setattr(_module.subprocess, "run", patched_run)

    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postchecks / "postcheck.json"),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck["status"] == "inconclusive"
    assert "stdout_excerpt_truncated" in postcheck.get("failure_reasons", [])
    assert postcheck["status"] != "passed"
    validate_instance(postcheck, _postcheck_schema(), Path("postcheck-truncated-trace.json"))


# ---------------------------------------------------------------------------
# No mutating git command is reachable from the postcheck module
# ---------------------------------------------------------------------------


def test_no_mutating_git_command_reachable(tmp_path: Path, monkeypatch):
    """The postcheck must only invoke bounded read-only git subprocesses."""
    import subprocess as _subprocess

    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    mutating_subcommands = frozenset({
        "pull", "fetch", "push", "merge", "rebase", "reset", "clean",
        "checkout", "switch", "branch", "commit", "add", "rm",
    })
    observed_commands: list[list[str]] = []
    original_run = _subprocess.run

    def patched_run(args, **kwargs):
        if isinstance(args, list) and args:
            observed_commands.append(list(args))
        return original_run(args, **kwargs)

    monkeypatch.setattr(_subprocess, "run", patched_run)

    import steuerboard.run_postchecks as _module
    monkeypatch.setattr(_module.subprocess, "run", patched_run)

    run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postchecks / "postcheck.json"),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    for cmd in observed_commands:
        git_subcommands = [tok for tok in cmd if tok in mutating_subcommands]
        assert git_subcommands == [], (
            f"mutating git subcommand found in subprocess call: {cmd}"
        )


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_postcheck_read_only_success(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    # First produce run artifacts via action run-read-only CLI
    plan = _pilot_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    run_result_cli = _cli(
        [
            sys.executable, "-m", "steuerboard",
            "action", "run-read-only",
            str(plan_path),
            "--repo-path", str(repo),
            "--command-trace-out", str(artifacts / "trace.json"),
            "--run-result-out", str(artifacts / "run-result.json"),
            "--json",
        ],
        cwd=tmp_path,
    )
    assert run_result_cli.returncode == 0, f"action run-read-only failed: {run_result_cli.stderr}"

    # Now run postcheck
    result = _cli(
        [
            sys.executable, "-m", "steuerboard",
            "action", "postcheck-read-only",
            str(artifacts / "run-result.json"),
            "--command-trace", str(artifacts / "trace.json"),
            "--repo-path", str(repo),
            "--postcheck-out", str(postchecks / "postcheck.json"),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, f"postcheck failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert output["schema_version"] == "run-postcheck.v1"
    assert output["status"] == "passed"
    assert output["redaction_verified"] is True

    # Schema validate
    validate_instance(output, _postcheck_schema(), Path("cli-postcheck.json"))

    # Output file written
    assert (postchecks / "postcheck.json").exists()


def test_cli_postcheck_blocked_output_inside_repo(tmp_path: Path):
    """CLI emits schema-valid run-postcheck.v1 with inconclusive status when blocked."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    run_result_cli = _cli(
        [
            sys.executable, "-m", "steuerboard",
            "action", "run-read-only",
            str(plan_path),
            "--repo-path", str(repo),
            "--command-trace-out", str(artifacts / "trace.json"),
            "--run-result-out", str(artifacts / "run-result.json"),
            "--json",
        ],
        cwd=tmp_path,
    )
    assert run_result_cli.returncode == 0

    result = _cli(
        [
            sys.executable, "-m", "steuerboard",
            "action", "postcheck-read-only",
            str(artifacts / "run-result.json"),
            "--command-trace", str(artifacts / "trace.json"),
            "--repo-path", str(repo),
            "--postcheck-out", str(repo / "postcheck.json"),  # inside repo — blocked
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    validate_instance(output, _postcheck_schema(), Path("cli-blocked-postcheck.json"))
    assert output["schema_version"] == "run-postcheck.v1"
    assert output["status"] == "inconclusive"
    assert isinstance(output["failure_reasons"], list)
    assert len(output["failure_reasons"]) >= 1

    # No postcheck written inside the repo
    assert not (repo / "postcheck.json").exists()


def test_cli_postcheck_help_works(tmp_path: Path):
    result = _cli(
        [sys.executable, "-m", "steuerboard", "action", "postcheck-read-only", "--help"],
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "postcheck-read-only" in result.stdout or "run_result_json" in result.stdout


def test_cli_postcheck_invalid_run_result_json_emits_inconclusive(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    trace_path = tmp_path / "trace.json"
    run_result_path = tmp_path / "run-result.json"
    postcheck_path = tmp_path / "postcheck.json"

    # Invalid JSON payload in run-result input.
    run_result_path.write_text("{", encoding="utf-8")
    trace_path.write_text("{}", encoding="utf-8")

    result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "postcheck-read-only",
            str(run_result_path),
            "--command-trace",
            str(trace_path),
            "--repo-path",
            str(repo),
            "--postcheck-out",
            str(postcheck_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    validate_instance(output, _postcheck_schema(), Path("cli-invalid-run-result-postcheck.json"))
    assert output["status"] == "inconclusive"
    assert output["failure_reasons"][0].startswith("invalid_run_result_json:")


def test_cli_postcheck_invalid_command_trace_json_emits_inconclusive(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    trace_path = tmp_path / "trace.json"
    run_result_path = tmp_path / "run-result.json"
    postcheck_path = tmp_path / "postcheck.json"

    run_result_path.write_text("{}", encoding="utf-8")
    trace_path.write_text("{", encoding="utf-8")

    result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "postcheck-read-only",
            str(run_result_path),
            "--command-trace",
            str(trace_path),
            "--repo-path",
            str(repo),
            "--postcheck-out",
            str(postcheck_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    validate_instance(
        output, _postcheck_schema(), Path("cli-invalid-command-trace-postcheck.json")
    )
    assert output["status"] == "inconclusive"
    assert output["failure_reasons"][0].startswith("invalid_command_trace_json:")


# ---------------------------------------------------------------------------
# Schema-level example validation
# ---------------------------------------------------------------------------


def test_example_run_postcheck_passed_is_valid():
    postcheck_path = ROOT / "examples" / "run-postchecks" / "git-status-read-only-passed.json"
    assert postcheck_path.exists(), f"example not found: {postcheck_path}"
    postcheck = load_json(postcheck_path)
    schema = load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json")
    validate_instance(postcheck, schema, postcheck_path)
    assert postcheck["status"] == "passed"
    assert postcheck["action"] == "git-status-read-only"
    assert postcheck["redaction_verified"] is True


def test_example_run_postcheck_inconclusive_is_valid():
    postcheck_path = (
        ROOT / "examples" / "run-postchecks" / "git-status-read-only-inconclusive.json"
    )
    assert postcheck_path.exists(), f"example not found: {postcheck_path}"
    postcheck = load_json(postcheck_path)
    schema = load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json")
    validate_instance(postcheck, schema, postcheck_path)
    assert postcheck["status"] == "inconclusive"
    assert postcheck["action"] == "git-status-read-only"


def test_example_run_postcheck_failed_is_valid():
    postcheck_path = ROOT / "examples" / "run-postchecks" / "git-status-read-only-failed.json"
    assert postcheck_path.exists(), f"example not found: {postcheck_path}"
    postcheck = load_json(postcheck_path)
    schema = load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json")
    validate_instance(postcheck, schema, postcheck_path)
    assert postcheck["status"] == "failed"
    assert "worktree_changed_after_run" in postcheck.get("failure_reasons", [])
