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


def test_explain_assessment_preserves_missing_evidence():
    assessment = _assessment("non_default_branch")
    assessment["missing_evidence"] = ["branch_contains_origin_main_or_pr_merged", "fresh_origin_main"]

    explanation = explain_assessment(assessment)

    assert explanation["status_explanations"][0]["missing_evidence"] == assessment["missing_evidence"]


def test_clean_default_current_mentions_unverified_default_branch_source():
    explanation = explain_assessment(_assessment("clean_default_current"))

    assert "default_branch_source remains unverified" in explanation["status_explanations"][0]["meaning"]


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


def test_explanation_schema_rejects_forbidden_top_level_fields():
    schema = _schema()
    explanation = explain_assessment(_assessment("dirty_worktree"))

    for field in FORBIDDEN_EXPLANATION_KEYS:
        invalid = copy.deepcopy(explanation)
        invalid[field] = "forbidden"
        with pytest.raises(ValidationError):
            validate_instance(invalid, schema, Path(f"invalid-{field}.json"))
