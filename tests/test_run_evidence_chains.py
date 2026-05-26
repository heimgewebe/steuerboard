from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.run_evidence_chains import validate_run_evidence_chain


def _chain_schema() -> dict:
    return load_json(SCHEMAS_DIR / "run-evidence-chain.v1.schema.json")


def _base_artifacts(tmp_path: Path) -> tuple[dict, dict, dict, dict, dict[str, Path]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    action_plan_path = tmp_path / "inputs" / "plan.json"
    command_trace_path = tmp_path / "inputs" / "trace.json"
    run_result_path = tmp_path / "inputs" / "run-result.json"
    run_postcheck_path = tmp_path / "inputs" / "postcheck.json"
    chain_out_path = tmp_path / "outputs" / "chain.json"
    action_plan_path.parent.mkdir()
    chain_out_path.parent.mkdir()

    action_plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-git-status-read-only-test-001",
        "action": "git-status-read-only",
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
    command_trace = {
        "schema_version": "command-trace.v1",
        "trace_id": "trace-read-only-test-001",
        "command": [
            "git",
            "--no-optional-locks",
            "-C",
            str(repo.resolve()),
            "status",
            "--porcelain=v1",
        ],
        "exit_code": 0,
        "stdout_excerpt": "",
        "stderr_excerpt": "",
        "redacted": True,
    }
    run_result = {
        "schema_version": "run-result.v1",
        "run_id": "run-read-only-test-001",
        "status": "success",
        "started_at": "2026-05-26T10:00:00Z",
        "finished_at": "2026-05-26T10:00:01Z",
        "redaction_verified": True,
        "evidence_paths": [str(command_trace_path.resolve())],
    }
    run_postcheck = {
        "schema_version": "run-postcheck.v1",
        "postcheck_id": "postcheck-read-only-test-001",
        "run_id": run_result["run_id"],
        "trace_ref": command_trace["trace_id"],
        "run_result_ref": run_result["run_id"],
        "action": "git-status-read-only",
        "repo_toplevel": str(repo.resolve()),
        "checked_at": "2026-05-26T10:00:05Z",
        "status": "passed",
        "observations": [],
        "redaction_verified": True,
        "source_refs": ["git.status_porcelain", "run-result.v1", "command-trace.v1"],
        "evidence_paths": [
            str(command_trace_path.resolve()),
            str(run_result_path.resolve()),
        ],
    }

    for path, payload in (
        (action_plan_path, action_plan),
        (command_trace_path, command_trace),
        (run_result_path, run_result),
        (run_postcheck_path, run_postcheck),
    ):
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paths = {
        "action_plan": action_plan_path,
        "command_trace": command_trace_path,
        "run_result": run_result_path,
        "run_postcheck": run_postcheck_path,
        "chain_out": chain_out_path,
        "repo": repo,
    }
    return action_plan, command_trace, run_result, run_postcheck, paths


def _validate_happy_chain(
    tmp_path: Path,
    *,
    mutate: callable | None = None,
) -> dict:
    action_plan, command_trace, run_result, run_postcheck, paths = _base_artifacts(tmp_path)
    if mutate is not None:
        mutate(action_plan, command_trace, run_result, run_postcheck, paths)
    chain = validate_run_evidence_chain(
        action_plan=action_plan,
        command_trace=command_trace,
        run_result=run_result,
        run_postcheck=run_postcheck,
        action_plan_path=str(paths["action_plan"]),
        command_trace_path=str(paths["command_trace"]),
        run_result_path=str(paths["run_result"]),
        run_postcheck_path=str(paths["run_postcheck"]),
        chain_out=str(paths["chain_out"]),
    )
    validate_instance(chain, _chain_schema(), Path("chain.json"))
    written = json.loads(paths["chain_out"].read_text(encoding="utf-8"))
    validate_instance(written, _chain_schema(), Path("chain-written.json"))
    assert written == chain
    return chain


def _cli(args: list[str], cwd: Path):
    import os
    import subprocess

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}:{existing}"
    return subprocess.run(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )


def test_happy_path_valid_chain(tmp_path: Path):
    chain = _validate_happy_chain(tmp_path)
    assert chain["status"] == "valid"
    assert chain["redaction_verified"] is True
    assert chain["action"] == "git-status-read-only"
    assert chain["run_result_ref"] == "run-read-only-test-001"
    assert chain["postcheck_ref"] == "postcheck-read-only-test-001"
    assert chain["plan_ref"] == "plan-git-status-read-only-test-001"
    assert len(chain["evidence_paths"]) == 4
    assert "failure_reasons" not in chain


def test_invalid_when_postcheck_failed(tmp_path: Path):
    def mutate(_plan, _trace, _result, postcheck, _paths):
        postcheck["status"] = "failed"
        postcheck["failure_reasons"] = ["worktree_changed_after_run"]

    chain = _validate_happy_chain(tmp_path, mutate=mutate)
    assert chain["status"] == "invalid"
    assert "postcheck_failed" in chain["failure_reasons"]


def test_inconclusive_when_postcheck_inconclusive(tmp_path: Path):
    def mutate(_plan, _trace, _result, postcheck, _paths):
        postcheck["status"] = "inconclusive"
        postcheck["failure_reasons"] = ["stdout_excerpt_truncated"]

    chain = _validate_happy_chain(tmp_path, mutate=mutate)
    assert chain["status"] == "inconclusive"
    assert "postcheck_inconclusive" in chain["failure_reasons"]


def test_invalid_when_trace_missing_from_run_result_evidence_paths(tmp_path: Path):
    def mutate(_plan, _trace, result, _postcheck, paths):
        result["evidence_paths"] = [str(paths["run_result"].resolve())]

    chain = _validate_happy_chain(tmp_path, mutate=mutate)
    assert chain["status"] == "invalid"
    assert "trace_path_missing_from_run_result" in chain["failure_reasons"]


def test_invalid_when_postcheck_trace_ref_mismatches(tmp_path: Path):
    def mutate(_plan, _trace, _result, postcheck, _paths):
        postcheck["trace_ref"] = "trace-other"

    chain = _validate_happy_chain(tmp_path, mutate=mutate)
    assert chain["status"] == "invalid"
    assert "postcheck_trace_ref_mismatch" in chain["failure_reasons"]


def test_invalid_when_postcheck_run_result_ref_mismatches(tmp_path: Path):
    def mutate(_plan, _trace, _result, postcheck, _paths):
        postcheck["run_result_ref"] = "run-other"

    chain = _validate_happy_chain(tmp_path, mutate=mutate)
    assert chain["status"] == "invalid"
    assert "postcheck_run_result_ref_mismatch" in chain["failure_reasons"]


def test_invalid_when_run_result_not_success(tmp_path: Path):
    def mutate(_plan, _trace, result, _postcheck, _paths):
        result["status"] = "failure"

    chain = _validate_happy_chain(tmp_path, mutate=mutate)
    assert chain["status"] == "invalid"
    assert "run_result_not_success" in chain["failure_reasons"]


def test_invalid_when_trace_exit_code_nonzero(tmp_path: Path):
    def mutate(_plan, trace, _result, _postcheck, _paths):
        trace["exit_code"] = 1

    chain = _validate_happy_chain(tmp_path, mutate=mutate)
    assert chain["status"] == "invalid"
    assert "trace_exit_code_nonzero" in chain["failure_reasons"]


def test_blocked_when_chain_out_exists(tmp_path: Path):
    action_plan, command_trace, run_result, run_postcheck, paths = _base_artifacts(tmp_path)
    paths["chain_out"].write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="must not already exist"):
        validate_run_evidence_chain(
            action_plan=action_plan,
            command_trace=command_trace,
            run_result=run_result,
            run_postcheck=run_postcheck,
            action_plan_path=str(paths["action_plan"]),
            command_trace_path=str(paths["command_trace"]),
            run_result_path=str(paths["run_result"]),
            run_postcheck_path=str(paths["run_postcheck"]),
            chain_out=str(paths["chain_out"]),
        )


def test_blocked_when_chain_out_parent_missing(tmp_path: Path):
    action_plan, command_trace, run_result, run_postcheck, paths = _base_artifacts(tmp_path)
    missing_output = tmp_path / "missing" / "chain.json"

    with pytest.raises(ValueError, match="parent directory must exist"):
        validate_run_evidence_chain(
            action_plan=action_plan,
            command_trace=command_trace,
            run_result=run_result,
            run_postcheck=run_postcheck,
            action_plan_path=str(paths["action_plan"]),
            command_trace_path=str(paths["command_trace"]),
            run_result_path=str(paths["run_result"]),
            run_postcheck_path=str(paths["run_postcheck"]),
            chain_out=str(missing_output),
        )


def test_cli_emits_schema_valid_output(tmp_path: Path):
    _base_artifacts(tmp_path)
    inputs = tmp_path / "inputs"
    output = tmp_path / "outputs" / "chain-cli.json"
    proc = _cli(
        [
            "python",
            "-m",
            "steuerboard",
            "action",
            "validate-run-chain",
            str(inputs / "plan.json"),
            "--command-trace",
            str(inputs / "trace.json"),
            "--run-result",
            str(inputs / "run-result.json"),
            "--run-postcheck",
            str(inputs / "postcheck.json"),
            "--chain-out",
            str(output),
            "--json",
        ],
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    validate_instance(payload, _chain_schema(), Path("cli-chain.json"))
    assert payload["status"] == "valid"
    assert output.exists()


def test_no_subprocess_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import subprocess

    def fail(*_args, **_kwargs):
        raise AssertionError("subprocess.run must not be called in Phase 8C")

    monkeypatch.setattr(subprocess, "run", fail)
    chain = _validate_happy_chain(tmp_path)
    assert chain["status"] == "valid"