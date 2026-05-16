from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, EXAMPLES_DIR, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.omnipull_reports import load_omnipull_report

FORBIDDEN_REPORT_KEYS = {
    "action",
    "plan_id",
    "would_run",
    "would_mutate",
    "command_trace",
    "run_result",
    "safe_actions",
    "safe_alternatives",
}


def _schema() -> dict:
    return load_json(SCHEMAS_DIR / "omnipull-report.v1.schema.json")


def test_mixed_run_example_validates_against_schema():
    example_path = EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json"
    instance = load_json(example_path)

    validate_instance(instance, _schema(), example_path)


def test_load_omnipull_report_returns_schema_valid_object(tmp_path: Path):
    source = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    payload = dict(source)
    payload["boundary"] = {
        "does_not_execute": False,
        "does_not_mutate": False,
        "does_not_authorise_actions": False,
    }
    payload["action"] = "switch-main"
    payload["would_run"] = True

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_omnipull_report(report_path)

    validate_instance(loaded, _schema(), Path("generated-omnipull-report.json"))
    assert loaded["schema_version"] == "omnipull-report.v1"
    assert loaded["boundary"] == {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }


def test_load_omnipull_report_rejects_wrong_schema_version(tmp_path: Path):
    payload = {
        "schema_version": "repo-assessment.v1",
        "report_id": "report-id",
        "run_id": "run-id",
        "generated_at": "2026-05-16T09:32:00Z",
        "source_path": "examples/omnipull-reports/mixed-run.json",
        "repos": [],
    }
    report_path = tmp_path / "invalid-schema-version.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        load_omnipull_report(report_path)


def test_load_omnipull_report_rejects_non_object_json(tmp_path: Path):
    report_path = tmp_path / "not-object.json"
    report_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_omnipull_report(report_path)


def test_boundary_false_is_not_adopted(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "dirty-worktree.json")
    payload["boundary"] = {
        "does_not_execute": False,
        "does_not_mutate": False,
        "does_not_authorise_actions": False,
    }
    report_path = tmp_path / "boundary-false.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_omnipull_report(report_path)

    assert loaded["boundary"] == {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }


def test_runtime_never_emits_executor_fields(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "non-default-branch.json")
    payload.update(
        {
            "action": "switch-main",
            "plan_id": "plan-1",
            "would_run": True,
            "would_mutate": True,
            "command_trace": {"id": "trace-1"},
            "run_result": {"id": "result-1"},
            "safe_actions": ["noop"],
            "safe_alternatives": ["inspect"],
        }
    )
    report_path = tmp_path / "forbidden-fields.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_omnipull_report(report_path)

    assert FORBIDDEN_REPORT_KEYS.isdisjoint(loaded.keys())


def test_omnipull_report_show_cli_smoke_emits_valid_json():
    report_path = EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "show",
            str(report_path),
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    payload = json.loads(result.stdout)
    validate_instance(payload, _schema(), Path("omnipull-report-show-cli-smoke.json"))


def test_omnipull_report_latest_command_is_not_available():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "latest",
            "--json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "invalid choice" in result.stderr
