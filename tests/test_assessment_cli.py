from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.assessment import assess_repo


FORBIDDEN_ASSESSMENT_KEYS = {
    "action",
    "plan_id",
    "would_run",
    "would_mutate",
    "safe_actions",
    "safe_alternatives",
    "command_trace",
    "run_result",
}


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init_repo(path: Path) -> None:
    """Create a Git repo with one commit on main."""
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.email", "test@example.invalid"], path)
    _run(["git", "config", "user.name", "Test User"], path)
    _run(["git", "config", "commit.gpgsign", "false"], path)
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    _run(["git", "add", "README.md"], path)
    _run(["git", "commit", "-m", "init"], path)


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


def _assert_assessment_invariants(assessment: dict, schema: dict, label: Path) -> None:
    validate_instance(assessment, schema, label)
    assert FORBIDDEN_ASSESSMENT_KEYS.isdisjoint(assessment), (
        f"Assessment contains forbidden action-plan field(s): "
        f"{FORBIDDEN_ASSESSMENT_KEYS & assessment.keys()}"
    )


# ---------------------------------------------------------------------------
# Invariant: no action-plan fields in any assessment output
# ---------------------------------------------------------------------------

def test_assess_no_action_plan_fields_for_non_git_path(tmp_path: Path):
    non_git = tmp_path / "not-a-repo"
    non_git.mkdir()
    config_path = _write_local_config(tmp_path, [], [])

    assessment = assess_repo(non_git, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-non-git.json"))


def test_assess_no_action_plan_fields_for_git_repo(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-git.json"))


# ---------------------------------------------------------------------------
# Non-git path
# ---------------------------------------------------------------------------

def test_assess_non_git_path_emits_not_git_repo(tmp_path: Path):
    non_git = tmp_path / "plain-dir"
    non_git.mkdir()
    config_path = _write_local_config(tmp_path, [], [])

    assessment = assess_repo(non_git, config_path=config_path)

    assert "not_git_repo" in assessment["derived_status"]
    assert "not_git_repo" in assessment["skip_reasons"]
    assert assessment["decision_state"] == "action_blocked"
    assert assessment["risk_level"] == "medium"


# ---------------------------------------------------------------------------
# Dirty worktree
# ---------------------------------------------------------------------------

def test_assess_dirty_worktree_emits_dirty_worktree(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    # Make worktree dirty by adding an untracked file
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    config_path = _write_local_config(tmp_path, [canonical_root], [])
    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-dirty.json"))
    assert "dirty_worktree" in assessment["derived_status"]
    assert "dirty_worktree" in assessment["skip_reasons"]
    assert assessment["decision_state"] == "action_blocked"
    assert assessment["risk_level"] == "medium"


# ---------------------------------------------------------------------------
# Feature branch (non-default branch, clean)
# ---------------------------------------------------------------------------

def test_assess_feature_branch_emits_non_default_branch(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    # Switch to a feature branch (main still exists → default_branch_candidate = "main")
    _run(["git", "checkout", "-b", "feature-xyz"], repo)

    config_path = _write_local_config(tmp_path, [canonical_root], [])
    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-feature-branch.json"))
    assert "non_default_branch" in assessment["derived_status"]
    assert "non_default_branch" in assessment["skip_reasons"]
    assert assessment["decision_state"] == "evidence_missing"
    assert assessment["risk_level"] == "medium"
    assert "branch_contains_origin_main_or_pr_merged" in assessment["missing_evidence"]
    assert "fresh_origin_main" in assessment["missing_evidence"]


# ---------------------------------------------------------------------------
# Scope: backup
# ---------------------------------------------------------------------------

def test_assess_scope_backup_emits_scope_backup(tmp_path: Path):
    canonical_root = tmp_path / "roots"
    repo = canonical_root / "backups" / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-scope-backup.json"))
    assert "scope_backup" in assessment["derived_status"]
    assert "scope_backup" in assessment["skip_reasons"]
    assert assessment["decision_state"] == "action_blocked"
    assert assessment["risk_level"] == "medium"


# ---------------------------------------------------------------------------
# Scope: gdrive
# ---------------------------------------------------------------------------

def test_assess_scope_gdrive_emits_scope_gdrive(tmp_path: Path):
    canonical_root = tmp_path / "roots"
    repo = canonical_root / "GDrive" / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-scope-gdrive.json"))
    assert "scope_gdrive" in assessment["derived_status"]
    assert "scope_gdrive" in assessment["skip_reasons"]
    assert assessment["decision_state"] == "action_blocked"


# ---------------------------------------------------------------------------
# Scope: excluded
# ---------------------------------------------------------------------------

def test_assess_scope_excluded_emits_scope_excluded(tmp_path: Path):
    excluded_root = tmp_path / "excluded-project"
    _init_repo(excluded_root)
    config_path = _write_local_config(tmp_path, [], [excluded_root])

    assessment = assess_repo(excluded_root, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-scope-excluded.json"))
    assert "scope_excluded" in assessment["derived_status"]
    assert "scope_excluded" in assessment["skip_reasons"]
    assert assessment["decision_state"] == "action_blocked"


# ---------------------------------------------------------------------------
# Clean canonical repo on default branch
# ---------------------------------------------------------------------------

def test_assess_clean_canonical_default_branch_emits_clear(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    # Still on main after init — default_branch_candidate resolves to "main"
    # (refs/heads/main exists after the init commit).
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-clear.json"))
    assert "clean_default_current" in assessment["derived_status"]
    assert assessment["decision_state"] == "assessment_clear"
    assert assessment["risk_level"] == "low"
    assert assessment["skip_reasons"] == []
    # The observation does not expose whether default_branch_candidate came from
    # refs/remotes/origin/HEAD (strong) or heuristic fallback. The epistemic gap
    # is marked explicitly so downstream consumers know.
    assert "default_branch_source" in assessment["missing_evidence"]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def test_assess_cli_smoke_emits_schema_valid_json(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    result = subprocess.run(
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
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assessment = json.loads(result.stdout)
    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-cli-smoke.json"))
    assert assessment["schema_version"] == "repo-assessment.v1"
    assert "assessment_id" in assessment
    assert "observation_ref" in assessment


# ---------------------------------------------------------------------------
# Schema version and required fields
# ---------------------------------------------------------------------------

def test_assess_output_has_required_schema_fields(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assessment = assess_repo(repo, config_path=config_path)

    assert assessment["schema_version"] == "repo-assessment.v1"
    assert assessment["assessment_id"].startswith("assess-")
    assert isinstance(assessment["observation_ref"], str)
    assert isinstance(assessment["derived_status"], list)
    assert isinstance(assessment["source_refs"], list)
    assert isinstance(assessment["decision_state"], str)
    assert isinstance(assessment["risk_level"], str)
    assert assessment["risk_level"] in {"low", "medium", "high", "unknown"}
    assert isinstance(assessment["skip_reasons"], list)
    assert isinstance(assessment["confidence"], (int, float))
    assert 0.0 <= assessment["confidence"] <= 1.0
    assert isinstance(assessment["missing_evidence"], list)


# ---------------------------------------------------------------------------
# Contract: decision_state enum enforced by schema
# ---------------------------------------------------------------------------

def test_schema_rejects_unknown_decision_state(tmp_path: Path):
    """decision_state is a contractual enum; unknown values must be rejected."""
    schema = _assessment_schema()
    from scripts.validate_examples import ValidationError, validate_instance

    invalid = {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example-test",
        "observation_ref": "obs-example-test",
        "derived_status": ["not_git_repo"],
        "source_refs": ["git.rev_parse.worktree"],
        "decision_state": "some_future_state_not_in_enum",
    }
    with pytest.raises((ValidationError, Exception)):
        validate_instance(invalid, schema, Path("invalid-decision-state.json"))


def test_schema_accepts_all_valid_decision_states():
    """All three enum values must be accepted by the schema."""
    schema = _assessment_schema()
    from scripts.validate_examples import validate_instance

    for state in ("action_blocked", "evidence_missing", "assessment_clear"):
        instance = {
            "schema_version": "repo-assessment.v1",
            "assessment_id": f"assess-example-{state}",
            "observation_ref": "obs-example-test",
            "derived_status": ["not_git_repo"],
            "source_refs": ["git.rev_parse.worktree"],
            "decision_state": state,
        }
        validate_instance(instance, schema, Path(f"{state}.json"))  # must not raise


# ---------------------------------------------------------------------------
# Epistemic boundary: clean_default_current marks default_branch_source gap
# ---------------------------------------------------------------------------

def test_clean_default_current_marks_default_branch_source_gap(tmp_path: Path):
    """Even when clean on default branch, the source of default_branch_candidate
    is unverifiable from observation alone. The epistemic gap must be marked."""
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assessment = assess_repo(repo, config_path=config_path)

    assert "clean_default_current" in assessment["derived_status"]
    # Observation does not expose whether default_branch_candidate came from
    # refs/remotes/origin/HEAD or local heuristic. Gap must be marked.
    assert "default_branch_source" in assessment["missing_evidence"]
    # confidence reflects the unverified source
    assert assessment["confidence"] < 0.9


# ---------------------------------------------------------------------------
# Multi-befund: dirty_worktree collected even in non-canonical scope
# ---------------------------------------------------------------------------

def test_non_canonical_scope_also_records_dirty_worktree(tmp_path: Path):
    """derived_status is a list; dirty_worktree is collected alongside scope
    when both are observed, even though scope already blocks the action."""
    canonical_root = tmp_path / "roots"
    repo = canonical_root / "backups" / "project"
    _init_repo(repo)
    # Make worktree dirty
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-scope-backup-dirty.json"))
    assert "scope_backup" in assessment["derived_status"]
    assert "dirty_worktree" in assessment["derived_status"]
    assert assessment["decision_state"] == "action_blocked"
