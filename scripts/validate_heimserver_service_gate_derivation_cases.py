import json
import hashlib
from pathlib import Path
import sys

# The 14 canonical case IDs that MUST be present and validated.
CANONICAL_CASES = [
    "golden-blocked-service-evidence-mismatch",
    "golden-blocked-subject-mismatch",
    "golden-extra-evidence-service-ignored",
    "golden-inconclusive-empty-expectation",
    "golden-inconclusive-evidence-status-unknown",
    "golden-inconclusive-freshness-unknown",
    "golden-inconclusive-no-service-evidence",
    "golden-inconclusive-stale-evidence",
    "golden-inconclusive-unmatched-evidence-service",
    "golden-multi-service-blocked-over-inconclusive",
    "golden-multi-service-blocked-precedence",
    "golden-multi-service-inconclusive-precedence",
    "golden-multi-service-inconclusive-reason-order",
    "golden-passed-single-service-fresh"
]

MASTER_REASON_ENUM = [
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

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def sha256_file(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def sort_reasons(reasons: list[str]) -> list[str]:
    # Ensure they are deduplicated and in master enum order
    deduped = []
    for r in reasons:
        if r not in deduped:
            deduped.append(r)
    return sorted(deduped, key=lambda x: MASTER_REASON_ENUM.index(x))

def validate_case_file(case_id: str):
    case_path = Path(f"examples/heimserver-service-gate-derivation-cases/{case_id}.json")
    if not case_path.exists():
        raise FileNotFoundError(f"Canonical case {case_id} is missing.")

    case = load_json(case_path)
    
    # 1. Reference Integrity Check
    refs = [
        case["inputs"]["server_facts_ref"],
        case["inputs"]["expectation_ref"],
        case["inputs"]["service_evidence_ref"],
        case["expected_assessment_ref"]
    ]
    for ref in refs:
        p = Path(ref["path"])
        if not p.exists():
            raise FileNotFoundError(f"Referenced path {p} missing in {case_id}")
        if sha256_file(p) != ref["sha256"]:
            raise ValueError(f"Hash mismatch for {p} in {case_id}")

    facts = load_json(Path(case["inputs"]["server_facts_ref"]["path"]))
    exp = load_json(Path(case["inputs"]["expectation_ref"]["path"]))
    ev = load_json(Path(case["inputs"]["service_evidence_ref"]["path"]))
    ass = load_json(Path(case["expected_assessment_ref"]["path"]))

    validate_derivation(case_id, case, facts, exp, ev, ass)

def validate_derivation(case_id: str, case: dict, facts: dict, exp: dict, ev: dict, ass: dict):
    # 1. Input equivalence

    case_path = Path(f"examples/heimserver-service-gate-derivation-cases/{case_id}.json")
    if not case_path.exists():
        raise FileNotFoundError(f"Canonical case {case_id} is missing.")

    case = load_json(case_path)
    
    # 1. Reference Integrity Check
    refs = [
        case["inputs"]["server_facts_ref"],
        case["inputs"]["expectation_ref"],
        case["inputs"]["service_evidence_ref"],
        case["expected_assessment_ref"]
    ]
    for ref in refs:
        p = Path(ref["path"])
        if not p.exists():
            raise FileNotFoundError(f"Referenced path {p} missing in {case_id}")
        if sha256_file(p) != ref["sha256"]:
            raise ValueError(f"Hash mismatch for {p} in {case_id}")


    # Assessment inputs must exactly equal the derivation case inputs
    if ass["inputs"] != case["inputs"]:
        raise ValueError(f"Assessment inputs do not strictly match case inputs in {case_id}")

    # 2. Host Identity Rule
    facts_host = facts["host"]["hostname"]
    exp_host = exp["host"]
    ev_host = ev["host"]

    if not (facts_host == exp_host == ev_host):
        # Must be blocked due to host mismatch
        if ass["status"] != "blocked":
            raise ValueError(f"Expected status blocked due to host mismatch in {case_id}")
        if ass["subject"]["host"] != exp_host:
            raise ValueError(f"Subject host must match expectation host in {case_id}")
        if ass.get("evaluated_services", []) != []:
            raise ValueError(f"Evaluated services must be empty on host mismatch in {case_id}")
        if ass["reason_codes"] != ["service_gate_subject_mismatch"]:
            raise ValueError(f"Top level reason must be subject_mismatch in {case_id}")
        
        expected_text = f"Host identity mismatch: server_facts='{facts_host}', expectation='{exp_host}', service_evidence='{ev_host}'."
        if ass["evidence"] != [expected_text]:
            raise ValueError(f"Evidence text mismatch for host identity in {case_id}")
        if ass["freshness"]["status"] != ev["freshness_status"] or ass["freshness"]["observed_at"] != ev["observed_at"]:
            raise ValueError(f"Freshness must map strictly from evidence even on mismatch in {case_id}")
        return

    # Normal Processing (Host Identity Passed)
    if ass["subject"]["host"] != exp_host:
        raise ValueError(f"Subject host mismatch in {case_id}")

    # 3. Expected Services Rule
    if ass.get("expected_services", []) != exp.get("expected_services", []):
        raise ValueError(f"Expected services must match exactly in {case_id}")

    # Empty Expectation Special Case
    if not exp.get("expected_services", []):
        if ass["status"] != "inconclusive":
            raise ValueError(f"Empty expectation must be inconclusive in {case_id}")
        if ass["reason_codes"] != ["service_gate_expectation_missing"]:
            raise ValueError(f"Empty expectation reason mismatch in {case_id}")
        if ass["evidence"] != ["No expected services were declared."]:
            raise ValueError(f"Empty expectation evidence mismatch in {case_id}")
        return

    # 4. Service Join Rule
    ev_map = {s["service_name"]: s for s in ev.get("services", [])}
    derived_evaluated_services = []
    has_blocked = False
    has_inconclusive = False
    all_reasons = []

    for exp_s in exp.get("expected_services", []):
        s_name = exp_s["service_name"]
        e_role = exp_s["expected_role"]
        
        ev_s = ev_map.get(s_name)
        
        s_status = None
        s_reasons = []
        s_ev_text = []

        if not ev_s:
            s_status = "inconclusive"
            s_reasons = ["service_gate_no_service_evidence"]
            s_ev_text = [f"No matching artifact-derived evidence found for expected service '{s_name}'."]
        else:
            e_status = ev_s["evidence_status"]
            f_status = ev["freshness_status"]
            
            if e_status == "mismatch":
                s_status = "blocked"
                s_reasons = ["service_gate_service_evidence_mismatch"]
            elif e_status in ("missing", "unknown"):
                s_status = "inconclusive"
                s_reasons = ["service_gate_no_service_evidence"]
            elif e_status == "present":
                if f_status == "fresh":
                    s_status = "passed"
                    s_reasons = ["service_gate_artifact_only_scope"]
                elif f_status == "stale":
                    s_status = "inconclusive"
                    s_reasons = ["service_gate_artifacts_stale"]
                elif f_status == "unknown":
                    s_status = "inconclusive"
                    s_reasons = ["service_gate_freshness_unknown"]
            else:
                raise ValueError(f"Unknown evidence status {e_status}")

            if e_status != "mismatch" and e_status not in ("missing", "unknown"):
                # Real evidence texts from evidence should be passed if not mapped to a fixed string.
                # Actually, our schema might just map evidence directly or have fixed strings.
                # Let's just compare if it aligns with the assessment's evidence for that service.
                pass
            
            if s_status == "blocked":
                s_ev_text = ev_s.get("evidence", [])
            elif s_status == "passed":
                s_ev_text = ev_s.get("evidence", [])
            elif s_status == "inconclusive" and e_status not in ("missing", "unknown"):
                s_ev_text = ev_s.get("evidence", [])
            elif e_status in ("missing", "unknown"):
                s_ev_text = [f"No matching artifact-derived evidence found for expected service '{s_name}'."]

        derived_evaluated_services.append({
            "service_name": s_name,
            "expected_role": e_role,
            "status": s_status,
            "reason_codes": s_reasons,
            "evidence": s_ev_text
        })
        
        if s_status == "blocked":
            has_blocked = True
            
        if s_status == "inconclusive":
            has_inconclusive = True

    # Top level aggregation
    top_status = "passed"
    if has_blocked:
        top_status = "blocked"
    elif has_inconclusive:
        top_status = "inconclusive"

    all_reasons = []
    if top_status == "passed":
        all_reasons = ["service_gate_artifact_only_scope"]
    elif top_status == "blocked":
        for s in derived_evaluated_services:
            if s["status"] == "blocked":
                all_reasons.extend(s["reason_codes"])
    elif top_status == "inconclusive":
        for s in derived_evaluated_services:
            if s["status"] == "inconclusive":
                all_reasons.extend(s["reason_codes"])

    # Compare evaluated_services
    ass_eval = ass.get("evaluated_services", [])
    if ass_eval != derived_evaluated_services:
        # Check carefully to provide a good diff if mismatched
        if len(ass_eval) != len(derived_evaluated_services):
            raise ValueError(f"Evaluated services length mismatch in {case_id}")
        for i, (a_s, d_s) in enumerate(zip(ass_eval, derived_evaluated_services)):
            if a_s != d_s:
                raise ValueError(f"Evaluated service {i} mismatch in {case_id}:\nExpected: {d_s}\nGot: {a_s}")
    
    derived_reasons = sort_reasons(all_reasons)
    
    if ass["status"] != top_status:
        raise ValueError(f"Top level status mismatch in {case_id}. Expected {top_status}, got {ass['status']}")
    if ass["reason_codes"] != derived_reasons:
        raise ValueError(f"Top level reasons mismatch in {case_id}. Expected {derived_reasons}, got {ass['reason_codes']}")

    # Freshness
    if ass["freshness"]["status"] != ev["freshness_status"]:
        raise ValueError(f"Freshness status mismatch in {case_id}")
    if ass["freshness"]["observed_at"] != ev["observed_at"]:
        raise ValueError(f"Freshness observed_at mismatch in {case_id}")

    # Does Not Prove
    expected_dnp = ["live_service_running", "service_reachable", "runtime_correctness", "service_role_fulfilled"]
    if ass["does_not_prove"] != expected_dnp:
        raise ValueError(f"does_not_prove mismatch in {case_id}")

def main():
    print("Validating 14 canonical Heimserver Service Gate Derivation Cases...")
    for case_id in CANONICAL_CASES:
        try:
            validate_case_file(case_id)
            print(f"PASS: {case_id}")
        except Exception as e:
            print(f"FAIL: {case_id}")
            print(f"  {e}")
            sys.exit(1)
            
    print("All cases successfully validated.")

if __name__ == "__main__":
    main()
