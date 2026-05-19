from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import (
    EXAMPLES_DIR,
    ROOT,
    SCHEMAS_DIR,
    ValidationError,
    load_json,
    validate_instance,
)
from steuerboard.omnipull_run_indexes import (
    load_omnipull_run_index,
    select_latest_report,
)

FORBIDDEN_INDEX_KEYS = {
    "action",
    "plan_id",
    "would_run",
    "would_mutate",
    "command_trace",
    "run_result",
    "safe_actions",
    "safe_alternatives",
}


def _index_schema() -> dict:
    return load_json(SCHEMAS_DIR / "omnipull-run-index.v1.schema.json")


def _ref_schema() -> dict:
    return load_json(SCHEMAS_DIR / "omnipull-report-ref.v1.schema.json")


def _write_index(tmp_path: Path, payload: dict, *, name: str = "index.json") -> Path:
    index_path = tmp_path / name
    payload["source_path"] = str(index_path)
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    return index_path


def _base_payload() -> dict:
    return json.loads(
        json.dumps(load_json(EXAMPLES_DIR / "omnipull-run-indexes" / "multiple-runs.json"))
    )


# ---------------------------------------------------------------------------
# Schema validation of checked-in examples
# ---------------------------------------------------------------------------


def test_minimal_index_example_validates_against_schema():
    example_path = EXAMPLES_DIR / "omnipull-run-indexes" / "minimal.json"
    instance = load_json(example_path)

    validate_instance(instance, _index_schema(), example_path)


def test_multiple_runs_example_validates_against_schema():
    example_path = EXAMPLES_DIR / "omnipull-run-indexes" / "multiple-runs.json"
    instance = load_json(example_path)

    validate_instance(instance, _index_schema(), example_path)


def test_empty_index_example_validates_against_schema():
    example_path = EXAMPLES_DIR / "omnipull-run-indexes" / "empty.json"
    instance = load_json(example_path)

    validate_instance(instance, _index_schema(), example_path)
    assert instance["reports"] == []


def test_ref_example_validates_against_schema():
    example_path = EXAMPLES_DIR / "omnipull-report-refs" / "minimal-latest.json"
    instance = load_json(example_path)

    validate_instance(instance, _ref_schema(), example_path)


# ---------------------------------------------------------------------------
# Runtime loader: positive contracts
# ---------------------------------------------------------------------------


def test_load_run_index_returns_schema_valid_object(tmp_path: Path):
    payload = _base_payload()
    index_path = _write_index(tmp_path, payload, name="ok.json")

    loaded = load_omnipull_run_index(index_path)

    validate_instance(loaded, _index_schema(), Path("loaded.json"))
    assert loaded["schema_version"] == "omnipull-run-index.v1"
    assert loaded["boundary"] == {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }
    assert len(loaded["reports"]) == 3


def test_load_run_index_accepts_empty_reports(tmp_path: Path):
    payload = _base_payload()
    payload["reports"] = []
    index_path = _write_index(tmp_path, payload, name="empty.json")

    loaded = load_omnipull_run_index(index_path)

    assert loaded["reports"] == []


def test_load_run_index_accepts_explicit_source_path_ref(tmp_path: Path):
    payload = _base_payload()
    nested = tmp_path / "nested"
    nested.mkdir()
    index_path = nested / "index.json"
    payload["source_path"] = "./nested/index.json"
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_omnipull_run_index(index_path, source_path_ref="./nested/index.json")

    assert loaded["source_path"] == "./nested/index.json"


# ---------------------------------------------------------------------------
# Latest selection
# ---------------------------------------------------------------------------


def test_select_latest_report_picks_newest_generated_at(tmp_path: Path):
    payload = _base_payload()
    index_path = _write_index(tmp_path, payload, name="multi.json")
    loaded = load_omnipull_run_index(index_path)

    ref = select_latest_report(loaded)

    assert ref == {
        "schema_version": "omnipull-report-ref.v1",
        "report_id": "omnipull-report-example-mixed-run",
        "run_id": "run-2026-05-16-003",
        "source_path": "examples/omnipull-reports/mixed-run.json",
        "selected_by": "latest.generated_at",
    }
    validate_instance(ref, _ref_schema(), Path("latest-ref.json"))


def test_select_latest_report_breaks_ties_by_run_id_lexicographically(tmp_path: Path):
    payload = _base_payload()
    same_ts = "2026-05-16T09:30:00Z"
    payload["reports"] = [
        {
            "report_id": "alpha",
            "run_id": "run-aaaa",
            "generated_at": same_ts,
            "source_path": "examples/omnipull-reports/non-default-branch.json",
        },
        {
            "report_id": "omega",
            "run_id": "run-zzzz",
            "generated_at": same_ts,
            "source_path": "examples/omnipull-reports/dirty-worktree.json",
        },
        {
            "report_id": "middle",
            "run_id": "run-mmmm",
            "generated_at": same_ts,
            "source_path": "examples/omnipull-reports/mixed-run.json",
        },
    ]
    index_path = _write_index(tmp_path, payload, name="tied.json")
    loaded = load_omnipull_run_index(index_path)

    ref = select_latest_report(loaded)

    assert ref["run_id"] == "run-zzzz"
    assert ref["report_id"] == "omega"


def test_select_latest_report_orders_generated_at_chronologically_with_offsets(
    tmp_path: Path,
):
    payload = _base_payload()
    payload["reports"] = [
        {
            "report_id": "offset-plus-two",
            "run_id": "run-plus-two",
            "generated_at": "2026-05-16T10:00:00+02:00",
            "source_path": "examples/omnipull-reports/non-default-branch.json",
        },
        {
            "report_id": "utc-later",
            "run_id": "run-utc",
            "generated_at": "2026-05-16T08:30:00Z",
            "source_path": "examples/omnipull-reports/dirty-worktree.json",
        },
    ]
    index_path = _write_index(tmp_path, payload, name="offset-order.json")
    loaded = load_omnipull_run_index(index_path)

    ref = select_latest_report(loaded)

    assert ref["run_id"] == "run-utc"
    assert ref["report_id"] == "utc-later"


def test_select_latest_report_is_stable_across_input_orderings(tmp_path: Path):
    payload = _base_payload()
    payload["reports"] = list(reversed(payload["reports"]))
    index_path = _write_index(tmp_path, payload, name="reversed.json")
    loaded = load_omnipull_run_index(index_path)

    ref = select_latest_report(loaded)

    assert ref["run_id"] == "run-2026-05-16-003"


def test_select_latest_report_raises_for_empty_reports():
    index = {
        "schema_version": "omnipull-run-index.v1",
        "generated_at": "2026-05-19T10:00:00Z",
        "source_path": "examples/omnipull-run-indexes/empty.json",
        "reports": [],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    with pytest.raises(ValueError, match="empty"):
        select_latest_report(index)


def test_select_latest_report_rejects_invalid_in_memory_generated_at():
    index = {
        "schema_version": "omnipull-run-index.v1",
        "generated_at": "2026-05-19T10:00:00Z",
        "source_path": "examples/omnipull-run-indexes/in-memory.json",
        "reports": [
            {
                "report_id": "x",
                "run_id": "run-x",
                "generated_at": "not-a-timestamp",
                "source_path": "examples/omnipull-reports/x.json",
            }
        ],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    with pytest.raises(ValueError, match="reports\\[\\]\\.generated_at"):
        select_latest_report(index)


@pytest.mark.parametrize("value", [None, "", " report-id "])
def test_select_latest_report_rejects_invalid_in_memory_report_id(value: object):
    index = {
        "schema_version": "omnipull-run-index.v1",
        "generated_at": "2026-05-19T10:00:00Z",
        "source_path": "examples/omnipull-run-indexes/in-memory.json",
        "reports": [
            {
                "report_id": value,
                "run_id": "run-x",
                "generated_at": "2026-05-19T10:00:00Z",
                "source_path": "examples/omnipull-reports/x.json",
            }
        ],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    with pytest.raises(ValueError, match="reports\\[\\]\\.report_id"):
        select_latest_report(index)


@pytest.mark.parametrize("value", [None, "", " examples/omnipull-reports/x.json "])
def test_select_latest_report_rejects_invalid_in_memory_source_path(value: object):
    index = {
        "schema_version": "omnipull-run-index.v1",
        "generated_at": "2026-05-19T10:00:00Z",
        "source_path": "examples/omnipull-run-indexes/in-memory.json",
        "reports": [
            {
                "report_id": "report-x",
                "run_id": "run-x",
                "generated_at": "2026-05-19T10:00:00Z",
                "source_path": value,
            }
        ],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }

    with pytest.raises(ValueError, match="reports\\[\\]\\.source_path"):
        select_latest_report(index)


# ---------------------------------------------------------------------------
# Runtime loader: negative contracts
# ---------------------------------------------------------------------------


def test_load_run_index_rejects_wrong_schema_version(tmp_path: Path):
    payload = _base_payload()
    payload["schema_version"] = "run-index.v1"
    index_path = _write_index(tmp_path, payload, name="bad-version.json")

    with pytest.raises(ValueError, match="schema_version"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_non_object_json(tmp_path: Path):
    index_path = tmp_path / "list.json"
    index_path.write_text(json.dumps(["nope"]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_unknown_top_level_field(tmp_path: Path):
    payload = _base_payload()
    payload["unexpected"] = "value"
    index_path = _write_index(tmp_path, payload, name="unknown-top.json")

    with pytest.raises(ValueError, match="unknown fields"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_unknown_report_entry_field(tmp_path: Path):
    payload = _base_payload()
    payload["reports"][0]["unexpected"] = "value"
    index_path = _write_index(tmp_path, payload, name="unknown-entry.json")

    with pytest.raises(ValueError, match="unknown fields"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_invalid_generated_at(tmp_path: Path):
    payload = _base_payload()
    payload["generated_at"] = "2026-05-19 10:00:00"
    index_path = _write_index(tmp_path, payload, name="bad-ts-top.json")

    with pytest.raises(ValueError, match="date-time"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_invalid_report_generated_at(tmp_path: Path):
    payload = _base_payload()
    payload["reports"][0]["generated_at"] = "not-a-timestamp"
    index_path = _write_index(tmp_path, payload, name="bad-ts-entry.json")

    with pytest.raises(ValueError, match="date-time"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_missing_boundary(tmp_path: Path):
    payload = _base_payload()
    payload.pop("boundary")
    index_path = _write_index(tmp_path, payload, name="no-boundary.json")

    with pytest.raises(ValueError, match="boundary"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_boundary_mismatch(tmp_path: Path):
    payload = _base_payload()
    payload["boundary"] = {
        "does_not_execute": False,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }
    index_path = _write_index(tmp_path, payload, name="bad-boundary.json")

    with pytest.raises(ValueError, match="boundary"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_boundary_extra_field(tmp_path: Path):
    payload = _base_payload()
    payload["boundary"] = {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
        "extra": True,
    }
    index_path = _write_index(tmp_path, payload, name="boundary-extra.json")

    with pytest.raises(ValueError, match="boundary"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_forbidden_top_level_fields(tmp_path: Path):
    payload = _base_payload()
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
    index_path = _write_index(tmp_path, payload, name="forbidden-top.json")

    with pytest.raises(ValueError, match="forbidden fields"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_forbidden_report_entry_fields(tmp_path: Path):
    payload = _base_payload()
    payload["reports"][0]["action"] = "switch-main"
    index_path = _write_index(tmp_path, payload, name="forbidden-entry.json")

    with pytest.raises(ValueError, match="forbidden fields"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_source_path_mismatch(tmp_path: Path):
    payload = _base_payload()
    index_path = tmp_path / "real.json"
    payload["source_path"] = str(tmp_path / "different.json")
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_path"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_dot_slash_alias_mismatch(tmp_path: Path):
    payload = _base_payload()
    nested = tmp_path / "nested"
    nested.mkdir()
    index_path = nested / "index.json"
    payload["source_path"] = f"{nested}/./index.json"
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_path"):
        load_omnipull_run_index(index_path)


def test_load_run_index_rejects_whitespace_padded_source_path(tmp_path: Path):
    payload = _base_payload()
    index_path = tmp_path / "padded.json"
    payload["source_path"] = f"  {index_path}  "
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_path"):
        load_omnipull_run_index(index_path)


@pytest.mark.parametrize(
    "field",
    ["report_id", "run_id", "source_path"],
)
def test_load_run_index_rejects_whitespace_padded_report_strings(
    tmp_path: Path, field: str
):
    payload = _base_payload()
    payload["reports"][0][field] = f" {payload['reports'][0][field]} "
    index_path = _write_index(tmp_path, payload, name=f"padded-{field}.json")

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        load_omnipull_run_index(index_path)


@pytest.mark.parametrize(
    "field",
    ["report_id", "run_id", "source_path"],
)
def test_load_run_index_rejects_blank_report_strings(tmp_path: Path, field: str):
    payload = _base_payload()
    payload["reports"][0][field] = "   "
    index_path = _write_index(tmp_path, payload, name=f"blank-{field}.json")

    with pytest.raises(ValueError, match=field):
        load_omnipull_run_index(index_path)


# ---------------------------------------------------------------------------
# Schema-level coverage (forbidden fields, missing fields, whitespace)
# ---------------------------------------------------------------------------


def test_schema_rejects_forbidden_top_level_fields():
    schema = _index_schema()
    base = _base_payload()

    for field in sorted(FORBIDDEN_INDEX_KEYS):
        candidate = json.loads(json.dumps(base))
        candidate[field] = "forbidden"
        with pytest.raises(ValidationError):
            validate_instance(candidate, schema, Path(f"forbidden-top-{field}.json"))


def test_schema_rejects_forbidden_report_entry_fields():
    schema = _index_schema()
    base = _base_payload()

    for field in sorted(FORBIDDEN_INDEX_KEYS):
        candidate = json.loads(json.dumps(base))
        candidate["reports"][0][field] = "forbidden"
        with pytest.raises(ValidationError):
            validate_instance(candidate, schema, Path(f"forbidden-entry-{field}.json"))


def test_schema_rejects_missing_required_top_level_fields():
    schema = _index_schema()
    required = ["schema_version", "generated_at", "source_path", "reports", "boundary"]

    for field in required:
        candidate = _base_payload()
        candidate.pop(field)
        with pytest.raises(ValidationError):
            validate_instance(candidate, schema, Path(f"missing-top-{field}.json"))


def test_schema_rejects_missing_required_report_entry_fields():
    schema = _index_schema()
    required = ["report_id", "run_id", "generated_at", "source_path"]

    for field in required:
        candidate = _base_payload()
        candidate["reports"][0].pop(field)
        with pytest.raises(ValidationError):
            validate_instance(candidate, schema, Path(f"missing-entry-{field}.json"))


def test_schema_rejects_boundary_false_and_extra_field():
    schema = _index_schema()
    candidate_false = _base_payload()
    candidate_false["boundary"] = {
        "does_not_execute": False,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }
    with pytest.raises(ValidationError):
        validate_instance(candidate_false, schema, Path("invalid-boundary-false.json"))

    candidate_extra = _base_payload()
    candidate_extra["boundary"] = {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
        "extra": True,
    }
    with pytest.raises(ValidationError):
        validate_instance(candidate_extra, schema, Path("invalid-boundary-extra.json"))


@pytest.mark.parametrize("field", ["source_path"])
def test_schema_rejects_whitespace_only_top_level_strings(field: str):
    schema = _index_schema()
    candidate = _base_payload()
    candidate[field] = "   "
    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"whitespace-top-{field}.json"))


@pytest.mark.parametrize("field", ["report_id", "run_id", "source_path"])
def test_schema_rejects_whitespace_padded_report_strings(field: str):
    schema = _index_schema()
    candidate = _base_payload()
    candidate["reports"][0][field] = f" {candidate['reports'][0][field]} "
    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path(f"whitespace-entry-{field}.json"))


def test_ref_schema_rejects_unknown_selected_by():
    schema = _ref_schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-report-refs" / "minimal-latest.json")
    candidate["selected_by"] = "earliest.generated_at"

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path("invalid-selected-by.json"))


def test_ref_schema_rejects_unknown_top_level_field():
    schema = _ref_schema()
    candidate = load_json(EXAMPLES_DIR / "omnipull-report-refs" / "minimal-latest.json")
    candidate["extra"] = "value"

    with pytest.raises(ValidationError):
        validate_instance(candidate, schema, Path("ref-unknown-field.json"))


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_omnipull_report_latest_cli_smoke_emits_valid_ref_json():
    index_path = Path("examples/omnipull-run-indexes/multiple-runs.json")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "latest",
            str(index_path),
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    payload = json.loads(result.stdout)
    validate_instance(payload, _ref_schema(), Path("latest-cli-smoke.json"))
    assert payload["selected_by"] == "latest.generated_at"
    assert payload["run_id"] == "run-2026-05-16-003"


def test_omnipull_report_latest_cli_rejects_missing_file(tmp_path: Path):
    missing_path = tmp_path / "missing.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "latest",
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


def test_omnipull_report_latest_cli_rejects_invalid_json(tmp_path: Path):
    bad_path = tmp_path / "broken.json"
    bad_path.write_text("{not json", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "latest",
            str(bad_path),
            "--json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0


def test_omnipull_report_latest_cli_rejects_invalid_schema(tmp_path: Path):
    bad_path = tmp_path / "wrong-schema.json"
    bad_path.write_text(
        json.dumps(
            {
                "schema_version": "run-index.v1",
                "runs": [{"run_id": "x", "status": "blocked"}],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "latest",
            str(bad_path),
            "--json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "schema_version" in result.stderr or "unknown fields" in result.stderr


def test_omnipull_report_latest_cli_rejects_empty_reports():
    index_path = Path("examples/omnipull-run-indexes/empty.json")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "latest",
            str(index_path),
            "--json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "empty" in result.stderr


def test_omnipull_report_latest_cli_rejects_dot_slash_alias_for_example():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "latest",
            "./examples/omnipull-run-indexes/multiple-runs.json",
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


def test_omnipull_report_latest_cli_requires_positional_run_index():
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
    assert "run_index_json" in result.stderr or "required" in result.stderr


def test_omnipull_report_latest_command_is_available():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "omnipull-report",
            "latest",
            "--help",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "run_index_json" in result.stdout
    assert "--json" in result.stdout


# ---------------------------------------------------------------------------
# Boundary invariants
# ---------------------------------------------------------------------------


def test_runtime_does_not_load_referenced_report_files(tmp_path: Path):
    payload = _base_payload()
    payload["reports"] = [
        {
            "report_id": "phantom-report",
            "run_id": "run-phantom",
            "generated_at": "2026-05-16T09:32:00Z",
            "source_path": "examples/omnipull-reports/does-not-exist.json",
        }
    ]
    index_path = _write_index(tmp_path, payload, name="phantom.json")

    loaded = load_omnipull_run_index(index_path)
    ref = select_latest_report(loaded)

    assert ref["source_path"] == "examples/omnipull-reports/does-not-exist.json"
    assert ref["report_id"] == "phantom-report"


def test_runtime_module_imports_no_subprocess_or_network():
    import ast

    import steuerboard.omnipull_run_indexes as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    forbidden = {"subprocess", "urllib", "requests", "socket", "glob", "shutil"}
    assert forbidden.isdisjoint(imported_modules), (
        f"omnipull_run_indexes imports forbidden modules: "
        f"{sorted(forbidden & imported_modules)}"
    )
    assert "/home/alex/logs/omnipull" not in source
