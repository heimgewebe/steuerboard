"""Regression tests for the service-evidence preimage container guard."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from steuerboard.heimserver_service_gate_artifacts import (
    HeimserverServiceGateArtifactError,
    derive_heimserver_service_gate_assessment_from_refs,
)
from steuerboard import heimserver_service_gate_artifacts as adapter_module

_EXISTING_TEST_FILE = Path(__file__).with_name(
    "test_heimserver_service_gate_artifacts.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "_steuerboard_existing_artifact_adapter_tests",
    _EXISTING_TEST_FILE,
)
assert _SPEC is not None and _SPEC.loader is not None
_existing = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_existing)


@pytest.mark.parametrize("bad_evidence", [7, None])
def test_evidence_non_list_rejected_before_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_evidence: object
) -> None:
    spy = _existing.install_spy(monkeypatch)
    _existing._patch_schemas(
        tmp_path,
        monkeypatch,
        {_existing.EVIDENCE_SCHEMA_FILE: b"{}"},
    )
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
    refs = _existing.build_valid_root(
        tmp_path,
        ev_bytes=json.dumps(payload).encode(),
    )

    with pytest.raises(HeimserverServiceGateArtifactError) as exc_info:
        derive_heimserver_service_gate_assessment_from_refs(
            artifact_root=tmp_path,
            input_refs=refs,
        )

    assert exc_info.value.code == "contract_schema_invalid"
    assert exc_info.value.stage == "contract_schema"
    assert exc_info.value.path == _existing.EVIDENCE_SCHEMA_FILE
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
    assert exc_info.value.path == _existing.EVIDENCE_SCHEMA_FILE
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
