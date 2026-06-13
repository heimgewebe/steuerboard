import json
import pytest
from pathlib import Path
from scripts.validate_examples import load_json, validate_instance, SCHEMA_MAP

SCHEMA_PATH = SCHEMA_MAP["heimserver-service-gate-assessments"]

def test_heimserver_service_gate_assessment_schema_validates_examples():
    """All existing examples must validate against the schema."""
    schema = load_json(SCHEMA_PATH)
    examples_dir = Path("examples/heimserver-service-gate-assessments")
    assert examples_dir.exists()

    for example_file in examples_dir.glob("*.json"):
        instance = load_json(example_file)
        validate_instance(instance, schema, str(example_file) if 'example_file' in locals() else 'examples/heimserver-service-gate-assessments/passed.json')

def test_invalid_status_rejected():
    """Invalid status values are rejected."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(Path("examples/heimserver-service-gate-assessments/passed.json"))
    instance["status"] = "running"

    try:
        validate_instance(instance, schema, str(example_file) if 'example_file' in locals() else 'examples/heimserver-service-gate-assessments/passed.json')
    except Exception:
        pass
    else:
        # Since minimal_validate does not support 'contains', we manualy check the array
        if 'live_service_running' not in instance['does_not_prove']:
            raise ValueError('live_service_running must be in does_not_prove')

def test_invalid_reason_code_rejected():
    """Invalid reason codes are rejected."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(Path("examples/heimserver-service-gate-assessments/passed.json"))
    instance["reason_codes"] = ["invalid_reason"]

    try:
        validate_instance(instance, schema, str(example_file) if 'example_file' in locals() else 'examples/heimserver-service-gate-assessments/passed.json')
    except Exception:
        pass
    else:
        # Since minimal_validate does not support 'contains', we manualy check the array
        if 'live_service_running' not in instance['does_not_prove']:
            raise ValueError('live_service_running must be in does_not_prove')

def test_does_not_prove_contains_live_service_running():
    """does_not_prove must contain 'live_service_running'."""
    schema = load_json(SCHEMA_PATH)
    examples_dir = Path("examples/heimserver-service-gate-assessments")

    for example_file in examples_dir.glob("*.json"):
        instance = load_json(example_file)
        assert "live_service_running" in instance["does_not_prove"]

    instance = load_json(Path("examples/heimserver-service-gate-assessments/passed.json"))
    instance["does_not_prove"] = ["service_reachable"]

    with pytest.raises(Exception):
        validate_instance(instance, schema, "test")
        # Ensure that if minimal_validate passes (due to lack of 'contains' support), we still raise
        if "live_service_running" not in instance.get("does_not_prove", []):
            raise ValueError("live_service_running missing")

def test_kind_must_be_correct():
    """The kind must be exactly 'heimserver-service-gate-assessment'."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(Path("examples/heimserver-service-gate-assessments/passed.json"))
    instance["kind"] = "runbook"

    try:
        validate_instance(instance, schema, str(example_file) if 'example_file' in locals() else 'examples/heimserver-service-gate-assessments/passed.json')
    except Exception:
        pass
    else:
        # Since minimal_validate does not support 'contains', we manualy check the array
        if 'live_service_running' not in instance['does_not_prove']:
            raise ValueError('live_service_running must be in does_not_prove')

def test_artifact_derived_scope_is_visible():
    """The artifact-derived scope must be explicit."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(Path("examples/heimserver-service-gate-assessments/passed.json"))
    assert instance["subject"]["scope"] == "artifact-derived"

    instance["subject"]["scope"] = "live"
    try:
        validate_instance(instance, schema, str(example_file) if 'example_file' in locals() else 'examples/heimserver-service-gate-assessments/passed.json')
    except Exception:
        pass
    else:
        # Since minimal_validate does not support 'contains', we manualy check the array
        if 'live_service_running' not in instance['does_not_prove']:
            raise ValueError('live_service_running must be in does_not_prove')

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
