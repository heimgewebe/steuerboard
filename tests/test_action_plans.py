from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import SCHEMAS_DIR, ValidationError, load_json, validate_instance
from steuerboard.action_plans import plan_git_pull_ff_only, plan_switch_main


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
        if statuses == ["clean_default_current"]:
            decision_state = "assessment_clear"
        elif statuses == ["non_default_branch"] or statuses == ["default_branch_unknown"]:
            decision_state = "evidence_missing"
        else:
            decision_state = "action_blocked"

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


def _assessment_for_remote_refresh_example(statuses: list[str]) -> dict:
    """Helper: assessment matching example remote-refresh-result.v1 repo_ref."""
    return {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example-pull-preflight-local-clear-evidence-missing",
        "observation_ref": "observe-example-pull-preflight-local-clear-evidence-missing",
        "derived_status": statuses,
        "source_refs": ["local.git.status"],
        "decision_state": "evidence_missing",
        "missing_evidence": ["remote_freshness"],
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

    with pytest.raises(ValidationError, match="minItems|fewer than|non-empty|too short"):
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


def test_lone_clean_default_current_requires_assessment_clear_decision_state():
    # Regression A: lone clean_default_current must remain internally coherent.
    # Without additional unrelated statuses there is no justification for a
    # non-assessment_clear aggregate, so the planner must reject it.
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
def test_null_required_assessment_list_field_raises_value_error(field: str):
    """Verify null required list fields raise ValueError."""
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment[field] = None

    with pytest.raises(ValueError, match=field):
        plan_switch_main(assessment)


@pytest.mark.parametrize("field", [
    "missing_evidence",
    "rule_refs",
    "freshness_refs",
    "falsification_refs",
])
def test_missing_optional_assessment_list_field_defaults_to_empty_list(field: str):
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment.pop(field)

    plan = plan_switch_main(assessment)

    assert plan[field] == []


def test_null_source_refs_raises_value_error():
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment["source_refs"] = None

    with pytest.raises(ValueError, match="source_refs"):
        plan_switch_main(assessment)


def test_missing_source_refs_raises_value_error():
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment.pop("source_refs")

    with pytest.raises(ValueError, match="source_refs"):
        plan_switch_main(assessment)


def test_empty_source_refs_raises_value_error():
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment["source_refs"] = []

    with pytest.raises(ValueError, match="source_refs"):
        plan_switch_main(assessment)


@pytest.mark.parametrize("field", [
    "source_refs",
    "missing_evidence",
    "rule_refs",
    "freshness_refs",
    "falsification_refs",
])
def test_whitespace_only_assessment_list_items_raise_value_error(field: str):
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment[field] = ["   "]

    with pytest.raises(ValueError, match=field):
        plan_switch_main(assessment)


def test_padded_assessment_id_raises_value_error():
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment["assessment_id"] = f" {assessment['assessment_id']} "

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        plan_switch_main(assessment)


def test_padded_observation_ref_raises_value_error():
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment["observation_ref"] = f" {assessment['observation_ref']} "

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        plan_switch_main(assessment)


@pytest.mark.parametrize("field", [
    "source_refs",
    "missing_evidence",
    "rule_refs",
    "freshness_refs",
    "falsification_refs",
])
def test_padded_assessment_list_items_raise_value_error(field: str):
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment[field] = [f" {assessment[field][0]} "]

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        plan_switch_main(assessment)


@pytest.mark.parametrize("field,value", [
    ("action", "switch-main"),
    ("plan_id", "plan-legacy"),
    ("would_run", ["git switch main"]),
    ("would_mutate", ["current_branch"]),
    ("safe_alternatives", ["show_diff_against_default"]),
    ("required_evidence", ["fresh_origin_main"]),
    ("command_trace", {"schema_version": "command-trace.v1"}),
    ("run_result", {"schema_version": "run-result.v1"}),
])
def test_runtime_rejects_forbidden_plan_or_executor_input_fields(field: str, value: object):
    assessment = _assessment_with_statuses(["non_default_branch"])
    assessment[field] = value

    with pytest.raises(ValueError, match="forbidden"):
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


@pytest.mark.parametrize("field", [
    "source_refs",
    "rule_refs",
    "freshness_refs",
    "falsification_refs",
    "missing_evidence",
])
def test_schema_rejects_whitespace_only_action_plan_list_items(field: str):
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
    plan[field] = ["   "]

    with pytest.raises(ValidationError):
        validate_instance(plan, schema, Path(f"plan-whitespace-{field}.json"))


@pytest.mark.parametrize("field", [
    "source_refs",
    "rule_refs",
    "freshness_refs",
    "falsification_refs",
    "missing_evidence",
])
def test_schema_rejects_padded_action_plan_list_items(field: str):
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
    plan[field] = [" git.current_branch "]

    with pytest.raises(ValidationError):
        validate_instance(plan, schema, Path(f"plan-padded-{field}.json"))


def test_schema_rejects_whitespace_only_blocked_because_item():
    schema = _action_plan_schema()
    plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example",
        "action": "switch-main",
        "assessment_ref": "assess-example",
        "decision": "blocked",
        "blocked_because": ["   "],
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

    with pytest.raises(ValidationError):
        validate_instance(plan, schema, Path("plan-whitespace-blocked-because.json"))


def test_schema_rejects_padded_plan_scalars_and_blocked_because_item():
    schema = _action_plan_schema()
    plan = {
        "schema_version": "action-plan.v1",
        "plan_id": " plan-example ",
        "action": "switch-main",
        "assessment_ref": " assess-example ",
        "decision": "blocked",
        "blocked_because": [" dirty_worktree "],
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

    with pytest.raises(ValidationError):
        validate_instance(plan, schema, Path("plan-padded-scalars.json"))


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


# ---------------------------------------------------------------------------
# Phase 7a.2 pull-readiness regression tests
# Ensure switch-main planner tolerates known pull-readiness statuses without
# treating them as switch-main blockers or unknown statuses.
# ---------------------------------------------------------------------------

def test_pull_readiness_local_preflight_clear_with_evidence_missing_does_not_crash():
    # Regression B: mixed clean_default_current + pull-readiness statuses with evidence_missing.
    # Pull-readiness statuses are switch-main-irrelevant and push the aggregate to evidence_missing.
    # switch-main planner must emit not_applicable; it ignores aggregate decision_state when
    # unrelated known statuses are present alongside clean_default_current.
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
        decision_state="evidence_missing",
    )

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "not_applicable"
    assert "blocked_because" not in plan


def test_pull_readiness_blocked_missing_upstream_does_not_crash_switch_main():
    # Regression C: mixed clean_default_current + pull blocked due to missing upstream.
    # Pull-readiness pushes aggregate to action_blocked, but that is unrelated to switch-main.
    # switch-main planner must emit not_applicable (already on default branch).
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_blocked_missing_upstream",
        ],
        decision_state="action_blocked",
    )

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "not_applicable"
    assert "blocked_because" not in plan


def test_truly_unknown_status_still_raises():
    # Regression D: genuinely unknown statuses must still raise ValueError.
    assessment = _assessment_with_statuses(["totally_unknown_and_invented_status"])

    with pytest.raises(ValueError, match="unknown derived_status"):
        plan_switch_main(assessment)


def test_switch_main_blockers_still_block_regardless_of_pull_readiness():
    # Regression E: switch-main blockers remain effective even when pull-readiness
    # statuses are present alongside them.
    assessment = _assessment_with_statuses(
        [
            "non_default_branch",
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
        decision_state="evidence_missing",
    )

    plan = plan_switch_main(assessment)

    assert plan["decision"] == "blocked"
    assert "non_default_branch" in plan["blocked_because"]


def test_cli_plan_switch_main_with_pull_readiness_example(tmp_path: Path):
    # CLI smoke: use the checked-in pull-preflight-local-clear example which has
    # decision_state: evidence_missing and pull-readiness statuses present.
    examples_dir = Path(__file__).parent.parent / "examples" / "assessments"
    assessment_path = examples_dir / "pull-preflight-local-clear-evidence-missing.json"

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
    validate_instance(plan, _action_plan_schema(), Path("cli-plan-switch-main-pull-readiness.json"))
    assert plan["decision"] == "not_applicable"


# ---------------------------------------------------------------------------
# Phase 7a.3 git-pull-ff-only plan preview tests
# ---------------------------------------------------------------------------

def test_schema_accepts_git_pull_ff_only_action():
    schema = _action_plan_schema()
    plan = {
        "schema_version": "action-plan.v1",
        "plan_id": "plan-example-git-pull-ff-only",
        "action": "git-pull-ff-only",
        "assessment_ref": "assess-example",
        "decision": "blocked",
        "blocked_because": ["git_pull_ff_only_evidence_missing_remote_freshness"],
        "source_refs": ["git.current_branch"],
        "rule_refs": ["assessment.rule.git_pull_ff_only_evidence_missing_remote_freshness"],
        "freshness_refs": ["freshness.remote_tracking.not_observed_no_fetch"],
        "falsification_refs": ["failure-case.origin_main_stale"],
        "missing_evidence": ["remote_freshness"],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    validate_instance(plan, schema, Path("plan-git-pull-ff-only-valid.json"))


def test_plan_git_pull_ff_only_emits_schema_valid_action_plan_v1():
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
        decision_state="evidence_missing",
    )
    assessment["missing_evidence"] = ["default_branch_source", "remote_freshness"]

    plan = plan_git_pull_ff_only(assessment)

    validate_instance(plan, _action_plan_schema(), Path("plan-git-pull-ff-only.json"))
    assert plan["action"] == "git-pull-ff-only"
    assert plan["decision"] == "blocked"


def test_cli_plan_git_pull_ff_only_emits_schema_valid_action_plan_v1(tmp_path: Path):
    examples_dir = Path(__file__).parent.parent / "examples" / "assessments"
    assessment_path = examples_dir / "pull-preflight-local-clear-evidence-missing.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "plan",
            "git-pull-ff-only",
            str(assessment_path),
            "--json",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    plan = json.loads(result.stdout)
    validate_instance(plan, _action_plan_schema(), Path("cli-plan-git-pull-ff-only.json"))
    assert plan["action"] == "git-pull-ff-only"
    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_evidence_missing_remote_freshness" in plan["blocked_because"]


def test_git_pull_remote_freshness_missing_blocks_pull_plan():
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
        decision_state="evidence_missing",
    )
    assessment["missing_evidence"] = ["remote_freshness"]

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["git_pull_ff_only_evidence_missing_remote_freshness"]
    assert "remote_freshness" in plan["missing_evidence"]


def test_git_pull_dirty_worktree_blocks_pull_plan():
    assessment = _assessment_with_statuses(["dirty_worktree"])

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["dirty_worktree"]


def test_git_pull_non_default_branch_blocks_pull_plan():
    assessment = _assessment_with_statuses(["non_default_branch"], decision_state="evidence_missing")

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["non_default_branch"]


def test_git_pull_branch_ahead_blocks_pull_plan():
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_blocked_branch_ahead",
        ],
        decision_state="action_blocked",
    )

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["git_pull_ff_only_blocked_branch_ahead"]


def test_git_pull_branch_diverged_blocks_pull_plan():
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_blocked_branch_diverged",
        ],
        decision_state="action_blocked",
    )

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["git_pull_ff_only_blocked_branch_diverged"]


def test_git_pull_missing_upstream_blocks_pull_plan():
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_blocked_missing_upstream",
        ],
        decision_state="action_blocked",
    )

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["git_pull_ff_only_blocked_missing_upstream"]


def test_git_pull_missing_tracking_counts_blocks_pull_plan():
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_evidence_missing_tracking_counts",
        ],
        decision_state="evidence_missing",
    )

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["git_pull_ff_only_evidence_missing_tracking_counts"]


def test_git_pull_missing_pull_assessment_blocks_with_missing_evidence_marker():
    assessment = _assessment_with_statuses(["clean_default_current"], decision_state="assessment_clear")
    assessment["missing_evidence"] = ["default_branch_source"]

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["git_pull_ff_only_assessment_missing_preflight"]
    assert "git_pull_ff_only_assessment" in plan["missing_evidence"]


def test_git_pull_preview_only_blocker_adds_execution_gate_missing_evidence():
    assessment = _assessment_with_statuses(
        ["clean_default_current", "git_pull_ff_only_local_preflight_clear"],
        decision_state="assessment_clear",
    )

    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["git_pull_ff_only_preview_only_execution_out_of_scope"]
    assert "execution_authorization" in plan["missing_evidence"]
    assert "runner_contract" in plan["missing_evidence"]
    assert "user_approval" in plan["missing_evidence"]
    assert "would_run" not in plan
    assert "would_mutate" not in plan
    assert "command_trace" not in plan
    assert "run_result" not in plan


def test_git_pull_planner_does_not_emit_command_advice_fields():
    assessment = _assessment_with_statuses(["dirty_worktree"])

    plan = plan_git_pull_ff_only(assessment)

    assert "safe_alternatives" not in plan
    assert "required_evidence" not in plan


def test_git_pull_planner_does_not_emit_execution_fields():
    assessment = _assessment_with_statuses(["dirty_worktree"])

    plan = plan_git_pull_ff_only(assessment)

    assert "would_run" not in plan
    assert "would_mutate" not in plan
    assert "command_trace" not in plan
    assert "run_result" not in plan


@pytest.mark.parametrize("field,value", [
    ("action", "switch-main"),
    ("plan_id", "plan-legacy"),
    ("would_run", ["git pull --ff-only"]),
    ("would_mutate", ["refs/heads/main"]),
    ("safe_alternatives", ["observe repo ."]),
    ("required_evidence", ["remote_freshness"]),
    ("command_trace", {"schema_version": "command-trace.v1"}),
    ("run_result", {"schema_version": "run-result.v1"}),
])
def test_git_pull_planner_rejects_forbidden_input_fields(field: str, value: object):
    assessment = _assessment_with_statuses(["dirty_worktree"])
    assessment[field] = value

    with pytest.raises(ValueError, match="forbidden"):
        plan_git_pull_ff_only(assessment)


def test_switch_main_ignores_unrelated_git_pull_tracking_count_statuses():
    assessment = _assessment_with_statuses(
        [
            "clean_default_current",
            "git_pull_ff_only_evidence_missing_tracking_counts",
        ],
        decision_state="evidence_missing",
    )

    plan = plan_switch_main(assessment)

    assert plan["action"] == "switch-main"
    assert plan["decision"] == "not_applicable"


def test_git_pull_planner_rejects_unknown_derived_status():
    """Verify that unknown statuses are rejected with ValueError, not silently ignored."""
    assessment = _assessment_with_statuses(
        ["clean_default_current", "truly_unknown_status"],
        decision_state="assessment_clear",
    )

    with pytest.raises(ValueError, match="unknown statuses not in action plan vocabulary"):
        plan_git_pull_ff_only(assessment)


def test_git_pull_planner_rejects_invalid_decision_state():
    assessment = _assessment_with_statuses(
        ["clean_default_current", "git_pull_ff_only_local_preflight_clear"],
        decision_state="assessment_clear",
    )
    assessment["decision_state"] = "bogus_state"

    with pytest.raises(ValueError, match="decision_state"):
        plan_git_pull_ff_only(assessment)


def test_git_pull_planner_does_not_mutate_input_assessment():
    """Verify that planner creates defensive copies and does not mutate input."""
    assessment = _assessment_with_statuses(
        ["git_pull_ff_only_local_preflight_clear"],
        decision_state="assessment_clear",
    )
    original_missing_evidence = assessment["missing_evidence"][:]
    original_rule_refs = assessment["rule_refs"][:]

    plan = plan_git_pull_ff_only(assessment)

    # Input assessment must not be modified
    assert assessment["missing_evidence"] == original_missing_evidence
    assert assessment["rule_refs"] == original_rule_refs
    # But plan may add to its own copies
    assert isinstance(plan["missing_evidence"], list)


@pytest.mark.parametrize(
    "pull_status",
    [
        "git_pull_ff_only_local_preflight_clear",
        "git_pull_ff_only_blocked_missing_upstream",
        "git_pull_ff_only_evidence_missing_tracking_counts",
        "git_pull_ff_only_blocked_branch_ahead",
        "git_pull_ff_only_blocked_branch_diverged",
        "git_pull_ff_only_evidence_missing_remote_freshness",
    ],
)
def test_switch_main_tolerates_all_known_pull_statuses(pull_status: str):
    """Verify switch-main planner tolerates all known git_pull_ff_only_* statuses."""
    assessment = _assessment_with_statuses(
        ["clean_default_current", pull_status],
        decision_state="evidence_missing" if "missing" in pull_status else "assessment_clear",
    )

    # Must not raise ValueError for unknown status
    plan = plan_switch_main(assessment)

    # Switch-main should still return "not_applicable" for clean_default_current
    assert plan["action"] == "switch-main"
    assert plan["decision"] == "not_applicable"


def test_switch_main_planner_rejects_truly_unknown_derived_status():
    """Verify that switch-main also rejects unknown statuses (not in KNOWN_ASSESSMENT_STATUSES)."""
    assessment = _assessment_with_statuses(
        ["clean_default_current", "totally_bogus_status"],
        decision_state="assessment_clear",
    )

    with pytest.raises(ValueError, match="unknown derived_status value"):
        plan_switch_main(assessment)


# ---------------------------------------------------------------------------
# Phase 7b.2 remote-refresh-result integration tests
# Verify planner behavior with optional remote-refresh-result.v1 artifacts
# ---------------------------------------------------------------------------

def _remote_refresh_result() -> dict:
    """Helper: load example remote-refresh-result.v1 (success case)."""
    return load_json(Path(__file__).parent.parent / "examples" / "remote-refresh-results" / "fetch-origin-prune-success.json")


def _remote_refresh_result_failed() -> dict:
    """Helper: load example remote-refresh-result.v1 (network failure case)."""
    return load_json(Path(__file__).parent.parent / "examples" / "remote-refresh-results" / "fetch-origin-prune-network-failed.json")


def test_git_pull_planner_without_remote_refresh_still_blocks_on_missing_remote_freshness():
    """A: Backward compatibility. Without --remote-refresh-result, behavior unchanged."""
    assessment = _assessment_with_statuses(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
        decision_state="evidence_missing",
    )

    # No remote_refresh_result argument
    plan = plan_git_pull_ff_only(assessment)

    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_evidence_missing_remote_freshness" in plan["blocked_because"]
    assert "remote_freshness" in plan["missing_evidence"]


def test_git_pull_planner_with_successful_remote_refresh_removes_freshness_blocker():
    """B1: Successful remote-refresh result removes remote freshness blocker."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    # Freshness blocker must be removed
    assert "git_pull_ff_only_evidence_missing_remote_freshness" not in plan["blocked_because"]
    assert "remote_freshness" not in plan["missing_evidence"]

    # But must still be blocked as preview-only
    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_preview_only_execution_out_of_scope" in plan["blocked_because"]


def test_git_pull_planner_with_successful_remote_refresh_adds_provenance():
    """B2: Successful remote-refresh adds refresh evidence to source_refs and freshness_refs."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    refresh_id = remote_refresh["refresh_id"]

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    # Refresh provenance must be added
    assert f"remote_refresh.{refresh_id}" in plan["source_refs"]
    assert "freshness.remote_tracking.fetch_origin_prune.fresh" in plan["freshness_refs"]


def test_git_pull_planner_with_failed_remote_refresh_keeps_blocker():
    """C1: Failed remote-refresh keeps remote freshness blocker."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result_failed()

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_evidence_missing_remote_freshness" in plan["blocked_because"]
    assert "remote_freshness" in plan["missing_evidence"]


def test_git_pull_planner_with_failed_remote_refresh_adds_blocker_when_missing_in_assessment():
    """C1b: Failed/unfresh refresh must add freshness blocker even if absent initially."""
    assessment = _assessment_for_remote_refresh_example(
        ["git_pull_ff_only_local_preflight_clear"],
    )
    remote_refresh = _remote_refresh_result_failed()

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_evidence_missing_remote_freshness" in plan["blocked_because"]
    assert "git_pull_ff_only_preview_only_execution_out_of_scope" not in plan["blocked_because"]
    assert "remote_freshness" in plan["missing_evidence"]


def test_git_pull_planner_with_failed_remote_refresh_adds_provenance():
    """C2: Failed remote-refresh adds provenance so failure is explainable."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result_failed()
    refresh_id = remote_refresh["refresh_id"]

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    # Refresh provenance must still be added for audit trail
    assert f"remote_refresh.{refresh_id}" in plan["source_refs"]


def test_git_pull_planner_rejects_remote_refresh_repo_ref_mismatch():
    """D1: repo_ref mismatch raises ValueError with clear message."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    # Corrupt the repo_ref
    remote_refresh["repo_ref"] = "repo-completely-different"

    with pytest.raises(ValueError, match="repo_ref mismatch"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_wrong_schema_version():
    """E1: Defensive validation rejects wrong schema_version."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["schema_version"] = "remote-refresh-result.v2"

    with pytest.raises(ValueError, match="schema_version"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_wrong_operation():
    """E2: Defensive validation rejects wrong operation."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["operation"] = "git.pull"

    with pytest.raises(ValueError, match="operation"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_exit_code_zero_with_unknown_freshness():
    """E2g: Cross-field validation rejects exit_code==0 with remote_freshness!='fresh'."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["exit_code"] = 0
    remote_refresh["remote_freshness"] = "unknown"

    with pytest.raises(ValueError, match="exit_code == 0 requires remote_freshness == 'fresh'"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_exit_code_zero_with_stale_freshness():
    """E2h: Cross-field validation rejects exit_code==0 with remote_freshness=='stale'."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["exit_code"] = 0
    remote_refresh["remote_freshness"] = "stale"

    with pytest.raises(ValueError, match="exit_code == 0 requires remote_freshness == 'fresh'"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_exit_code_nonzero_with_fresh_freshness():
    """E2i: Cross-field validation rejects exit_code>=1 with remote_freshness=='fresh'."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result_failed()
    remote_refresh["exit_code"] = 1
    remote_refresh["remote_freshness"] = "fresh"

    with pytest.raises(ValueError, match="exit_code >= 1 requires remote_freshness to be one of"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_accepts_valid_success_remote_refresh_example():
    """E2j: Valid success example (exit_code==0, remote_freshness=='fresh') accepted."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_evidence_missing_remote_freshness" not in plan["blocked_because"]


def test_git_pull_planner_accepts_valid_network_failed_remote_refresh_example():
    """E2k: Valid failed example (exit_code>=1, remote_freshness in {stale,unknown,unavailable}) accepted."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result_failed()

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    assert plan["decision"] == "blocked"
    assert "git_pull_ff_only_evidence_missing_remote_freshness" in plan["blocked_because"]


def test_git_pull_planner_rejects_remote_refresh_mutates_refs_non_bool():
    """E2c: Strict validation rejects non-boolean mutates_refs."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["mutates_refs"] = "banana"

    with pytest.raises(ValueError, match="mutates_refs"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_started_at_invalid_datetime():
    """E2d: Strict validation rejects invalid started_at date-time."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["started_at"] = "gestern nach dem kaesebrot"

    with pytest.raises(ValueError, match="started_at"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_completed_at_invalid_datetime():
    """E2e: Strict validation rejects invalid completed_at date-time."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["completed_at"] = "definitely-not-a-datetime"

    with pytest.raises(ValueError, match="completed_at"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


@pytest.mark.parametrize("bad_trace_ref", ["", " command-trace.example "])
def test_git_pull_planner_rejects_remote_refresh_invalid_command_trace_ref(bad_trace_ref: str):
    """E2f: Strict validation rejects blank or padded command_trace_ref."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["command_trace_ref"] = bad_trace_ref

    with pytest.raises(ValueError, match="command_trace_ref"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_unknown_top_level_field():
    """E2b: Strict validation rejects unknown top-level fields."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["executor_hint"] = "should-not-be-here"

    with pytest.raises(ValueError, match="unknown top-level"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_mutates_worktree_true():
    """E3: Defensive validation rejects mutates_worktree=true."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["mutates_worktree"] = True

    with pytest.raises(ValueError, match="mutates_worktree"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_mutates_remote_true():
    """E3b: Defensive validation rejects mutates_remote=true."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["mutates_remote"] = True

    with pytest.raises(ValueError, match="mutates_remote"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_remote_name_not_origin():
    """E3c: Defensive validation rejects remote_name values other than origin."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["remote_name"] = "upstream"

    with pytest.raises(ValueError, match="remote_name"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_redacted_false():
    """E4: Defensive validation rejects redacted=false."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["redacted"] = False

    with pytest.raises(ValueError, match="redacted"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_boundary_mismatch():
    """E5: Defensive validation rejects incorrect boundary markers."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["boundary"]["does_not_pull"] = False

    with pytest.raises(ValueError, match="boundary"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_rejects_remote_refresh_boundary_with_extra_field():
    """E5b: Strict validation rejects unknown boundary fields."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()
    remote_refresh["boundary"]["does_not_force_push"] = True

    with pytest.raises(ValueError, match="boundary"):
        plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)


def test_git_pull_planner_successful_refresh_without_local_preflight_keeps_non_empty_blockers():
    """Coherence: successful refresh must not yield blocked decision with empty blocked_because."""
    assessment = _assessment_for_remote_refresh_example(
        ["git_pull_ff_only_evidence_missing_remote_freshness"],
    )
    remote_refresh = _remote_refresh_result()

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["git_pull_ff_only_assessment_missing_preflight"]
    assert "git_pull_ff_only_assessment" in plan["missing_evidence"]


def test_git_pull_planner_does_not_mutate_input_assessment_with_remote_refresh():
    """F: Input purity with remote-refresh argument."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    remote_refresh = _remote_refresh_result()

    original_missing_evidence = assessment["missing_evidence"][:]
    original_source_refs = assessment["source_refs"][:]
    original_remote_refresh = json.loads(json.dumps(remote_refresh))  # Deep copy

    plan = plan_git_pull_ff_only(assessment, remote_refresh_result=remote_refresh)

    # Assessment must not be modified
    assert assessment["missing_evidence"] == original_missing_evidence
    assert assessment["source_refs"] == original_source_refs

    # remote_refresh dict must not be modified
    assert remote_refresh == original_remote_refresh


def test_cli_git_pull_planner_with_remote_refresh_result(tmp_path: Path):
    """CLI integration: --remote-refresh-result option works end-to-end."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    assessment_path = tmp_path / "assessment.json"
    assessment_path.write_text(json.dumps(assessment), encoding="utf-8")

    remote_refresh = _remote_refresh_result()
    remote_refresh_path = tmp_path / "remote-refresh.json"
    remote_refresh_path.write_text(json.dumps(remote_refresh), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "plan",
            "git-pull-ff-only",
            str(assessment_path),
            "--remote-refresh-result",
            str(remote_refresh_path),
            "--json",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    plan = json.loads(result.stdout)
    validate_instance(plan, _action_plan_schema(), Path("cli-plan-git-pull-ff-only-with-refresh.json"))
    assert "git_pull_ff_only_evidence_missing_remote_freshness" not in plan["blocked_because"]
    assert "remote_freshness" not in plan["missing_evidence"]


def test_cli_git_pull_planner_rejects_invalid_remote_refresh_json(tmp_path: Path):
    """CLI: invalid remote-refresh JSON triggers parser.error."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    assessment_path = tmp_path / "assessment.json"
    assessment_path.write_text(json.dumps(assessment), encoding="utf-8")

    bad_refresh_path = tmp_path / "bad-remote-refresh.json"
    bad_refresh_path.write_text("{ invalid json", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "plan",
            "git-pull-ff-only",
            str(assessment_path),
            "--remote-refresh-result",
            str(bad_refresh_path),
            "--json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "invalid remote-refresh-result JSON" in result.stderr


def test_cli_git_pull_planner_rejects_remote_refresh_mismatch(tmp_path: Path):
    """CLI: repo_ref mismatch triggers parser.error."""
    assessment = _assessment_for_remote_refresh_example(
        [
            "git_pull_ff_only_local_preflight_clear",
            "git_pull_ff_only_evidence_missing_remote_freshness",
        ],
    )
    assessment_path = tmp_path / "assessment.json"
    assessment_path.write_text(json.dumps(assessment), encoding="utf-8")

    remote_refresh = _remote_refresh_result()
    remote_refresh["repo_ref"] = "repo-completely-wrong"
    remote_refresh_path = tmp_path / "remote-refresh.json"
    remote_refresh_path.write_text(json.dumps(remote_refresh), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "plan",
            "git-pull-ff-only",
            str(assessment_path),
            "--remote-refresh-result",
            str(remote_refresh_path),
            "--json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "repo_ref" in result.stderr or "mismatch" in result.stderr
