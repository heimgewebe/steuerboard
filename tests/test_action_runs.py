from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.action_runs import (
    MUTATING_ACTIONS,
    PHASE_8A_ALLOWLIST,
    run_read_only_action,
    _excerpt,
    _EXCERPT_LIMIT,
    _write_artifacts_atomic,
    _GIT_STATUS_COMMAND,
)
from steuerboard.canonical_json import canonical_json_sha256


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(command: list[str], cwd: Path):  # type: ignore[return]
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


def _cli(args: list[str], cwd: Path):
    import subprocess
    import os
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}:{existing}"
    return subprocess.run(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )


# ---------------------------------------------------------------------------
# Phase 8A allowlist / mutating set invariants
# ---------------------------------------------------------------------------

def test_allowlist_contains_exactly_one_pilot():
    assert PHASE_8A_ALLOWLIST == {"git-status-read-only"}


def test_mutating_actions_not_in_allowlist():
    assert MUTATING_ACTIONS.isdisjoint(PHASE_8A_ALLOWLIST)


# ---------------------------------------------------------------------------
# Happy path: allowed read-only action produces valid artifacts
# ---------------------------------------------------------------------------

def test_happy_path_produces_valid_trace_and_run_result(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    trace_path = artifacts / "trace.json"
    result_path = artifacts / "run-result.json"

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_pilot_plan()), encoding="utf-8")

    with plan_path.open() as fh:
        plan = json.load(fh)

    run_result = run_read_only_action(
        action_plan=plan,
        repo_path=str(repo),
        command_trace_out=str(trace_path),
        run_result_out=str(result_path),
    )

    # Both files must exist
    assert trace_path.exists(), "command-trace output was not written"
    assert result_path.exists(), "run-result output was not written"

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))

    # Schema validation
    validate_instance(trace, _trace_schema(), Path("trace.json"))
    validate_instance(result, _run_result_schema(), Path("run-result.json"))

    # Structural assertions
    assert trace["schema_version"] == "command-trace.v1"
    assert trace["redacted"] is True
    assert trace["command"] == [
        "git",
        "--no-optional-locks",
        "-C",
        str(repo.resolve()),
        "status",
        "--porcelain=v1",
    ]
    assert trace["exit_code"] == 0

    assert result["schema_version"] == "run-result.v1"
    assert result["plan_ref"] == plan["plan_id"]
    assert result["plan_content_sha256"] == canonical_json_sha256(plan)
    assert result["status"] == "success"
    assert result["redaction_verified"] is True
    assert len(result["evidence_paths"]) == 1
    assert str(trace_path) in result["evidence_paths"][0]

    # Returned dict must match written file
    assert run_result == result


# ---------------------------------------------------------------------------
# Blocked: mutating actions are rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", sorted(MUTATING_ACTIONS))
def test_mutating_action_is_blocked(tmp_path: Path, action: str):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan(action)
    # Patch decision/blocked_because to keep the plan semantically consistent
    if action == "git-pull-ff-only":
        plan["decision"] = "blocked"
        plan["blocked_because"] = ["git_pull_ff_only_evidence_missing_remote_freshness"]

    with pytest.raises(ValueError, match="mutating action"):
        run_read_only_action(
            action_plan=plan,
            repo_path=str(repo),
            command_trace_out=str(artifacts / "trace.json"),
            run_result_out=str(artifacts / "result.json"),
        )

    # No partial output must be written
    assert not (artifacts / "trace.json").exists()
    assert not (artifacts / "result.json").exists()


def test_unknown_action_is_blocked(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan("some-future-action")
    # Schema validation fires first (unknown action is not in the enum).
    with pytest.raises(ValueError, match="action-plan.v1"):
        run_read_only_action(
            action_plan=plan,
            repo_path=str(repo),
            command_trace_out=str(artifacts / "trace.json"),
            run_result_out=str(artifacts / "result.json"),
        )

    assert not (artifacts / "trace.json").exists()
    assert not (artifacts / "result.json").exists()


# ---------------------------------------------------------------------------
# Blocked: output files already exist
# ---------------------------------------------------------------------------

def test_blocked_trace_file_already_exists(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    trace_path = artifacts / "trace.json"
    trace_path.write_text("{}", encoding="utf-8")  # pre-existing

    with pytest.raises(ValueError, match="must not already exist"):
        run_read_only_action(
            action_plan=_pilot_plan(),
            repo_path=str(repo),
            command_trace_out=str(trace_path),
            run_result_out=str(artifacts / "result.json"),
        )

    # The existing file must not be mutated
    assert trace_path.read_text(encoding="utf-8") == "{}"


def test_blocked_run_result_file_already_exists(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    result_path = artifacts / "result.json"
    result_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="must not already exist"):
        run_read_only_action(
            action_plan=_pilot_plan(),
            repo_path=str(repo),
            command_trace_out=str(artifacts / "trace.json"),
            run_result_out=str(result_path),
        )

    assert not (artifacts / "trace.json").exists()


# ---------------------------------------------------------------------------
# Blocked: output parent directory missing
# ---------------------------------------------------------------------------

def test_blocked_trace_parent_missing(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    with pytest.raises(ValueError, match="parent directory must exist"):
        run_read_only_action(
            action_plan=_pilot_plan(),
            repo_path=str(repo),
            command_trace_out=str(tmp_path / "nonexistent" / "trace.json"),
            run_result_out=str(tmp_path / "nonexistent" / "result.json"),
        )


def test_blocked_run_result_parent_missing(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    with pytest.raises(ValueError, match="parent directory must exist"):
        run_read_only_action(
            action_plan=_pilot_plan(),
            repo_path=str(repo),
            command_trace_out=str(artifacts / "trace.json"),
            run_result_out=str(tmp_path / "missing" / "result.json"),
        )

    assert not (artifacts / "trace.json").exists()


# ---------------------------------------------------------------------------
# stdout/stderr excerpt truncation
# ---------------------------------------------------------------------------

def test_excerpt_truncates_at_limit():
    long_text = "x" * (_EXCERPT_LIMIT + 500)
    result = _excerpt(long_text)
    assert len(result) == _EXCERPT_LIMIT


def test_excerpt_preserves_short_text():
    short = "hello world"
    assert _excerpt(short) == short


def test_stdout_excerpt_in_trace_is_bounded(tmp_path: Path):
    """Even if git status somehow returned a huge output, the excerpt must be bounded."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    run_read_only_action(
        action_plan=_pilot_plan(),
        repo_path=str(repo),
        command_trace_out=str(artifacts / "trace.json"),
        run_result_out=str(artifacts / "result.json"),
    )

    trace = json.loads((artifacts / "trace.json").read_text(encoding="utf-8"))
    assert len(trace.get("stdout_excerpt", "")) <= _EXCERPT_LIMIT
    assert len(trace.get("stderr_excerpt", "")) <= _EXCERPT_LIMIT


# ---------------------------------------------------------------------------
# Schema-level example validation
# ---------------------------------------------------------------------------

def test_example_action_plan_git_status_read_only_is_valid():
    plan_path = ROOT / "examples" / "action-plans" / "git-status-read-only-pilot.json"
    assert plan_path.exists(), f"example not found: {plan_path}"
    plan = load_json(plan_path)
    schema = load_json(SCHEMAS_DIR / "action-plan.v1.schema.json")
    validate_instance(plan, schema, plan_path)
    assert plan["action"] == "git-status-read-only"


def test_example_command_trace_read_only_pilot_is_valid():
    trace_path = ROOT / "examples" / "evidence" / "command-trace-read-only-pilot.json"
    assert trace_path.exists()
    trace = load_json(trace_path)
    schema = load_json(SCHEMAS_DIR / "command-trace.v1.schema.json")
    validate_instance(trace, schema, trace_path)
    assert trace["redacted"] is True


def test_example_command_trace_read_only_pilot_uses_hardened_command():
    trace_path = ROOT / "examples" / "evidence" / "command-trace-read-only-pilot.json"
    assert trace_path.exists()
    trace = load_json(trace_path)
    assert trace["command"] == [
        "git",
        "--no-optional-locks",
        "-C",
        "/path/to/repo",
        "status",
        "--porcelain=v1",
    ]


def test_example_run_result_read_only_success_is_valid():
    result_path = ROOT / "examples" / "run-results" / "run-read-only-success.json"
    assert result_path.exists()
    result = load_json(result_path)
    schema = load_json(SCHEMAS_DIR / "run-result.v1.schema.json")
    validate_instance(result, schema, result_path)
    assert result["status"] == "success"


def test_example_run_result_read_only_success_unbound_is_still_valid():
    result_path = ROOT / "examples" / "run-results" / "run-read-only-success-unbound.json"
    assert result_path.exists()
    result = load_json(result_path)
    schema = load_json(SCHEMAS_DIR / "run-result.v1.schema.json")
    validate_instance(result, schema, result_path)
    assert result["status"] == "success"


def test_example_run_result_blocked_is_valid():
    result_path = ROOT / "examples" / "run-results" / "run-blocked.json"
    assert result_path.exists()
    result = load_json(result_path)
    schema = load_json(SCHEMAS_DIR / "run-result.v1.schema.json")
    validate_instance(result, schema, result_path)
    assert result["status"] == "blocked"


def test_example_run_result_read_only_blocked_is_valid():
    result_path = ROOT / "examples" / "run-results" / "run-read-only-blocked.json"
    assert result_path.exists()
    result = load_json(result_path)
    schema = load_json(SCHEMAS_DIR / "run-result.v1.schema.json")
    validate_instance(result, schema, result_path)
    assert result["status"] == "blocked"


# ---------------------------------------------------------------------------
# CLI integration: --json output and exit codes
# ---------------------------------------------------------------------------

def test_cli_run_read_only_success(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = _cli(
        [
            sys.executable, "-m", "steuerboard",
            "action", "run-read-only",
            str(plan_path),
            "--repo-path", str(repo),
            "--command-trace-out", str(artifacts / "trace.json"),
            "--run-result-out", str(artifacts / "result.json"),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    output = json.loads(result.stdout)
    assert output["schema_version"] == "run-result.v1"
    assert output["status"] == "success"
    assert output["redaction_verified"] is True


def test_cli_run_read_only_blocked_mutating_action(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan("git-pull-ff-only")
    plan["decision"] = "blocked"
    plan["blocked_because"] = ["git_pull_ff_only_evidence_missing_remote_freshness"]
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = _cli(
        [
            sys.executable, "-m", "steuerboard",
            "action", "run-read-only",
            str(plan_path),
            "--repo-path", str(repo),
            "--command-trace-out", str(artifacts / "trace.json"),
            "--run-result-out", str(artifacts / "result.json"),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    schema = _run_result_schema()
    validate_instance(output, schema, Path("cli-blocked-output.json"))
    assert output["status"] == "blocked"
    assert "blocked_reasons" in output
    assert isinstance(output["blocked_reasons"], list)
    assert len(output["blocked_reasons"]) >= 1
    # No partial output files written
    assert not (artifacts / "trace.json").exists()
    assert not (artifacts / "result.json").exists()


def test_cli_help_works(tmp_path: Path):
    result = _cli(
        [sys.executable, "-m", "steuerboard", "action", "run-read-only", "--help"],
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "run-read-only" in result.stdout or "action_plan_json" in result.stdout


# ---------------------------------------------------------------------------
# New rework tests
# ---------------------------------------------------------------------------

def test_invalid_plan_missing_boundary_is_blocked(tmp_path: Path):
    """An action plan missing required fields must be rejected before execution."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    # Missing required 'boundary' field — schema-invalid
    bad_plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-bad-001",
        "action": "git-status-read-only",
        "assessment_ref": "assess-001",
        "decision": "not_applicable",
        "source_refs": ["git.status_porcelain"],
        "rule_refs": [],
        "freshness_refs": [],
        "falsification_refs": [],
        "missing_evidence": [],
        # boundary is deliberately omitted
    }

    with pytest.raises(ValueError, match="action-plan.v1"):
        run_read_only_action(
            action_plan=bad_plan,
            repo_path=str(repo),
            command_trace_out=str(artifacts / "trace.json"),
            run_result_out=str(artifacts / "result.json"),
        )

    # No output must be written on schema-invalid input
    assert not (artifacts / "trace.json").exists()
    assert not (artifacts / "result.json").exists()


def test_invalid_plan_extra_property_is_blocked(tmp_path: Path):
    """An action plan with additionalProperties must be rejected."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan()
    plan["unexpected_field"] = "should-fail"

    with pytest.raises(ValueError, match="action-plan.v1"):
        run_read_only_action(
            action_plan=plan,
            repo_path=str(repo),
            command_trace_out=str(artifacts / "trace.json"),
            run_result_out=str(artifacts / "result.json"),
        )

    assert not (artifacts / "trace.json").exists()
    assert not (artifacts / "result.json").exists()


def test_invalid_plan_boundary_false_is_blocked(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan()
    plan["boundary"]["does_not_execute"] = False

    with pytest.raises(ValueError, match="action-plan.v1"):
        run_read_only_action(
            action_plan=plan,
            repo_path=str(repo),
            command_trace_out=str(artifacts / "trace.json"),
            run_result_out=str(artifacts / "result.json"),
        )

    assert not (artifacts / "trace.json").exists()
    assert not (artifacts / "result.json").exists()


def test_invalid_plan_empty_source_refs_is_blocked(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan()
    plan["source_refs"] = []

    with pytest.raises(ValueError, match="action-plan.v1"):
        run_read_only_action(
            action_plan=plan,
            repo_path=str(repo),
            command_trace_out=str(artifacts / "trace.json"),
            run_result_out=str(artifacts / "result.json"),
        )

    assert not (artifacts / "trace.json").exists()
    assert not (artifacts / "result.json").exists()


def test_cli_blocked_output_is_schema_valid(tmp_path: Path):
    """The blocked JSON emitted by the CLI must be valid against run-result.v1."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan("git-pull-ff-only")
    plan["decision"] = "blocked"
    plan["blocked_because"] = ["git_pull_ff_only_evidence_missing_remote_freshness"]
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = _cli(
        [
            sys.executable, "-m", "steuerboard",
            "action", "run-read-only",
            str(plan_path),
            "--repo-path", str(repo),
            "--command-trace-out", str(artifacts / "trace.json"),
            "--run-result-out", str(artifacts / "result.json"),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)

    # The output must be schema-valid against run-result.v1
    schema = _run_result_schema()
    validate_instance(output, schema, Path("cli-blocked-output.json"))

    assert output["status"] == "blocked"
    assert "blocked_reasons" in output


def test_trace_command_is_exact_no_optional_locks_porcelain_v1(tmp_path: Path):
    """The trace must record the exact hardened command form."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    run_read_only_action(
        action_plan=_pilot_plan(),
        repo_path=str(repo),
        command_trace_out=str(artifacts / "trace.json"),
        run_result_out=str(artifacts / "result.json"),
    )

    trace = json.loads((artifacts / "trace.json").read_text(encoding="utf-8"))
    cmd = trace["command"]

    expected_command = [
        "git",
        "--no-optional-locks",
        "-C",
        str(repo.resolve()),
        "status",
        "--porcelain=v1",
    ]
    assert cmd == expected_command
    assert tuple(cmd[1:]) == ("--no-optional-locks", "-C", str(repo.resolve()), "status", "--porcelain=v1")


def test_no_partial_final_outputs_on_second_write_failure(tmp_path: Path):
    """If the second replace fails, no final artifacts or temp files remain."""
    import unittest.mock as mock

    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    plan = _pilot_plan()

    replace_calls = 0

    def failing_replace(src, dst):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("simulated failure on second replace")
        return original_replace(src, dst)

    original_replace = _write_artifacts_atomic.__globals__["os"].replace

    with mock.patch("steuerboard.action_runs.os.replace", side_effect=failing_replace):
        with pytest.raises(OSError, match="second replace"):
            run_read_only_action(
                action_plan=plan,
                repo_path=str(repo),
                command_trace_out=str(artifacts / "trace.json"),
                run_result_out=str(artifacts / "result.json"),
            )

    tmp_files = list(artifacts.glob("*.tmp"))
    assert tmp_files == [], f"orphaned temp files found: {tmp_files}"
    assert not (artifacts / "trace.json").exists()
    assert not (artifacts / "result.json").exists()


def test_rejects_identical_trace_and_run_result_paths(tmp_path: Path):
    import unittest.mock as mock

    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    same_path = artifacts / "same.json"

    with mock.patch("steuerboard.action_runs.subprocess.run") as run_mock:
        with pytest.raises(ValueError, match="must be different files"):
            run_read_only_action(
                action_plan=_pilot_plan(),
                repo_path=str(repo),
                command_trace_out=str(same_path),
                run_result_out=str(same_path),
            )
    # Must fail before any git command.
    run_mock.assert_not_called()
    assert not same_path.exists()


def test_cli_rejects_identical_trace_and_run_result_paths_schema_valid(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    same_path = artifacts / "same.json"

    plan = _pilot_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "run-read-only",
            str(plan_path),
            "--repo-path",
            str(repo),
            "--command-trace-out",
            str(same_path),
            "--run-result-out",
            str(same_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    validate_instance(output, _run_result_schema(), Path("cli-identical-paths-blocked.json"))
    assert output["status"] == "blocked"
    assert not same_path.exists()


def test_rejects_trace_output_inside_inspected_repo(tmp_path: Path):
    import unittest.mock as mock

    repo = tmp_path / "repo"
    _init_repo(repo)
    outside = tmp_path / "artifacts"
    outside.mkdir()

    inside_trace = repo / "trace.json"
    outside_result = outside / "result.json"

    def fake_git(command, **kwargs):
        # Allow only preflight checks; status command must never run.
        if command[-2:] == ["rev-parse", "--is-inside-work-tree"]:
            return mock.Mock(returncode=0, stdout="true\n", stderr="")
        if command[-1] == "--show-toplevel":
            return mock.Mock(returncode=0, stdout=f"{repo}\n", stderr="")
        if "status" in command:
            raise AssertionError("git status must not be executed")
        raise AssertionError(f"unexpected git command: {command}")

    with mock.patch("steuerboard.action_runs.subprocess.run", side_effect=fake_git):
        with pytest.raises(ValueError, match="must not be inside the inspected repository"):
            run_read_only_action(
                action_plan=_pilot_plan(),
                repo_path=str(repo),
                command_trace_out=str(inside_trace),
                run_result_out=str(outside_result),
            )

    assert not inside_trace.exists()
    assert not outside_result.exists()


def test_rejects_run_result_output_inside_inspected_repo(tmp_path: Path):
    import unittest.mock as mock

    repo = tmp_path / "repo"
    _init_repo(repo)
    outside = tmp_path / "artifacts"
    outside.mkdir()

    outside_trace = outside / "trace.json"
    inside_result = repo / "result.json"

    def fake_git(command, **kwargs):
        # Allow only preflight checks; status command must never run.
        if command[-2:] == ["rev-parse", "--is-inside-work-tree"]:
            return mock.Mock(returncode=0, stdout="true\n", stderr="")
        if command[-1] == "--show-toplevel":
            return mock.Mock(returncode=0, stdout=f"{repo}\n", stderr="")
        if "status" in command:
            raise AssertionError("git status must not be executed")
        raise AssertionError(f"unexpected git command: {command}")

    with mock.patch("steuerboard.action_runs.subprocess.run", side_effect=fake_git):
        with pytest.raises(ValueError, match="must not be inside the inspected repository"):
            run_read_only_action(
                action_plan=_pilot_plan(),
                repo_path=str(repo),
                command_trace_out=str(outside_trace),
                run_result_out=str(inside_result),
            )

    assert not outside_trace.exists()
    assert not inside_result.exists()


def test_cli_rejects_trace_output_inside_inspected_repo_schema_valid(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    outside = tmp_path / "artifacts"
    outside.mkdir()

    inside_trace = repo / "trace.json"
    outside_result = outside / "result.json"

    plan = _pilot_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "run-read-only",
            str(plan_path),
            "--repo-path",
            str(repo),
            "--command-trace-out",
            str(inside_trace),
            "--run-result-out",
            str(outside_result),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    validate_instance(output, _run_result_schema(), Path("cli-inside-trace-blocked.json"))
    assert output["status"] == "blocked"
    assert not inside_trace.exists()
    assert not outside_result.exists()


def test_cli_rejects_run_result_output_inside_inspected_repo_schema_valid(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    outside = tmp_path / "artifacts"
    outside.mkdir()

    outside_trace = outside / "trace.json"
    inside_result = repo / "result.json"

    plan = _pilot_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "action",
            "run-read-only",
            str(plan_path),
            "--repo-path",
            str(repo),
            "--command-trace-out",
            str(outside_trace),
            "--run-result-out",
            str(inside_result),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    validate_instance(output, _run_result_schema(), Path("cli-inside-result-blocked.json"))
    assert output["status"] == "blocked"
    assert not outside_trace.exists()
    assert not inside_result.exists()
