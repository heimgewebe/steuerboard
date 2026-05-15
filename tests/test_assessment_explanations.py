from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.validate_examples import SCHEMAS_DIR, ValidationError, load_json, validate_instance
from steuerboard.assessment_explanations import explain_assessment


FORBIDDEN_EXPLANATION_KEYS = {
    "action",
    "plan_id",
    "would_run",
    "would_mutate",
    "safe_actions",
    "safe_alternatives",
    "command_trace",
    "run_result",
}


def _schema() -> dict:
    return load_json(SCHEMAS_DIR / "repo-assessment-explanation.v1.schema.json")


def _assessment(status: str) -> dict:
    return {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example",
        "observation_ref": "obs-example",
        "derived_status": [status],
        "source_refs": ["git.current_branch", "git.status.porcelain"],
        "decision_state": "assessment_clear",
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": [],
        "missing_evidence": ["default_branch_source"],
    }


def test_explain_assessment_output_validates_against_schema():
    explanation = explain_assessment(_assessment("dirty_worktree"))
    validate_instance(explanation, _schema(), Path("assessment-explain.json"))


def test_explain_assessment_rejects_unknown_status():
    with pytest.raises(ValueError, match="Unsupported derived_status"):
        explain_assessment(_assessment("not_a_known_status"))


def test_explain_assessment_requires_repo_assessment_schema_version():
    missing = _assessment("dirty_worktree")
    missing.pop("schema_version")
    with pytest.raises(ValueError, match="schema_version must be repo-assessment.v1"):
        explain_assessment(missing)

    wrong = _assessment("dirty_worktree")
    wrong["schema_version"] = "not-repo-assessment.v1"
    with pytest.raises(ValueError, match="schema_version must be repo-assessment.v1"):
        explain_assessment(wrong)


def test_explain_assessment_preserves_missing_evidence():
    assessment = _assessment("non_default_branch")
    assessment["missing_evidence"] = ["branch_contains_origin_main_or_pr_merged", "fresh_origin_main"]

    explanation = explain_assessment(assessment)

    assert explanation["status_explanations"][0]["missing_evidence"] == assessment["missing_evidence"]


def test_clean_default_current_mentions_unverified_default_branch_source():
    explanation = explain_assessment(_assessment("clean_default_current"))

    assert "default_branch_source remains unverified" in explanation["status_explanations"][0]["meaning"]


def test_clean_default_current_without_source_gap_mentions_recorded_source_evidence():
    assessment = _assessment("clean_default_current")
    assessment["missing_evidence"] = []
    assessment["source_refs"] = [
        "git.current_branch",
        "git.status.porcelain",
        "git.default_branch_candidate_source",
    ]

    explanation = explain_assessment(assessment)
    status_item = explanation["status_explanations"][0]

    assert "recorded source evidence" in status_item["meaning"]
    assert "remote freshness is not claimed" in status_item["meaning"]
    assert "freshness.default_branch_source.unverified" not in status_item["freshness_refs"]
    assert (
        "freshness.default_branch_source.remote_origin_head_local_observed"
        in status_item["freshness_refs"]
    )


def test_non_default_branch_does_not_claim_fresh_remote_state():
    explanation = explain_assessment(_assessment("non_default_branch"))
    meaning = explanation["status_explanations"][0]["meaning"]

    assert "fresh" not in meaning.lower()
    assert "not observed" in meaning


def test_explain_assessment_rejects_missing_or_empty_derived_status():
    without = _assessment("dirty_worktree")
    without.pop("derived_status")
    with pytest.raises(ValueError, match="derived_status must be a non-empty list"):
        explain_assessment(without)

    empty = _assessment("dirty_worktree")
    empty["derived_status"] = []
    with pytest.raises(ValueError, match="derived_status must be a non-empty list"):
        explain_assessment(empty)


def test_explain_assessment_rejects_missing_or_null_source_refs():
    missing = _assessment("dirty_worktree")
    missing.pop("source_refs")
    with pytest.raises(ValueError, match="source_refs must be a list of strings"):
        explain_assessment(missing)

    null_value = _assessment("dirty_worktree")
    null_value["source_refs"] = None
    with pytest.raises(ValueError, match="source_refs must be a list of strings"):
        explain_assessment(null_value)


def test_explain_assessment_rejects_null_optional_list_when_present():
    assessment = _assessment("dirty_worktree")
    assessment["missing_evidence"] = None

    with pytest.raises(ValueError, match="missing_evidence must be a list of strings"):
        explain_assessment(assessment)


def test_explanation_schema_rejects_forbidden_top_level_fields():
    schema = _schema()
    explanation = explain_assessment(_assessment("dirty_worktree"))

    for field in FORBIDDEN_EXPLANATION_KEYS:
        invalid = copy.deepcopy(explanation)
        invalid[field] = "forbidden"
        with pytest.raises(ValidationError):
            validate_instance(invalid, schema, Path(f"invalid-{field}.json"))


def test_explanation_schema_rejects_boundary_false_values():
    schema = _schema()
    explanation = explain_assessment(_assessment("dirty_worktree"))

    for key in (
        "does_not_authorise_actions",
        "does_not_mutate",
        "does_not_plan_actions",
    ):
        invalid = copy.deepcopy(explanation)
        invalid["boundary"][key] = False
        with pytest.raises(ValidationError):
            validate_instance(invalid, schema, Path(f"invalid-boundary-{key}.json"))


def test_explain_assessment_multi_status_emits_two_status_explanations():
    assessment = {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example-multi",
        "observation_ref": "obs-example-multi",
        "derived_status": ["scope_backup", "dirty_worktree"],
        "source_refs": [
            "git.status.porcelain",
            "local_config.canonical_repo_roots",
            "local_config.excluded_repo_roots",
            "filesystem.path",
        ],
        "decision_state": "action_blocked",
        "missing_evidence": ["default_branch_source"],
    }

    explanation = explain_assessment(assessment)
    entries = explanation["status_explanations"]

    assert len(entries) == 2
    assert [item["status"] for item in entries] == ["scope_backup", "dirty_worktree"]

    scope_item = entries[0]
    dirty_item = entries[1]

    assert scope_item["rule_refs"] == ["assessment.rule.scope_backup_blocks_action"]
    assert scope_item["freshness_refs"] == ["freshness.local_scope_config.current_invocation"]
    assert scope_item["falsification_refs"] == ["failure-case.backup_repo_accidentally_used"]

    assert dirty_item["rule_refs"] == ["assessment.rule.dirty_worktree_blocks_action"]
    assert dirty_item["freshness_refs"] == ["freshness.local_git_status.current_invocation"]
    assert dirty_item["falsification_refs"] == ["failure-case.dirty_worktree"]

    # missing_evidence remains assessment-level context and is repeated per status item.
    assert scope_item["missing_evidence"] == ["default_branch_source"]
    assert dirty_item["missing_evidence"] == ["default_branch_source"]
