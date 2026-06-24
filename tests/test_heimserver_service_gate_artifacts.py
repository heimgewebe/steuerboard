"""Tests for the Phase 11F-I safe artifact input adapter.

These tests prove that the adapter
``steuerboard.heimserver_service_gate_artifacts.derive_heimserver_service_gate_assessment_from_refs``
loads explicit, repository-relative artifact references safely, binds raw bytes
to their declared SHA-256, decodes strict UTF-8/JSON, validates payloads against
the canonical Draft 2020-12 schemas, calls the unchanged producer once, and
validates the producer's assessment — all with a deterministic failure priority.

The independent reference oracle and the existing producer guard are not touched.
"""

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from jsonschema import Draft202012Validator

from steuerboard import heimserver_service_gate_artifacts as adapter_module
from steuerboard.heimserver_service_gate_artifacts import (
    HeimserverServiceGateArtifactError,
    derive_heimserver_service_gate_assessment_from_refs,
)
from steuerboard.heimserver_service_gate import (
    derive_heimserver_service_gate_assessment,
)
from scripts.validate_heimserver_service_gate_derivation_cases import CANONICAL_CASES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
CASES_DIR = REPO_ROOT / "examples" / "heimserver-service-gate-derivation-cases"
ASSESSMENT_SCHEMA_PATH = SCHEMAS_DIR / "heimserver-service-gate-assessment.v1.schema.json"
EVIDENCE_SCHEMA_PATH = SCHEMAS_DIR / "heimserver-service-evidence.v1.schema.json"

BASE_CASE_ID = "golden-passed-single-service-fresh"

# A 64-character lowercase-hex string that is structurally valid for the
# ``sha256`` pattern but never matches real artifact bytes.
WRONG_SHA256 = "0" * 64


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_case(case_id: str) -> dict:
    return _read_json(CASES_DIR / f"{case_id}.json")


def load_expected_assessment(case: dict) -> dict:
    return _read_json(REPO_ROOT / case["expected_assessment_ref"]["path"])


def direct_producer_for_case(case: dict) -> dict:
    inputs = case["inputs"]
    facts = _read_json(REPO_ROOT / inputs["server_facts_ref"]["path"])
    exp = _read_json(REPO_ROOT / inputs["expectation_ref"]["path"])
    ev = _read_json(REPO_ROOT / inputs["service_evidence_ref"]["path"])
    return derive_heimserver_service_gate_assessment(
        server_facts=facts,
        expectation=exp,
        service_evidence=ev,
        input_refs=inputs,
    )


def base_payloads() -> tuple[dict, dict, dict]:
    case = load_case(BASE_CASE_ID)
    inputs = case["inputs"]
    facts = _read_json(REPO_ROOT / inputs["server_facts_ref"]["path"])
    exp = _read_json(REPO_ROOT / inputs["expectation_ref"]["path"])
    ev = _read_json(REPO_ROOT / inputs["service_evidence_ref"]["path"])
    return facts, exp, ev


def _encode(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def write_artifact(root: Path, rel: str, payload=None, *, raw_bytes: bytes = None):
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if raw_bytes is None:
        raw_bytes = _encode(payload)
    target.write_bytes(raw_bytes)
    return rel, hashlib.sha256(raw_bytes).hexdigest()


def build_valid_root(
    root: Path,
    *,
    facts_bytes: bytes = None,
    exp_bytes: bytes = None,
    ev_bytes: bytes = None,
) -> dict:
    """Materialise the three input artifacts under ``root`` and return input_refs."""
    facts, exp, ev = base_payloads()
    refs: dict = {}
    rel, sha = write_artifact(root, "server-facts.json", facts, raw_bytes=facts_bytes)
    refs["server_facts_ref"] = {"path": rel, "sha256": sha}
    rel, sha = write_artifact(root, "expectation.json", exp, raw_bytes=exp_bytes)
    refs["expectation_ref"] = {"path": rel, "sha256": sha}
    rel, sha = write_artifact(root, "evidence.json", ev, raw_bytes=ev_bytes)
    refs["service_evidence_ref"] = {"path": rel, "sha256": sha}
    return refs


def make_schemas_dir(tmp_path: Path, *, override: dict = None, drop: set = None) -> Path:
    """Build a private canonical-schemas dir mirroring the real one, with edits."""
    override = override or {}
    drop = drop or set()
    out = tmp_path / "schemas"
    out.mkdir()
    for filename in adapter_module._CANONICAL_SCHEMA_FILENAMES:
        if filename in drop:
            continue
        if filename in override:
            (out / filename).write_bytes(override[filename])
        else:
            (out / filename).write_bytes((SCHEMAS_DIR / filename).read_bytes())
    return out


class ProducerSpy:
    """Records whether the producer was called and the args it received."""

    def __init__(self, *, return_value=None, passthrough: bool = True):
        self.called = False
        self.calls = 0
        self.received_input_refs = None
        self.received_payloads = None
        self._return_value = return_value
        self._passthrough = passthrough

    def __call__(self, *, server_facts, expectation, service_evidence, input_refs):
        self.called = True
        self.calls += 1
        self.received_input_refs = input_refs
        self.received_payloads = (server_facts, expectation, service_evidence)
        if self._return_value is not None:
            return self._return_value
        if self._passthrough:
            return derive_heimserver_service_gate_assessment(
                server_facts=server_facts,
                expectation=expectation,
                service_evidence=service_evidence,
                input_refs=input_refs,
            )
        return {"unexpected": "producer should not have been called"}


def install_spy(monkeypatch, **kwargs) -> ProducerSpy:
    spy = ProducerSpy(**kwargs)
    monkeypatch.setattr(
        adapter_module, "derive_heimserver_service_gate_assessment", spy
    )
    return spy


# --------------------------------------------------------------------------- #
# 14.1 Golden-case integration
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case_id", CANONICAL_CASES)
def test_golden_case_reproduced_via_adapter(case_id):
    case = load_case(case_id)
    expected = load_expected_assessment(case)

    produced = derive_heimserver_service_gate_assessment_from_refs(
        artifact_root=REPO_ROOT,
        input_refs=case["inputs"],
    )

    # 1-4. exact golden equality
    assert produced == expected

    # Adapter result == direct producer call for the same inputs
    assert produced == direct_producer_for_case(case)

    # 5. schema validation of the adapter result
    schema = _read_json(ASSESSMENT_SCHEMA_PATH)
    assert list(Draft202012Validator(schema).iter_errors(produced)) == []


def test_all_canonical_cases_present():
    assert len(CANONICAL_CASES) == 14
    on_disk = {p.stem for p in CASES_DIR.glob("*.json")}
    assert set(CANONICAL_CASES) == on_disk


def test_valid_temp_root_is_passed(tmp_path):
    refs = build_valid_root(tmp_path)
    produced = derive_heimserver_service_gate_assessment_from_refs(
        artifact_root=tmp_path, input_refs=refs
    )
    assert produced["status"] == "passed"
    assert produced["inputs"] == refs


# --------------------------------------------------------------------------- #
# 14.2 Negative: artifact root
# --------------------------------------------------------------------------- #
def test_artifact_root_missing(tmp_path):
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path / "nope", input_refs={}
        )
    assert ei.value.code == "invalid_artifact_root"
    assert ei.value.stage == "artifact_root"


def test_artifact_root_is_a_file(tmp_path):
    file_root = tmp_path / "root-file"
    file_root.write_text("not a dir", encoding="utf-8")
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=file_root, input_refs={}
        )
    assert ei.value.code == "invalid_artifact_root"


def test_artifact_root_not_path_like(tmp_path):
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=12345, input_refs={}
        )
    assert ei.value.code == "invalid_artifact_root"


# --------------------------------------------------------------------------- #
# 14.2 Negative: input_refs shape / contract
# --------------------------------------------------------------------------- #
def test_input_refs_not_a_mapping(tmp_path):
    refs = build_valid_root(tmp_path)  # noqa: F841 - root must be valid first
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=["not", "a", "mapping"]
        )
    assert ei.value.code == "invalid_input_refs"
    assert ei.value.stage == "input_refs"


def test_input_refs_missing_ref(tmp_path):
    refs = build_valid_root(tmp_path)
    del refs["expectation_ref"]
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


def test_input_refs_extra_ref(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["bonus_ref"] = {"path": "evidence.json", "sha256": WRONG_SHA256}
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


def test_input_ref_value_not_a_mapping(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"] = "scalar"
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"
    assert ei.value.input_name == "server_facts_ref"


def test_input_ref_missing_path(tmp_path):
    refs = build_valid_root(tmp_path)
    del refs["server_facts_ref"]["path"]
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


def test_input_ref_missing_sha256(tmp_path):
    refs = build_valid_root(tmp_path)
    del refs["server_facts_ref"]["sha256"]
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


def test_input_ref_extra_field(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"]["note"] = "extra"
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


def test_input_ref_empty_path(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"]["path"] = ""
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


def test_input_ref_sha256_wrong_length(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"]["sha256"] = "0" * 63
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


def test_input_ref_sha256_uppercase(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"]["sha256"] = "A" * 64
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


def test_input_ref_sha256_non_hex(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"]["sha256"] = "g" * 64
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_input_refs"


# --------------------------------------------------------------------------- #
# 14.2 Negative: path
# --------------------------------------------------------------------------- #
def test_path_absolute_rejected(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"] = {"path": "/etc/hostname", "sha256": WRONG_SHA256}
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "unsafe_path"
    assert ei.value.input_name == "server_facts_ref"


def test_path_parent_traversal_rejected(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"] = {"path": "../escape.json", "sha256": WRONG_SHA256}
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "unsafe_path"


def test_path_missing_file(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"] = {"path": "absent.json", "sha256": WRONG_SHA256}
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "file_missing"


def test_path_target_is_directory(tmp_path):
    refs = build_valid_root(tmp_path)
    (tmp_path / "a-directory").mkdir()
    refs["server_facts_ref"] = {"path": "a-directory", "sha256": WRONG_SHA256}
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "not_regular_file"


def test_internal_symlink_accepted(tmp_path):
    facts, exp, ev = base_payloads()
    raw = _encode(facts)
    (tmp_path / "facts-real.json").write_bytes(raw)
    try:
        (tmp_path / "facts-link.json").symlink_to(tmp_path / "facts-real.json")
    except OSError:
        pytest.skip("filesystem does not support symlinks")

    refs = {}
    refs["server_facts_ref"] = {
        "path": "facts-link.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    rel, sha = write_artifact(tmp_path, "expectation.json", exp)
    refs["expectation_ref"] = {"path": rel, "sha256": sha}
    rel, sha = write_artifact(tmp_path, "evidence.json", ev)
    refs["service_evidence_ref"] = {"path": rel, "sha256": sha}

    produced = derive_heimserver_service_gate_assessment_from_refs(
        artifact_root=tmp_path, input_refs=refs
    )
    assert produced["status"] == "passed"


def test_external_symlink_rejected_as_unsafe(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.json"
    raw = _encode(base_payloads()[0])
    outside.write_bytes(raw)
    try:
        (root / "server-facts.json").symlink_to(outside)
    except OSError:
        pytest.skip("filesystem does not support symlinks")

    # Declared hash equals the external file's bytes: unsafe_path must win first,
    # which also proves the producer is never reached.
    refs = {
        "server_facts_ref": {
            "path": "server-facts.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "expectation_ref": {"path": "expectation.json", "sha256": WRONG_SHA256},
        "service_evidence_ref": {"path": "evidence.json", "sha256": WRONG_SHA256},
    }
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=root, input_refs=refs
        )
    assert ei.value.code == "unsafe_path"
    assert ei.value.input_name == "server_facts_ref"


# --------------------------------------------------------------------------- #
# 14.2 Negative: byte and hash
# --------------------------------------------------------------------------- #
def test_wrong_sha256_is_hash_mismatch(tmp_path):
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"]["sha256"] = WRONG_SHA256
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "hash_mismatch"
    assert ei.value.stage == "hash"
    assert ei.value.input_name == "server_facts_ref"


def test_reformatted_json_needs_a_different_hash(tmp_path):
    facts, exp, ev = base_payloads()
    compact = json.dumps(facts, separators=(",", ":")).encode("utf-8")
    indented = (json.dumps(facts, indent=2) + "\n").encode("utf-8")
    assert hashlib.sha256(compact).hexdigest() != hashlib.sha256(indented).hexdigest()

    # On-disk bytes are the compact form; the ref declares the indented hash.
    refs = build_valid_root(tmp_path, facts_bytes=compact)
    refs["server_facts_ref"]["sha256"] = hashlib.sha256(indented).hexdigest()

    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "hash_mismatch"


def test_each_input_file_read_exactly_once(tmp_path, monkeypatch):
    refs = build_valid_root(tmp_path)
    reads: list[Path] = []
    real_read = Path.read_bytes

    def counting_read(self):
        reads.append(Path(self).resolve())
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", counting_read)
    derive_heimserver_service_gate_assessment_from_refs(
        artifact_root=tmp_path, input_refs=refs
    )

    for rel in ("server-facts.json", "expectation.json", "evidence.json"):
        target = (tmp_path / rel).resolve()
        assert reads.count(target) == 1


def test_producer_not_called_on_hash_error(tmp_path, monkeypatch):
    spy = install_spy(monkeypatch, passthrough=False)
    refs = build_valid_root(tmp_path)
    refs["server_facts_ref"]["sha256"] = WRONG_SHA256
    with pytest.raises(HeimserverServiceGateArtifactError):
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert spy.called is False


# --------------------------------------------------------------------------- #
# 14.2 Negative: UTF-8 and JSON
# --------------------------------------------------------------------------- #
def test_invalid_utf8(tmp_path):
    refs = build_valid_root(tmp_path, facts_bytes=b"\xff\xfe\x00not-utf8")
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_utf8"
    assert ei.value.stage == "utf8_decode"


def test_invalid_json(tmp_path):
    refs = build_valid_root(tmp_path, facts_bytes=b"{ this is not json ")
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_json"
    assert ei.value.stage == "json_decode"


def test_duplicate_json_key_rejected(tmp_path):
    refs = build_valid_root(tmp_path, facts_bytes=b'{"a": 1, "a": 2}')
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_json"


def test_nan_rejected(tmp_path):
    refs = build_valid_root(tmp_path, facts_bytes=b'{"x": NaN}')
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_json"


def test_infinity_rejected(tmp_path):
    refs = build_valid_root(tmp_path, facts_bytes=b'{"x": Infinity}')
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "invalid_json"


def test_producer_not_called_on_json_error(tmp_path, monkeypatch):
    spy = install_spy(monkeypatch, passthrough=False)
    refs = build_valid_root(tmp_path, facts_bytes=b'{"x": NaN}')
    with pytest.raises(HeimserverServiceGateArtifactError):
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert spy.called is False


# --------------------------------------------------------------------------- #
# 14.2 Negative: schema
# --------------------------------------------------------------------------- #
def test_invalid_server_facts_schema(tmp_path):
    facts, exp, ev = base_payloads()
    del facts["host"]
    refs = build_valid_root(tmp_path, facts_bytes=_encode(facts))
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "input_schema_invalid"
    assert ei.value.input_name == "server_facts_ref"


def test_invalid_expectation_schema(tmp_path):
    facts, exp, ev = base_payloads()
    exp["scope"] = "not-artifact-derived"
    refs = build_valid_root(tmp_path, exp_bytes=_encode(exp))
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "input_schema_invalid"
    assert ei.value.input_name == "expectation_ref"


def test_invalid_service_evidence_schema(tmp_path):
    facts, exp, ev = base_payloads()
    ev["services"][0]["evidence_status"] = "bogus"
    refs = build_valid_root(tmp_path, ev_bytes=_encode(ev))
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "input_schema_invalid"
    assert ei.value.input_name == "service_evidence_ref"


def test_wrong_schema_version(tmp_path):
    facts, exp, ev = base_payloads()
    facts["schema_version"] = "server-facts.v2"
    refs = build_valid_root(tmp_path, facts_bytes=_encode(facts))
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "input_schema_invalid"


def test_canonical_schema_missing(tmp_path, monkeypatch):
    server_facts_schema = adapter_module._INPUT_SCHEMAS["server_facts_ref"]
    schemas_dir = make_schemas_dir(tmp_path, drop={server_facts_schema})
    monkeypatch.setattr(adapter_module, "_SCHEMAS_DIR", schemas_dir)
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs={}
        )
    assert ei.value.code == "contract_load_failed"
    assert ei.value.stage == "contract_load"


def test_canonical_schema_invalid_json(tmp_path, monkeypatch):
    server_facts_schema = adapter_module._INPUT_SCHEMAS["server_facts_ref"]
    schemas_dir = make_schemas_dir(
        tmp_path, override={server_facts_schema: b"{ not valid json"}
    )
    monkeypatch.setattr(adapter_module, "_SCHEMAS_DIR", schemas_dir)
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs={}
        )
    assert ei.value.code == "contract_load_failed"


def test_canonical_schema_itself_schema_invalid(tmp_path, monkeypatch):
    server_facts_schema = adapter_module._INPUT_SCHEMAS["server_facts_ref"]
    bogus_schema = json.dumps({"type": 123}).encode("utf-8")  # valid JSON, invalid schema
    schemas_dir = make_schemas_dir(
        tmp_path, override={server_facts_schema: bogus_schema}
    )
    monkeypatch.setattr(adapter_module, "_SCHEMAS_DIR", schemas_dir)
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs={}
        )
    assert ei.value.code == "contract_schema_invalid"
    assert ei.value.stage == "contract_schema"


def test_producer_not_called_on_input_schema_error(tmp_path, monkeypatch):
    spy = install_spy(monkeypatch, passthrough=False)
    facts, exp, ev = base_payloads()
    del facts["host"]
    refs = build_valid_root(tmp_path, facts_bytes=_encode(facts))
    with pytest.raises(HeimserverServiceGateArtifactError):
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert spy.called is False


# --------------------------------------------------------------------------- #
# 14.2 Full Draft 2020-12 evaluation (contains)
# --------------------------------------------------------------------------- #
def test_contains_rule_is_enforced(tmp_path):
    """An evidence service whose `present` status omits the contains-required
    reason code is rejected only under full Draft 2020-12 `contains` evaluation."""
    facts, exp, ev = base_payloads()
    service = ev["services"][0]
    assert service["evidence_status"] == "present"
    assert "service_evidence_present_in_artifacts" in service["reason_codes"]

    # Remove ONLY the contains-required reason code. The remaining code is still
    # allowed by `items`, so the violation is exclusively the `present`-branch
    # `contains` requirement.
    service["reason_codes"] = ["service_evidence_artifact_only_scope"]

    # Precise proof that the violated keyword is `contains` under full Draft 2020-12.
    evidence_schema = _read_json(EVIDENCE_SCHEMA_PATH)
    errors = list(Draft202012Validator(evidence_schema).iter_errors(ev))
    assert any(error.validator == "contains" for error in errors)

    # The adapter enforces exactly this and rejects the evidence input.
    refs = build_valid_root(tmp_path, ev_bytes=_encode(ev))
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "input_schema_invalid"
    assert ei.value.input_name == "service_evidence_ref"


# --------------------------------------------------------------------------- #
# 14.2 Contract authority
# --------------------------------------------------------------------------- #
def test_planted_schema_under_artifact_root_has_no_effect(tmp_path):
    """A weakened schema placed next to the artifacts must be ignored: the
    canonical steuerboard schema still governs."""
    facts, exp, ev = base_payloads()
    ev["services"][0]["evidence_status"] = "totally-invalid"  # rejected by real schema

    refs = build_valid_root(tmp_path, ev_bytes=_encode(ev))

    # Plant a fully-permissive replacement schema where a naive loader might look.
    planted = tmp_path / "schemas"
    planted.mkdir()
    (planted / "heimserver-service-evidence.v1.schema.json").write_text(
        json.dumps({"type": "object"}), encoding="utf-8"
    )

    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "input_schema_invalid"
    assert ei.value.input_name == "service_evidence_ref"


# --------------------------------------------------------------------------- #
# 14.2 Output schema
# --------------------------------------------------------------------------- #
def test_output_schema_invalid(tmp_path, monkeypatch):
    install_spy(monkeypatch, return_value={"schema_version": "WRONG", "kind": "x"})
    refs = build_valid_root(tmp_path)
    with pytest.raises(HeimserverServiceGateArtifactError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert ei.value.code == "output_schema_invalid"
    assert ei.value.stage == "output_schema"


def test_producer_domain_error_is_not_translated(tmp_path, monkeypatch):
    """A producer ValueError is a domain error, not an artifact-load failure."""

    def boom(**kwargs):
        raise ValueError("producer domain failure")

    monkeypatch.setattr(
        adapter_module, "derive_heimserver_service_gate_assessment", boom
    )
    refs = build_valid_root(tmp_path)
    with pytest.raises(ValueError) as ei:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path, input_refs=refs
        )
    assert not isinstance(ei.value, HeimserverServiceGateArtifactError)
    assert str(ei.value) == "producer domain failure"


# --------------------------------------------------------------------------- #
# 14.2 Determinism
# --------------------------------------------------------------------------- #
def test_error_priority_is_mapping_order_independent(tmp_path):
    """Two refs are broken; the first error is always the canonical-first input
    regardless of the caller's mapping insertion order."""
    valid = build_valid_root(tmp_path)
    facts_ref = {"path": valid["server_facts_ref"]["path"], "sha256": WRONG_SHA256}
    exp_ref = {"path": valid["expectation_ref"]["path"], "sha256": WRONG_SHA256}
    ev_ref = dict(valid["service_evidence_ref"])

    order_a = {
        "server_facts_ref": dict(facts_ref),
        "expectation_ref": dict(exp_ref),
        "service_evidence_ref": dict(ev_ref),
    }
    order_b = {
        "service_evidence_ref": dict(ev_ref),
        "expectation_ref": dict(exp_ref),
        "server_facts_ref": dict(facts_ref),
    }

    errors = []
    for refs in (order_a, order_b):
        with pytest.raises(HeimserverServiceGateArtifactError) as ei:
            derive_heimserver_service_gate_assessment_from_refs(
                artifact_root=tmp_path, input_refs=refs
            )
        errors.append((ei.value.code, ei.value.stage, ei.value.input_name))

    assert errors[0] == errors[1]
    assert errors[0] == ("hash_mismatch", "hash", "server_facts_ref")


# --------------------------------------------------------------------------- #
# 14.2 Alias freedom
# --------------------------------------------------------------------------- #
def test_original_input_refs_unchanged(tmp_path):
    refs = build_valid_root(tmp_path)
    snapshot = copy.deepcopy(refs)
    derive_heimserver_service_gate_assessment_from_refs(
        artifact_root=tmp_path, input_refs=refs
    )
    assert refs == snapshot


def test_producer_receives_independent_copies(tmp_path, monkeypatch):
    spy = install_spy(monkeypatch, passthrough=True)
    refs = build_valid_root(tmp_path)
    derive_heimserver_service_gate_assessment_from_refs(
        artifact_root=tmp_path, input_refs=refs
    )
    assert spy.received_input_refs is not refs
    assert spy.received_input_refs == refs
    # Mutating what the producer received must not touch the caller's refs.
    spy.received_input_refs["server_facts_ref"]["path"] = "mutated"
    assert refs["server_facts_ref"]["path"] != "mutated"


def test_return_mutation_does_not_touch_inputs(tmp_path):
    refs = build_valid_root(tmp_path)
    snapshot = copy.deepcopy(refs)
    produced = derive_heimserver_service_gate_assessment_from_refs(
        artifact_root=tmp_path, input_refs=refs
    )
    produced["inputs"]["server_facts_ref"]["path"] = "mutated"
    produced["evaluated_services"][0]["evidence"][0] = "changed"
    assert refs == snapshot


def test_later_input_mutation_does_not_change_returned_assessment(tmp_path):
    refs = build_valid_root(tmp_path)
    produced = derive_heimserver_service_gate_assessment_from_refs(
        artifact_root=tmp_path, input_refs=refs
    )
    before = copy.deepcopy(produced)
    refs["server_facts_ref"]["path"] = "mutated-after-call"
    refs["service_evidence_ref"]["sha256"] = WRONG_SHA256
    assert produced == before


# --------------------------------------------------------------------------- #
# 14.3 Purity boundary
# --------------------------------------------------------------------------- #
FORBIDDEN_IMPORTS = {
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "http",
    "ssl",
    "ftplib",
    "telnetlib",
    "smtplib",
    "os",
    "glob",
    "random",
    "secrets",
    "time",
    "datetime",
    "asyncio",
    "paramiko",
    "fabric",
}

FORBIDDEN_CALLS = {
    "system",
    "popen",
    "Popen",
    "run",
    "check_output",
    "check_call",
    "getaddrinfo",
    "create_connection",
    "urlopen",
    "getfqdn",
    "gethostname",
    "gethostbyname",
    "connect",
    "sleep",
    "glob",
    "iglob",
    "expanduser",
    "expandvars",
    "getenv",
    "walk",
    "scandir",
    "listdir",
    "write_text",
    "write_bytes",
    "mkdir",
    "unlink",
    "rmdir",
    "remove",
    "open",
}


def test_adapter_purity_guard():
    module_path = REPO_ROOT / "steuerboard" / "heimserver_service_gate_artifacts.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert (
                    alias.name.split(".")[0] not in FORBIDDEN_IMPORTS
                ), f"forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert (
                    node.module.split(".")[0] not in FORBIDDEN_IMPORTS
                ), f"forbidden import-from: {node.module}"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id not in FORBIDDEN_CALLS, f"forbidden call: {func.id}"
            elif isinstance(func, ast.Attribute):
                assert (
                    func.attr not in FORBIDDEN_CALLS
                ), f"forbidden method call: {func.attr}"
