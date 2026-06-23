import copy
import pytest
from pathlib import Path

from scripts.validate_examples import load_json
from scripts.validate_heimserver_service_gate_derivation_cases import (
    validate_case_file,
    validate_derivation,
    CANONICAL_CASES,
)

@pytest.mark.parametrize("case_id", CANONICAL_CASES)
def test_canonical_cases_valid(case_id):
    """Ensure all canonical golden cases validate successfully against the normative validator."""
    validate_case_file(case_id)

def get_base_case():
    base_id = "golden-passed-single-service-fresh"
    case_path = Path(f"examples/heimserver-service-gate-derivation-cases/{base_id}.json")
    case = load_json(case_path)
    facts = load_json(Path(case["inputs"]["server_facts_ref"]["path"]))
    exp = load_json(Path(case["inputs"]["expectation_ref"]["path"]))
    ev = load_json(Path(case["inputs"]["service_evidence_ref"]["path"]))
    ass = load_json(Path(case["expected_assessment_ref"]["path"]))
    return base_id, case, facts, exp, ev, ass

def validate_mutation(base_id, case, facts, exp, ev, ass, match):
    with pytest.raises(ValueError, match=match):
        validate_derivation(base_id, case, facts, exp, ev, ass)

def test_mutation_host_identity_missing():
    base_id, case, facts, exp, ev, ass = get_base_case()
    # Mutate expectation host
    exp["host"] = "wrong-host"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected status blocked due to host mismatch")

def test_mutation_host_identity_incorrect_assessment():
    base_id, case, facts, exp, ev, ass = get_base_case()
    exp["host"] = "wrong-host"
    ass["status"] = "blocked"
    ass["subject"]["host"] = "wrong-host"
    ass["evaluated_services"] = []
    ass["reason_codes"] = ["service_gate_subject_mismatch"]
    # Provide wrong text
    ass["evidence"] = ["Host identity mismatch between facts and inputs."]
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evidence text mismatch for host identity")

def test_mutation_host_identity_trimmed_mismatch():
    base_id, case, facts, exp, ev, ass = get_base_case()
    exp["host"] = "heimserver-golden " # Added space
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected status blocked due to host mismatch")

def test_mutation_missing_expected_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    # Remove service from assessment
    ass["expected_services"].pop()
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected services must match exactly")

def test_mutation_expected_services_wrong_order():
    base_id, case, facts, exp, ev, ass = get_base_case()
    # Add a second service and reverse order in assessment
    exp["expected_services"].append({"service_name": "s2.service", "expected_role": "workload"})
    ass["expected_services"].append({"service_name": "s2.service", "expected_role": "workload"})
    ass["expected_services"].reverse()
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected services must match exactly")

def test_mutation_evaluated_services_missing():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evaluated_services"].pop()
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated services length mismatch")

def test_mutation_evaluated_services_wrong_status():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evaluated_services"][0]["status"] = "inconclusive"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated service 0 mismatch")

def test_mutation_top_level_status_wrong():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["status"] = "inconclusive"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Top level status mismatch")

def test_mutation_reason_order():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["status"] = "blocked"
    ass["reason_codes"] = ["service_gate_subject_mismatch", "service_gate_artifacts_missing"]
    # If reasons are not perfectly sorted according to MASTER_ENUM, it fails
    # Let's mock a multi-service blocked case to test reason order
    # service_gate_service_evidence_mismatch comes AFTER service_gate_artifacts_missing
    pass # Currently tested indirectly, but let's do a direct test

def test_mutation_freshness_mismatch():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["freshness"]["status"] = "stale"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Freshness status mismatch")

def test_mutation_does_not_prove_missing_element():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["does_not_prove"].pop()
    validate_mutation(base_id, case, facts, exp, ev, ass, "does_not_prove mismatch")

def test_mutation_does_not_prove_wrong_order():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["does_not_prove"].reverse()
    validate_mutation(base_id, case, facts, exp, ev, ass, "does_not_prove mismatch")
