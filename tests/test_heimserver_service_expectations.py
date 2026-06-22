import hashlib
from pathlib import Path

import pytest

from scripts.validate_examples import (
    SCHEMA_MAP,
    load_json,
    validate_instance,
)

EXAMPLES_DIR = Path("examples/heimserver-service-expectations")
MINIMAL_EXAMPLE = EXAMPLES_DIR / "minimal-tailscale.json"
SCHEMA_PATH = SCHEMA_MAP["heimserver-service-expectations"]
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))

ASSESSMENTS_DIR = Path("examples/heimserver-service-gate-assessments")


def assert_invalid(instance: dict, schema: dict, source: str = "test") -> None:
    with pytest.raises(Exception):
        validate_instance(instance, schema, source)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_validator_knows_the_expectation_contract():
    """The validator (SCHEMA_MAP) must wire the expectation directory to its schema."""
    assert SCHEMA_PATH.name == "heimserver-service-expectation.v1.schema.json"
    assert SCHEMA_PATH.exists()


@pytest.mark.parametrize("example_file", EXAMPLE_FILES, ids=lambda path: path.name)
def test_expectation_examples_validate(example_file):
    """Every expectation example must validate against the expectation schema."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(example_file)
    validate_instance(instance, schema, str(example_file))


def test_schema_version_const_enforced():
    """schema_version is the dominant repo convention; the const must hold."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    assert instance["schema_version"] == "heimserver-service-expectation.v1"

    instance["schema_version"] = "1"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_scope_must_be_artifact_derived():
    """scope is locked to the const 'artifact-derived' — never a live scope."""
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    assert instance["scope"] == "artifact-derived"

    instance["scope"] = "live"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


@pytest.mark.parametrize(
    "missing", ["schema_version", "host", "scope", "expected_services"]
)
def test_missing_required_top_level_field_rejected(missing):
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    del instance[missing]
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


@pytest.mark.parametrize("missing", ["service_name", "expected_role"])
def test_missing_required_service_field_rejected(missing):
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    del instance["expected_services"][0][missing]
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_additional_top_level_property_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["live_status"] = "running"
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_additional_service_property_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["expected_services"][0]["active"] = True
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_empty_service_name_rejected():
    schema = load_json(SCHEMA_PATH)
    instance = load_json(MINIMAL_EXAMPLE)
    instance["expected_services"][0]["service_name"] = ""
    assert_invalid(instance, schema, str(MINIMAL_EXAMPLE))


def test_contract_stays_a_pure_input():
    """The expectation must remain a static input: no runtime/evidence/result fields.

    Guards the Phase 11F-D boundary — the expectation contract is the producer's
    preimage, not a place to smuggle live state.
    """
    schema = load_json(SCHEMA_PATH)
    props = set(schema["properties"])
    assert props == {"schema_version", "host", "scope", "expected_services"}

    forbidden = {
        "status",
        "evaluated_services",
        "reason_codes",
        "evidence",
        "freshness",
        "does_not_prove",
        "live_service_running",
        "service_reachable",
        "runtime_correctness",
    }
    assert not (props & forbidden)


def test_shape_assessment_expectation_refs_match_shared_example():
    """Current shape fixtures share one expectation reference.
    This checks path/hash integrity only and does not assert that each verdict
    is derivable from the shared expectation artifact.
    """
    actual = sha256_file(MINIMAL_EXAMPLE)
    assessment_files = [f for f in sorted(ASSESSMENTS_DIR.glob("*.json")) if not f.name.startswith("golden-")]
    assert assessment_files

    for assessment_file in assessment_files:
        assessment = load_json(assessment_file)
        ref = assessment["inputs"]["expectation_ref"]
        assert ref["path"] == str(MINIMAL_EXAMPLE), (
            f"{assessment_file.name}: unexpected expectation_ref.path {ref['path']}"
        )
        assert ref["sha256"] == actual, (
            f"{assessment_file.name}: expectation_ref.sha256 does not match {MINIMAL_EXAMPLE}"
        )
