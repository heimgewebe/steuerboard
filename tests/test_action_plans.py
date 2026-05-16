from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import (
    ROOT,
    SCHEMAS_DIR,
    ValidationError,
    load_json,
    validate_instance,
)
from steuerboard.action_plans import plan_switch_main


FORBIDDEN_EXECUTION_KEYS = {
    "command_trace",
    "run_result",
    "executed_at",
    "execution_id",
    "side_effects",
    "next_action",
}


def _schema() -> dict:
    return load_json(SCHEMAS_DIR / "action-plan.v1.schema.json")


_NOT_APPLICABLE_STATUSES = frozenset({"clean_default_current"})
_EVIDENCE_MISSING_STATUSES = frozenset(
    {"default_branch_unknown", "non_default_branch"}
)


def _default_decision_state(statuses: list[str]) -> str:
    """Pick a schema-coherent decision_state for the given derived_status set.

    Mirrors steuerboard/assessment.py: blocking statuses → action_blocked,
    non-default/default-unknown → evidence_missing, clean_default_current →
    assessment_clear. Used by the test builder so fixtures stay schema-near.
    """
    status_set = set(statuses)
    if status_set & _NOT_APPLICABLE_STATUSES:
        return "assessment_clear"
    if status_set & _EVIDENCE_MISSING_STATUSES:
        return "evidence_missing"
    return "action_blocked"


def _assessment(
    status: str | list[str],
    *,
    missing_evidence: list[str] | None = None,
    decision_state: str | None = None,
) -> dict:
    statuses = [status] if isinstance(status, str) else list(status)
    return {
        "schema_version": "repo-assessment.v1",
        "assessment_id": "assess-example",
        "observation_ref": "obs-example",
        "derived_status": statuses,
        "source_refs": [
            "git.current_branch",
            "git.status.porcelain",
            "git.default_branch_candidate_source",
        ],
        "decision_state": (
            decision_state
            if decision_state is not None
            else _default_decision_state(statuses)
        ),
        "rule_refs": ["assessment.rule.example"],
        "freshness_refs": ["freshness.example"],
        "falsification_refs": [],
        "missing_evidence": list(missing_evidence) if missing_evidence else [],
    }


# ---------------------------------------------------------------------------
# 1. plan_switch_main produces schema-valid action-plan.v1
# ---------------------------------------------------------------------------

def test_plan_switch_main_output_validates_against_schema():
    plan = plan_switch_main(_assessment("dirty_worktree"))
    validate_instance(plan, _schema(), Path("plan-switch-main.json"))
    assert plan["schema_version"] == "action-plan.v1"
    assert plan["action"] == "switch-main"


# ---------------------------------------------------------------------------
# 2. non_default_branch blocks and preserves missing_evidence
# ---------------------------------------------------------------------------

def test_plan_switch_main_non_default_branch_blocks_and_preserves_missing_evidence():
    missing = ["branch_contains_origin_main_or_pr_merged", "fresh_origin_main"]
    assessment = _assessment("non_default_branch", missing_evidence=missing)

    plan = plan_switch_main(assessment)

    validate_instance(plan, _schema(), Path("plan-non-default.json"))
    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["non_default_branch"]
    assert plan["required_evidence"] == missing
    assert plan["assessment_ref"] == assessment["assessment_id"]
    assert plan["would_run"] == ["git switch main"]
    assert plan["would_mutate"] == ["current_branch"]


# ---------------------------------------------------------------------------
# 3. dirty_worktree blocks
# ---------------------------------------------------------------------------

def test_plan_switch_main_dirty_worktree_blocks():
    plan = plan_switch_main(_assessment("dirty_worktree"))

    validate_instance(plan, _schema(), Path("plan-dirty.json"))
    assert plan["decision"] == "blocked"
    assert "dirty_worktree" in plan["blocked_because"]


# ---------------------------------------------------------------------------
# 4. non-canonical scope blocks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "scope_status",
    ["scope_backup", "scope_gdrive", "scope_excluded", "scope_unknown", "scope_shadow"],
)
def test_plan_switch_main_non_canonical_scope_blocks(scope_status: str):
    plan = plan_switch_main(_assessment(scope_status))

    validate_instance(plan, _schema(), Path(f"plan-{scope_status}.json"))
    assert plan["decision"] == "blocked"
    assert scope_status in plan["blocked_because"]


def test_plan_switch_main_collects_scope_and_dirty_without_overwrite():
    plan = plan_switch_main(_assessment(["scope_backup", "dirty_worktree"]))

    validate_instance(plan, _schema(), Path("plan-scope-dirty.json"))
    assert plan["decision"] == "blocked"
    assert plan["blocked_because"] == ["scope_backup", "dirty_worktree"]


# ---------------------------------------------------------------------------
# 5. clean_default_current → not_applicable
# ---------------------------------------------------------------------------

def test_plan_switch_main_clean_default_current_is_not_applicable():
    plan = plan_switch_main(_assessment("clean_default_current"))

    validate_instance(plan, _schema(), Path("plan-clean.json"))
    assert plan["decision"] == "not_applicable"
    assert plan["blocked_because"] == []
    assert plan["would_run"] == []
    assert plan["would_mutate"] == []
    assert plan["required_evidence"] == []


# ---------------------------------------------------------------------------
# 6. unknown status raises ValueError
# ---------------------------------------------------------------------------

def test_plan_switch_main_rejects_unknown_status():
    with pytest.raises(ValueError, match="Unsupported derived_status"):
        plan_switch_main(_assessment("not_a_known_status"))


def test_plan_switch_main_rejects_mixed_blocking_and_not_applicable():
    with pytest.raises(ValueError, match="mixes blocking and not_applicable"):
        plan_switch_main(_assessment(["clean_default_current", "dirty_worktree"]))


# ---------------------------------------------------------------------------
# 7. wrong or missing schema_version raises ValueError
# ---------------------------------------------------------------------------

def test_plan_switch_main_requires_repo_assessment_schema_version():
    missing = _assessment("dirty_worktree")
    missing.pop("schema_version")
    with pytest.raises(ValueError, match="schema_version must be repo-assessment.v1"):
        plan_switch_main(missing)

    wrong = _assessment("dirty_worktree")
    wrong["schema_version"] = "action-plan.v1"
    with pytest.raises(ValueError, match="schema_version must be repo-assessment.v1"):
        plan_switch_main(wrong)


def test_plan_switch_main_rejects_non_object_input():
    with pytest.raises(ValueError, match="assessment must be an object"):
        plan_switch_main(["not-a-dict"])  # type: ignore[arg-type]


def test_plan_switch_main_rejects_empty_or_missing_derived_status():
    without = _assessment("dirty_worktree")
    without.pop("derived_status")
    with pytest.raises(ValueError, match="derived_status must be a non-empty list"):
        plan_switch_main(without)

    empty = _assessment("dirty_worktree")
    empty["derived_status"] = []
    with pytest.raises(ValueError, match="derived_status must be a non-empty list"):
        plan_switch_main(empty)


def test_plan_switch_main_rejects_missing_or_invalid_source_refs():
    missing = _assessment("dirty_worktree")
    missing.pop("source_refs")
    with pytest.raises(ValueError, match="source_refs must be a list of strings"):
        plan_switch_main(missing)

    invalid = _assessment("dirty_worktree")
    invalid["source_refs"] = None
    with pytest.raises(ValueError, match="source_refs must be a list of strings"):
        plan_switch_main(invalid)


def test_plan_switch_main_rejects_null_optional_list_when_present():
    assessment = _assessment("dirty_worktree")
    assessment["missing_evidence"] = None
    with pytest.raises(ValueError, match="missing_evidence must be a list of strings"):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_missing_observation_ref():
    assessment = _assessment("clean_default_current")
    assessment.pop("observation_ref")
    with pytest.raises(ValueError, match="observation_ref must be a non-empty string"):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_empty_observation_ref():
    assessment = _assessment("clean_default_current")
    assessment["observation_ref"] = ""
    with pytest.raises(ValueError, match="observation_ref must be a non-empty string"):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_non_string_observation_ref():
    assessment = _assessment("clean_default_current")
    assessment["observation_ref"] = 123
    with pytest.raises(ValueError, match="observation_ref must be a non-empty string"):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_missing_decision_state():
    assessment = _assessment("clean_default_current")
    assessment.pop("decision_state")
    with pytest.raises(ValueError, match="decision_state must be a non-empty string"):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_empty_decision_state():
    assessment = _assessment("clean_default_current")
    assessment["decision_state"] = ""
    with pytest.raises(ValueError, match="decision_state must be a non-empty string"):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_invalid_decision_state_value():
    assessment = _assessment("clean_default_current", decision_state="some_future_state")
    with pytest.raises(
        ValueError,
        match=r"decision_state must be one of",
    ):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_input_contract_incoherence_clean_with_action_blocked():
    """Input-contract coherence: clean_default_current is only consistent with
    decision_state == 'assessment_clear'."""
    assessment = _assessment("clean_default_current", decision_state="action_blocked")
    with pytest.raises(ValueError, match="input-contract incoherence"):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_input_contract_incoherence_blocking_with_assessment_clear():
    """Input-contract coherence: a blocking derived_status is incompatible with
    decision_state == 'assessment_clear'."""
    assessment = _assessment("dirty_worktree", decision_state="assessment_clear")
    with pytest.raises(ValueError, match="input-contract incoherence"):
        plan_switch_main(assessment)


def test_plan_switch_main_rejects_missing_or_blank_assessment_id():
    no_id = _assessment("dirty_worktree")
    no_id.pop("assessment_id")
    with pytest.raises(ValueError, match="assessment_id must be a non-empty string"):
        plan_switch_main(no_id)

    empty_id = _assessment("dirty_worktree")
    empty_id["assessment_id"] = ""
    with pytest.raises(ValueError, match="assessment_id must be a non-empty string"):
        plan_switch_main(empty_id)


# ---------------------------------------------------------------------------
# 8. Boundary fields must be true; schema rejects false
# ---------------------------------------------------------------------------

def test_action_plan_schema_rejects_boundary_false_values():
    schema = _schema()
    plan = plan_switch_main(_assessment("dirty_worktree"))

    for key in ("does_not_execute", "does_not_mutate", "does_not_authorise_actions"):
        invalid = copy.deepcopy(plan)
        invalid["boundary"][key] = False
        with pytest.raises(ValidationError):
            validate_instance(invalid, schema, Path(f"invalid-boundary-{key}.json"))


def test_action_plan_schema_rejects_missing_boundary():
    schema = _schema()
    plan = plan_switch_main(_assessment("dirty_worktree"))
    invalid = copy.deepcopy(plan)
    invalid.pop("boundary")
    with pytest.raises(ValidationError):
        validate_instance(invalid, schema, Path("invalid-missing-boundary.json"))


# ---------------------------------------------------------------------------
# 9. Forbidden execution fields are not generated
# ---------------------------------------------------------------------------

def test_plan_switch_main_does_not_emit_execution_fields():
    plan = plan_switch_main(_assessment("dirty_worktree"))

    assert FORBIDDEN_EXECUTION_KEYS.isdisjoint(plan), (
        f"Plan contains forbidden execution field(s): "
        f"{FORBIDDEN_EXECUTION_KEYS & plan.keys()}"
    )


def test_plan_switch_main_never_emits_allowed_decision():
    """switch-main is a mutating action. This read-only preview slice must
    never authorise it."""
    for status in (
        "not_git_repo",
        "scope_backup",
        "scope_gdrive",
        "scope_excluded",
        "scope_unknown",
        "scope_shadow",
        "dirty_worktree",
        "detached_head",
        "default_branch_unknown",
        "non_default_branch",
        "clean_default_current",
    ):
        plan = plan_switch_main(_assessment(status))
        assert plan["decision"] in {"blocked", "not_applicable"}


# ---------------------------------------------------------------------------
# 10. CLI smoke for `plan switch-main <assessment-json> --json`
# ---------------------------------------------------------------------------

def test_plan_switch_main_cli_smoke_emits_schema_valid_json(tmp_path: Path):
    assessment = _assessment(
        "non_default_branch",
        missing_evidence=["branch_contains_origin_main_or_pr_merged", "fresh_origin_main"],
    )
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
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    plan = json.loads(result.stdout)
    validate_instance(plan, _schema(), Path("plan-cli-smoke.json"))
    assert plan["schema_version"] == "action-plan.v1"
    assert plan["action"] == "switch-main"
    assert plan["decision"] == "blocked"


def test_plan_switch_main_cli_smoke_clean_default_current_is_not_applicable(tmp_path: Path):
    assessment = _assessment("clean_default_current")
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
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    plan = json.loads(result.stdout)
    assert plan["decision"] == "not_applicable"


def test_plan_switch_main_cli_rejects_invalid_assessment_json(tmp_path: Path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not valid json", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "plan",
            "switch-main",
            str(bad),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "invalid assessment JSON" in result.stderr


def test_plan_switch_main_cli_rejects_assessment_with_wrong_schema_version(tmp_path: Path):
    assessment_path = tmp_path / "wrong-schema.json"
    assessment_path.write_text(
        json.dumps(
            {
                "schema_version": "action-plan.v1",
                "assessment_id": "x",
                "derived_status": ["dirty_worktree"],
                "source_refs": [],
            }
        ),
        encoding="utf-8",
    )

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
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "schema_version must be repo-assessment.v1" in result.stderr
