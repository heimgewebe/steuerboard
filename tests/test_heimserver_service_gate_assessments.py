import hashlib
from pathlib import Path

import pytest

from scripts.validate_examples import (
    SCHEMA_MAP,
    ValidationError,
    load_json,
    minimal_validate,
    validate_instance,
)

EXAMPLES_DIR = Path("examples/heimserver-service-gate-assessments")
PASSED_EXAMPLE = EXAMPLES_DIR / "passed.json"
SCHEMA_PATH = SCHEMA_MAP["heimserver-service-gate-assessments"]
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))
MODEL_DOC = Path("docs/heimserver-service-gate-model.md")

def assert_invalid(instance: dict, schema: dict, source: str = "test") -> None:
    with pytest.raises(Exception):
        validate_instance(instance, schema, source)

def assert_minimal_invalid(instance: dict, schema: dict, source: str = "test") -> None:
    with pytest.raises(ValidationError):
        minimal_validate(instance, schema, source)

@pytest.mark.parametrize("example_file", EXAMPLE_FILES, ids=lambda path: path.name)
def test_heimserver_service_gate_assessment_schema_validates_examples(example_file):
    """All existing examples must validate against the schema."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(example_file)
    validate_instance(instance, schema, str(example_file))

def test_invalid_status_rejected():
    """Invalid status values are rejected."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["status"] = "running"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_invalid_reason_code_rejected():
    """Invalid reason codes are rejected."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["reason_codes"] = ["invalid_reason"]
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_does_not_prove_contains_live_service_running():
    """does_not_prove must contain 'live_service_running'."""
    schema = load_json(SCHEMA_PATH)

    for example_file in EXAMPLE_FILES:
        instance = load_json(example_file)
        assert "live_service_running" in instance["does_not_prove"]

    instance = load_json(PASSED_EXAMPLE)
    instance["does_not_prove"] = ["service_reachable"]

    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_kind_must_be_correct():
    """The kind must be exactly 'heimserver-service-gate-assessment'."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["kind"] = "runbook"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_artifact_derived_scope_is_visible():
    """The artifact-derived scope must be explicit."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    assert instance["subject"]["scope"] == "artifact-derived"

    instance["subject"]["scope"] = "live"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

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


def test_doc_preserves_producer_preimage_boundary():
    """Guard the documented Phase 11F-C producer-preimage boundary.

    test_no_runbook_kind_added already locks the code/schema side (no runbook kind in
    SUPPORTED_RUNBOOK_KINDS, runbook-plan.v1, or runbook-result.v1). This test locks the
    documentation side: the model doc must keep naming both declared inputs, keep stating
    what `passed` does not prove, and keep listing the forbidden live-runtime mechanisms,
    so the contract fence cannot be silently eroded by a doc edit.
    """
    doc = MODEL_DOC.read_text(encoding="utf-8")

    # The Phase 11F-C boundary section and its artifact-derived framing must be present.
    assert "Phase 11F-C" in doc
    assert "Producer Preimage Boundary" in doc
    assert "artifact-derived" in doc

    # The field lineage must name both declared inputs.
    for declared_input in ("server_facts_ref", "expectation_ref"):
        assert declared_input in doc, f"lineage missing declared input: {declared_input}"

    # `passed` must keep disclaiming the three live-truth properties.
    for protection in ("live_service_running", "service_reachable", "runtime_correctness"):
        assert protection in doc, f"does_not_prove protection missing from doc: {protection}"

    # The forbidden live-runtime mechanisms must remain documented.
    for forbidden in ("systemctl", "SSH", "Tailscale", "subprocess", "network probe", "Stage-D", "CLI"):
        assert forbidden in doc, f"forbidden-list entry missing from doc: {forbidden}"


def test_reason_code_subsets_partition_master_enum():
    """The per-status reason-code subsets must form a complete, disjoint partition of
    the master enum, and the evaluated-service enum must mirror the master enum.

    This locks the contract's core design (every status owns a distinct set of reason
    codes) and guards the two inlined reason-code enum copies against silent drift.
    """
    schema = load_json(SCHEMA_PATH)
    master = set(schema["properties"]["reason_codes"]["items"]["enum"])

    subsets: dict[str, set] = {}
    for clause in schema["allOf"]:
        status = clause["if"]["properties"]["status"]["const"]
        subsets[status] = set(clause["then"]["properties"]["reason_codes"]["items"]["enum"])

    # Every declared status owns a reason-code subset.
    assert set(subsets) == set(schema["properties"]["status"]["enum"])

    # Subsets are pairwise disjoint.
    seen: set = set()
    for codes in subsets.values():
        overlap = codes & seen
        assert not overlap, f"reason codes shared across statuses: {sorted(overlap)}"
        seen |= codes

    # The subsets exactly cover the master enum (no orphan or stray codes).
    assert seen == master, f"partition mismatch: {sorted(master ^ seen)}"

    # The evaluated-service reason-code enum must stay identical to the master enum.
    evaluated_enum = set(
        schema["properties"]["evaluated_services"]["items"]["properties"]["reason_codes"][
            "items"
        ]["enum"]
    )
    assert evaluated_enum == master


def test_invalid_sha256_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["inputs"]["server_facts_ref"]["sha256"] = "abc"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_service_evidence_ref_required():
    """Phase 11F-F: every assessment must declare which evidence artifact it derives from."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    assert instance["inputs"]["service_evidence_ref"]["path"] == (
        "examples/heimserver-service-evidence/minimal-artifact-only.json"
    )
    del instance["inputs"]["service_evidence_ref"]
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_invalid_service_evidence_sha256_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["inputs"]["service_evidence_ref"]["sha256"] = "abc"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_inputs_reject_unknown_ref():
    """Boundary: inputs is closed; no runtime/probe/executor ref can be smuggled in."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["inputs"]["service_probe_ref"] = {
        "path": "examples/whatever.json",
        "sha256": "0" * 64,
    }
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_assessment_rejects_runtime_or_executor_fields():
    """Boundary: the assessment top level is closed; no CLI/Stage-D/runtime field fits."""
    schema = load_json(SCHEMA_PATH)
    for field in ("executor", "command", "stage_d_action", "live_status"):
        instance = load_json(PASSED_EXAMPLE)
        instance[field] = "x"
        assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_empty_reason_codes_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["reason_codes"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_empty_service_reason_codes_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"][0]["reason_codes"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_empty_evidence_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evidence"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_supports_contains():
    schema = {"type": "array", "contains": {"const": "live_service_running"}}
    minimal_validate(["service_reachable", "live_service_running"], schema, "test")

def test_minimal_validate_rejects_missing_contains_match():
    schema = {"type": "array", "contains": {"const": "live_service_running"}}
    with pytest.raises(ValidationError):
        minimal_validate(["service_reachable"], schema, "test")

def test_minimal_validate_rejects_non_array_for_contains():
    schema = {"contains": {"const": "live_service_running"}}
    with pytest.raises(ValidationError, match="expected array for array validation keywords"):
        minimal_validate("not-an-array", schema, "test")

def test_minimal_validate_rejects_non_array_for_min_items():
    schema = {"minItems": 1}
    with pytest.raises(ValidationError, match="expected array for array validation keywords"):
        minimal_validate("not-an-array", schema, "test")

def test_passed_with_empty_expected_services_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["expected_services"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_passed_with_empty_evaluated_services_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"] = []
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_passed_with_stale_freshness_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["freshness"]["status"] = "stale"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_passed_with_blocked_reason_code_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["reason_codes"] = ["service_gate_artifacts_missing"]
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_passed_with_blocked_evaluated_service_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"][0]["status"] = "blocked"
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_supports_allof_and_if_then():
    schema = {
        "allOf": [
            {
                "if": {
                    "properties": {
                        "status": {"const": "passed"}
                    },
                    "required": ["status"]
                },
                "then": {
                    "properties": {
                        "freshness": {
                            "properties": {
                                "status": {"const": "fresh"}
                            },
                            "required": ["status"]
                        }
                    },
                    "required": ["freshness"]
                },
            }
        ]
    }

    minimal_validate(
        {"status": "passed", "freshness": {"status": "fresh"}},
        schema,
        "test",
    )

    with pytest.raises(ValidationError):
        minimal_validate(
            {"status": "passed", "freshness": {"status": "stale"}},
            schema,
            "test",
        )

    minimal_validate(
        {"status": "blocked", "freshness": {"status": "stale"}},
        schema,
        "test",
    )

def test_passed_with_blocked_evaluated_service_reason_code_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"][0]["reason_codes"] = ["service_gate_service_evidence_mismatch"]
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_rejects_passed_with_stale_freshness_via_conditionals():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["freshness"]["status"] = "stale"
    assert_minimal_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_rejects_passed_with_blocked_reason_code_via_conditionals():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["reason_codes"] = ["service_gate_artifacts_missing"]
    assert_minimal_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_rejects_passed_with_empty_expected_services_via_conditionals():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["expected_services"] = []
    assert_minimal_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_rejects_passed_with_blocked_evaluated_service_via_conditionals():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"][0]["status"] = "blocked"
    assert_minimal_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_minimal_validate_rejects_passed_with_blocked_evaluated_service_reason_code_via_conditionals():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["evaluated_services"][0]["reason_codes"] = ["service_gate_service_evidence_mismatch"]
    assert_minimal_invalid(instance, schema, str(PASSED_EXAMPLE))

def test_invalid_does_not_prove_value_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(PASSED_EXAMPLE)
    instance["does_not_prove"].append("bananen")
    assert_invalid(instance, schema, str(PASSED_EXAMPLE))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

@pytest.mark.parametrize("example_file", EXAMPLE_FILES, ids=lambda path: path.name)
def test_example_input_hashes_match_referenced_artifacts(example_file):
    """Every example's declared input hashes must match the referenced artifacts on disk.

    All examples reference the same server-facts, expectation, and service-evidence
    artifacts, so an artifact edit that updates only one example's hash would otherwise
    go unnoticed.
    """
    instance = load_json(example_file)
    for ref_name in ("server_facts_ref", "expectation_ref", "service_evidence_ref"):
        ref = instance["inputs"][ref_name]
        assert sha256_file(Path(ref["path"])) == ref["sha256"], (
            f"{example_file.name}: {ref_name} sha256 does not match {ref['path']}"
        )
