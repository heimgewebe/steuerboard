from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts.validate_examples import SCHEMAS_DIR, load_json, validate_instance, ValidationError
from steuerboard.observation import observe_repo


FORBIDDEN_OBSERVATION_KEYS = {
    "risk_level",
    "decision_state",
    "safe_actions",
    "skip_reasons",
    "derived_status",
}


def test_generated_observation_matches_hardened_schema(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(cmd: list[str]) -> None:
        subprocess.run(
            cmd,
            cwd=repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "test@example.invalid"])
    run(["git", "config", "user.name", "Test User"])
    run(["git", "config", "commit.gpgsign", "false"])
    run(["git", "remote", "add", "origin", "git@github.com:heimgewebe/example.git"])

    (repo / "README.md").write_text("# Example\n", encoding="utf-8")
    run(["git", "add", "README.md"])
    run(["git", "commit", "-m", "init"])

    observation = observe_repo(repo)
    schema = load_json(SCHEMAS_DIR / "repo-observation.v1.schema.json")
    validate_instance(observation, schema, Path("generated-observation.json"))

    state = observation["observed_state"]
    assert FORBIDDEN_OBSERVATION_KEYS.isdisjoint(observation)
    assert FORBIDDEN_OBSERVATION_KEYS.isdisjoint(state)
    assert state["git_toplevel"] == str(repo.resolve())
    assert state["git_worktree_check_exit_code"] == 0


def test_observation_schema_rejects_assessment_fields():
    schema = load_json(SCHEMAS_DIR / "repo-observation.v1.schema.json")
    invalid = {
        "schema_version": "repo-observation.v1",
        "observation_id": "obs-invalid",
        "source_refs": ["git.status.porcelain"],
        "observed_state": {
            "path": "/tmp/repo",
            "is_git_repo": True,
            "git_status_exit_code": 0,
            "decision_state": "blocked",
        },
    }

    with pytest.raises(ValidationError):
        validate_instance(invalid, schema, Path("invalid-observation.json"))
