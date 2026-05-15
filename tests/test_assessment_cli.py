from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, ValidationError, load_json, minimal_validate, validate_instance
from steuerboard.assessment import assess_repo
from steuerboard.assessment_rules import ASSESSMENT_PROVENANCE, attach_assessment_provenance


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


def _assessment_explanation_schema() -> dict:
    return load_json(SCHEMAS_DIR / "repo-assessment-explanation.v1.schema.json")


def _assert_provenance_covers_all_statuses(assessment: dict) -> None:
    for status in assessment["derived_status"]:
        expected = ASSESSMENT_PROVENANCE[status]["rule_refs"]
        for ref in expected:
            assert ref in assessment["rule_refs"], (
                f"Missing rule_ref {ref!r} for derived_status {status!r}"
            )


def _assert_assessment_invariants(assessment: dict, schema: dict, label: Path) -> None:
    validate_instance(assessment, schema, label)
    assert FORBIDDEN_ASSESSMENT_KEYS.isdisjoint(assessment), (
        f"Assessment contains forbidden action-plan field(s): "
        f"{FORBIDDEN_ASSESSMENT_KEYS & assessment.keys()}"
    )
    assert isinstance(assessment.get("rule_refs"), list)
    assert isinstance(assessment.get("freshness_refs"), list)
    assert isinstance(assessment.get("falsification_refs"), list)
    _assert_provenance_covers_all_statuses(assessment)


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
    assert "assessment.rule.dirty_worktree_blocks_action" in assessment["rule_refs"]
    assert "failure-case.dirty_worktree" in assessment["falsification_refs"]
    assert assessment["freshness_refs"]


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
    assert "assessment.rule.non_default_branch_requires_lifecycle_evidence" in assessment["rule_refs"]
    assert "failure-case.feature_branch_unmerged" in assessment["falsification_refs"]
    assert "freshness.remote_branch_lifecycle.not_observed_no_fetch" in assessment["freshness_refs"]
    assert "freshness.remote_branch_lifecycle.fresh" not in assessment["freshness_refs"]


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
    assert "failure-case.backup_repo_accidentally_used" in assessment["falsification_refs"]


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
    # Source is local heuristic in this fixture; epistemic gap remains marked.
    assert "default_branch_source" in assessment["missing_evidence"]
    assert "assessment.rule.clean_default_current_is_clear_but_default_source_unverified" in assessment["rule_refs"]


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
    invalid = {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example-test",
        "observation_ref": "obs-example-test",
        "derived_status": ["not_git_repo"],
        "source_refs": ["git.rev_parse.worktree"],
        "decision_state": "some_future_state_not_in_enum",
    }
    with pytest.raises(ValidationError):
        validate_instance(invalid, schema, Path("invalid-decision-state.json"))


def test_schema_accepts_all_valid_decision_states():
    """All three enum values must be accepted by the schema."""
    schema = _assessment_schema()
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
    """Local heuristic source keeps the default_branch_source evidence gap marked."""
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assessment = assess_repo(repo, config_path=config_path)

    assert "clean_default_current" in assessment["derived_status"]
    # This fixture has no refs/remotes/origin/HEAD, so local heuristic applies.
    assert "default_branch_source" in assessment["missing_evidence"]
    assert assessment["confidence"] == 0.8


def test_clean_default_current_with_remote_origin_head_has_no_source_gap(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    _run(["git", "update-ref", "refs/remotes/origin/main", head_sha], repo)
    _run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"],
        repo,
    )

    assessment = assess_repo(repo, config_path=config_path)

    assert "clean_default_current" in assessment["derived_status"]
    assert "default_branch_source" not in assessment["missing_evidence"]
    assert assessment["confidence"] >= 0.9
    assert (
        "assessment.rule.clean_default_current_is_clear_but_default_source_unverified"
        not in assessment["rule_refs"]
    )
    assert (
        "assessment.rule.clean_default_current_remote_origin_head_local_source_observed"
        in assessment["rule_refs"]
    )
    assert "freshness.default_branch_source.unverified" not in assessment["freshness_refs"]
    assert (
        "freshness.default_branch_source.remote_origin_head_local_observed"
        in assessment["freshness_refs"]
    )


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

# ---------------------------------------------------------------------------
# Review regressions: symlink scope, explicit config, ID uniqueness, branch edges
# ---------------------------------------------------------------------------

def test_assess_uses_unresolved_path_for_scope_classification(tmp_path: Path):
    real_root = tmp_path / "real"
    symlink_root = tmp_path / "repos-link"
    repo = real_root / "project"
    _init_repo(repo)

    try:
        symlink_root.symlink_to(real_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable in test environment: {exc}")

    config_path = _write_local_config(tmp_path, [symlink_root], [])
    assessment = assess_repo(symlink_root / "project", config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-symlink-scope.json"))
    assert "scope_unknown" not in assessment["derived_status"]
    assert "clean_default_current" in assessment["derived_status"]


def test_assess_explicit_missing_config_raises(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    with pytest.raises(FileNotFoundError):
        assess_repo(repo, config_path=tmp_path / "missing-config.json")


def test_assessment_id_is_unique_for_repeated_same_path_calls(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    first = assess_repo(repo, config_path=config_path)
    second = assess_repo(repo, config_path=config_path)

    assert first["assessment_id"] != second["assessment_id"]


def test_assess_detached_head_emits_detached_head(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    _run(["git", "checkout", "--detach", "HEAD"], repo)

    config_path = _write_local_config(tmp_path, [canonical_root], [])
    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-detached-head.json"))
    assert "detached_head" in assessment["derived_status"]
    assert "detached_head" in assessment["skip_reasons"]
    assert assessment["decision_state"] == "action_blocked"
    assert "failure-case.detached_head" in assessment["falsification_refs"]


def test_assess_default_branch_unknown_when_no_candidate(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    repo.mkdir(parents=True)

    _run(["git", "init", "-b", "feature-only"], repo)
    _run(["git", "config", "user.email", "test@example.invalid"], repo)
    _run(["git", "config", "user.name", "Test User"], repo)
    _run(["git", "config", "commit.gpgsign", "false"], repo)
    (repo / "README.md").write_text("# Test\n", encoding="utf-8")
    _run(["git", "add", "README.md"], repo)
    _run(["git", "commit", "-m", "init"], repo)

    config_path = _write_local_config(tmp_path, [canonical_root], [])
    assessment = assess_repo(repo, config_path=config_path)

    schema = _assessment_schema()
    _assert_assessment_invariants(assessment, schema, Path("assess-default-branch-unknown.json"))
    assert "default_branch_unknown" in assessment["derived_status"]
    assert "default_branch_unknown" in assessment["skip_reasons"]
    assert assessment["decision_state"] == "evidence_missing"
    assert "default_branch" in assessment["missing_evidence"]
    assert "failure-case.unknown_default_branch" in assessment["falsification_refs"]


def test_minimal_validator_rejects_confidence_above_one():
    schema = _assessment_schema()
    invalid = {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example-confidence-too-high",
        "observation_ref": "obs-example-test",
        "derived_status": ["clean_default_current"],
        "source_refs": ["git.rev_parse.worktree"],
        "decision_state": "assessment_clear",
        "confidence": 1.1,
    }

    with pytest.raises(ValidationError):
        minimal_validate(invalid, schema)


def test_provenance_rejects_unknown_falsification_ref(monkeypatch: pytest.MonkeyPatch):
    invalid_mapping = {
        **ASSESSMENT_PROVENANCE,
        "dirty_worktree": {
            **ASSESSMENT_PROVENANCE["dirty_worktree"],
            "falsification_refs": ["failure-case.not_a_real_case"],
        },
    }
    monkeypatch.setattr(
        "steuerboard.assessment_rules.ASSESSMENT_PROVENANCE",
        invalid_mapping,
    )

    with pytest.raises(ValueError, match="Unknown falsification_ref"):
        attach_assessment_provenance(["dirty_worktree"])


def test_provenance_rejects_empty_derived_status():
    with pytest.raises(ValueError, match="derived_status must not be empty"):
        attach_assessment_provenance([])


# ---------------------------------------------------------------------------
# Context-sensitive freshness: scope_unknown without available config
# ---------------------------------------------------------------------------

def test_scope_unknown_without_config_uses_unavailable_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When no config file exists, explain_scope raises FileNotFoundError and
    assess_repo falls back to scope_unknown + source_refs=['local_config.unavailable'].
    freshness_refs must say 'unavailable' — not 'current_invocation'.
    The two directly contradict each other: a file that was not found cannot
    be 'freshly read'."""
    repo = tmp_path / "orphan-repo"
    _init_repo(repo)

    # Simulate no config file existing anywhere (developer machine may have one)
    def _raise_no_config(*args, **kwargs):
        raise FileNotFoundError("no config found")

    monkeypatch.setattr("steuerboard.assessment.explain_scope", _raise_no_config)

    assessment = assess_repo(repo)  # config_path=None → fallback, not re-raise

    assert "scope_unknown" in assessment["derived_status"]
    assert "local_config.unavailable" in assessment["source_refs"]
    assert "freshness.local_scope_config.unavailable" in assessment["freshness_refs"]
    assert "freshness.local_scope_config.current_invocation" not in assessment["freshness_refs"]


# ---------------------------------------------------------------------------
# Provenance: falsification_ref prefix validation
# ---------------------------------------------------------------------------

def test_provenance_rejects_falsification_ref_without_prefix(monkeypatch: pytest.MonkeyPatch):
    """Both error paths in _validate_falsification_refs must be covered.
    This test covers the prefix check (ref does not start with 'failure-case.')."""
    invalid_mapping = {
        **ASSESSMENT_PROVENANCE,
        "dirty_worktree": {
            **ASSESSMENT_PROVENANCE["dirty_worktree"],
            "falsification_refs": ["no-prefix-at-all"],
        },
    }
    monkeypatch.setattr(
        "steuerboard.assessment_rules.ASSESSMENT_PROVENANCE",
        invalid_mapping,
    )

    with pytest.raises(ValueError, match="Invalid falsification_ref prefix"):
        attach_assessment_provenance(["dirty_worktree"])


def test_assess_explain_cli_smoke_emits_schema_valid_json(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_local_config(tmp_path, [canonical_root], [])

    assess_result = subprocess.run(
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
    assessment_path = tmp_path / "assessment.json"
    assessment_path.write_text(assess_result.stdout, encoding="utf-8")

    explain_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "assess",
            "explain",
            str(assessment_path),
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    explanation = json.loads(explain_result.stdout)
    validate_instance(
        explanation,
        _assessment_explanation_schema(),
        Path("assess-explain-cli-smoke.json"),
    )
    assert explanation["schema_version"] == "repo-assessment-explanation.v1"
