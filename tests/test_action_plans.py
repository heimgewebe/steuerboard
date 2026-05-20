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
