import pytest

from scripts.validate_examples import (
    EXAMPLES_DIR,
    SCHEMAS_DIR,
    _is_date_time,
    load_json,
    validate_examples,
    validate_instance,
    validate_schemas,
    minimal_validate,
    ValidationError,
)
from steuerboard.assessment_rules import (
    ASSESSMENT_PROVENANCE,
    EXISTING_FAILURE_CASE_IDS,
    attach_assessment_provenance,
)
from steuerboard.canonical_json import canonical_json_sha256

REQUIRED_FAILURE_CASES = {
    "backup_repo_accidentally_used.json",
    "branch_local_only.json",
    "branch_remote_deleted.json",
    "detached_head.json",
    "dirty_submodule.json",
    "dirty_worktree.json",
    "dubious_ownership.json",
    "duplicate_repo.json",
    "evidence_contains_secret_like_pattern.json",
    "feature_branch_merged.json",
    "feature_branch_unmerged.json",
    "ff_only_not_possible.json",
    "foreign_owner_present.json",
    "gdrive_shadow_repo.json",
    "missing_upstream.json",
    "omnipull_skip_unknown_reason.json",
    "origin_main_stale.json",
    "remote_missing.json",
    "remote_unreachable.json",
    "stale_metarepo.json",
    "stale_omnipull_log.json",
    "unknown_default_branch.json",
    "wrong_remote.json",
}

REQUIRED_SCHEMA_EXAMPLES = {
    "action-approval-validations/git-pull-ff-only-binding-valid.json",
    "action-approval-validations/git-pull-ff-only-rejected.json",
    "action-approval-validations/git-pull-ff-only-expired.json",
    "action-approval-validations/git-pull-ff-only-plan-mismatch.json",
    "action-approval-validations/switch-main-binding-valid.json",
    "action-capabilities/git-fetch-all-prune.json",
    "action-approvals/git-pull-ff-only-approved.json",
    "action-approvals/git-pull-ff-only-approved-plan-mismatch.json",
    "action-approvals/git-pull-ff-only-rejected.json",
    "action-approvals/switch-main-approved.json",
    "action-plans/git-pull-ff-only-approval-binding-base.json",
    "action-plans/git-pull-ff-only-blocked-dirty-worktree.json",
    "action-plans/git-pull-ff-only-blocked-non-default-branch.json",
    "action-plans/git-pull-ff-only-blocked-remote-freshness.json",
    "action-plans/switch-main-blocked.json",
    "action-plans/switch-main-not-applicable.json",
    "assessment-explanations/clean-default-current.json",
    "assessment-explanations/dirty-worktree.json",
    "assessment-explanations/non-default-branch.json",
    "assessment-explanations/pull-preflight-local-clear.json",
    "assessments/clean-default-current.json",
    "assessments/dirty-worktree-blocked.json",
    "assessments/feature-branch-clean-blocked.json",
    "assessments/non-default-branch-evidence-missing.json",
    "assessments/not-git-repo-blocked.json",
    "assessments/pull-preflight-local-clear-evidence-missing.json",
    "assessments/scope-backup-blocked.json",
    "duplicates/minimal-duplicates.json",
    "evidence/command-trace-redacted.json",
    "inventories/minimal-inventory.json",
    "local-configs/heim-pc.json",
    "omnipull-report-refs/minimal-latest.json",
    "omnipull-reports/dirty-worktree.json",
    "omnipull-reports/mixed-run.json",
    "omnipull-reports/non-default-branch.json",
    "omnipull-run-indexes/empty.json",
    "omnipull-run-indexes/minimal.json",
    "omnipull-run-indexes/multiple-runs.json",
    "observations/clean-default-current-no-upstream.json",
    "observations/clean-default-current-tracking-behind.json",
    "observations/feature-branch-clean.json",
    "redaction-policies/default-redaction-policy.json",
    "remote-refresh-results/fetch-origin-prune-network-failed.json",
    "remote-refresh-results/fetch-origin-prune-success.json",
    "run-indexes/minimal-run-index.json",
    "run-results/run-blocked.json",
    "scope-explanations/backup.json",
    "scope-explanations/canonical.json",
    "scope-explanations/excluded.json",
    "scope-explanations/gdrive.json",
    "scope-explanations/unknown.json",
    "source-refs/git-current-branch.json",
    "action-execution-readiness/git-pull-ff-only-inconclusive-binding-unproven.json",
    "action-execution-readiness/git-pull-ff-only-blocked-rejected-approval.json",
    "action-execution-readiness/git-pull-ff-only-blocked-expired-approval.json",
    "action-execution-readiness/git-pull-ff-only-inconclusive-chain.json",
    "action-execution-readiness/git-pull-ff-only-blocked-invalid-chain.json",
    "switch-main-preflight-proofs/ready.json",
    "switch-main-preflight-proofs/blocked-dirty-worktree.json",
    "switch-main-preflight-proofs/blocked-plan-content-mismatch.json",
    "switch-main-preflight-proofs/blocked-plan-action-mismatch.json",
    "switch-main-preflight-proofs/blocked-branch-unmerged.json",
    "switch-main-preflight-proofs/inconclusive-default-branch-unknown.json",
    "switch-main-preflight-proofs/inconclusive-missing-repo-toplevel.json",
    "switch-main-preflight-proofs/inconclusive-branch-lifecycle-unknown.json",
    "switch-main-readiness/ready.json",
    "switch-main-readiness/blocked-dirty-worktree.json",
    "switch-main-readiness/blocked-plan-action-mismatch.json",
    "switch-main-readiness/blocked-plan-content-mismatch.json",
    "switch-main-readiness/blocked-branch-unmerged.json",
    "switch-main-readiness/inconclusive-default-branch-unknown.json",
    "switch-main-readiness/inconclusive-missing-repo-toplevel.json",
    "switch-main-readiness/inconclusive-branch-lifecycle-unknown.json",
    "ui-view-models/cli-surface-summary.json",
    "ui-view-models/switch-main-readiness-ready-view.json",
    "ui-view-models/run-switch-main-success-view.json",
    "ui-view-models/blocked-readiness-view.json",
    "runbooks/repo-sync-gate.json",
    "runbook-results/repo-sync-gate-passed.json",
    "runbook-results/repo-sync-gate-blocked.json",
    "runbook-results/repo-sync-gate-inconclusive.json",
}

FORBIDDEN_ASSESSMENT_EXPLANATION_KEYS = {
    "action",
    "plan_id",
    "would_run",
    "would_mutate",
    "safe_actions",
    "safe_alternatives",
    "command_trace",
    "run_result",
}


def test_schemas_are_valid():
    validated = validate_schemas()
    assert validated
    assert any(path.name == "falsification-case.v1.schema.json" for path in validated)


def test_examples_validate_against_schemas():
    validated = validate_examples()
    validated_names = {path.name for path in validated}
    assert len(validated_names) >= len(REQUIRED_FAILURE_CASES)
    assert REQUIRED_FAILURE_CASES <= validated_names


def test_non_failure_schema_examples_validate_against_schemas():
    validated = validate_examples()
    validated_rel = {
        path.relative_to(EXAMPLES_DIR).as_posix()
        for path in validated
        if not path.relative_to(EXAMPLES_DIR).as_posix().startswith("failure-cases/")
    }
    assert REQUIRED_SCHEMA_EXAMPLES <= validated_rel


def test_assessment_explanation_examples_validate_against_new_schema():
    schema = load_json(SCHEMAS_DIR / "repo-assessment-explanation.v1.schema.json")
    examples = sorted((EXAMPLES_DIR / "assessment-explanations").glob("*.json"))
    assert examples

    for example_path in examples:
        instance = load_json(example_path)
        validate_instance(instance, schema, example_path)


def test_assessment_explanation_schema_rejects_forbidden_action_fields():
    schema = load_json(SCHEMAS_DIR / "repo-assessment-explanation.v1.schema.json")
    base = {
        "schema_version": "repo-assessment-explanation.v1",
        "explanation_id": "assess-expl-example",
        "assessment_ref": "assess-example",
        "summary": "Read-only interpretation.",
        "status_explanations": [
            {
                "status": "dirty_worktree",
                "meaning": "Working tree contains uncommitted changes.",
                "decision_effect": "blocks_action",
                "evidence_refs": ["obs-example"],
                "rule_refs": ["assessment.rule.dirty_worktree_blocks_action"],
                "freshness_refs": ["freshness.local_git_status.current_invocation"],
                "falsification_refs": ["failure-case.dirty_worktree"],
                "missing_evidence": [],
            }
        ],
        "boundary": {
            "does_not_authorise_actions": True,
            "does_not_mutate": True,
            "does_not_plan_actions": True,
        },
    }

    for forbidden_key in FORBIDDEN_ASSESSMENT_EXPLANATION_KEYS:
        invalid = dict(base)
        invalid[forbidden_key] = "forbidden"
        with pytest.raises(ValidationError):
            validate_instance(invalid, schema, EXAMPLES_DIR / f"invalid-{forbidden_key}.json")


def test_assessment_examples_match_runtime_provenance_contract():
    schema = load_json(SCHEMAS_DIR / "repo-assessment.v1.schema.json")

    for example_path in sorted((EXAMPLES_DIR / "assessments").glob("*.json")):
        assessment = load_json(example_path)
        validate_instance(assessment, schema, example_path)
        expected = attach_assessment_provenance(
            assessment["derived_status"],
            source_refs=assessment.get("source_refs", []),
        )

        for status in assessment["derived_status"]:
            assert status in ASSESSMENT_PROVENANCE, (
                f"{example_path.name}: unknown derived_status {status!r}"
            )

        assert assessment.get("rule_refs", []) == expected["rule_refs"], (
            f"{example_path.name}: rule_refs drift from runtime provenance"
        )
        assert assessment.get("freshness_refs", []) == expected["freshness_refs"], (
            f"{example_path.name}: freshness_refs drift from runtime provenance"
        )
        assert assessment.get("falsification_refs", []) == expected["falsification_refs"], (
            f"{example_path.name}: falsification_refs drift from runtime provenance"
        )

        for ref in assessment.get("falsification_refs", []):
            prefix = "failure-case."
            assert ref.startswith(prefix), (
                f"{example_path.name}: invalid falsification_ref prefix {ref!r}"
            )
            case_id = ref[len(prefix) :]
            assert case_id in EXISTING_FAILURE_CASE_IDS, (
                f"{example_path.name}: unknown falsification_ref {ref!r}"
            )


def test_existing_failure_case_ids_have_example_files():
    failure_cases_dir = EXAMPLES_DIR / "failure-cases"
    expected = {f"{case_id}.json" for case_id in EXISTING_FAILURE_CASE_IDS}
    actual = {path.name for path in failure_cases_dir.glob("*.json")}
    assert actual == expected


def test_fallback_date_time_check_requires_rfc3339_shape():
    assert _is_date_time("2026-05-08T12:00:00Z")
    assert _is_date_time("2026-05-08T12:00:00.123+00:00")
    assert not _is_date_time("2026-05-08+00:00")
    assert not _is_date_time("2026-05-08 12:00:00+00:00")


def test_minimal_validator_supports_nullable_type_arrays():
    minimal_validate(None, {"type": ["string", "null"]})
    minimal_validate("main", {"type": ["string", "null"]})


def test_minimal_validator_rejects_wrong_nullable_type():
    with pytest.raises(ValidationError):
        minimal_validate(123, {"type": ["string", "null"]})


def test_minimal_validator_supports_anyof_head_sha_shape():
    schema = {
        "anyOf": [
            {"type": "string", "pattern": "^([0-9a-f]{40}|[0-9a-f]{64})$"},
            {"type": "null"},
        ]
    }

    minimal_validate("1111111111111111111111111111111111111111", schema)
    minimal_validate("2" * 64, schema)
    minimal_validate(None, schema)


def test_minimal_validator_rejects_invalid_anyof_head_sha_shape():
    schema = {
        "anyOf": [
            {"type": "string", "pattern": "^([0-9a-f]{40}|[0-9a-f]{64})$"},
            {"type": "null"},
        ]
    }

    with pytest.raises(ValidationError):
        minimal_validate("not-a-sha", schema)


def _remote_refresh_schema() -> dict:
    return load_json(SCHEMAS_DIR / "remote-refresh-result.v1.schema.json")


def _valid_remote_refresh_result() -> dict:
    return {
        "schema_version": "remote-refresh-result.v1",
        "refresh_id": "refresh-example-origin-prune-success",
        "repo_ref": "repo-assess-example-pull-preflight-local-clear-evidence-missing",
        "operation": "git.fetch_origin_prune",
        "remote_name": "origin",
        "started_at": "2026-05-23T09:10:01Z",
        "completed_at": "2026-05-23T09:10:02Z",
        "exit_code": 0,
        "mutates_worktree": False,
        "mutates_refs": True,
        "mutates_remote": False,
        "remote_freshness": "fresh",
        "command_trace_ref": "examples/evidence/command-trace-redacted.json",
        "redacted": True,
        "boundary": {
            "does_not_pull": True,
            "does_not_merge": True,
            "does_not_switch": True,
            "does_not_reset": True,
            "does_not_clean": True,
            "does_not_authorise_pull": True,
        },
    }


def test_remote_refresh_schema_rejects_exit_code_zero_with_non_fresh_freshness():
    invalid = _valid_remote_refresh_result()
    invalid["remote_freshness"] = "unavailable"

    with pytest.raises(ValidationError):
        validate_instance(
            invalid,
            _remote_refresh_schema(),
            EXAMPLES_DIR / "invalid-remote-refresh-exit-zero-non-fresh.json",
        )


def test_remote_refresh_schema_rejects_failed_exit_code_with_fresh_freshness():
    invalid = _valid_remote_refresh_result()
    invalid["exit_code"] = 128

    with pytest.raises(ValidationError):
        validate_instance(
            invalid,
            _remote_refresh_schema(),
            EXAMPLES_DIR / "invalid-remote-refresh-failed-fresh.json",
        )


def test_remote_refresh_schema_rejects_non_origin_remote_for_origin_operation():
    invalid = _valid_remote_refresh_result()
    invalid["remote_name"] = "upstream"

    with pytest.raises(ValidationError):
        validate_instance(
            invalid,
            _remote_refresh_schema(),
            EXAMPLES_DIR / "invalid-remote-refresh-remote-name.json",
        )


def test_remote_refresh_schema_rejects_redacted_false():
    invalid = _valid_remote_refresh_result()
    invalid["redacted"] = False

    with pytest.raises(ValidationError):
        validate_instance(
            invalid,
            _remote_refresh_schema(),
            EXAMPLES_DIR / "invalid-remote-refresh-redacted-false.json",
        )


def test_remote_refresh_schema_rejects_boundary_false_and_extra_field():
    invalid_false = _valid_remote_refresh_result()
    invalid_false["boundary"] = {
        **invalid_false["boundary"],
        "does_not_pull": False,
    }

    with pytest.raises(ValidationError):
        validate_instance(
            invalid_false,
            _remote_refresh_schema(),
            EXAMPLES_DIR / "invalid-remote-refresh-boundary-false.json",
        )

    invalid_extra = _valid_remote_refresh_result()
    invalid_extra["boundary"] = {
        **invalid_extra["boundary"],
        "extra": True,
    }

    with pytest.raises(ValidationError):
        validate_instance(
            invalid_extra,
            _remote_refresh_schema(),
            EXAMPLES_DIR / "invalid-remote-refresh-boundary-extra.json",
        )


def _action_approval_schema() -> dict:
    return load_json(SCHEMAS_DIR / "action-approval.v1.schema.json")


_ACTION_APPROVAL_PLAN = {
    "schema_version": "action-plan.v1",
    "plan_id": "plan-git-pull-ff-only-2026-05-23-001",
    "action": "git-pull-ff-only",
    "assessment_ref": "assess-example-001",
    "decision": "blocked",
    "blocked_because": ["git_pull_ff_only_evidence_missing_remote_freshness"],
    "source_refs": ["git.current_branch"],
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
_ACTION_APPROVAL_PLAN_SHA256 = canonical_json_sha256(_ACTION_APPROVAL_PLAN)


def _valid_action_approval(decision: str = "approved") -> dict:
    approval = {
        "schema_version": "action-approval.v1",
        "approval_id": "approval-2026-05-23-pull-ff-only-001",
        "plan_ref": "plan-git-pull-ff-only-2026-05-23-001",
        "plan_content_sha256": _ACTION_APPROVAL_PLAN_SHA256,
        "action": "git-pull-ff-only",
        "decision": decision,
        "decided_at": "2026-05-23T10:00:00Z",
        "approver_ref": "user:alex",
        "approval_scope": {
            "single_plan_only": True,
            "no_plan_substitution": True,
            "no_command_substitution": True,
        },
        "expires_at": "2026-05-23T18:00:00Z",
        "constraints": {
            "requires_same_plan_id": True,
            "requires_same_action": True,
            "requires_revalidation_before_execution": True,
            "requires_runner_contract": True,
            "requires_postcheck": True,
        },
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_unplanned_action": True,
            "does_not_create_runner": True,
        },
    }
    if decision == "rejected":
        approval["reason"] = "Approval withheld pending manual confirmation of execution boundary."
    return approval


def test_action_approval_examples_validate():
    schema = _action_approval_schema()
    approved = load_json(EXAMPLES_DIR / "action-approvals/git-pull-ff-only-approved.json")
    approved_plan_mismatch = load_json(
        EXAMPLES_DIR / "action-approvals/git-pull-ff-only-approved-plan-mismatch.json"
    )
    rejected = load_json(EXAMPLES_DIR / "action-approvals/git-pull-ff-only-rejected.json")

    validate_instance(approved, schema, EXAMPLES_DIR / "action-approvals/git-pull-ff-only-approved.json")
    validate_instance(
        approved_plan_mismatch,
        schema,
        EXAMPLES_DIR / "action-approvals/git-pull-ff-only-approved-plan-mismatch.json",
    )
    validate_instance(rejected, schema, EXAMPLES_DIR / "action-approvals/git-pull-ff-only-rejected.json")


def test_action_approval_schema_allows_approved_without_reason():
    approved_without_reason = _valid_action_approval(decision="approved")
    approved_without_reason.pop("reason", None)

    validate_instance(
        approved_without_reason,
        _action_approval_schema(),
        EXAMPLES_DIR / "valid-action-approval-approved-without-reason.json",
    )


def test_action_approval_schema_rejects_missing_plan_ref():
    invalid = _valid_action_approval()
    del invalid["plan_ref"]

    with pytest.raises(ValidationError):
        validate_instance(invalid, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-missing-plan-ref.json")


def test_action_approval_schema_rejects_unknown_action():
    invalid = _valid_action_approval()
    invalid["action"] = "git-merge"

    with pytest.raises(ValidationError):
        validate_instance(invalid, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-unknown-action.json")


def test_action_approval_schema_rejects_unknown_decision():
    invalid = _valid_action_approval()
    invalid["decision"] = "pending"

    with pytest.raises(ValidationError):
        validate_instance(invalid, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-unknown-decision.json")


def test_action_approval_schema_rejects_rejected_without_reason():
    invalid = _valid_action_approval(decision="rejected")
    invalid.pop("reason", None)

    with pytest.raises(ValidationError):
        validate_instance(
            invalid,
            _action_approval_schema(),
            EXAMPLES_DIR / "invalid-action-approval-rejected-missing-reason.json",
        )


def test_action_approval_schema_rejects_rejected_with_empty_or_whitespace_reason():
    invalid_empty = _valid_action_approval(decision="rejected")
    invalid_empty["reason"] = ""
    with pytest.raises(ValidationError):
        validate_instance(
            invalid_empty,
            _action_approval_schema(),
            EXAMPLES_DIR / "invalid-action-approval-rejected-empty-reason.json",
        )

    invalid_whitespace = _valid_action_approval(decision="rejected")
    invalid_whitespace["reason"] = " rejected for now "
    with pytest.raises(ValidationError):
        validate_instance(
            invalid_whitespace,
            _action_approval_schema(),
            EXAMPLES_DIR / "invalid-action-approval-rejected-whitespace-reason.json",
        )


def test_action_approval_schema_rejects_extra_top_level_field():
    invalid = _valid_action_approval()
    invalid["extra"] = True

    with pytest.raises(ValidationError):
        validate_instance(invalid, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-extra-field.json")


def test_action_approval_schema_rejects_false_scope_constraints_and_boundary_values():
    invalid_scope = _valid_action_approval()
    invalid_scope["approval_scope"] = {
        **invalid_scope["approval_scope"],
        "single_plan_only": False,
    }
    with pytest.raises(ValidationError):
        validate_instance(invalid_scope, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-scope-false.json")

    invalid_constraints = _valid_action_approval()
    invalid_constraints["constraints"] = {
        **invalid_constraints["constraints"],
        "requires_postcheck": False,
    }
    with pytest.raises(ValidationError):
        validate_instance(invalid_constraints, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-constraints-false.json")

    invalid_boundary = _valid_action_approval()
    invalid_boundary["boundary"] = {
        **invalid_boundary["boundary"],
        "does_not_execute": False,
    }
    with pytest.raises(ValidationError):
        validate_instance(invalid_boundary, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-boundary-false.json")


def test_action_approval_schema_rejects_whitespace_padded_identifiers():
    invalid_approval_id = _valid_action_approval()
    invalid_approval_id["approval_id"] = " approval-2026-05-23 "
    with pytest.raises(ValidationError):
        validate_instance(invalid_approval_id, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-whitespace-approval-id.json")

    invalid_plan_ref = _valid_action_approval()
    invalid_plan_ref["plan_ref"] = " plan-git-pull-ff-only-2026-05-23-001 "
    with pytest.raises(ValidationError):
        validate_instance(invalid_plan_ref, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-whitespace-plan-ref.json")
