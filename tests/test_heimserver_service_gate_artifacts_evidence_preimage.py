"""Regression tests for the service-evidence preimage container guard."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from steuerboard import heimserver_service_gate_artifacts as adapter_module
from steuerboard.heimserver_service_gate_artifacts import (
    HeimserverServiceGateArtifactError,
    derive_heimserver_service_gate_assessment_from_refs,
)
from steuerboard.heimserver_service_gate import (
    derive_heimserver_service_gate_assessment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
CASES_DIR = REPO_ROOT / "examples" / "heimserver-service-gate-derivation-cases"
BASE_CASE_ID = "golden-passed-single-service-fresh"
EVIDENCE_SCHEMA_FILE = adapter_module._INPUT_SCHEMAS["service_evidence_ref"]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _base_payloads() -> tuple[dict, dict, dict]:
    case = _read_json(CASES_DIR / f"{BASE_CASE_ID}.json")
    inputs = case["inputs"]
    return (
        _read_json(REPO_ROOT / inputs["server_facts_ref"]["path"]),
        _read_json(REPO_ROOT / inputs["expectation_ref"]["path"]),
        _read_json(REPO_ROOT / inputs["service_evidence_ref"]["path"]),
    )


def _write_artifact(root: Path, name: str, payload: dict, raw: bytes | None = None):
    data = raw if raw is not None else (json.dumps(payload, indent=2) + "\n").encode()
    (root / name).write_bytes(data)
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}


def _build_valid_root(root: Path, *, evidence_bytes: bytes) -> dict:
    facts, expectation, evidence = _base_payloads()
    return {
        "server_facts_ref": _write_artifact(root, "server-facts.json", facts),
        "expectation_ref": _write_artifact(root, "expectation.json", expectation),
        "service_evidence_ref": _write_artifact(
            root, "evidence.json", evidence, evidence_bytes
        ),
    }


def _patch_evidence_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "schemas"
    out.mkdir()
    for filename in adapter_module._CANONICAL_SCHEMA_FILENAMES:
        source = SCHEMAS_DIR / filename
        (out / filename).write_bytes(
            b"{}" if filename == EVIDENCE_SCHEMA_FILE else source.read_bytes()
        )
    monkeypatch.setattr(adapter_module, "_SCHEMAS_DIR", out)


class _ProducerSpy:
    def __init__(self) -> None:
        self.called = False

    def __call__(self, *, server_facts, expectation, service_evidence, input_refs):
        self.called = True
        return derive_heimserver_service_gate_assessment(
            server_facts=server_facts,
            expectation=expectation,
            service_evidence=service_evidence,
            input_refs=input_refs,
        )


@pytest.mark.parametrize("bad_evidence", [7, None])
def test_evidence_non_list_rejected_before_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_evidence: object
) -> None:
    spy = _ProducerSpy()
    monkeypatch.setattr(
        adapter_module, "derive_heimserver_service_gate_assessment", spy
    )
    _patch_evidence_schema(tmp_path, monkeypatch)
    payload = {
        "host": "heimserver-golden",
        "observed_at": "2026-01-01T00:00:00Z",
        "freshness_status": "fresh",
        "services": [
            {
                "service_name": "tailscaled.service",
                "evidence_status": "present",
                "evidence": bad_evidence,
            }
        ],
    }
    refs = _build_valid_root(
        tmp_path,
        evidence_bytes=json.dumps(payload).encode(),
    )

    with pytest.raises(HeimserverServiceGateArtifactError) as exc_info:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path,
            input_refs=refs,
        )

    assert exc_info.value.code == "contract_schema_invalid"
    assert exc_info.value.stage == "contract_schema"
    assert exc_info.value.path == EVIDENCE_SCHEMA_FILE
    assert exc_info.value.input_name == "service_evidence_ref"
    assert spy.called is False


@pytest.mark.parametrize(
    "bad_evidence",
    [None, 7, True, "text", {"source": "x"}],
)
def test_preimage_guard_rejects_non_list_evidence(bad_evidence: object) -> None:
    payload = {
        "host": "heimserver",
        "observed_at": "2026-01-01T00:00:00Z",
        "services": [
            {
                "service_name": "tailscale",
                "evidence_status": "present",
                "evidence": bad_evidence,
            }
        ],
    }

    with pytest.raises(HeimserverServiceGateArtifactError) as exc_info:
        adapter_module._assert_producer_preimage_shape(
            input_name="service_evidence_ref",
            payload=payload,
        )

    assert exc_info.value.code == "contract_schema_invalid"
    assert exc_info.value.stage == "contract_schema"
    assert exc_info.value.path == EVIDENCE_SCHEMA_FILE
    assert exc_info.value.input_name == "service_evidence_ref"


def test_preimage_guard_accepts_list_evidence() -> None:
    adapter_module._assert_producer_preimage_shape(
        input_name="service_evidence_ref",
        payload={
            "host": "heimserver",
            "observed_at": "2026-01-01T00:00:00Z",
            "services": [
                {
                    "service_name": "tailscale",
                    "evidence_status": "present",
                    "evidence": ["artifact-derived observation"],
                }
            ],
        },
    )


def test_preimage_guard_allows_missing_evidence_for_producer_default() -> None:
    adapter_module._assert_producer_preimage_shape(
        input_name="service_evidence_ref",
        payload={
            "host": "heimserver",
            "observed_at": "2026-01-01T00:00:00Z",
            "services": [
                {
                    "service_name": "tailscale",
                    "evidence_status": "present",
                }
            ],
        },
    )
