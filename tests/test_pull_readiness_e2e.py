from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance


FORBIDDEN_EXECUTION_FIELDS = {
    "would_run",
    "would_mutate",
    "command_trace",
    "run_result",
    "safe_alternatives",
    "required_evidence",
}


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _run_with_env(command: list[str], cwd: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(extra_env)
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _cli(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not existing_path else f"{ROOT}:{existing_path}"
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.email", "test@example.invalid"], path)
    _run(["git", "config", "user.name", "Test User"], path)
    _run(["git", "config", "commit.gpgsign", "false"], path)
    (path / "README.md").write_text("# Seed\n", encoding="utf-8")
    _run(["git", "add", "README.md"], path)
    _run(["git", "commit", "-m", "init"], path)


def _init_bare_origin_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "workspace" / "repo"

    _run(["git", "init", "--bare", str(origin)], tmp_path)
    _init_repo(seed)
    _run(["git", "remote", "add", "origin", str(origin)], seed)
    _run_with_env(["git", "push", "-u", "origin", "main"], seed, {"ALLOW_MAIN_PUSH": "1"})
    _run(["git", "clone", str(origin), str(clone)], tmp_path)
    return origin, clone


def _write_local_config(path: Path, canonical_roots: list[Path], excluded_roots: list[Path]) -> Path:
    config = {
        "schema_version": "local-config.v1",
        "host": {"name": "test-host"},
        "paths": {
            "canonical_repo_roots": [str(item.absolute()) for item in canonical_roots],
            "excluded_repo_roots": [str(item.absolute()) for item in excluded_roots],
        },
        "policy": {
            "allow_mutating_actions": False,
            "allow_branch_switch": False,
            "allow_network_fetch": False,
        },
    }
    config_path = path / "local-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def _assessment_schema() -> dict:
    return load_json(SCHEMAS_DIR / "repo-assessment.v1.schema.json")


def _remote_refresh_schema() -> dict:
    return load_json(SCHEMAS_DIR / "remote-refresh-result.v1.schema.json")


def _command_trace_schema() -> dict:
    return load_json(SCHEMAS_DIR / "command-trace.v1.schema.json")


def _action_plan_schema() -> dict:
    return load_json(SCHEMAS_DIR / "action-plan.v1.schema.json")


def test_pull_readiness_e2e_chain_with_fresh_remote_evidence(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    porcelain = _run(["git", "-C", str(repo), "status", "--porcelain"], tmp_path).stdout.strip()
    assert porcelain == ""

    upstream = _run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        tmp_path,
    ).stdout.strip()
    assert upstream == "origin/main"

    assess_result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "assess",
            "repo",
            str(repo),
            "--config",
            str(config_path),
            "--json",
        ],
        cwd=tmp_path,
    )
    assert assess_result.returncode == 0, assess_result.stderr
    assessment = json.loads(assess_result.stdout)
    validate_instance(assessment, _assessment_schema(), Path("pull-readiness-e2e-assessment.json"))

    assessment_path = artifacts_dir / "assessment.json"
    assessment_path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
    assessment_id = assessment["assessment_id"]

    trace_path = artifacts_dir / "trace.json"
    refresh_result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "remote-refresh",
            "fetch-origin-prune",
            str(repo),
            "--config",
            str(config_path),
            "--assessment-id",
            assessment_id,
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )
    assert refresh_result.returncode == 0, refresh_result.stderr

    refresh = json.loads(refresh_result.stdout)
    validate_instance(refresh, _remote_refresh_schema(), Path("pull-readiness-e2e-refresh-success.json"))
    assert refresh["exit_code"] == 0
    assert refresh["remote_freshness"] == "fresh"

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    validate_instance(trace, _command_trace_schema(), Path("pull-readiness-e2e-trace-success.json"))

    refresh_path = artifacts_dir / "refresh-success.json"
    refresh_path.write_text(json.dumps(refresh, indent=2), encoding="utf-8")

    plan_result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "plan",
            "git-pull-ff-only",
            str(assessment_path),
            "--remote-refresh-result",
            str(refresh_path),
            "--json",
        ],
        cwd=tmp_path,
    )
    assert plan_result.returncode == 0, plan_result.stderr

    plan = json.loads(plan_result.stdout)
    validate_instance(plan, _action_plan_schema(), Path("pull-readiness-e2e-plan-success.json"))
    assert plan["action"] == "git-pull-ff-only"
    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_evidence_missing_remote_freshness" not in plan.get("blocked_because", [])
    assert "remote_freshness" not in plan["missing_evidence"]
    assert "git_pull_ff_only_preview_only_execution_out_of_scope" in plan.get("blocked_because", [])
    assert "execution_authorization" in plan["missing_evidence"]
    assert "runner_contract" in plan["missing_evidence"]
    assert "user_approval" in plan["missing_evidence"]
    assert FORBIDDEN_EXECUTION_FIELDS.isdisjoint(plan.keys())


def test_pull_readiness_e2e_chain_with_unavailable_remote_evidence_stays_blocked(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    assess_result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "assess",
            "repo",
            str(repo),
            "--config",
            str(config_path),
            "--json",
        ],
        cwd=tmp_path,
    )
    assert assess_result.returncode == 0, assess_result.stderr
    assessment = json.loads(assess_result.stdout)
    validate_instance(assessment, _assessment_schema(), Path("pull-readiness-e2e-assessment-failed-refresh.json"))
    assessment_id = assessment["assessment_id"]

    assessment_path = artifacts_dir / "assessment.json"
    assessment_path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")

    _run(["git", "-C", str(repo), "remote", "set-url", "origin", str(tmp_path / "missing-origin.git")], tmp_path)

    trace_path = artifacts_dir / "trace-failed.json"
    refresh_result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "remote-refresh",
            "fetch-origin-prune",
            str(repo),
            "--config",
            str(config_path),
            "--assessment-id",
            assessment_id,
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )
    assert refresh_result.returncode == 0, refresh_result.stderr

    refresh = json.loads(refresh_result.stdout)
    validate_instance(refresh, _remote_refresh_schema(), Path("pull-readiness-e2e-refresh-failed.json"))
    assert refresh["exit_code"] != 0
    assert refresh["remote_freshness"] == "unavailable"

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    validate_instance(trace, _command_trace_schema(), Path("pull-readiness-e2e-trace-failed.json"))

    refresh_path = artifacts_dir / "refresh-failed.json"
    refresh_path.write_text(json.dumps(refresh, indent=2), encoding="utf-8")

    plan_result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "plan",
            "git-pull-ff-only",
            str(assessment_path),
            "--remote-refresh-result",
            str(refresh_path),
            "--json",
        ],
        cwd=tmp_path,
    )
    assert plan_result.returncode == 0, plan_result.stderr

    plan = json.loads(plan_result.stdout)
    validate_instance(plan, _action_plan_schema(), Path("pull-readiness-e2e-plan-failed-refresh.json"))
    assert plan["action"] == "git-pull-ff-only"
    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_evidence_missing_remote_freshness" in plan.get("blocked_because", [])
    assert "remote_freshness" in plan["missing_evidence"]
    assert FORBIDDEN_EXECUTION_FIELDS.isdisjoint(plan.keys())
