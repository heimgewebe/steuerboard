from pathlib import Path

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
from steuerboard.assessment_rules import ASSESSMENT_PROVENANCE, EXISTING_FAILURE_CASE_IDS

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
    "action-plans/switch-main-blocked.json",
    "assessments/clean-default-current.json",
    "assessments/dirty-worktree-blocked.json",
    "assessments/feature-branch-clean-blocked.json",
    "assessments/non-default-branch-evidence-missing.json",
    "assessments/not-git-repo-blocked.json",
    "assessments/scope-backup-blocked.json",
    "duplicates/minimal-duplicates.json",
    "evidence/command-trace-redacted.json",
    "inventories/minimal-inventory.json",
    "local-configs/heim-pc.json",
    "observations/feature-branch-clean.json",
    "redaction-policies/default-redaction-policy.json",
    "run-indexes/minimal-run-index.json",
    "run-results/run-blocked.json",
    "scope-explanations/backup.json",
    "scope-explanations/canonical.json",
    "scope-explanations/excluded.json",
    "scope-explanations/gdrive.json",
    "scope-explanations/unknown.json",
    "source-refs/git-current-branch.json",
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


def test_assessment_examples_match_runtime_provenance_contract():
    schema = load_json(SCHEMAS_DIR / "repo-assessment.v1.schema.json")

    for example_path in sorted((EXAMPLES_DIR / "assessments").glob("*.json")):
        assessment = load_json(example_path)
        validate_instance(assessment, schema, example_path)

        for status in assessment["derived_status"]:
            assert status in ASSESSMENT_PROVENANCE, (
                f"{example_path.name}: unknown derived_status {status!r}"
            )
            expected_rule_refs = ASSESSMENT_PROVENANCE[status]["rule_refs"]
            for ref in expected_rule_refs:
                assert ref in assessment["rule_refs"], (
                    f"{example_path.name}: missing rule_ref {ref!r} for status {status!r}"
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
    for case_id in sorted(EXISTING_FAILURE_CASE_IDS):
        path = failure_cases_dir / f"{case_id}.json"
        assert path.exists(), f"missing failure-case example file: {path}"


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
