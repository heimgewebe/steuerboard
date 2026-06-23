import pytest
from scripts.validate_examples import load_json, validate_instance, minimal_validate, ValidationError

from pathlib import Path
SCHEMA_PATH = Path("schemas/heimserver-service-gate-assessment.v1.schema.json")

@pytest.fixture
def schema():
    return load_json(SCHEMA_PATH)

def base_assessment(status: str) -> dict:
    return {
        "schema_version": "1",
        "kind": "heimserver-service-gate-assessment",
        "status": status,
        "subject": {
            "host": "heimserver",
            "scope": "artifact-derived"
        },
        "inputs": {
            "server_facts_ref": {
                "path": "examples/server-facts/minimal-linux.json",
                "sha256": "8512d826401aa6b3eb31b3ed22036db5ca5034880966e15f96cefc64b337eee2"
            },
            "expectation_ref": {
                "path": "examples/heimserver-service-expectations/minimal-tailscale.json",
                "sha256": "d281c5cf0f78bd318bcf5154dd5be2d2b2a8df42a3afbd5e1b712ca97457b530"
            },
            "service_evidence_ref": {
                "path": "examples/heimserver-service-evidence/minimal-artifact-only.json",
                "sha256": "9e2ed048140db9cf78fe88c15cb5ba5d877335ded4bc429f77abf2c628d3c3c1"
            }
        },
        "expected_services": [
            {
                "service_name": "tailscaled.service",
                "expected_role": "overlay-network-admin"
            }
        ],
        "evaluated_services": [
            {
                "service_name": "tailscaled.service",
                "expected_role": "overlay-network-admin",
                "status": "passed",
                "reason_codes": ["service_gate_artifact_only_scope"],
                "evidence": ["ok"]
            }
        ],
        "reason_codes": [],
        "evidence": ["ok"],
        "freshness": {
            "status": "fresh",
            "observed_at": "2026-06-13T00:00:00Z"
        },
        "does_not_prove": [
            "live_service_running",
            "service_reachable",
            "runtime_correctness",
            "service_role_fulfilled"
        ]
    }

def check_valid(instance, schema):
    validate_instance(instance, schema, "test")
    minimal_validate(instance, schema, "test")

def check_invalid(instance, schema):
    with pytest.raises(Exception):
        validate_instance(instance, schema, "test")
    with pytest.raises(ValidationError):
        minimal_validate(instance, schema, "test")

def test_blocked_service_evidence_mismatch_with_passed_services(schema):
    ass = base_assessment("blocked")
    ass["reason_codes"] = ["service_gate_service_evidence_mismatch"]
    check_invalid(ass, schema)

def test_blocked_subject_mismatch_alone_empty_services(schema):
    ass = base_assessment("blocked")
    ass["reason_codes"] = ["service_gate_subject_mismatch"]
    ass["evaluated_services"] = []
    check_valid(ass, schema)

def test_blocked_subject_mismatch_and_evidence_mismatch_with_passed_services(schema):
    ass = base_assessment("blocked")
    ass["reason_codes"] = ["service_gate_subject_mismatch", "service_gate_service_evidence_mismatch"]
    check_invalid(ass, schema)

def test_inconclusive_no_service_evidence_with_passed_services(schema):
    ass = base_assessment("inconclusive")
    ass["reason_codes"] = ["service_gate_no_service_evidence"]
    check_invalid(ass, schema)

def test_inconclusive_artifacts_stale_with_passed_services(schema):
    ass = base_assessment("inconclusive")
    ass["reason_codes"] = ["service_gate_artifacts_stale"]
    # also set freshness_status to stale so that base schema logic doesn't fail on freshness vs top-level
    ass["freshness"]["status"] = "stale"
    check_invalid(ass, schema)

def test_inconclusive_freshness_unknown_with_passed_services(schema):
    ass = base_assessment("inconclusive")
    ass["reason_codes"] = ["service_gate_freshness_unknown"]
    ass["freshness"]["status"] = "unknown"
    check_invalid(ass, schema)

def test_inconclusive_expectation_missing_empty_services(schema):
    ass = base_assessment("inconclusive")
    ass["reason_codes"] = ["service_gate_expectation_missing"]
    ass["evaluated_services"] = []
    check_valid(ass, schema)

def test_inconclusive_expectation_missing_and_no_service_evidence_passed_services(schema):
    ass = base_assessment("inconclusive")
    ass["reason_codes"] = ["service_gate_expectation_missing", "service_gate_no_service_evidence"]
    # with evaluated_services being passed
    check_invalid(ass, schema)

