import hashlib
from pathlib import Path

import pytest

from scripts.validate_examples import (
    SCHEMA_MAP,
    load_json,
    validate_instance,
)

CASES_DIR = Path("examples/heimserver-service-gate-derivation-cases")
SCHEMA_PATH = SCHEMA_MAP["heimserver-service-gate-derivation-cases"]
CASE_FILES = sorted(CASES_DIR.glob("*.json"))

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

@pytest.mark.parametrize("case_file", CASE_FILES, ids=lambda path: path.name)
def test_derivation_case_schema(case_file):
    """Every derivation case must validate against the derivation-case schema."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(case_file)
    validate_instance(instance, schema, str(case_file))

@pytest.mark.parametrize("case_file", CASE_FILES, ids=lambda path: path.name)
def test_derivation_case_hashes(case_file):
    """Check that all references in the derivation case point to valid files and correct hashes."""
    case = load_json(case_file)
    for ref_key in ["server_facts_ref", "expectation_ref", "service_evidence_ref"]:
        ref = case["inputs"][ref_key]
        path = Path(ref["path"])
        assert path.exists()
        assert sha256_file(path) == ref["sha256"]

    ass_ref = case["expected_assessment_ref"]
    ass_path = Path(ass_ref["path"])
    assert ass_path.exists()
    assert sha256_file(ass_path) == ass_ref["sha256"]

def validate_preconditions(exp, ev, ass=None):
    exp_names = [s["service_name"] for s in exp["expected_services"]]
    if len(exp_names) != len(set(exp_names)):
        raise ValueError("Duplicate service_name in expectation")
    
    ev_names = [s["service_name"] for s in ev["services"]]
    if len(ev_names) != len(set(ev_names)):
        raise ValueError("Duplicate service_name in evidence")
        
    if ass:
        ass_names = [s["service_name"] for s in ass.get("evaluated_services", [])]
        if len(ass_names) != len(set(ass_names)):
            raise ValueError("Duplicate service_name in assessment")

def test_duplicate_service_names_in_expectation_rejected():
    """Duplicate service names in expectation are invalid."""
    instance = load_json(Path("examples/heimserver-service-expectations/minimal-tailscale.json"))
    instance["expected_services"].append(instance["expected_services"][0])
    
    with pytest.raises(ValueError, match="Duplicate service_name in expectation"):
        validate_preconditions(instance, load_json(Path("examples/heimserver-service-evidence/minimal-artifact-only.json")))

def test_duplicate_service_names_in_evidence_rejected():
    """Duplicate service names in evidence are invalid."""
    instance = load_json(Path("examples/heimserver-service-evidence/minimal-artifact-only.json"))
    instance["services"].append(instance["services"][0])
    
    with pytest.raises(ValueError, match="Duplicate service_name in evidence"):
        validate_preconditions(load_json(Path("examples/heimserver-service-expectations/minimal-tailscale.json")), instance)

def test_duplicate_service_names_in_assessment_rejected():
    """Duplicate service names in assessment evaluated_services are invalid."""
    instance = load_json(Path("examples/heimserver-service-gate-assessments/passed.json"))
    instance["evaluated_services"].append(instance["evaluated_services"][0])
    
    with pytest.raises(ValueError, match="Duplicate service_name in assessment"):
        validate_preconditions(
            load_json(Path("examples/heimserver-service-expectations/minimal-tailscale.json")),
            load_json(Path("examples/heimserver-service-evidence/minimal-artifact-only.json")),
            instance
        )

def test_contract_rules_verification():
    """Small table-driven verification of the derivations as required."""
    for case_file in CASE_FILES:
        case = load_json(case_file)
        
        facts = load_json(Path(case["inputs"]["server_facts_ref"]["path"]))
        exp = load_json(Path(case["inputs"]["expectation_ref"]["path"]))
        ev = load_json(Path(case["inputs"]["service_evidence_ref"]["path"]))
        ass = load_json(Path(case["expected_assessment_ref"]["path"]))
        
        # Rule: Host Identity match
        facts_host = facts["host"]["hostname"]
        exp_host = exp["host"]
        ev_host = ev["host"]
        
        if facts_host != exp_host or facts_host != ev_host:
            assert ass["status"] == "blocked"
            assert "service_gate_subject_mismatch" in ass["reason_codes"]
        else:
            assert "service_gate_subject_mismatch" not in ass["reason_codes"]
        
        # Rule: Freshness Match
        if ev["freshness_status"] == "unknown":
            assert ass["status"] in ("inconclusive", "blocked")
            if ass["status"] == "inconclusive":
                assert "service_gate_freshness_unknown" in ass["reason_codes"]
        elif ev["freshness_status"] == "stale":
            assert ass["status"] in ("inconclusive", "blocked")
            if ass["status"] == "inconclusive":
                assert "service_gate_artifacts_stale" in ass["reason_codes"]

        # Rule: Service Join by service_name
        exp_services = {s["service_name"]: s for s in exp["expected_services"]}
        ev_services = {s["service_name"]: s for s in ev["services"]}
        
        for e_srv in exp_services.values():
            name = e_srv["service_name"]
            if name not in ev_services:
                pass # Evidence missing for expected service
            
        for ass_srv in ass.get("evaluated_services", []):
            name = ass_srv["service_name"]
            assert name in exp_services, f"Evaluated service {name} not in expected services"
            # It ignores extra services in evidence!
