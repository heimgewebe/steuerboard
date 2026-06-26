"""Integration tests for the artifact-derived Heimserver-Service-Gate runbook."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import steuerboard.runbooks as runbooks
from steuerboard.cli import main
from steuerboard.runbooks import run_runbook

ROOT = Path(__file__).resolve().parents[1]
ASSESSMENTS = ROOT / "examples" / "heimserver-service-gate-assessments"

BOUNDARY = {
    "does_not_execute_mutating_actions": True,
    "does_not_mutate": True,
    "does_not_authorise_actions": True,
    "read_only_or_dry_run_only": True,
}


def _golden(case_name: str) -> dict:
    return json.loads((ASSESSMENTS / f"{case_name}.json").read_text(encoding="utf-8"))


def _plan(case_name: str) -> dict:
    assessment = _golden(case_name)
    return {
        "schema_version": "runbook-plan.v1",
        "runbook_id": f"runbook-{case_name}",
        "runbook_kind": "heimserver-service-gate",
        "created_at": "2026-06-26T18:45:00Z",
        "repo_path": str(ROOT),
        "mode": "read_only",
        "source_refs": [ref["path"] for ref in assessment["inputs"].values()],
        "service_gate_inputs": {
            "artifact_root": str(ROOT),
            "input_refs": assessment["inputs"],
        },
        "boundary": dict(BOUNDARY),
    }


def _run(tmp_path: Path, plan: dict) -> tuple[dict, Path, Path, Path]:
    result_path = tmp_path / "result.json"
    trace_path = tmp_path / "trace.jsonl"
    assessment_path = tmp_path / "heimserver-service-gate-assessment.json"
    result = run_runbook(
        runbook_plan=plan,
        result_out=str(result_path),
        command_trace_out=str(trace_path),
    )
    return result, result_path, trace_path, assessment_path


@pytest.mark.parametrize(
    ("case_name", "expected_status"),
    [
        ("golden-passed-single-service-fresh", "passed"),
        ("golden-blocked-subject-mismatch", "blocked"),
        ("golden-inconclusive-stale-evidence", "inconclusive"),
    ],
)
def test_runbook_maps_assessment_status_and_writes_complete_artifact_set(
    tmp_path: Path,
    case_name: str,
    expected_status: str,
) -> None:
    result, result_path, trace_path, assessment_path = _run(
        tmp_path, _plan(case_name)
    )

    assert result["runbook_kind"] == "heimserver-service-gate"
    assert result["status"] == expected_status
    assert result_path.exists()
    assert trace_path.exists()
    assert assessment_path.exists()
    assert json.loads(result_path.read_text(encoding="utf-8")) == result
    assert json.loads(assessment_path.read_text(encoding="utf-8")) == _golden(case_name)
    assert result["evidence_paths"] == [str(trace_path), str(assessment_path)]
    assert result["boundary"] == BOUNDARY

    traces = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["step_id"] for entry in traces] == [
        "step-service-gate-derive",
        "step-service-gate-write",
        "step-service-gate-status",
    ]
    assert {entry["capability_class"] for entry in traces} <= {
        "read_only",
        "derivation_only",
    }
    assert all(entry["redaction_verified"] is True for entry in traces)


def test_adapter_failure_is_inconclusive_without_assessment_artifact(
    tmp_path: Path,
) -> None:
    plan = _plan("golden-passed-single-service-fresh")
    plan["service_gate_inputs"]["input_refs"]["server_facts_ref"]["sha256"] = (
        "0" * 64
    )

    result, result_path, trace_path, assessment_path = _run(tmp_path, plan)

    assert result["status"] == "inconclusive"
    assert "technical_code=hash_mismatch" in result["short_assessment"]
    assert result_path.exists()
    assert trace_path.exists()
    assert not os.path.lexists(assessment_path)
    assert result["evidence_paths"] == [str(trace_path)]
    traces = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(traces) == 1
    assert traces[0]["status"] == "inconclusive"



def test_invalid_artifact_root_is_structured_as_inconclusive(
    tmp_path: Path,
) -> None:
    plan = _plan("golden-passed-single-service-fresh")
    plan["service_gate_inputs"]["artifact_root"] = "bad\x00root"

    result, result_path, trace_path, assessment_path = _run(tmp_path, plan)

    assert result["status"] == "inconclusive"
    assert "technical_code=invalid_artifact_root" in result["short_assessment"]
    assert result_path.exists()
    assert trace_path.exists()
    assert not os.path.lexists(assessment_path)

def test_existing_assessment_target_blocks_before_any_output(tmp_path: Path) -> None:
    assessment_path = tmp_path / "heimserver-service-gate-assessment.json"
    assessment_path.write_text("sentinel\n", encoding="utf-8")
    result_path = tmp_path / "result.json"
    trace_path = tmp_path / "trace.jsonl"

    with pytest.raises(ValueError, match="service_gate_assessment_out"):
        run_runbook(
            runbook_plan=_plan("golden-passed-single-service-fresh"),
            result_out=str(result_path),
            command_trace_out=str(trace_path),
        )

    assert assessment_path.read_text(encoding="utf-8") == "sentinel\n"
    assert not result_path.exists()
    assert not trace_path.exists()


def test_later_result_failure_rolls_back_assessment_and_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_result_validation(_result: dict) -> None:
        raise RuntimeError("simulated result validation failure")

    monkeypatch.setattr(runbooks, "_validate_result", fail_result_validation)
    result_path = tmp_path / "result.json"
    trace_path = tmp_path / "trace.jsonl"
    assessment_path = tmp_path / "heimserver-service-gate-assessment.json"

    with pytest.raises(RuntimeError, match="simulated result validation failure"):
        run_runbook(
            runbook_plan=_plan("golden-passed-single-service-fresh"),
            result_out=str(result_path),
            command_trace_out=str(trace_path),
        )

    assert not os.path.lexists(result_path)
    assert not os.path.lexists(trace_path)
    assert not os.path.lexists(assessment_path)
    assert list(tmp_path.glob("*.tmp")) == []


def test_service_gate_plan_requires_dedicated_inputs(tmp_path: Path) -> None:
    plan = _plan("golden-passed-single-service-fresh")
    del plan["service_gate_inputs"]

    with pytest.raises(ValueError, match="schema validation failed"):
        run_runbook(
            runbook_plan=plan,
            result_out=str(tmp_path / "result.json"),
            command_trace_out=str(tmp_path / "trace.jsonl"),
        )


def test_service_gate_inputs_are_forbidden_for_other_runbook_kinds(
    tmp_path: Path,
) -> None:
    plan = json.loads(
        (ROOT / "examples" / "runbooks" / "repo-sync-gate.json").read_text(
            encoding="utf-8"
        )
    )
    plan["repo_path"] = str(ROOT)
    plan["service_gate_inputs"] = _plan(
        "golden-passed-single-service-fresh"
    )["service_gate_inputs"]

    with pytest.raises(ValueError, match="schema validation failed"):
        run_runbook(
            runbook_plan=plan,
            result_out=str(tmp_path / "result.json"),
            command_trace_out=str(tmp_path / "trace.jsonl"),
        )


def test_generic_runbook_cli_executes_service_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(_plan("golden-passed-single-service-fresh")),
        encoding="utf-8",
    )
    result_path = tmp_path / "result.json"
    trace_path = tmp_path / "trace.jsonl"

    exit_code = main(
        [
            "runbook",
            "run",
            str(plan_path),
            "--result-out",
            str(result_path),
            "--command-trace-out",
            str(trace_path),
            "--json",
        ]
    )

    assert exit_code == 0
    stdout_result = json.loads(capsys.readouterr().out)
    assert stdout_result["runbook_kind"] == "heimserver-service-gate"
    assert stdout_result["status"] == "passed"
    assert result_path.exists()
    assert trace_path.exists()
    assert (tmp_path / "heimserver-service-gate-assessment.json").exists()
