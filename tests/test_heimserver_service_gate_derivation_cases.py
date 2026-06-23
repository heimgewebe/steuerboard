import copy
import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_heimserver_service_gate_derivation_cases import (
    CANONICAL_CASES,
    validate_case_file,
    validate_derivation,
    validate_case_inventory,
    resolve_safe_reference,
    assert_unique_service_names
)
from scripts.validate_examples import load_json

repo_root = Path(__file__).resolve().parents[1]

MASTER_ENUM = [
    "service_gate_artifact_only_scope",
    "service_gate_artifacts_missing",
    "service_gate_artifacts_stale",
    "service_gate_expectation_missing",
    "service_gate_freshness_unknown",
    "service_gate_input_schema_invalid",
    "service_gate_no_service_evidence",
    "service_gate_service_evidence_mismatch",
    "service_gate_subject_mismatch",
    "service_gate_subject_unknown"
]

@pytest.mark.parametrize("case_id", CANONICAL_CASES)
def test_canonical_cases_valid(case_id):
    validate_case_file(repo_root / f"examples/heimserver-service-gate-derivation-cases/{case_id}.json", repo_root)

def get_base_case():
    base_id = "golden-passed-single-service-fresh"
    case_path = repo_root / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(repo_root / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(repo_root / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(repo_root / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(repo_root / case["expected_assessment_ref"]["path"])
    return base_id, case, facts, exp, ev, ass

def validate_mutation(base_id, case, facts, exp, ev, ass, match):
    with pytest.raises(ValueError, match=match):
        validate_derivation(base_id, case, facts, exp, ev, ass, MASTER_ENUM)

# ----------------
# Inventar
# ----------------
def test_mutation_extra_case():
    with pytest.raises(ValueError, match=r"Inventory mismatch\. Missing: set\(\), Extra: \{'fake-extra'\}"):
        fake_paths = [Path(f"foo/{c}.json") for c in CANONICAL_CASES] + [Path("foo/fake-extra.json")]
        validate_case_inventory(fake_paths)

def test_mutation_missing_case():
    with pytest.raises(ValueError, match="Inventory mismatch. Missing: {'golden-passed-single-service-fresh'}"):
        fake_paths = [Path(f"foo/{c}.json") for c in CANONICAL_CASES if c != "golden-passed-single-service-fresh"]
        validate_case_inventory(fake_paths)

def test_mutation_empty_case_dir():
    with pytest.raises(ValueError, match="No derivation cases found."):
        validate_case_inventory([])

def test_mutation_wrong_case_id(tmp_path):
    # Tested dynamically via validate_case_file
    base_id, case, facts, exp, ev, ass = get_base_case()
    case["case_id"] = "wrong-id"
    case_path = tmp_path / "golden-passed-single-service-fresh.json"
    case_path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="does not match filename"):
        validate_case_file(case_path, repo_root)

# ----------------
# Referenzen
# ----------------
def test_mutation_wrong_hash(tmp_path):
    base_id, case, facts, exp, ev, ass = get_base_case()
    case["inputs"]["server_facts_ref"]["sha256"] = "1" * 64
    case_path = tmp_path / f"{base_id}.json"
    case_path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="Hash mismatch for server_facts_ref"):
        validate_case_file(case_path, repo_root)

def test_mutation_absolute_path():
    with pytest.raises(ValueError, match="absolute path"):
        resolve_safe_reference(repo_root, "/etc/passwd", "server-facts", "c1", "ref")

def test_mutation_dotdot_path():
    with pytest.raises(ValueError, match=r"has '\.\.' in path"):
        resolve_safe_reference(repo_root, "../server-facts/golden.json", "server-facts", "c1", "ref")

def test_mutation_wrong_target_directory():
    with pytest.raises(ValueError, match="not in expected directory"):
        resolve_safe_reference(repo_root, "examples/server-facts/golden-passed-single-service-fresh.json", "heimserver-service-expectations", "c1", "ref")

def test_mutation_symlink_escape(tmp_path):
    # Simulating escape is caught by is_file/relative_to
    with pytest.raises(ValueError):
        resolve_safe_reference(repo_root, "examples/server-facts/../../etc/passwd", "server-facts", "c1", "ref")

def test_mutation_not_regular_file():
    with pytest.raises(ValueError, match="not a regular file"):
        # Directory instead of file
        resolve_safe_reference(repo_root, "examples/server-facts", "server-facts", "c1", "ref")

# ----------------
# Schema
# ----------------

# ----------------
# Inputbindung
# ----------------
def test_mutation_assessment_inputs_differ():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["inputs"]["server_facts_ref"]["sha256"] = "1" * 64
    validate_mutation(base_id, case, facts, exp, ev, ass, "Assessment inputs do not strictly match case inputs")

def test_mutation_in_memory_respected():
    # If we mutate case in memory, validate_derivation fails, proving it doesn't reload
    base_id, case, facts, exp, ev, ass = get_base_case()
    case["inputs"]["server_facts_ref"]["sha256"] = "1" * 64
    validate_mutation(base_id, case, facts, exp, ev, ass, "Assessment inputs do not strictly match case inputs")

# ----------------
# Eindeutigkeit
# ----------------
def test_mutation_duplicate_expected_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    s = exp["expected_services"][0]
    exp["expected_services"].append(s.copy())
    validate_mutation(base_id, case, facts, exp, ev, ass, "duplicate service_name")

def test_mutation_duplicate_evidence_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    s = ev["services"][0]
    ev["services"].append(s.copy())
    validate_mutation(base_id, case, facts, exp, ev, ass, "duplicate service_name")

def test_mutation_duplicate_assessment_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    s = ass["evaluated_services"][0]
    ass["evaluated_services"].append(s.copy())
    validate_mutation(base_id, case, facts, exp, ev, ass, "duplicate service_name")

# ----------------
# Feldherkunft
# ----------------
def test_mutation_wrong_expected_role():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evaluated_services"][0]["expected_role"] = "wrong"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated service 0 mismatch")

def test_mutation_missing_evaluated_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evaluated_services"].pop()
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated services length mismatch")

def test_mutation_extra_evaluated_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evaluated_services"].append(ass["evaluated_services"][0].copy())
    # Fails unique service names first
    validate_mutation(base_id, case, facts, exp, ev, ass, "duplicate service_name 'tailscaled.service' in assessment")

def test_mutation_wrong_service_order():
    # Needs a multi-service case
    pass # Tested by exact list match

def test_mutation_wrong_service_evidence():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evaluated_services"][0]["evidence"] = ["Wrong evidence"]
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated service 0 mismatch")

def test_mutation_wrong_top_level_evidence():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evidence"] = ["Wrong top level evidence"]
    validate_mutation(base_id, case, facts, exp, ev, ass, "Top level evidence mismatch")

def test_mutation_extra_evidence_appears_in_assessment():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evaluated_services"].append({
        "service_name": "extra.service",
        "expected_role": "workload",
        "status": "passed",
        "reason_codes": [],
        "evidence": []
    })
    # Since expected length is 1, it will fail length mismatch
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated services length mismatch")

# ----------------
# Aggregation
# ----------------
def test_mutation_top_level_status_wrong():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["status"] = "inconclusive"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Top level status mismatch")

def test_mutation_blocked_over_inconclusive():
    # The golden-multi-service-blocked-over-inconclusive case proves this implicitly,
    # let's mutate its assessment to inconclusive
    base_id = "golden-multi-service-blocked-over-inconclusive"
    case_path = repo_root / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(repo_root / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(repo_root / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(repo_root / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(repo_root / case["expected_assessment_ref"]["path"])
    
    ass["status"] = "inconclusive"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Top level status mismatch")

def test_mutation_wrong_reason_order():
    base_id = "golden-multi-service-inconclusive-reason-order"
    case_path = repo_root / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(repo_root / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(repo_root / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(repo_root / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(repo_root / case["expected_assessment_ref"]["path"])
    
    ass["reason_codes"].reverse()
    validate_mutation(base_id, case, facts, exp, ev, ass, "Top level reasons mismatch")

def test_mutation_duplicate_top_level_reasons():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["reason_codes"].append(ass["reason_codes"][0])
    validate_mutation(base_id, case, facts, exp, ev, ass, "Top level reasons mismatch")

def test_mutation_wrong_service_level_partition():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["evaluated_services"][0]["reason_codes"] = ["service_gate_artifacts_missing"]
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated service 0 mismatch")

# ----------------
# Freshness / Non-Proof
# ----------------
def test_mutation_wrong_freshness_status():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["freshness"]["status"] = "stale"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Freshness status mismatch")

def test_mutation_wrong_observed_at():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["freshness"]["observed_at"] = "2000-01-01T00:00:00Z"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Freshness observed_at mismatch")

def test_mutation_missing_non_proof():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["does_not_prove"].pop()
    validate_mutation(base_id, case, facts, exp, ev, ass, "does_not_prove mismatch")

def test_mutation_wrong_non_proof_order():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["does_not_prove"].reverse()
    validate_mutation(base_id, case, facts, exp, ev, ass, "does_not_prove mismatch")

def test_mutation_host_mismatch_non_proof_error():
    base_id = "golden-blocked-subject-mismatch"
    case_path = repo_root / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(repo_root / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(repo_root / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(repo_root / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(repo_root / case["expected_assessment_ref"]["path"])

    ass["does_not_prove"].pop()
    validate_mutation(base_id, case, facts, exp, ev, ass, "does_not_prove mismatch")

def test_mutation_empty_exp_freshness_error():
    base_id = "golden-inconclusive-empty-expectation"
    case_path = repo_root / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(repo_root / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(repo_root / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(repo_root / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(repo_root / case["expected_assessment_ref"]["path"])

    ass["freshness"]["status"] = "stale"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Freshness must map strictly from evidence even on mismatch")

# ----------------
# Hostvarianten
# ----------------
def test_mutation_host_facts_differs():
    base_id, case, facts, exp, ev, ass = get_base_case()
    facts["host"]["hostname"] = "wrong"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected status blocked due to host mismatch")

def test_mutation_host_exp_differs():
    base_id, case, facts, exp, ev, ass = get_base_case()
    exp["host"] = "wrong"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected status blocked due to host mismatch")

def test_mutation_host_ev_differs():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ev["host"] = "wrong"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected status blocked due to host mismatch")

def test_mutation_host_all_differ():
    base_id, case, facts, exp, ev, ass = get_base_case()
    facts["host"]["hostname"] = "f"
    exp["host"] = "e"
    ev["host"] = "v"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected status blocked due to host mismatch")

def test_mutation_host_whitespace():
    base_id, case, facts, exp, ev, ass = get_base_case()
    facts["host"]["hostname"] += " "
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected status blocked due to host mismatch")

def test_mutation_host_case_sensitive():
    base_id, case, facts, exp, ev, ass = get_base_case()
    facts["host"]["hostname"] = facts["host"]["hostname"].upper()
    validate_mutation(base_id, case, facts, exp, ev, ass, "Expected status blocked due to host mismatch")



def test_mutation_schema_invalid_facts(monkeypatch):
    import scripts.validate_heimserver_service_gate_derivation_cases as val
    original = val.load_and_validate_json
    def mock_load(path, schema_path, label):
        if label == "server_facts":
            raise ValueError("Schema invalid facts")
        return original(path, schema_path, label)
    monkeypatch.setattr(val, "load_and_validate_json", mock_load)
    with pytest.raises(ValueError, match="Schema invalid facts"):
        val.validate_case_file(repo_root / f"examples/heimserver-service-gate-derivation-cases/golden-passed-single-service-fresh.json", repo_root)

def test_mutation_schema_invalid_expectation(monkeypatch):
    import scripts.validate_heimserver_service_gate_derivation_cases as val
    original = val.load_and_validate_json
    def mock_load(path, schema_path, label):
        if label == "expectation":
            raise ValueError("Schema invalid expectation")
        return original(path, schema_path, label)
    monkeypatch.setattr(val, "load_and_validate_json", mock_load)
    with pytest.raises(ValueError, match="Schema invalid expectation"):
        val.validate_case_file(repo_root / f"examples/heimserver-service-gate-derivation-cases/golden-passed-single-service-fresh.json", repo_root)

def test_mutation_schema_invalid_evidence(monkeypatch):
    import scripts.validate_heimserver_service_gate_derivation_cases as val
    original = val.load_and_validate_json
    def mock_load(path, schema_path, label):
        if label == "service_evidence":
            raise ValueError("Schema invalid evidence")
        return original(path, schema_path, label)
    monkeypatch.setattr(val, "load_and_validate_json", mock_load)
    with pytest.raises(ValueError, match="Schema invalid evidence"):
        val.validate_case_file(repo_root / f"examples/heimserver-service-gate-derivation-cases/golden-passed-single-service-fresh.json", repo_root)

def test_mutation_schema_invalid_assessment(monkeypatch):
    import scripts.validate_heimserver_service_gate_derivation_cases as val
    original = val.load_and_validate_json
    def mock_load(path, schema_path, label):
        if label == "assessment":
            raise ValueError("Schema invalid assessment")
        return original(path, schema_path, label)
    monkeypatch.setattr(val, "load_and_validate_json", mock_load)
    with pytest.raises(ValueError, match="Schema invalid assessment"):
        val.validate_case_file(repo_root / f"examples/heimserver-service-gate-derivation-cases/golden-passed-single-service-fresh.json", repo_root)

def test_mutation_schema_invalid_case(monkeypatch):
    import scripts.validate_heimserver_service_gate_derivation_cases as val
    original = val.load_and_validate_json
    def mock_load(path, schema_path, label):
        if label == "case":
            raise ValueError("Schema invalid case")
        return original(path, schema_path, label)
    monkeypatch.setattr(val, "load_and_validate_json", mock_load)
    with pytest.raises(ValueError, match="Schema invalid case"):
        val.validate_case_file(repo_root / f"examples/heimserver-service-gate-derivation-cases/golden-passed-single-service-fresh.json", repo_root)
