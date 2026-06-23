#!/usr/bin/env python3
import json
import hashlib
import sys
from pathlib import Path

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

def discover_case_paths(repo_root: Path) -> list[Path]:
    cases_dir = repo_root / "examples" / "heimserver-service-gate-derivation-cases"
    return sorted(cases_dir.glob("*.json"))

def validate_case_inventory(case_paths: list[Path]):
    actual_ids = {p.stem for p in case_paths}
    expected_ids = set(CANONICAL_CASES)
    if not case_paths:
        raise ValueError("No derivation cases found.")
    if actual_ids != expected_ids:
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        raise ValueError(f"Inventory mismatch. Missing: {missing}, Extra: {extra}")

def resolve_safe_reference(repo_root: Path, raw_path: str, expected_directory: str, case_id: str, reference_name: str) -> Path:
    raw = Path(raw_path)
    if raw.is_absolute():
        raise ValueError(f"{case_id}: {reference_name} has absolute path {raw_path}")
    if not str(raw_path).strip():
        raise ValueError(f"{case_id}: {reference_name} path is empty")
    if ".." in raw.parts:
        raise ValueError(f"{case_id}: {reference_name} has '..' in path {raw_path}")
    
    candidate = (repo_root / raw).resolve(strict=True)
    repo_root_resolved = repo_root.resolve(strict=True)
    expected_resolved = (repo_root / "examples" / expected_directory).resolve(strict=True)
    
    # Must be relative to repo_root and expected_directory
    try:
        candidate.relative_to(repo_root_resolved)
    except ValueError:
        raise ValueError(f"{case_id}: {reference_name} escapes repository root")
        
    try:
        candidate.relative_to(expected_resolved)
    except ValueError:
        raise ValueError(f"{case_id}: {reference_name} is not in expected directory {expected_directory}")
        
    if not candidate.is_file():
        raise ValueError(f"{case_id}: {reference_name} is not a regular file")
        
    return candidate

def sha256_file(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def load_json_file(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_and_validate_json(path: Path, schema_path: Path, label: str) -> dict:
    # Use existing validation mechanism
    # Note: the prompt suggests using steuerboard.schema_validation or minimal_validate.
    # We will import minimal_validate from validate_examples for now.
    import importlib.util
    sys.path.insert(0, str(Path(__file__).resolve().parents[1])) # Add repo root to sys.path
    import scripts.validate_examples as validator
    
    data = load_json_file(path)
    schema = load_json_file(schema_path)
    validator.validate_schema(schema, schema_path)
    validator.validate_instance(data, schema, path)
    return data

def assert_unique_service_names(services: list[dict], label: str, case_id: str) -> None:
    seen = set()
    for service in services:
        name = service["service_name"]
        if name in seen:
            raise ValueError(f"{case_id}: duplicate service_name {name!r} in {label}")
        seen.add(name)

def sort_reasons(reasons: list[str], master_enum: list[str]) -> list[str]:
    deduped = []
    for r in reasons:
        if r not in deduped:
            deduped.append(r)
    
    for r in deduped:
        if r not in master_enum:
            raise ValueError(f"Reason {r} is not in the master enum")
            
    return sorted(deduped, key=lambda x: master_enum.index(x))

def validate_derivation(case_id: str, case: dict, server_facts: dict, expectation: dict, service_evidence: dict, assessment: dict, master_enum: list[str]) -> None:
    # Assessment inputs must exactly equal the derivation case inputs
    if assessment["inputs"] != case["inputs"]:
        raise ValueError(f"Assessment inputs do not strictly match case inputs in {case_id}")

    assert_unique_service_names(expectation.get("expected_services", []), "expectation", case_id)
    assert_unique_service_names(service_evidence.get("services", []), "service_evidence", case_id)
    assert_unique_service_names(assessment.get("evaluated_services", []), "assessment", case_id)

    facts_host = server_facts["host"]["hostname"]
    exp_host = expectation["host"]
    ev_host = service_evidence["host"]

    if not (facts_host == exp_host == ev_host):
        if assessment["status"] != "blocked":
            raise ValueError(f"Expected status blocked due to host mismatch in {case_id}")
        if assessment["subject"]["host"] != exp_host:
            raise ValueError(f"Subject host must match expectation host in {case_id}")
        if assessment.get("evaluated_services", []) != []:
            raise ValueError(f"Evaluated services must be empty on host mismatch in {case_id}")
        if assessment["reason_codes"] != ["service_gate_subject_mismatch"]:
            raise ValueError(f"Top level reason must be subject_mismatch in {case_id}")
        
        expected_text = f"Host identity mismatch: server_facts='{facts_host}', expectation='{exp_host}', service_evidence='{ev_host}'."
        if assessment["evidence"] != [expected_text]:
            raise ValueError(f"Evidence text mismatch for host identity in {case_id}")
        if assessment["freshness"]["status"] != service_evidence["freshness_status"] or assessment["freshness"]["observed_at"] != service_evidence["observed_at"]:
            raise ValueError(f"Freshness must map strictly from evidence even on mismatch in {case_id}")
        if assessment["does_not_prove"] != ["live_service_running", "service_reachable", "runtime_correctness", "service_role_fulfilled"]:
            raise ValueError(f"does_not_prove mismatch in {case_id}")
        return

    # Normal Processing
    if assessment["subject"]["host"] != exp_host:
        raise ValueError(f"Subject host mismatch in {case_id}")

    if assessment.get("expected_services", []) != expectation.get("expected_services", []):
        raise ValueError(f"Expected services must match exactly in {case_id}")

    if not expectation.get("expected_services", []):
        if assessment["status"] != "inconclusive":
            raise ValueError(f"Empty expectation must be inconclusive in {case_id}")
        if assessment["reason_codes"] != ["service_gate_expectation_missing"]:
            raise ValueError(f"Empty expectation reason mismatch in {case_id}")
        if assessment["evidence"] != ["No expected services were declared."]:
            raise ValueError(f"Empty expectation evidence mismatch in {case_id}")
        if assessment["freshness"]["status"] != service_evidence["freshness_status"] or assessment["freshness"]["observed_at"] != service_evidence["observed_at"]:
            raise ValueError(f"Freshness must map strictly from evidence even on mismatch in {case_id}")
        if assessment.get("evaluated_services", []) != []:
            raise ValueError(f"Evaluated services must be empty in {case_id}")
        if assessment["does_not_prove"] != ["live_service_running", "service_reachable", "runtime_correctness", "service_role_fulfilled"]:
            raise ValueError(f"does_not_prove mismatch in {case_id}")
        return

    ev_map = {s["service_name"]: s for s in service_evidence.get("services", [])}
    derived_evaluated_services = []
    has_blocked = False
    has_inconclusive = False

    for exp_s in expectation.get("expected_services", []):
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
            f_status = service_evidence["freshness_status"]
            
            if e_status == "mismatch":
                s_status = "blocked"
                s_reasons = ["service_gate_service_evidence_mismatch"]
                s_ev_text = ev_s.get("evidence", [])
            elif e_status in ("missing", "unknown"):
                s_status = "inconclusive"
                s_reasons = ["service_gate_no_service_evidence"]
                s_ev_text = ev_s.get("evidence", [])
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
                s_ev_text = ev_s.get("evidence", [])
            else:
                raise ValueError(f"Unknown evidence status {e_status}")

        derived_evaluated_services.append({
            "service_name": s_name,
            "expected_role": e_role,
            "status": s_status,
            "reason_codes": s_reasons,
            "evidence": s_ev_text
        })
        
        if s_status == "blocked":
            has_blocked = True
        elif s_status == "inconclusive":
            has_inconclusive = True

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

    derived_reasons = sort_reasons(all_reasons, master_enum)
    
    expected_top_evidence = [
        text
        for service in derived_evaluated_services
        for text in service["evidence"]
    ]

    ass_eval = assessment.get("evaluated_services", [])
    if ass_eval != derived_evaluated_services:
        if len(ass_eval) != len(derived_evaluated_services):
            raise ValueError(f"Evaluated services length mismatch in {case_id}")
        for i, (a_s, d_s) in enumerate(zip(ass_eval, derived_evaluated_services)):
            if a_s != d_s:
                raise ValueError(f"Evaluated service {i} mismatch in {case_id}:\nExpected: {d_s}\nGot: {a_s}")
    
    if assessment["status"] != top_status:
        raise ValueError(f"Top level status mismatch in {case_id}. Expected {top_status}, got {assessment['status']}")
    if assessment["reason_codes"] != derived_reasons:
        raise ValueError(f"Top level reasons mismatch in {case_id}. Expected {derived_reasons}, got {assessment['reason_codes']}")
    if assessment["evidence"] != expected_top_evidence:
        raise ValueError(f"Top level evidence mismatch in {case_id}. Expected {expected_top_evidence}, got {assessment['evidence']}")

    if assessment["freshness"]["status"] != service_evidence["freshness_status"]:
        raise ValueError(f"Freshness status mismatch in {case_id}")
    if assessment["freshness"]["observed_at"] != service_evidence["observed_at"]:
        raise ValueError(f"Freshness observed_at mismatch in {case_id}")

    if assessment["does_not_prove"] != ["live_service_running", "service_reachable", "runtime_correctness", "service_role_fulfilled"]:
        raise ValueError(f"does_not_prove mismatch in {case_id}")

def validate_case_file(case_path: Path, repo_root: Path):
    case_id = case_path.stem
    if case_id not in CANONICAL_CASES:
        pass # The inventory check already caught missing/extra, this allows running individual tests if needed
        
    case_schema_path = repo_root / "schemas" / "heimserver-service-gate-derivation-case.v1.schema.json"
    case = load_and_validate_json(case_path, case_schema_path, "case")
    
    if case.get("case_id") != case_id:
        raise ValueError(f"Internal case_id {case.get('case_id')} does not match filename {case_id}")

    facts_ref = case["inputs"]["server_facts_ref"]
    exp_ref = case["inputs"]["expectation_ref"]
    ev_ref = case["inputs"]["service_evidence_ref"]
    ass_ref = case["expected_assessment_ref"]

    facts_path = resolve_safe_reference(repo_root, facts_ref["path"], "server-facts", case_id, "server_facts_ref")
    exp_path = resolve_safe_reference(repo_root, exp_ref["path"], "heimserver-service-expectations", case_id, "expectation_ref")
    ev_path = resolve_safe_reference(repo_root, ev_ref["path"], "heimserver-service-evidence", case_id, "service_evidence_ref")
    ass_path = resolve_safe_reference(repo_root, ass_ref["path"], "heimserver-service-gate-assessments", case_id, "expected_assessment_ref")

    if sha256_file(facts_path) != facts_ref["sha256"]:
        raise ValueError(f"{case_id}: Hash mismatch for server_facts_ref {facts_path}")
    if sha256_file(exp_path) != exp_ref["sha256"]:
        raise ValueError(f"{case_id}: Hash mismatch for expectation_ref {exp_path}")
    if sha256_file(ev_path) != ev_ref["sha256"]:
        raise ValueError(f"{case_id}: Hash mismatch for service_evidence_ref {ev_path}")
    if sha256_file(ass_path) != ass_ref["sha256"]:
        raise ValueError(f"{case_id}: Hash mismatch for expected_assessment_ref {ass_path}")

    ass_schema_path = repo_root / "schemas" / "heimserver-service-gate-assessment.v1.schema.json"
    ass_schema = load_json_file(ass_schema_path)
    master_enum = ass_schema["properties"]["reason_codes"]["items"]["enum"]

    facts = load_and_validate_json(facts_path, repo_root / "schemas" / "server-facts.v1.schema.json", "server_facts")
    exp = load_and_validate_json(exp_path, repo_root / "schemas" / "heimserver-service-expectation.v1.schema.json", "expectation")
    ev = load_and_validate_json(ev_path, repo_root / "schemas" / "heimserver-service-evidence.v1.schema.json", "service_evidence")
    ass = load_and_validate_json(ass_path, ass_schema_path, "assessment")

    validate_derivation(case_id, case, facts, exp, ev, ass, master_enum)

def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    
    try:
        case_paths = discover_case_paths(repo_root)
        validate_case_inventory(case_paths)
        
        for case_path in case_paths:
            validate_case_file(case_path, repo_root)
            
        print(f"validated {len(case_paths)} heimserver service gate derivation case(s)")
        return 0
    except Exception as e:
        print(f"Validation failed:\n{e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
