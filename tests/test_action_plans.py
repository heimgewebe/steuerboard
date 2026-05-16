from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import SCHEMAS_DIR, ValidationError, load_json, validate_instance
from steuerboard.action_plans import plan_switch_main


FORBIDDEN_EXECUTION_FIELDS = {
    "would_run",
    "would_mutate",
    "safe_alternatives",
    "required_evidence",
}


def _action_plan_schema() -> dict:
    return load_json(SCHEMAS_DIR / "action-plan.v1.schema.json")


def _assessment_with_statuses(statuses: list[str]) -> dict:
    return {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example",
        "derived_status": statuses,
        "source_refs": ["local.git.status"],
        "missing_evidence": ["fresh_origin_main"],
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": ["failure-case.feature_branch_unmerged"],
    }


def test_plan_switch_main_emits_schema_valid_action_plan_v1():
    assessment = _assessment_with_statuses(["non_default_branch"])

    plan = plan_switch_main(assessment)

    validate_instance(plan, _action_plan_schema(), Path("plan-switch-main.json"))


def test_non_default_branch_blocks_and_preserves_missing_evidence():
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment["missing_evidence"] = [
        "branch_contains_origin_main_or_pr_merged",
        "fresh_origin_main",
    ]

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["non_default_branch"]
    assert plan["missing_evidence"] == assessment["missing_evidence"]


def test_dirty_worktree_blocks():
    assessment = _assessment_with_statuses(["dirty_worktree"])

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["dirty_worktree"]


def test_non_canonical_scope_blocks():
    assessment = _assessment_with_statuses(["scope_backup"])

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["scope_backup"]


def test_clean_default_current_is_not_applicable():
    assessment = _assessment_with_statuses(["clean_default_current"])

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "not_applicable"
    assert "blocked_because" not in plan


def test_unknown_status_raises_value_error():
    assessment = _assessment_with_statuses(["totally_unknown_status"])

    with pytest.raises(ValueError):
        plan_switch_main(assessment)


def test_missing_or_wrong_schema_version_raises_value_error():
    missing_schema = _assessment_with_statuses(["dirty_worktree"])
    missing_schema.pop("schema_version")

    with pytest.raises(ValueError):
        plan_switch_main(missing_schema)

    wrong_schema = _assessment_with_statuses(["dirty_worktree"])
    wrong_schema["schema_version"] = "repo-assessment.v2"

    with pytest.raises(ValueError):
        plan_switch_main(wrong_schema)


def test_schema_rejects_boundary_fields_if_false():
    assessment = _assessment_with_statuses(["dirty_worktree"])
    plan = plan_switch_main(assessment)
    plan["boundary"] = {
        "does_not_execute": False,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }

    with pytest.raises(ValidationError):
        validate_instance(plan, _action_plan_schema(), Path("plan-invalid-boundary.json"))


def test_forbidden_execution_fields_are_not_emitted():
    assessment = _assessment_with_statuses(["non_default_branch"])

    plan = plan_switch_main(assessment)

    assert FORBIDDEN_EXECUTION_FIELDS.isdisjoint(plan.keys())


def test_cli_plan_switch_main_smoke(tmp_path: Path):
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment["missing_evidence"] = [
        "branch_contains_origin_main_or_pr_merged",
        "fresh_origin_main",
    ]
    assessment_path = tmp_path / "assessment.json"
    assessment_path.write_text(json.dumps(assessment), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "plan",
            "switch-main",
            str(assessment_path),
            "--json",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    plan = json.loads(result.stdout)
    validate_instance(plan, _action_plan_schema(), Path("cli-plan-switch-main.json"))
    assert plan["decision"] == "blocked"
    assert plan["assessment_ref"] == "assess-example"
