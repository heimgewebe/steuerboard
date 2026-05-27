"""Tests for Phase 8B: run_postchecks.py — read-only postcheck for git-status-read-only."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.action_runs import _EXCERPT_LIMIT, run_read_only_action
from steuerboard.run_postchecks import _validate_trace_command, run_read_only_postcheck


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


def _trace_schema() -> dict:
    return load_json(SCHEMAS_DIR / "command-trace.v1.schema.json")


def _run_result_schema() -> dict:
    return load_json(SCHEMAS_DIR / "run-result.v1.schema.json")


def _postcheck_schema() -> dict:
    return load_json(SCHEMAS_DIR / "run-postcheck.v1.schema.json")


def _cli(args: list[str], cwd: Path):
    import os
    import subprocess

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}:{existing}"
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)


def _run_action_and_get_artifacts(repo: Path, artifacts_dir: Path) -> tuple[dict, dict, Path, Path]:
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


def test_validate_trace_command_happy_path():
    cmd = ["git", "--no-optional-locks", "-C", "/some/repo", "status", "--porcelain=v1"]
    toplevel = _validate_trace_command(cmd)
    assert toplevel == "/some/repo"


def test_validate_trace_command_wrong_length():
    with pytest.raises(ValueError, match="exactly"):
        _validate_trace_command(["git", "status"])


def test_validate_trace_command_wrong_subcommand():
    cmd = ["git", "--no-optional-locks", "-C", "/repo", "fetch", "--porcelain=v1"]
    with pytest.raises(ValueError, match=r"command\[4\]"):
        _validate_trace_command(cmd)


def test_validate_trace_command_empty_toplevel():
    cmd = ["git", "--no-optional-locks", "-C", "", "status", "--porcelain=v1"]
    with pytest.raises(ValueError, match="non-empty"):
        _validate_trace_command(cmd)


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

    assert postcheck_path.exists()
    written = json.loads(postcheck_path.read_text(encoding="utf-8"))
    validate_instance(postcheck, _postcheck_schema(), Path("postcheck.json"))
    validate_instance(written, _postcheck_schema(), Path("postcheck-written.json"))
    assert postcheck == written
    assert postcheck["status"] == "passed"
    assert postcheck["redaction_verified"] is True
    assert postcheck["run_id"] == run_result["run_id"]
    assert postcheck["trace_ref"] == trace["trace_id"]
    assert str(trace_path) in postcheck["evidence_paths"]
    assert str(result_path) in postcheck["evidence_paths"]


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


def test_blocked_postcheck_out_parent_missing(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    with pytest.raises(ValueError, match="parent directory must exist"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(tmp_path / "missing" / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )


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


def test_cli_emits_schema_valid_output(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()
    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    postcheck_path = postchecks / "postcheck-cli.json"

    run_result_path = artifacts / "run-result.json"
    trace_path = artifacts / "trace.json"
    proc = _cli(
        [
            "python",
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
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    validate_instance(payload, _postcheck_schema(), Path("cli-postcheck.json"))
    assert payload["status"] == "passed"
    assert postcheck_path.exists()


class _FakeSubprocessModule:
    """Minimal subprocess module replacement for monkeypatching run_postchecks.

    Passes the first ``pass_through_calls`` calls to the real subprocess.run,
    then returns ``recheck_result`` for all subsequent calls.  ``PIPE`` is
    forwarded from the real subprocess module so that the production code can
    use ``stdout=subprocess.PIPE`` without AttributeError.
    """

    PIPE = subprocess.PIPE

    def __init__(self, real_run, recheck_result: subprocess.CompletedProcess, *, pass_through_calls: int = 2):
        self._real_run = real_run
        self._recheck_result = recheck_result
        self._call_count = 0
        self._pass_through_calls = pass_through_calls

    def run(self, cmd, **kwargs):
        self._call_count += 1
        if self._call_count <= self._pass_through_calls:
            return self._real_run(cmd, **kwargs)
        return self._recheck_result


def test_inconclusive_when_new_status_output_is_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    import steuerboard.run_postchecks as rpc

    monkeypatch.setattr(
        rpc,
        "subprocess",
        _FakeSubprocessModule(
            rpc.subprocess.run,
            recheck_result=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="M file.txt\n" * (_EXCERPT_LIMIT + 1),
                stderr="",
            ),
        ),
    )

    postcheck_path = postchecks / "postcheck.json"
    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postcheck_path),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck["status"] == "inconclusive"
    assert "stdout_excerpt_truncated" in postcheck["failure_reasons"]


def test_inconclusive_when_original_trace_excerpt_reaches_limit(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    # Simulate a trace whose excerpt is exactly at the truncation boundary
    trace["stdout_excerpt"] = "x" * _EXCERPT_LIMIT

    postcheck_path = postchecks / "postcheck.json"
    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postcheck_path),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck["status"] == "inconclusive"
    assert "stdout_excerpt_truncated" in postcheck["failure_reasons"]


def test_inconclusive_when_recheck_git_status_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    import steuerboard.run_postchecks as rpc

    monkeypatch.setattr(
        rpc,
        "subprocess",
        _FakeSubprocessModule(
            rpc.subprocess.run,
            recheck_result=subprocess.CompletedProcess(
                args=[],
                returncode=128,
                stdout="",
                stderr="fatal: not a git repository",
            ),
        ),
    )

    postcheck_path = postchecks / "postcheck.json"
    postcheck = run_read_only_postcheck(
        run_result=run_result,
        command_trace=trace,
        repo_path=str(repo),
        postcheck_out=str(postcheck_path),
        command_trace_path=str(trace_path),
        run_result_path=str(result_path),
    )

    assert postcheck["status"] == "inconclusive"
    assert "postcheck_command_failed" in postcheck["failure_reasons"]


def test_blocked_postcheck_out_inside_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)

    with pytest.raises(ValueError, match="must not be inside"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(repo / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )


def test_blocked_when_trace_command_not_hardened(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    run_result, trace, trace_path, result_path = _run_action_and_get_artifacts(repo, artifacts)
    # Replace the hardened git-status command with git-fetch (not allowed)
    trace["command"] = [
        "git",
        "--no-optional-locks",
        "-C",
        str(repo.resolve()),
        "fetch",
        "--porcelain=v1",
    ]

    with pytest.raises(ValueError, match="command"):
        run_read_only_postcheck(
            run_result=run_result,
            command_trace=trace,
            repo_path=str(repo),
            postcheck_out=str(postchecks / "postcheck.json"),
            command_trace_path=str(trace_path),
            run_result_path=str(result_path),
        )


def test_cli_postcheck_invalid_run_result_json_emits_inconclusive(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    _run_action_and_get_artifacts(repo, artifacts)

    bad_result = artifacts / "run-result.json"
    bad_result.write_text("not valid json", encoding="utf-8")

    proc = _cli(
        [
            "python",
            "-m",
            "steuerboard",
            "action",
            "postcheck-read-only",
            str(bad_result),
            "--command-trace",
            str(artifacts / "trace.json"),
            "--repo-path",
            str(repo),
            "--postcheck-out",
            str(postchecks / "postcheck.json"),
            "--json",
        ],
        cwd=ROOT,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    validate_instance(payload, _postcheck_schema(), Path("cli-postcheck-bad-result.json"))
    assert payload["status"] == "inconclusive"
    assert any("invalid_run_result_json" in r for r in payload["failure_reasons"])


def test_cli_postcheck_invalid_command_trace_json_emits_inconclusive(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    postchecks = tmp_path / "postchecks"
    postchecks.mkdir()

    _run_action_and_get_artifacts(repo, artifacts)

    bad_trace = artifacts / "trace.json"
    bad_trace.write_text("not valid json", encoding="utf-8")

    proc = _cli(
        [
            "python",
            "-m",
            "steuerboard",
            "action",
            "postcheck-read-only",
            str(artifacts / "run-result.json"),
            "--command-trace",
            str(bad_trace),
            "--repo-path",
            str(repo),
            "--postcheck-out",
            str(postchecks / "postcheck.json"),
            "--json",
        ],
        cwd=ROOT,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    validate_instance(payload, _postcheck_schema(), Path("cli-postcheck-bad-trace.json"))
    assert payload["status"] == "inconclusive"
    assert any("invalid_command_trace_json" in r for r in payload["failure_reasons"])