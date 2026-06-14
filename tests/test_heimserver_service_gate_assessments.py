import json
import pytest
from pathlib import Path
from scripts.validate_examples import load_json, validate_instance, SCHEMA_MAP

EXAMPLES_DIR = Path("examples/heimserver-service-gate-assessments")
PASSED_EXAMPLE = EXAMPLES_DIR / "passed.json"
SCHEMA_PATH = SCHEMA_MAP["heimserver-service-gate-assessments"]

def assert_invalid(instance: dict, schema: dict, source: str = "test") -> None:
    with pytest.raises(Exception):
        validate_instance(instance, schema, source)

def test_heimserver_service_gate_assessment_schema_validates_examples():
    """All existing examples must validate against the schema."""
    schema = load_json(SCHEMA_PATH)
    assert EXAMPLES_DIR.exists()

    for example_file in EXAMPLES_DIR.glob("*.json"):
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

    for example_file in EXAMPLES_DIR.glob("*.json"):
        instance = load_json(example_file)
        assert "live_service_running" in instance["does_not_prove"]

    instance = load_json(PASSED_EXAMPLE)
    instance["does_not_prove"] = ["service_reachable"]

    # Validation should fail. If minimal_validate passes, we catch it manually
    # to avoid false positives.
    try:
        validate_instance(instance, schema, str(PASSED_EXAMPLE))
    except Exception:
        pass # Expected validation error
    else:
        # manual check for minimal_validate fallback missing 'contains'
        if "live_service_running" not in instance.get("does_not_prove", []):
            pytest.fail("live_service_running missing from does_not_prove but minimal_validate did not catch it")

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
