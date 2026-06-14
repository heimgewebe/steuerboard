from pathlib import Path

import pytest

from scripts.validate_examples import (
    SCHEMA_MAP,
    ValidationError,
    load_json,
    minimal_validate,
    validate_instance,
)

EXAMPLES_DIR = Path("examples/heimserver-service-gate-assessments")
PASSED_EXAMPLE = EXAMPLES_DIR / "passed.json"
SCHEMA_PATH = SCHEMA_MAP["heimserver-service-gate-assessments"]
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))

def assert_invalid(instance: dict, schema: dict, source: str = "test") -> None:
    with pytest.raises(Exception):
        validate_instance(instance, schema, source)

@pytest.mark.parametrize("example_file", EXAMPLE_FILES, ids=lambda path: path.name)
def test_heimserver_service_gate_assessment_schema_validates_examples(example_file):
    """All existing examples must validate against the schema."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(example_file)
    validate_instance(instance, schema, str(example_file))

def test_invalid_status_rejected():
    """Invalid status values are rejected."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["status"] = "running"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_invalid_reason_code_rejected():
    """Invalid reason codes are rejected."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["reason_codes"] = ["invalid_reason"]
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_does_not_prove_contains_live_service_running():
    """does_not_prove must contain 'live_service_running'."""
    schema = load_json(SCHEMA_PATH)

    for example_file in EXAMPLE_FILES:
        instance = load_json(example_file)
        assert "live_service_running" in instance["does_not_prove"]

    instance = load_json(PASSED_EXAMPLE)
    instance["does_not_prove"] = ["service_reachable"]

    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_kind_must_be_correct():
    """The kind must be exactly 'heimserver-service-gate-assessment'."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["kind"] = "runbook"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_artifact_derived_scope_is_visible():
    """The artifact-derived scope must be explicit."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    assert instance["subject"]["scope"] == "artifact-derived"

    instance["subject"]["scope"] = "live"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_no_runbook_kind_added():
    """Ensure we haven't accidentally added heimserver-service-gate as a runbook kind."""
    from steuerboard.runbooks import SUPPORTED_RUNBOOK_KINDS
    assert "heimserver-service-gate" not in SUPPORTED_RUNBOOK_KINDS

    runbook_plan_schema = load_json(Path("schemas/runbook-plan.v1.schema.json"))
    kinds = runbook_plan_schema["properties"]["runbook_kind"]["enum"]
    assert "heimserver-service-gate" not in kinds

    runbook_result_schema = load_json(Path("schemas/runbook-result.v1.schema.json"))
    result_kinds = runbook_result_schema["properties"]["runbook_kind"]["enum"]
    assert "heimserver-service-gate" not in result_kinds


def test_invalid_sha256_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["inputs"]["server_facts_ref"]["sha256"] = "abc"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_empty_reason_codes_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["reason_codes"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_empty_service_reason_codes_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"][0]["reason_codes"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_empty_evidence_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evidence"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_supports_contains():
    schema = {"type": "array", "contains": {"const": "live_service_running"}}
    minimal_validate(["service_reachable", "live_service_running"], schema, "test")

def test_minimal_validate_rejects_missing_contains_match():
    schema = {"type": "array", "contains": {"const": "live_service_running"}}
    with pytest.raises(ValidationError):
        minimal_validate(["service_reachable"], schema, "test")

def test_minimal_validate_rejects_non_array_for_contains():
    schema = {"contains": {"const": "live_service_running"}}
    with pytest.raises(ValidationError, match="expected array for array validation keywords"):
        minimal_validate("not-an-array", schema, "test")

def test_minimal_validate_rejects_non_array_for_min_items():
    schema = {"minItems": 1}
    with pytest.raises(ValidationError, match="expected array for array validation keywords"):
        minimal_validate("not-an-array", schema, "test")

def test_passed_with_empty_expected_services_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["expected_services"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_passed_with_empty_evaluated_services_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_passed_with_stale_freshness_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["freshness"]["status"] = "stale"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_passed_with_blocked_reason_code_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["reason_codes"] = ["service_gate_artifacts_missing"]
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_passed_with_blocked_evaluated_service_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"][0]["status"] = "blocked"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_supports_allof_and_if_then():
    schema = {
        "allOf": [
            {
                "if": {"properties": {"status": {"const": "passed"}}},
                "then": {"properties": {"freshness": {"const": "fresh"}}}
            }
        ]
    }

    # 1. Valid instance should pass
    valid_instance = {"status": "passed", "freshness": "fresh"}
    minimal_validate(valid_instance, schema, "test")

    # 2. Invalid instance should fail due to 'then' constraint
    invalid_instance = {"status": "passed", "freshness": "stale"}
    with pytest.raises(ValidationError):
        minimal_validate(invalid_instance, schema, "test")

    # 3. Non-matching 'if' condition falls through (should pass)
    ignored_instance = {"status": "blocked", "freshness": "stale"}
    minimal_validate(ignored_instance, schema, "test")
