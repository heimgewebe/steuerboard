import hashlib
from pathlib import Path

import pytest

from scripts.validate_examples import (
    SCHEMA_MAP,
    load_json,
    validate_instance,
)

EXAMPLES_DIR = Path("examples/heimserver-service-evidence")
MINIMAL_EXAMPLE = EXAMPLES_DIR / "minimal-artifact-only.json"
SCHEMA_PATH = SCHEMA_MAP["heimserver-service-evidence"]
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))


def assert_invalid(instance: dict, schema: dict, source: str = "test") -> None:
    with pytest.raises(Exception):
        validate_instance(instance, schema, source)


def test_validator_knows_the_evidence_contract():
    """The validator (SCHEMA_MAP) must wire the evidence directory to its schema."""
    assert SCHEMA_PATH.name == "heimserver-service-evidence.v1.schema.json"
    assert SCHEMA_PATH.exists()


@pytest.mark.parametrize("example_file", EXAMPLE_FILES, ids=lambda path: path.name)
def test_evidence_examples_validate(example_file):
    """Every evidence example must validate against the evidence schema."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(example_file)
    validate_instance(instance, schema, str(example_file))


def test_schema_version_const_enforced():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    assert instance["schema_version"] == "heimserver-service-evidence.v1"

    instance["schema_version"] = "1"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_scope_must_be_artifact_derived():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    assert instance["scope"] == "artifact-derived"

    instance["scope"] = "live"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_observed_at_must_be_strict_utc_z():
    """observed_at uses the repo's strict UTC-Z pattern, not a loose date-time."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    # Offset timestamps must be rejected by the strict Z pattern.
    instance["observed_at"] = "2026-06-13T00:00:00+00:00"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_invalid_evidence_status_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["evidence_status"] = "running"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_invalid_reason_code_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["reason_codes"] = ["service_gate_artifacts_missing"]
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


@pytest.mark.parametrize(
    "missing", ["schema_version", "host", "scope", "freshness_status", "observed_at", "services"]
)
def test_missing_required_top_level_field_rejected(missing):
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    del instance[missing]
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


@pytest.mark.parametrize(
    "missing", ["service_name", "evidence_status", "reason_codes", "evidence"]
)
def test_missing_required_service_field_rejected(missing):
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    del instance["services"][0][missing]
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_additional_top_level_property_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["live_status"] = "running"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_additional_service_property_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["reachable"] = True
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_empty_service_name_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["service_name"] = ""
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_empty_evidence_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["evidence"] = []
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_empty_reason_codes_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["reason_codes"] = []
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_contract_stays_a_pure_artifact_input():
    """The evidence contract must stay descriptive input: no verdict, no live-truth fields.

    Guards the Phase 11F-E boundary — service evidence records what artifacts show,
    it is not a place to smuggle a verdict or a live claim.
    """
    schema = load_json(SCHEMA_PATH)
    top_props = set(schema["properties"])
    assert top_props == {"schema_version", "host", "scope", "freshness_status", "observed_at", "services"}

    service_props = set(
        schema["properties"]["services"]["items"]["properties"]
    )
    assert service_props == {"service_name", "evidence_status", "reason_codes", "evidence"}

    forbidden = {
        "status",
        "evaluated_services",
        "freshness",
        "does_not_prove",
        "live_service_running",
        "service_reachable",
        "runtime_correctness",
    }
    assert not (top_props & forbidden)
    assert not (service_props & forbidden)

    # The evidence_status vocabulary must stay descriptive, never a live claim.
    evidence_statuses = set(
        schema["properties"]["services"]["items"]["properties"]["evidence_status"]["enum"]
    )
    assert evidence_statuses == {"present", "missing", "mismatch", "unknown"}
    assert not (evidence_statuses & {"running", "reachable", "live", "active"})


def test_freshness_status_invalid_value_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["freshness_status"] = "something_else"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))

def test_evidence_status_reason_code_partition_enforced():
    schema = load_json(SCHEMA_PATH)
    
    # test present rejecting missing reason
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["evidence_status"] = "present"
    instance["services"][0]["reason_codes"] = [
        "service_evidence_artifact_only_scope",
        "service_evidence_absent_from_artifacts"
    ]
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))

    # test missing rejecting present reason
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["evidence_status"] = "missing"
    instance["services"][0]["reason_codes"] = [
        "service_evidence_artifact_only_scope",
        "service_evidence_present_in_artifacts"
    ]
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))

def test_stale_reason_code_only_allowed_when_freshness_stale():
    schema = load_json(SCHEMA_PATH)
    
    # fresh -> stale reason code rejected
    instance = load_json(MINIMAL_EXAMPLE)
    instance["freshness_status"] = "fresh"
    instance["services"][0]["reason_codes"].append("service_evidence_artifact_stale")
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))
    
    # stale -> stale reason code accepted
    instance["freshness_status"] = "stale"
    validate_instance(instance, schema, str(MINIMAL_EXAMPLE))

@pytest.mark.parametrize("status,reason", [
    ("present", "service_evidence_present_in_artifacts"),
    ("missing", "service_evidence_absent_from_artifacts"),
    ("mismatch", "service_evidence_artifact_mismatch"),
    ("unknown", "service_evidence_unknown"),
])
def test_evidence_status_reason_code_matrix(status, reason):
    """Enforces that each evidence_status strictly requires and allows only its corresponding reason."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    
    # Valid pairing
    instance["services"][0]["evidence_status"] = status
    instance["services"][0]["reason_codes"] = ["service_evidence_artifact_only_scope", reason]
    validate_instance(instance, schema, f"{status}_valid")
    
    # Invalid pair (wrong reason)
    wrong_reason = "service_evidence_unknown" if status != "unknown" else "service_evidence_present_in_artifacts"
    instance["services"][0]["reason_codes"] = ["service_evidence_artifact_only_scope", wrong_reason]
    assert_invalid(instance, schema, f"{status}_invalid")

def test_unique_items_on_reason_codes():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["services"][0]["reason_codes"] = [
        "service_evidence_artifact_only_scope",
        "service_evidence_present_in_artifacts",
        "service_evidence_present_in_artifacts"
    ]
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_no_runbook_leak():
    """Phase 11F-E must not turn the service gate into a runbook kind or runtime."""
    from steuerboard.runbooks import SUPPORTED_RUNBOOK_KINDS

    assert "heimserver-service-gate" not in SUPPORTED_RUNBOOK_KINDS
    assert "heimserver-service-evidence" not in SUPPORTED_RUNBOOK_KINDS

    plan_kinds = load_json(Path("schemas/runbook-plan.v1.schema.json"))[
        "properties"
    ]["runbook_kind"]["enum"]
    result_kinds = load_json(Path("schemas/runbook-result.v1.schema.json"))[
        "properties"
    ]["runbook_kind"]["enum"]
    for kinds in (plan_kinds, result_kinds):
        assert "heimserver-service-gate" not in kinds
        assert "heimserver-service-evidence" not in kinds



def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

ASSESSMENTS_DIR = Path("examples/heimserver-service-gate-assessments")

def test_shape_assessment_evidence_refs_match_shared_example():
    """Current shape fixtures share one evidence reference.
    This checks path/hash integrity only and does not assert that each verdict
    is derivable from the shared evidence artifact.
    """
    actual = sha256_file(MINIMAL_EXAMPLE)
    assessment_files = [f for f in sorted(ASSESSMENTS_DIR.glob("*.json")) if not f.name.startswith("golden-")]
    assert assessment_files

    for assessment_file in assessment_files:
        assessment = load_json(assessment_file)
        ref = assessment["inputs"]["service_evidence_ref"]
        assert ref["path"] == str(MINIMAL_EXAMPLE), (
            f"{assessment_file.name}: unexpected service_evidence_ref.path {ref['path']}"
        )
        assert ref["sha256"] == actual, (
            f"{assessment_file.name}: service_evidence_ref.sha256 does not match {MINIMAL_EXAMPLE}"
        )
