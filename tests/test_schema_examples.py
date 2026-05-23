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
    "action-capabilities/git-fetch-all-prune.json",
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
