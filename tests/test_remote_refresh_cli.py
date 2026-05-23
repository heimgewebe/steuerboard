from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _run_with_env(command: list[str], cwd: Path, extra_env: dict[str, str]) -> None:
    env = os.environ.copy()
    env.update(extra_env)
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _stdout(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


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
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
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


def _remote_refresh_schema() -> dict:
    return load_json(SCHEMAS_DIR / "remote-refresh-result.v1.schema.json")


def _command_trace_schema() -> dict:
    return load_json(SCHEMAS_DIR / "command-trace.v1.schema.json")


def test_remote_refresh_fetch_origin_prune_success(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])
    trace_path = tmp_path / "artifacts" / "trace.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    result = _cli(
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
            "assess-123",
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    refresh = json.loads(result.stdout)
    validate_instance(refresh, _remote_refresh_schema(), Path("remote-refresh-success.json"))
    assert refresh["schema_version"] == "remote-refresh-result.v1"
    assert refresh["operation"] == "git.fetch_origin_prune"
    assert refresh["remote_name"] == "origin"
    assert refresh["repo_ref"] == "repo-assess-123"
    assert refresh["exit_code"] == 0
    assert refresh["remote_freshness"] == "fresh"
    assert refresh["mutates_refs"] is True
    assert refresh["mutates_worktree"] is False
    assert refresh["mutates_remote"] is False

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    validate_instance(trace, _command_trace_schema(), Path("command-trace-success.json"))
    expected_toplevel = _stdout(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], tmp_path)
    assert trace["command"] == ["git", "-C", expected_toplevel, "fetch", "origin", "--prune"]


def test_remote_refresh_fetch_origin_prune_failure_unreachable_origin_writes_trace(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    _run(["git", "-C", str(repo), "remote", "set-url", "origin", str(tmp_path / "missing-origin.git")], tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])
    trace_path = tmp_path / "artifacts" / "trace-failed.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    result = _cli(
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
            "assess-456",
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    refresh = json.loads(result.stdout)
    validate_instance(refresh, _remote_refresh_schema(), Path("remote-refresh-failed.json"))
    assert refresh["exit_code"] != 0
    assert refresh["remote_freshness"] == "unavailable"
    assert refresh["mutates_refs"] is False

    assert trace_path.exists()
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    validate_instance(trace, _command_trace_schema(), Path("command-trace-failed.json"))


def test_remote_refresh_preflight_blocks_non_git_path(tmp_path: Path):
    non_git = tmp_path / "plain"
    non_git.mkdir()
    config_path = _write_local_config(tmp_path, [tmp_path], [])
    trace_path = tmp_path / "trace.json"

    result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "remote-refresh",
            "fetch-origin-prune",
            str(non_git),
            "--config",
            str(config_path),
            "--assessment-id",
            "assess-1",
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "git worktree" in result.stderr
    assert not trace_path.exists()


def test_remote_refresh_preflight_blocks_non_canonical_scope(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "somewhere-else"], [])
    trace_path = tmp_path / "trace.json"

    result = _cli(
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
            "assess-2",
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "scope_unknown" in result.stderr


def test_remote_refresh_preflight_blocks_missing_origin(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    _run(["git", "-C", str(repo), "remote", "remove", "origin"], tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])
    trace_path = tmp_path / "trace.json"

    result = _cli(
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
            "assess-3",
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "origin remote URL" in result.stderr
    assert not trace_path.exists()


def test_remote_refresh_preflight_refuses_existing_command_trace_out(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])
    trace_path = tmp_path / "existing-trace.json"
    trace_path.write_text("{}\n", encoding="utf-8")

    result = _cli(
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
            "assess-4",
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "must not already exist" in result.stderr


def test_remote_refresh_requires_command_trace_out_option(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])

    result = _cli(
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
            "assess-5",
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "--command-trace-out" in result.stderr


def test_remote_refresh_requires_config_option(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    trace_path = tmp_path / "trace.json"

    result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "remote-refresh",
            "fetch-origin-prune",
            str(repo),
            "--assessment-id",
            "assess-6",
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "--config" in result.stderr


def test_remote_refresh_requires_assessment_id_option(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])
    trace_path = tmp_path / "trace.json"

    result = _cli(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "remote-refresh",
            "fetch-origin-prune",
            str(repo),
            "--config",
            str(config_path),
            "--command-trace-out",
            str(trace_path),
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "--assessment-id" in result.stderr


def test_remote_refresh_command_trace_ref_matches_exact_cli_argument(tmp_path: Path):
    _, repo = _init_bare_origin_and_clone(tmp_path)
    config_path = _write_local_config(tmp_path, [tmp_path / "workspace"], [])
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    trace_arg = "./artifacts/trace-lexical.json"
    result = _cli(
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
            "assess-lexical",
            "--command-trace-out",
            trace_arg,
            "--json",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    refresh = json.loads(result.stdout)
    assert refresh["command_trace_ref"] == trace_arg


def test_remote_refresh_implementation_uses_no_shell_runner():
    source = (ROOT / "steuerboard" / "remote_refresh.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
