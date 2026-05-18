from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import (
    ROOT,
    EXAMPLES_DIR,
    SCHEMAS_DIR,
    ValidationError,
    load_json,
    validate_instance,
)
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
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")

    report_path = tmp_path / "report.json"
    payload["source_path"] = str(report_path)
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


def test_boundary_false_is_rejected(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "dirty-worktree.json")
    report_path = tmp_path / "boundary-false.json"
    payload["source_path"] = str(report_path)
    payload["boundary"] = {
        "does_not_execute": False,
        "does_not_mutate": False,
        "does_not_authorise_actions": False,
    }
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="boundary"):
        load_omnipull_report(report_path)


def test_runtime_rejects_executor_fields(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "non-default-branch.json")
    report_path = tmp_path / "forbidden-fields.json"
    payload["source_path"] = str(report_path)
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
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden fields"):
        load_omnipull_report(report_path)


def test_runtime_rejects_unknown_top_level_field(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "unknown-top-level.json"
    payload["source_path"] = str(report_path)
    payload["unexpected"] = "value"

    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown fields"):
        load_omnipull_report(report_path)


def test_runtime_rejects_unknown_repo_item_field(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "unknown-repo-field.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0]["unexpected_repo_field"] = "value"

    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown fields"):
        load_omnipull_report(report_path)


def test_runtime_rejects_unknown_status(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "unknown-status.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0]["status"] = "unsupported_status"

    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="status"):
        load_omnipull_report(report_path)


def test_runtime_rejects_invalid_generated_at_format(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "invalid-generated-at.json"
    payload["source_path"] = str(report_path)
    payload["generated_at"] = "2026-05-16 09:32:00"

    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="date-time"):
        load_omnipull_report(report_path)


def test_runtime_rejects_missing_boundary(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "missing-boundary.json"
    payload["source_path"] = str(report_path)
    payload.pop("boundary")

    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="boundary"):
        load_omnipull_report(report_path)


def test_runtime_rejects_source_path_mismatch(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "source-path-mismatch.json"
    payload["source_path"] = str(tmp_path / "other.json")
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_path"):
        load_omnipull_report(report_path)


def test_runtime_rejects_lexically_different_source_path_for_same_file(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_dir = tmp_path / "nested"
    report_dir.mkdir()
    report_path = report_dir / "report.json"
    payload["source_path"] = f"{report_dir}/./report.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_path"):
        load_omnipull_report(report_path)


def test_runtime_accepts_source_path_matching_explicit_reference(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_dir = tmp_path / "nested"
    report_dir.mkdir()
    report_path = report_dir / "report.json"
    payload["source_path"] = "./nested/report.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_omnipull_report(report_path, source_path_ref="./nested/report.json")

    assert loaded["source_path"] == "./nested/report.json"


def test_runtime_rejects_whitespace_padded_source_path(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "source-path-whitespace.json"
    payload["source_path"] = f"  {report_path}  "
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_path"):
        load_omnipull_report(report_path)


def test_runtime_accepts_empty_repos_for_empty_run(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "empty-run.json"
    payload["source_path"] = str(report_path)
    payload["repos"] = []
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_omnipull_report(report_path)

    validate_instance(loaded, _schema(), Path("empty-run.json"))
    assert loaded["repos"] == []


def test_runtime_rejects_empty_skip_reasons(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "empty-skip-reasons.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0]["skip_reasons"] = []
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="skip_reasons"):
        load_omnipull_report(report_path)


def test_runtime_rejects_status_not_present_in_skip_reasons(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "status-not-in-skip-reasons.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0]["skip_reasons"] = ["dirty_worktree"]
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="skip_reasons"):
        load_omnipull_report(report_path)


def test_runtime_rejects_empty_or_whitespace_repo_strings(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "empty-string-fields.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0]["repo_id"] = "   "
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="repo_id"):
        load_omnipull_report(report_path)


@pytest.mark.parametrize(
    "field",
    [
        "skip_reasons",
        "source_refs",
        "freshness_refs",
        "falsification_refs",
        "missing_evidence",
    ],
)
def test_runtime_rejects_empty_repo_list_items(tmp_path: Path, field: str):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / f"empty-{field}.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0][field] = [""]
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="non-blank strings"):
        load_omnipull_report(report_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("skip_reasons", " dirty_worktree "),
        ("source_refs", " source.branch.current "),
        ("freshness_refs", " freshness.origin_main.current "),
        ("falsification_refs", " failure-case.dirty_worktree "),
        ("missing_evidence", " missing.branch_state "),
    ],
)
def test_runtime_rejects_whitespace_padded_repo_list_items(
    tmp_path: Path, field: str, value: str
):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / f"whitespace-padded-{field}.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0][field] = [value]
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        load_omnipull_report(report_path)


def test_runtime_rejects_whitespace_padded_repo_strings(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "whitespace-padded-repo-strings.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0]["repo_id"] = " repo.mixed-run "
    payload["repos"][0]["path"] = " ./repo "
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        load_omnipull_report(report_path)


@pytest.mark.parametrize("field", ["report_id", "run_id"])
def test_runtime_rejects_whitespace_padded_top_level_strings(tmp_path: Path, field: str):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / f"whitespace-padded-{field}.json"
    payload["source_path"] = str(report_path)
    payload[field] = f" {payload[field]} "
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        load_omnipull_report(report_path)


def test_schema_rejects_whitespace_padded_source_path():
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate["source_path"] = " examples/omnipull-reports/mixed-run.json "

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path("whitespace-padded-source-path.json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("report_id", " report.mixed-run "),
        ("run_id", " run.mixed-run "),
    ],
)
def test_schema_rejects_whitespace_padded_top_level_strings(field: str, value: str):
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate[field] = value

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"whitespace-padded-top-level-{field}.json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("repo_id", " repo.mixed-run "),
        ("path", " ./repo "),
    ],
)
def test_schema_rejects_whitespace_padded_repo_strings(field: str, value: str):
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate["repos"][0][field] = value

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"whitespace-padded-repo-{field}.json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("skip_reasons", " dirty_worktree "),
        ("source_refs", " source.branch.current "),
        ("freshness_refs", " freshness.origin_main.current "),
        ("missing_evidence", " missing.branch_state "),
    ],
)
def test_schema_rejects_whitespace_padded_repo_list_items(field: str, value: str):
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate["repos"][0][field] = [value]

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"whitespace-padded-list-{field}.json"))


def test_runtime_rejects_falsification_ref_prefix(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "bad-falsification-prefix.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0]["falsification_refs"] = ["wrong-prefix.feature_branch_unmerged"]
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="failure-case"):
        load_omnipull_report(report_path)


def test_runtime_rejects_unknown_falsification_ref(tmp_path: Path):
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    report_path = tmp_path / "unknown-falsification-ref.json"
    payload["source_path"] = str(report_path)
    payload["repos"][0]["falsification_refs"] = ["failure-case.not_a_real_case"]
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown failure-case"):
        load_omnipull_report(report_path)


def test_schema_rejects_forbidden_top_level_fields():
    schema = _schema()
    base = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")

    for field in sorted(FORBIDDEN_REPORT_KEYS):
        candidate = json.loads(json.dumps(base))
        candidate[field] = "forbidden"
        with pytest.raises(ValidationError):
            validate_instance(candidate, schema, Path(f"forbidden-top-level-{field}.json"))


def test_schema_rejects_forbidden_repo_fields():
    schema = _schema()
    base = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")

    for field in sorted(FORBIDDEN_REPORT_KEYS):
        candidate = json.loads(json.dumps(base))
        candidate["repos"][0][field] = "forbidden"
        with pytest.raises(ValidationError):
            validate_instance(candidate, schema, Path(f"forbidden-repo-field-{field}.json"))


def test_schema_rejects_boundary_false_and_extra_field():
    schema = _schema()
    candidate_false = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate_false["boundary"] = {
        "does_not_execute": False,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }

    with pytest.raises(ValidationError):
        validate_instance(candidate_false, schema, Path("invalid-boundary-false.json"))

    candidate_extra = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate_extra["boundary"] = {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
        "unexpected": True,
    }

    with pytest.raises(ValidationError):
        validate_instance(candidate_extra, schema, Path("invalid-boundary-extra-field.json"))


def test_schema_rejects_missing_required_top_level_fields():
    schema = _schema()
    required = [
        "schema_version",
        "report_id",
        "run_id",
        "generated_at",
        "source_path",
        "repos",
        "boundary",
    ]

    for field in required:
        candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
        candidate.pop(field)
        with pytest.raises(ValidationError):
            validate_instance(candidate, schema, Path(f"missing-top-level-{field}.json"))


def test_schema_rejects_missing_required_repo_fields():
    schema = _schema()
    required = [
        "repo_id",
        "path",
        "status",
        "skip_reasons",
        "source_refs",
        "freshness_refs",
        "falsification_refs",
        "missing_evidence",
    ]

    for field in required:
        candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
        candidate["repos"][0].pop(field)
        with pytest.raises(ValidationError):
            validate_instance(candidate, schema, Path(f"missing-repo-field-{field}.json"))


@pytest.mark.parametrize("field", ["report_id", "run_id", "source_path"])
def test_schema_rejects_whitespace_only_omnipull_top_level_strings(field: str):
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate[field] = "   "

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"whitespace-top-level-{field}.json"))


@pytest.mark.parametrize("field", ["repo_id", "path", "status"])
def test_schema_rejects_whitespace_only_omnipull_repo_strings(field: str):
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate["repos"][0][field] = "   "

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"whitespace-repo-{field}.json"))


@pytest.mark.parametrize(
    "field",
    [
        "skip_reasons",
        "source_refs",
        "freshness_refs",
        "falsification_refs",
        "missing_evidence",
    ],
)
def test_schema_rejects_empty_repo_list_items(field: str):
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate["repos"][0][field] = [""]

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"empty-item-{field}.json"))


@pytest.mark.parametrize(
    "field",
    [
        "skip_reasons",
        "source_refs",
        "freshness_refs",
        "falsification_refs",
        "missing_evidence",
    ],
)
def test_schema_rejects_whitespace_only_omnipull_repo_list_items(field: str):
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate["repos"][0][field] = ["   "]

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"whitespace-list-item-{field}.json"))


def test_schema_rejects_invalid_falsification_ref_prefix():
    schema = _schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    candidate["repos"][0]["falsification_refs"] = ["not-a-failure-case.dirty_worktree"]

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path("invalid-falsification-ref-prefix.json"))


def test_mixed_run_default_branch_unknown_uses_assessment_vocabulary():
    payload = load_json(EXAMPLES_DIR / "omnipull-reports" / "mixed-run.json")
    unknown_default = next(
        repo for repo in payload["repos"] if repo["status"] == "default_branch_unknown"
    )

    assert unknown_default["missing_evidence"] == ["default_branch"]
    assert unknown_default["freshness_refs"] == [
        "freshness.default_branch_candidate.unavailable"
    ]


def test_omnipull_report_show_cli_rejects_missing_file(tmp_path: Path):
    missing_path = tmp_path / "does-not-exist.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "show",
            str(missing_path),
            "--json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0


def test_omnipull_report_show_cli_rejects_invalid_json(tmp_path: Path):
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "show",
            str(invalid_path),
            "--json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0


def test_omnipull_report_show_cli_smoke_emits_valid_json():
    report_path = Path("examples/omnipull-reports/mixed-run.json")

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


def test_omnipull_report_show_cli_rejects_dot_slash_alias_for_example():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "show",
            "./examples/omnipull-reports/mixed-run.json",
            "--json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "source_path" in result.stderr


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
