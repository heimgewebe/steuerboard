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



def test_schema_rejects_wrong_action():
    schema = _action_plan_schema()
    plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example",
        "action": "git.reset",
        "assessment_ref": "assess-example",
        "decision": "not_applicable",
        "source_refs": ["git.current_branch"],
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": [],
        "missing_evidence": [],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    with pytest.raises(ValidationError, match="switch-main|expected"):
        validate_instance(plan, schema, Path("plan-with-wrong-action.json"))


@pytest.mark.parametrize("decision", ["allowed", "warn"])
def test_schema_rejects_non_preview_decisions(decision: str):
    schema = _action_plan_schema()
    plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example",
        "action": "switch-main",
        "assessment_ref": "assess-example",
        "decision": decision,
        "source_refs": ["git.current_branch"],
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": [],
        "missing_evidence": [],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    with pytest.raises(ValidationError, match="const|enum|not one of"):
        validate_instance(plan, schema, Path(f"plan-with-{decision}.json"))


@pytest.mark.parametrize("missing_field", [
    "source_refs",
    "rule_refs",
    "freshness_refs",
    "falsification_refs",
    "missing_evidence",
])
def test_schema_requires_provenance_lists(missing_field: str):
    schema = _action_plan_schema()
    plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example",
        "action": "switch-main",
        "assessment_ref": "assess-example",
        "decision": "not_applicable",
        "source_refs": ["git.current_branch"],
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": [],
        "missing_evidence": [],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }
    plan.pop(missing_field)

    with pytest.raises(ValidationError, match="required property|is a required property"):
        validate_instance(plan, schema, Path(f"plan-missing-{missing_field}.json"))


def test_blocked_runtime_emits_blocked_because():
    assessment = _assessment_with_statuses(["non_default_branch"])

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "blocked"
    assert "blocked_because" in plan
    assert len(plan["blocked_because"]) >= 1


def test_not_applicable_runtime_omits_blocked_because():
    assessment = _assessment_with_statuses(["clean_default_current"])

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "not_applicable"
    assert "blocked_because" not in plan


def test_schema_enforces_blocked_because_conditionals():
    schema = _action_plan_schema()
    blocked_without_reason = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example",
        "action": "switch-main",
        "assessment_ref": "assess-example",
        "decision": "blocked",
        "source_refs": ["git.current_branch"],
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": [],
        "missing_evidence": [],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    not_applicable_with_reason = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example",
        "action": "switch-main",
        "assessment_ref": "assess-example",
        "decision": "not_applicable",
        "blocked_because": ["clean_default_current"],
        "source_refs": ["git.current_branch"],
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": [],
        "missing_evidence": [],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    with pytest.raises(ValidationError, match="blocked_because"):
        validate_instance(blocked_without_reason, schema, Path("plan-blocked-without-reason.json"))

    with pytest.raises(ValidationError, match="forbidden schema|should not be valid under"):
        validate_instance(
            not_applicable_with_reason,
            schema,
            Path("plan-not-applicable-with-reason.json"),
        )


def _action_plan_schema() -> dict:
    return load_json(SCHEMAS_DIR / "action-plan.v1.schema.json")


def _assessment_with_statuses(statuses: list[str], decision_state: str | None = None) -> dict:
    if decision_state is None:
        decision_state = "assessment_clear" if statuses == ["clean_default_current"] else "evidence_missing"

    return {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example",
        "observation_ref": "observe-example",
        "derived_status": statuses,
        "source_refs": ["local.git.status"],
        "decision_state": decision_state,
        "missing_evidence": ["fresh_origin_main"],
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": ["failure-case.feature_branch_unmerged"],
    }


def test_schema_rejects_empty_source_refs():
    schema = _action_plan_schema()
    plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example",
        "action": "switch-main",
        "assessment_ref": "assess-example",
        "decision": "not_applicable",
        "source_refs": [],
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

    with pytest.raises(ValidationError, match="minItems|fewer than|non-empty"):
        validate_instance(plan, schema, Path("plan-empty-source-refs.json"))


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


def test_missing_or_empty_observation_ref_raises_value_error():
    missing_observation = _assessment_with_statuses(["dirty_worktree"])
    missing_observation.pop("observation_ref")

    with pytest.raises(ValueError, match="observation_ref"):
        plan_switch_main(missing_observation)

    empty_observation = _assessment_with_statuses(["dirty_worktree"])
    empty_observation["observation_ref"] = "  "

    with pytest.raises(ValueError, match="observation_ref"):
        plan_switch_main(empty_observation)


def test_missing_or_invalid_decision_state_raises_value_error():
    missing_decision_state = _assessment_with_statuses(["dirty_worktree"])
    missing_decision_state.pop("decision_state")

    with pytest.raises(ValueError, match="decision_state"):
        plan_switch_main(missing_decision_state)

    invalid_decision_state = _assessment_with_statuses(["dirty_worktree"])
    invalid_decision_state["decision_state"] = "totally_invalid_state"

    with pytest.raises(ValueError, match="decision_state"):
        plan_switch_main(invalid_decision_state)


def test_input_contract_coherence_clean_default_requires_assessment_clear_decision_state():
    assessment = _assessment_with_statuses(["clean_default_current"], decision_state="evidence_missing")

    with pytest.raises(ValueError, match="decision_state"):
        plan_switch_main(assessment)


def test_input_contract_coherence_blocking_status_forbids_assessment_clear_decision_state():
    assessment = _assessment_with_statuses(["non_default_branch"], decision_state="assessment_clear")

    with pytest.raises(ValueError, match="decision_state"):
        plan_switch_main(assessment)


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
    assert "would_run" not in plan
    assert "would_mutate" not in plan
    assert "safe_alternatives" not in plan
    assert "required_evidence" not in plan


def test_multi_blocking_statuses_preserved():
    assessment = _assessment_with_statuses(["scope_backup", "dirty_worktree"])

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "blocked"
    assert set(plan["blocked_because"]) == {"scope_backup", "dirty_worktree"}


@pytest.mark.parametrize("field", [
    "missing_evidence",
    "rule_refs",
    "freshness_refs",
    "falsification_refs",
])
def test_null_optional_field_raises_value_error(field: str):
    """Verify null optional list fields raise ValueError."""
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment[field] = None

    with pytest.raises(ValueError, match=f"{field} must not be null"):
        plan_switch_main(assessment)


def test_null_source_refs_raises_value_error():
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment["source_refs"] = None

    with pytest.raises(ValueError, match="source_refs"):
        plan_switch_main(assessment)


@pytest.mark.parametrize("field,value", [
    ("would_run", ["git switch main"]),
    ("would_mutate", ["current_branch"]),
    ("safe_alternatives", ["show_diff_against_default"]),
    ("required_evidence", ["fresh_origin_main"]),
])
def test_schema_forbids_execution_fields(field: str, value: list[str]):
    """Verify schema rejects all old executor-oriented fields."""
    schema = _action_plan_schema()
    plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example",
        "action": "switch-main",
        "assessment_ref": "assess-example",
        "decision": "blocked",
        "source_refs": ["git.current_branch"],
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": [],
        "missing_evidence": [],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
        "blocked_because": ["dirty_worktree"],
        field: value,
    }

    with pytest.raises(ValidationError, match="not allowed|unexpected"):
        validate_instance(plan, schema, Path(f"plan-with-{field}.json"))


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
