import copy
import ast
import pytest
from pathlib import Path

from steuerboard.heimserver_service_gate import (
    derive_heimserver_service_gate_assessment,
    REASON_CODES_ORDER,
    DOES_NOT_PROVE,
)

# Reference Oracle for validation
from scripts.validate_heimserver_service_gate_derivation_cases import (
    validate_derivation,
    CANONICAL_CASES,
    load_json_file,
    resolve_safe_reference,
)
from scripts.validate_examples import validate_instance
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSESSMENT_SCHEMA_PATH = REPO_ROOT / "schemas" / "heimserver-service-gate-assessment.v1.schema.json"

def get_master_enum():
    schema = load_json_file(ASSESSMENT_SCHEMA_PATH)
    return schema["properties"]["reason_codes"]["items"]["enum"]

def get_master_does_not_prove():
    schema = load_json_file(ASSESSMENT_SCHEMA_PATH)
    prefix_items = schema["properties"]["does_not_prove"]["prefixItems"]
    return [item["const"] for item in prefix_items]

def load_case_artifacts(case_id: str):
    case_path = REPO_ROOT / "examples" / "heimserver-service-gate-derivation-cases" / f"{case_id}.json"
    case = load_json_file(case_path)

    facts_ref = case["inputs"]["server_facts_ref"]
    exp_ref = case["inputs"]["expectation_ref"]
    ev_ref = case["inputs"]["service_evidence_ref"]
    ass_ref = case["expected_assessment_ref"]

    facts_path = resolve_safe_reference(REPO_ROOT, facts_ref["path"], "server-facts", case_id, "server_facts_ref")
    exp_path = resolve_safe_reference(REPO_ROOT, exp_ref["path"], "heimserver-service-expectations", case_id, "expectation_ref")
    ev_path = resolve_safe_reference(REPO_ROOT, ev_ref["path"], "heimserver-service-evidence", case_id, "service_evidence_ref")
    ass_path = resolve_safe_reference(REPO_ROOT, ass_ref["path"], "heimserver-service-gate-assessments", case_id, "expected_assessment_ref")

    server_facts = load_json_file(facts_path)
    expectation = load_json_file(exp_path)
    service_evidence = load_json_file(ev_path)
    expected_assessment = load_json_file(ass_path)

    return case, server_facts, expectation, service_evidence, expected_assessment

def set_evidence_status(
    service: dict[str, Any],
    status: str,
    *,
    stale: bool = False,
) -> None:
    mapping = {
        "present": [
            "service_evidence_artifact_only_scope",
            "service_evidence_present_in_artifacts",
        ],
        "missing": [
            "service_evidence_artifact_only_scope",
            "service_evidence_absent_from_artifacts",
        ],
        "unknown": [
            "service_evidence_artifact_only_scope",
            "service_evidence_unknown",
        ],
        "mismatch": [
            "service_evidence_artifact_only_scope",
            "service_evidence_artifact_mismatch",
        ],
    }

    service["evidence_status"] = status
    service["reason_codes"] = mapping[status]

    if stale:
        service["reason_codes"].append("service_evidence_artifact_stale")

def validate_evidence(ev: dict[str, Any]) -> None:
    schema_path = REPO_ROOT / "schemas" / "heimserver-service-evidence.v1.schema.json"
    schema = load_json_file(schema_path)
    validate_instance(ev, schema, Path("virtual.json"))

@pytest.mark.parametrize("case_id", CANONICAL_CASES)
def test_golden_case_reproduction(case_id):
    case, server_facts, expectation, service_evidence, expected_assessment = load_case_artifacts(case_id)

    # Execute Producer
    produced = derive_heimserver_service_gate_assessment(
        server_facts=server_facts,
        expectation=expectation,
        service_evidence=service_evidence,
        input_refs=case["inputs"],
    )

    # 1. Exact Golden Comparison
    assert produced == expected_assessment

    # 2. Schema Validation
    schema = load_json_file(ASSESSMENT_SCHEMA_PATH)
    validate_instance(produced, schema, Path(f"virtual-{case_id}.json"))

    # 3. Oracle Validation
    validate_derivation(
        case_id=case_id,
        case=case,
        server_facts=server_facts,
        expectation=expectation,
        service_evidence=service_evidence,
        assessment=produced,
        master_enum=get_master_enum()
    )

def test_determinism_and_immutability():
    case_id = CANONICAL_CASES[0]
    case, server_facts, expectation, service_evidence, _ = load_case_artifacts(case_id)

    facts_copy = copy.deepcopy(server_facts)
    exp_copy = copy.deepcopy(expectation)
    ev_copy = copy.deepcopy(service_evidence)
    inputs_copy = copy.deepcopy(case["inputs"])

    first = derive_heimserver_service_gate_assessment(
        server_facts=server_facts,
        expectation=expectation,
        service_evidence=service_evidence,
        input_refs=case["inputs"],
    )

    second = derive_heimserver_service_gate_assessment(
        server_facts=server_facts,
        expectation=expectation,
        service_evidence=service_evidence,
        input_refs=case["inputs"],
    )

    assert first == second

    assert server_facts == facts_copy
    assert expectation == exp_copy
    assert service_evidence == ev_copy
    assert case["inputs"] == inputs_copy

    # Anti-alias tests: produced -> input
    if first.get("expected_services"):
        first["expected_services"][0]["expected_role"] = "mutated-role"
        assert expectation["expected_services"][0]["expected_role"] != "mutated-role"

    first["inputs"]["server_facts_ref"]["path"] = "mutated-path"
    assert case["inputs"]["server_facts_ref"]["path"] != "mutated-path"

    first["evaluated_services"][0]["evidence"][0] = "changed"
    assert service_evidence == ev_copy

    # Anti-alias tests: input -> produced
    expectation["host"] = "mutated-host"
    assert second["subject"]["host"] != "mutated-host"

    service_evidence["services"][0]["evidence"][0] = "changed-input"
    assert second["evaluated_services"][0]["evidence"] != ["changed-input"]


def test_schema_drift():
    master_enum = get_master_enum()
    assert list(REASON_CODES_ORDER) == master_enum

    master_dnp = get_master_does_not_prove()
    assert list(DOES_NOT_PROVE) == master_dnp

def test_purity_guard_ast():
    module_path = REPO_ROOT / "steuerboard" / "heimserver_service_gate.py"
    with open(module_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden_names = {
        "pathlib", "subprocess", "socket", "requests", "urllib",
        "datetime", "time", "random", "os", "open", "systemctl", "Path"
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in forbidden_names:
                    pytest.fail(f"Forbidden import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split('.')[0] in forbidden_names:
                pytest.fail(f"Forbidden import from: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in forbidden_names:
                    pytest.fail(f"Forbidden call: {node.func.id}")
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in forbidden_names:
                    pytest.fail(f"Forbidden method call: {node.func.attr}")


def test_negative_against_oracle():
    case_id = "golden-passed-single-service-fresh"
    case, server_facts, expectation, service_evidence, _ = load_case_artifacts(case_id)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=server_facts,
        expectation=expectation,
        service_evidence=service_evidence,
        input_refs=case["inputs"],
    )

    # Mutate to break consistency
    produced["status"] = "blocked"
    produced["reason_codes"] = ["service_gate_artifacts_missing"]

    with pytest.raises(ValueError):
        validate_derivation(
            case_id=case_id,
            case=case,
            server_facts=server_facts,
            expectation=expectation,
            service_evidence=service_evidence,
            assessment=produced,
            master_enum=get_master_enum()
        )

# Property Tests (Specific Invariants)
def get_base_inputs():
    return load_case_artifacts("golden-passed-single-service-fresh")[1:4] + (load_case_artifacts("golden-passed-single-service-fresh")[0]["inputs"],)

def test_host_mismatch_precedence_over_empty_expectation():
    facts, exp, ev, refs = get_base_inputs()
    facts["host"]["hostname"] = "host-a"
    exp["host"] = "host-b"
    ev["host"] = "host-c"
    exp["expected_services"] = []

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )

    assert produced["status"] == "blocked"
    assert produced["reason_codes"] == ["service_gate_subject_mismatch"]
    assert "Host identity mismatch" in produced["evidence"][0]

def test_no_whitespace_normalization_host():
    facts, exp, ev, refs = get_base_inputs()
    # trailing space on one
    exp["host"] = facts["host"]["hostname"] + " "
    ev["host"] = facts["host"]["hostname"]

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    assert produced["status"] == "blocked"

def test_no_case_normalization_host():
    facts, exp, ev, refs = get_base_inputs()
    exp["host"] = facts["host"]["hostname"].upper()
    ev["host"] = facts["host"]["hostname"]

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    assert produced["status"] == "blocked"

def test_extra_evidence_ignored():
    facts, exp, ev, refs = get_base_inputs()
    extra_service = {
        "service_name": "ghost-service",
        "evidence": ["ghost text"]
    }
    set_evidence_status(extra_service, "present")
    ev["services"].append(extra_service)
    validate_evidence(ev)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )

    eval_names = [s["service_name"] for s in produced["evaluated_services"]]
    assert "ghost-service" not in eval_names
    assert "ghost text" not in produced["evidence"]

def test_no_match_fixed_text():
    facts, exp, ev, refs = get_base_inputs()
    exp["expected_services"].append({
        "service_name": "missing-service",
        "expected_role": "role"
    })

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    missing_eval = [s for s in produced["evaluated_services"] if s["service_name"] == "missing-service"][0]
    assert missing_eval["status"] == "inconclusive"
    assert missing_eval["evidence"] == ["No matching artifact-derived evidence found for expected service 'missing-service'."]

def test_matching_unknown_keeps_evidence_text():
    facts, exp, ev, refs = get_base_inputs()
    set_evidence_status(ev["services"][0], "unknown")
    ev["services"][0]["evidence"] = ["Custom unknown text"]
    validate_evidence(ev)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    assert produced["evaluated_services"][0]["status"] == "inconclusive"
    assert produced["evaluated_services"][0]["evidence"] == ["Custom unknown text"]

def test_matching_missing_keeps_evidence_text():
    facts, exp, ev, refs = get_base_inputs()
    set_evidence_status(ev["services"][0], "missing")
    ev["services"][0]["evidence"] = ["Custom missing text"]
    validate_evidence(ev)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    assert produced["evaluated_services"][0]["status"] == "inconclusive"
    assert produced["evaluated_services"][0]["evidence"] == ["Custom missing text"]

def test_mismatch_over_freshness():
    facts, exp, ev, refs = get_base_inputs()
    set_evidence_status(ev["services"][0], "mismatch")
    ev["freshness_status"] = "fresh"  # fresh but mismatch
    validate_evidence(ev)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    assert produced["evaluated_services"][0]["status"] == "blocked"
    assert produced["status"] == "blocked"

def test_blocked_beats_inconclusive():
    facts, exp, ev, refs = get_base_inputs()
    # Add an inconclusive service
    exp["expected_services"].append({"service_name": "svc2", "expected_role": "r"})
    inconclusive_svc = {"service_name": "svc2", "evidence": ["dummy"]}
    set_evidence_status(inconclusive_svc, "missing")
    ev["services"].append(inconclusive_svc)

    # Make the first one blocked
    set_evidence_status(ev["services"][0], "mismatch")
    validate_evidence(ev)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    assert produced["status"] == "blocked"

def test_inconclusive_beats_passed():
    facts, exp, ev, refs = get_base_inputs()
    # First is passed
    # Add an inconclusive
    exp["expected_services"].append({"service_name": "svc2", "expected_role": "r"})
    inconclusive_svc = {"service_name": "svc2", "evidence": ["dummy"]}
    set_evidence_status(inconclusive_svc, "missing")
    ev["services"].append(inconclusive_svc)
    validate_evidence(ev)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    assert produced["status"] == "inconclusive"

def test_reason_deduplication_and_order():
    facts, exp, ev, refs = get_base_inputs()
    # Need two services with same reason to test dedup, and another to test ordering
    exp["expected_services"].append({"service_name": "svc2", "expected_role": "r"})
    exp["expected_services"].append({"service_name": "svc3", "expected_role": "r"})

    # First is stale
    set_evidence_status(ev["services"][0], "present", stale=True)
    ev["freshness_status"] = "stale"

    # Second is also stale -> tests deduplication
    svc2 = {"service_name": "svc2", "evidence": ["dummy"]}
    set_evidence_status(svc2, "present", stale=True)
    ev["services"].append(svc2)

    # Third is missing -> tests ordering
    svc3 = {"service_name": "svc3", "evidence": ["dummy"]}
    set_evidence_status(svc3, "missing")
    ev["services"].append(svc3)

    validate_evidence(ev)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    # The output should exactly have both service_gate_artifacts_stale and service_gate_no_service_evidence
    expected_reasons = ["service_gate_artifacts_stale", "service_gate_no_service_evidence"]
    assert produced["reason_codes"] == expected_reasons
    assert produced["reason_codes"].count("service_gate_artifacts_stale") == 1

def test_top_level_evidence_contains_all_services():
    facts, exp, ev, refs = get_base_inputs()
    exp["expected_services"].append({"service_name": "svc2", "expected_role": "r"})
    svc2 = {"service_name": "svc2", "evidence": ["text2"]}
    set_evidence_status(svc2, "present")
    ev["services"].append(svc2)
    ev["services"][0]["evidence"] = ["text1"]
    validate_evidence(ev)

    produced = derive_heimserver_service_gate_assessment(
        server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
    )
    assert produced["evidence"] == ["text1", "text2"]

def test_duplicate_expectation_service():
    facts, exp, ev, refs = get_base_inputs()
    exp["expected_services"].append(exp["expected_services"][0].copy())
    with pytest.raises(ValueError, match="duplicate service_name"):
        derive_heimserver_service_gate_assessment(
            server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
        )

def test_duplicate_evidence_service():
    facts, exp, ev, refs = get_base_inputs()
    ev["services"].append(ev["services"][0].copy())
    with pytest.raises(ValueError, match="duplicate service_name"):
        derive_heimserver_service_gate_assessment(
            server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
        )

def test_unknown_evidence_status():
    facts, exp, ev, refs = get_base_inputs()
    ev["services"][0]["evidence_status"] = "bizarre"
    with pytest.raises(ValueError, match="Unknown evidence_status"):
        derive_heimserver_service_gate_assessment(
            server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
        )

def test_unknown_freshness_status():
    facts, exp, ev, refs = get_base_inputs()
    ev["freshness_status"] = "bizarre"
    with pytest.raises(ValueError, match="Unknown freshness_status"):
        derive_heimserver_service_gate_assessment(
            server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
        )

def test_missing_input_refs():
    facts, exp, ev, refs = get_base_inputs()
    del refs["expectation_ref"]
    
    with pytest.raises(ValueError) as exc_info:
        derive_heimserver_service_gate_assessment(
            server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
        )
    
    assert str(exc_info.value) == (
        "input_refs must contain exactly: "
        "server_facts_ref, expectation_ref, service_evidence_ref"
    )

def test_extra_input_refs():
    facts, exp, ev, refs = get_base_inputs()
    refs["extra_ref"] = {"path": "extra"}
    
    with pytest.raises(ValueError) as exc_info:
        derive_heimserver_service_gate_assessment(
            server_facts=facts, expectation=exp, service_evidence=ev, input_refs=refs
        )
    
    assert str(exc_info.value) == (
        "input_refs must contain exactly: "
        "server_facts_ref, expectation_ref, service_evidence_ref"
    )
