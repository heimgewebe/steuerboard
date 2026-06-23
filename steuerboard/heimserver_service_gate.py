import copy
from typing import Any
from collections.abc import Mapping

DOES_NOT_PROVE = (
    "live_service_running",
    "service_reachable",
    "runtime_correctness",
    "service_role_fulfilled",
)

REASON_CODES_ORDER = (
    "service_gate_artifact_only_scope",
    "service_gate_artifacts_missing",
    "service_gate_artifacts_stale",
    "service_gate_expectation_missing",
    "service_gate_freshness_unknown",
    "service_gate_input_schema_invalid",
    "service_gate_no_service_evidence",
    "service_gate_service_evidence_mismatch",
    "service_gate_subject_mismatch",
    "service_gate_subject_unknown",
)

def _sort_reason_codes(reason_codes: list[str]) -> list[str]:
    deduped = []
    for r in reason_codes:
        if r not in deduped:
            deduped.append(r)

    for r in deduped:
        if r not in REASON_CODES_ORDER:
            raise ValueError(f"Unknown reason code: {r!r}")

    return sorted(deduped, key=lambda x: REASON_CODES_ORDER.index(x))


def derive_heimserver_service_gate_assessment(
    *,
    server_facts: Mapping[str, Any],
    expectation: Mapping[str, Any],
    service_evidence: Mapping[str, Any],
    input_refs: Mapping[str, Any],
) -> dict[str, Any]:

    # 1. Input Validation
    REQUIRED_INPUT_REFS = (
        "server_facts_ref",
        "expectation_ref",
        "service_evidence_ref",
    )
    if set(input_refs.keys()) != set(REQUIRED_INPUT_REFS):
        raise ValueError("input_refs must contain exactly: " + ", ".join(REQUIRED_INPUT_REFS))

    expected_services = expectation.get("expected_services", [])
    seen_expected = set()
    for s in expected_services:
        name = s["service_name"]
        if name in seen_expected:
            raise ValueError(f"duplicate service_name {name!r} in expectation.expected_services")
        seen_expected.add(name)

    evidence_services = service_evidence.get("services", [])
    seen_evidence = set()
    for s in evidence_services:
        name = s["service_name"]
        if name in seen_evidence:
            raise ValueError(f"duplicate service_name {name!r} in service_evidence.services")
        seen_evidence.add(name)

        e_status = s["evidence_status"]
        if e_status not in ("present", "missing", "unknown", "mismatch"):
            raise ValueError(f"Unknown evidence_status {e_status!r}")

    freshness_status = service_evidence.get("freshness_status")
    if freshness_status not in ("fresh", "stale", "unknown"):
        raise ValueError(f"Unknown freshness_status {freshness_status!r}")

    # 2. Extract hosts
    facts_host = server_facts["host"]["hostname"]
    exp_host = expectation["host"]
    ev_host = service_evidence["host"]

    # Initialize assessment frame
    assessment = {
        "schema_version": "1",
        "kind": "heimserver-service-gate-assessment",
        "subject": {
            "host": copy.deepcopy(exp_host),
            "scope": "artifact-derived",
        },
        "inputs": copy.deepcopy(dict(input_refs)),
        "freshness": {
            "status": copy.deepcopy(freshness_status),
            "observed_at": copy.deepcopy(service_evidence["observed_at"]),
        },
        "does_not_prove": list(DOES_NOT_PROVE),
    }

    # 3. Host-Mismatch Rules
    if not (facts_host == exp_host == ev_host):
        assessment["status"] = "blocked"
        assessment["expected_services"] = copy.deepcopy(expected_services)
        assessment["evaluated_services"] = []
        assessment["reason_codes"] = ["service_gate_subject_mismatch"]
        assessment["evidence"] = [
            f"Host identity mismatch: server_facts='{facts_host}', expectation='{exp_host}', service_evidence='{ev_host}'."
        ]
        return assessment

    # 4. Empty Expectation Rule
    if not expected_services:
        assessment["status"] = "inconclusive"
        assessment["expected_services"] = []
        assessment["evaluated_services"] = []
        assessment["reason_codes"] = ["service_gate_expectation_missing"]
        assessment["evidence"] = ["No expected services were declared."]
        return assessment

    # 5. Normal Processing (Service Join)
    ev_map = {s["service_name"]: s for s in evidence_services}
    derived_evaluated_services = []

    has_blocked = False
    has_inconclusive = False

    for exp_s in expected_services:
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
            s_ev_text = copy.deepcopy(ev_s.get("evidence", []))

            if e_status == "mismatch":
                s_status = "blocked"
                s_reasons = ["service_gate_service_evidence_mismatch"]
            elif e_status in ("missing", "unknown"):
                s_status = "inconclusive"
                s_reasons = ["service_gate_no_service_evidence"]
            elif e_status == "present":
                if freshness_status == "fresh":
                    s_status = "passed"
                    s_reasons = ["service_gate_artifact_only_scope"]
                elif freshness_status == "stale":
                    s_status = "inconclusive"
                    s_reasons = ["service_gate_artifacts_stale"]
                elif freshness_status == "unknown":
                    s_status = "inconclusive"
                    s_reasons = ["service_gate_freshness_unknown"]
            else:
                raise ValueError(f"Unknown evidence_status {e_status!r}")

        derived_evaluated_services.append({
            "service_name": copy.deepcopy(s_name),
            "expected_role": copy.deepcopy(e_role),
            "status": s_status,
            "reason_codes": s_reasons,
            "evidence": s_ev_text,
        })

        if s_status == "blocked":
            has_blocked = True
        elif s_status == "inconclusive":
            has_inconclusive = True

    # 6. Aggregation
    if has_blocked:
        top_status = "blocked"
    elif has_inconclusive:
        top_status = "inconclusive"
    else:
        top_status = "passed"

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

    derived_reasons = _sort_reason_codes(all_reasons)

    top_level_evidence = [
        text
        for service in derived_evaluated_services
        for text in service["evidence"]
    ]

    assessment["status"] = top_status
    assessment["expected_services"] = copy.deepcopy(expected_services)
    assessment["evaluated_services"] = derived_evaluated_services
    assessment["reason_codes"] = derived_reasons
    assessment["evidence"] = top_level_evidence

    return assessment
