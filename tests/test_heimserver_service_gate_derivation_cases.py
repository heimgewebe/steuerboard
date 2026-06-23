import json
import os
import shutil
import pytest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_heimserver_service_gate_derivation_cases import (
    CANONICAL_CASES,
    validate_case_file,
    validate_derivation,
    validate_case_inventory,
    resolve_safe_reference,
    assert_unique_service_names
)
from scripts.validate_examples import load_json

def get_master_enum():
    schema = load_json(REPO_ROOT / "schemas/heimserver-service-gate-assessment.v1.schema.json")
    return schema["properties"]["reason_codes"]["items"]["enum"]

MASTER_ENUM = get_master_enum()

@pytest.mark.parametrize("case_id", CANONICAL_CASES)
def test_canonical_cases_valid(case_id):
    validate_case_file(REPO_ROOT / f"examples/heimserver-service-gate-derivation-cases/{case_id}.json", REPO_ROOT)

def get_base_case():
    base_id = "golden-passed-single-service-fresh"
    case_path = REPO_ROOT / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(REPO_ROOT / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(REPO_ROOT / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(REPO_ROOT / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(REPO_ROOT / case["expected_assessment_ref"]["path"])
    return base_id, case, facts, exp, ev, ass

def validate_mutation(base_id, case, facts, exp, ev, ass, match):
    with pytest.raises(ValueError, match=match):
        validate_derivation(base_id, case, facts, exp, ev, ass, MASTER_ENUM)

# ----------------
# Inventar
# ----------------
def test_mutation_extra_case(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    for c in CANONICAL_CASES:
        (cases_dir / f"{c}.json").touch()
    (cases_dir / "fake-extra.json").touch()
    
    with pytest.raises(ValueError, match=r"Inventory mismatch\. Missing: set\(\), Extra: \{'fake-extra'\}"):
        validate_case_inventory(list(cases_dir.glob("*.json")))

def test_mutation_missing_case(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    for c in CANONICAL_CASES:
        if c != "golden-passed-single-service-fresh":
            (cases_dir / f"{c}.json").touch()
    
    with pytest.raises(ValueError, match=r"Inventory mismatch\. Missing: \{'golden-passed-single-service-fresh'\}, Extra: set\(\)"):
        validate_case_inventory(list(cases_dir.glob("*.json")))

def test_mutation_empty_case_dir():
    with pytest.raises(ValueError, match="No derivation cases found."):
        validate_case_inventory([])

def test_mutation_wrong_case_id(tmp_path):
    base_id, case, facts, exp, ev, ass = get_base_case()
    case["case_id"] = "wrong-id"
    case_path = tmp_path / "golden-passed-single-service-fresh.json"
    case_path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="does not match filename"):
        validate_case_file(case_path, REPO_ROOT, allow_noncanonical_case_id=True)

# ----------------
# Referenzen
# ----------------
def test_mutation_wrong_hash(tmp_path):
    base_id, case, facts, exp, ev, ass = get_base_case()
    case["inputs"]["server_facts_ref"]["sha256"] = "1" * 64
    case_path = tmp_path / f"{base_id}.json"
    case_path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="Hash mismatch for server_facts_ref"):
        validate_case_file(case_path, REPO_ROOT, allow_noncanonical_case_id=True)

def test_mutation_absolute_path():
    with pytest.raises(ValueError, match="absolute path"):
        resolve_safe_reference(REPO_ROOT, "/etc/passwd", "server-facts", "c1", "ref")

def test_mutation_dotdot_path():
    with pytest.raises(ValueError, match=r"has '\.\.' in path"):
        resolve_safe_reference(REPO_ROOT, "../server-facts/golden.json", "server-facts", "c1", "ref")

def test_mutation_wrong_target_directory():
    with pytest.raises(ValueError, match="not in expected directory"):
        resolve_safe_reference(REPO_ROOT, "examples/server-facts/golden-passed-single-service-fresh.json", "heimserver-service-expectations", "c1", "ref")

def test_mutation_symlink_escape(tmp_path):
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir()
    facts_dir = tmp_repo / "examples" / "server-facts"
    facts_dir.mkdir(parents=True)
    
    escape_target = tmp_path / "outside.json"
    escape_target.write_text("{}")
    
    symlink_path = facts_dir / "escape.json"
    os.symlink(escape_target, symlink_path)
    
    with pytest.raises(ValueError, match="escapes repository root"):
        resolve_safe_reference(tmp_repo, "examples/server-facts/escape.json", "server-facts", "c1", "ref")

def test_mutation_not_regular_file():
    with pytest.raises(ValueError, match="not a regular file"):
        resolve_safe_reference(REPO_ROOT, "examples/server-facts", "server-facts", "c1", "ref")

# ----------------
# Schema
# ----------------
def setup_tmp_repo_for_schema(tmp_path):
    import hashlib
    import copy
    from scripts.validate_examples import ValidationError

    def sha256_file(path: Path) -> str:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    tmp_repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "schemas", tmp_repo / "schemas")

    ex_dir = tmp_repo / "examples"
    ex_dir.mkdir()

    dirs = [
        "server-facts",
        "heimserver-service-expectations",
        "heimserver-service-evidence",
        "heimserver-service-gate-assessments",
        "heimserver-service-gate-derivation-cases"
    ]
    for d in dirs:
        (ex_dir / d).mkdir()

    base_id, case, facts, exp, ev, ass = get_base_case()

    def save_and_test(mutated_label, facts_m, exp_m, ev_m, ass_m, case_m):
        facts_path = ex_dir / "server-facts" / "facts.json"
        exp_path = ex_dir / "heimserver-service-expectations" / "exp.json"
        ev_path = ex_dir / "heimserver-service-evidence" / "ev.json"
        ass_path = ex_dir / "heimserver-service-gate-assessments" / "ass.json"
        case_path = ex_dir / "heimserver-service-gate-derivation-cases" / f"{base_id}.json"

        facts_path.write_text(json.dumps(facts_m))
        exp_path.write_text(json.dumps(exp_m))
        ev_path.write_text(json.dumps(ev_m))

        if mutated_label != "case":
            case_m["inputs"]["server_facts_ref"]["path"] = "examples/server-facts/facts.json"
            case_m["inputs"]["server_facts_ref"]["sha256"] = sha256_file(facts_path)

            case_m["inputs"]["expectation_ref"]["path"] = "examples/heimserver-service-expectations/exp.json"
            case_m["inputs"]["expectation_ref"]["sha256"] = sha256_file(exp_path)

            case_m["inputs"]["service_evidence_ref"]["path"] = "examples/heimserver-service-evidence/ev.json"
            case_m["inputs"]["service_evidence_ref"]["sha256"] = sha256_file(ev_path)

            ass_m["inputs"] = copy.deepcopy(case_m["inputs"])
            ass_path.write_text(json.dumps(ass_m))

            case_m["expected_assessment_ref"]["path"] = "examples/heimserver-service-gate-assessments/ass.json"
            case_m["expected_assessment_ref"]["sha256"] = sha256_file(ass_path)
        else:
            ass_path.write_text(json.dumps(ass_m))

        case_path.write_text(json.dumps(case_m))
        validate_case_file(case_path, tmp_repo, allow_noncanonical_case_id=False)

    return base_id, case, facts, exp, ev, ass, save_and_test

def test_temporary_valid_case_bundle_passes(tmp_path):
    base_id, case, facts, exp, ev, ass, save_and_test = setup_tmp_repo_for_schema(tmp_path)
    save_and_test("none", facts, exp, ev, ass, case)

def test_mutation_schema_invalid_facts(tmp_path):
    from scripts.validate_examples import ValidationError
    base_id, case, facts, exp, ev, ass, save_and_test = setup_tmp_repo_for_schema(tmp_path)
    facts["host"] = "not-an-object"
    with pytest.raises(ValidationError):
        save_and_test("server_facts", facts, exp, ev, ass, case)

def test_mutation_schema_invalid_expectation(tmp_path):
    from scripts.validate_examples import ValidationError
    base_id, case, facts, exp, ev, ass, save_and_test = setup_tmp_repo_for_schema(tmp_path)
    del exp["host"]
    with pytest.raises(ValidationError):
        save_and_test("expectation", facts, exp, ev, ass, case)

def test_mutation_schema_invalid_evidence(tmp_path):
    from scripts.validate_examples import ValidationError
    base_id, case, facts, exp, ev, ass, save_and_test = setup_tmp_repo_for_schema(tmp_path)
    ev["freshness_status"] = "invalid_enum"
    with pytest.raises(ValidationError):
        save_and_test("service_evidence", facts, exp, ev, ass, case)

def test_mutation_schema_invalid_assessment(tmp_path):
    from scripts.validate_examples import ValidationError
    base_id, case, facts, exp, ev, ass, save_and_test = setup_tmp_repo_for_schema(tmp_path)
    ass["status"] = "invalid_status"
    with pytest.raises(ValidationError):
        save_and_test("assessment", facts, exp, ev, ass, case)

def test_mutation_schema_invalid_case(tmp_path):
    from scripts.validate_examples import ValidationError
    base_id, case, facts, exp, ev, ass, save_and_test = setup_tmp_repo_for_schema(tmp_path)
    del case["expected_assessment_ref"]
    with pytest.raises(ValidationError):
        save_and_test("case", facts, exp, ev, ass, case)

# ----------------
# Inputbindung
# ----------------
def test_mutation_assessment_inputs_differ():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["inputs"]["server_facts_ref"]["sha256"] = "1" * 64
    validate_mutation(base_id, case, facts, exp, ev, ass, "Assessment inputs do not strictly match case inputs")

def test_mutation_in_memory_respected():
    base_id, case, facts, exp, ev, ass = get_base_case()
    case["inputs"]["server_facts_ref"]["sha256"] = "1" * 64
    validate_mutation(base_id, case, facts, exp, ev, ass, "Assessment inputs do not strictly match case inputs")

# ----------------
# Eindeutigkeit
# ----------------
def test_mutation_duplicate_expected_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    s = exp["expected_services"][0].copy()
    s["expected_role"] = "different-role"
    exp["expected_services"].append(s)
    
    s_ass = ass["expected_services"][0].copy()
    s_ass["expected_role"] = "different-role"
    ass["expected_services"].append(s_ass)
    
    validate_mutation(base_id, case, facts, exp, ev, ass, "duplicate service_name")

def test_mutation_duplicate_evidence_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    s = ev["services"][0].copy()
    s["status"] = "stale"
    ev["services"].append(s)
    
    s_ass = ass["evaluated_services"][0].copy()
    s_ass["status"] = "inconclusive"
    ass["evaluated_services"].append(s_ass)
    
    validate_mutation(base_id, case, facts, exp, ev, ass, "duplicate service_name")

def test_mutation_duplicate_assessment_service():
    base_id, case, facts, exp, ev, ass = get_base_case()
    s = ass["evaluated_services"][0].copy()
    s["expected_role"] = "different-role"
    ass["evaluated_services"].append(s)
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
    validate_mutation(base_id, case, facts, exp, ev, ass, "duplicate service_name 'tailscaled.service' in assessment")

def test_mutation_wrong_service_order():
    base_id = "golden-multi-service-inconclusive-precedence"
    case_path = REPO_ROOT / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(REPO_ROOT / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(REPO_ROOT / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(REPO_ROOT / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(REPO_ROOT / case["expected_assessment_ref"]["path"])
    
    ass["evaluated_services"].reverse()
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated service 0 mismatch")

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
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated services length mismatch")

# ----------------
# Aggregation
# ----------------
def test_mutation_top_level_status_wrong():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ass["status"] = "inconclusive"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Top level status mismatch")

def test_mutation_blocked_over_inconclusive():
    base_id = "golden-multi-service-blocked-over-inconclusive"
    case_path = REPO_ROOT / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(REPO_ROOT / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(REPO_ROOT / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(REPO_ROOT / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(REPO_ROOT / case["expected_assessment_ref"]["path"])
    
    ass["status"] = "inconclusive"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Top level status mismatch")

def test_mutation_wrong_reason_order():
    base_id = "golden-multi-service-inconclusive-reason-order"
    case_path = REPO_ROOT / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(REPO_ROOT / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(REPO_ROOT / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(REPO_ROOT / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(REPO_ROOT / case["expected_assessment_ref"]["path"])
    
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
    case_path = REPO_ROOT / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(REPO_ROOT / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(REPO_ROOT / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(REPO_ROOT / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(REPO_ROOT / case["expected_assessment_ref"]["path"])

    ass["does_not_prove"].pop()
    validate_mutation(base_id, case, facts, exp, ev, ass, "does_not_prove mismatch")

def test_mutation_empty_exp_freshness_error():
    base_id = "golden-inconclusive-empty-expectation"
    case_path = REPO_ROOT / f"examples/heimserver-service-gate-derivation-cases/{base_id}.json"
    case = load_json(case_path)
    facts = load_json(REPO_ROOT / case["inputs"]["server_facts_ref"]["path"])
    exp = load_json(REPO_ROOT / case["inputs"]["expectation_ref"]["path"])
    ev = load_json(REPO_ROOT / case["inputs"]["service_evidence_ref"]["path"])
    ass = load_json(REPO_ROOT / case["expected_assessment_ref"]["path"])

    ass["freshness"]["status"] = "stale"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Freshness status mismatch")

# ----------------
# Hostvarianten
# ----------------
def test_mutation_host_facts_differs():
    base_id, case, facts, exp, ev, ass = get_base_case()
    facts["host"]["hostname"] = "wrong"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated services must be empty on host mismatch")

def test_mutation_host_exp_differs():
    base_id, case, facts, exp, ev, ass = get_base_case()
    exp["host"] = "wrong"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Subject host must match expectation host")

def test_mutation_host_ev_differs():
    base_id, case, facts, exp, ev, ass = get_base_case()
    ev["host"] = "wrong"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated services must be empty on host mismatch")

def test_mutation_host_all_differ():
    base_id, case, facts, exp, ev, ass = get_base_case()
    facts["host"]["hostname"] = "f"
    exp["host"] = "e"
    ev["host"] = "v"
    validate_mutation(base_id, case, facts, exp, ev, ass, "Subject host must match expectation host")

def test_mutation_host_whitespace():
    base_id, case, facts, exp, ev, ass = get_base_case()
    facts["host"]["hostname"] += " "
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated services must be empty on host mismatch")

def test_mutation_host_case_sensitive():
    base_id, case, facts, exp, ev, ass = get_base_case()
    facts["host"]["hostname"] = facts["host"]["hostname"].upper()
    validate_mutation(base_id, case, facts, exp, ev, ass, "Evaluated services must be empty on host mismatch")
