from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard import observation as observation_module
from steuerboard.observation import observe_repo


FORBIDDEN_OBSERVATION_KEYS = {
    "risk_level",
    "decision_state",
    "safe_actions",
    "skip_reasons",
    "derived_status",
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


def _init_repo(path: Path) -> None:
    path.mkdir()
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.email", "test@example.invalid"], path)
    _run(["git", "config", "user.name", "Test User"], path)
    _run(["git", "remote", "add", "origin", "git@github.com:heimgewebe/example.git"], path)

    (path / "README.md").write_text("# Example\n", encoding="utf-8")
    _run(["git", "add", "README.md"], path)
    _run(["git", "commit", "-m", "init"], path)


def test_observe_repo_returns_schema_valid_observation(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    observation = observe_repo(repo)
    schema = load_json(SCHEMAS_DIR / "repo-observation.v1.schema.json")
    validate_instance(observation, schema, Path("generated-observation.json"))

    assert observation["schema_version"] == "repo-observation.v1"
    assert observation["repo_id"] == "heimgewebe/example"

    state = observation["observed_state"]
    assert state["is_git_repo"] is True
    assert state["current_branch"] == "main"
    assert state["dirty"] is False
    assert state["remote_url"] == "git@github.com:heimgewebe/example.git"
    assert state["git_toplevel"] == str(repo.resolve())


def test_observe_repo_does_not_emit_assessment_or_decision_fields(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    observation = observe_repo(repo)
    state = observation["observed_state"]

    assert FORBIDDEN_OBSERVATION_KEYS.isdisjoint(observation)
    assert FORBIDDEN_OBSERVATION_KEYS.isdisjoint(state)


def test_observe_repo_cli_emits_json(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = subprocess.run(
        [sys.executable, "-m", "steuerboard", "observe", "repo", str(repo), "--json"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
    )

    observation = json.loads(result.stdout)
    assert observation["schema_version"] == "repo-observation.v1"
    assert observation["observed_state"]["is_git_repo"] is True


def test_observe_non_repo_path_is_still_an_observation(tmp_path: Path):
    path = tmp_path / "not-a-repo"
    path.mkdir()

    observation = observe_repo(path)
    schema = load_json(SCHEMAS_DIR / "repo-observation.v1.schema.json")
    validate_instance(observation, schema, Path("generated-observation.json"))

    state = observation["observed_state"]
    assert state["is_git_repo"] is False
    assert state["git_metadata_present_at_observed_path"] is False
    assert isinstance(state["git_worktree_check_exit_code"], int)
    assert "git_worktree_check_stderr" in state
    assert observation["source_refs"] == ["git.rev_parse.worktree"]


def test_git_runner_disables_optional_locks(monkeypatch, tmp_path: Path):
    captured = {}

    class Completed:
        returncode = 0
        stdout = "true\n"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return Completed()

    monkeypatch.setattr(observation_module.subprocess, "run", fake_run)

    result = observation_module._run_git(tmp_path, "rev-parse", "--is-inside-work-tree")

    assert result.returncode == 0
    assert captured["command"][:3] == ["git", "-C", str(tmp_path)]
    assert captured["env"]["GIT_OPTIONAL_LOCKS"] == "0"


def test_observe_repo_redacts_https_remote_credentials(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            "https://user:token@github.com/heimgewebe/example.git",
        ],
        repo,
    )

    observation = observe_repo(repo)
    rendered = json.dumps(observation)

    assert observation["observed_state"]["remote_url"] == "https://github.com/heimgewebe/example.git"
    assert observation["repo_id"] == "heimgewebe/example"
    assert "token" not in rendered
    assert "user:token" not in rendered


def test_observe_repo_redacts_url_userinfo_for_non_https_schemes(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            "ssh://token@github.com/heimgewebe/example.git",
        ],
        repo,
    )

    observation = observe_repo(repo)
    rendered = json.dumps(observation)

    assert observation["observed_state"]["remote_url"] == "ssh://github.com/heimgewebe/example.git"
    assert observation["repo_id"] == "heimgewebe/example"
    assert "token" not in rendered


def test_observe_repo_strips_remote_query_and_fragment(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            "https://github.com/heimgewebe/example.git?token=secret#frag",
        ],
        repo,
    )

    observation = observe_repo(repo)
    rendered = json.dumps(observation)

    assert observation["observed_state"]["remote_url"] == "https://github.com/heimgewebe/example.git"
    assert observation["repo_id"] == "heimgewebe/example"
    assert "secret" not in rendered
    assert "token=secret" not in rendered
    assert "#frag" not in rendered


def test_observe_repo_strips_scp_like_remote_query_and_fragment(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            "git@github.com:heimgewebe/example.git?token=secret#frag",
        ],
        repo,
    )

    observation = observe_repo(repo)
    rendered = json.dumps(observation)

    assert observation["observed_state"]["remote_url"] == "git@github.com:heimgewebe/example.git"
    assert observation["repo_id"] == "heimgewebe/example"
    assert "secret" not in rendered
    assert "token=secret" not in rendered
    assert "#frag" not in rendered

def test_observe_repo_redacts_non_git_scp_like_user(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            "token@github.com:heimgewebe/example.git",
        ],
        repo,
    )

    observation = observe_repo(repo)
    rendered = json.dumps(observation)

    assert observation["observed_state"]["remote_url"] == "[REDACTED_USER]@github.com:heimgewebe/example.git"
    assert "token@github.com" not in rendered
