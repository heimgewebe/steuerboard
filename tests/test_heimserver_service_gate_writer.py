from __future__ import annotations

import ast
import copy
import json
import math
import os
from pathlib import Path
from typing import Any

import pytest

import steuerboard.heimserver_service_gate_writer as writer
from steuerboard.heimserver_service_gate_writer import (
    HeimserverServiceGateWriteError,
    write_heimserver_service_gate_assessment,
)


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "examples" / "heimserver-service-gate-assessments"
GOLDEN_PATHS = sorted(GOLDEN_DIR.glob("golden-*.json"))
ASSESSMENT_SCHEMA_NAME = "heimserver-service-gate-assessment.v1.schema.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _golden_assessment() -> dict[str, Any]:
    return _load_json(GOLDEN_DIR / "golden-passed-single-service-fresh.json")


def _expected_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _assert_writer_error(
    exc: pytest.ExceptionInfo[HeimserverServiceGateWriteError],
    *,
    code: str,
    stage: str,
    path: Path | str | None = None,
) -> HeimserverServiceGateWriteError:
    error = exc.value
    assert error.code == code
    assert error.stage == stage
    assert error.detail
    if path is not None:
        assert error.path == str(path)
    assert code in str(error)
    assert stage in str(error)
    return error


def _assert_no_target_or_temp(target: Path) -> None:
    assert not target.exists()
    assert not os.path.lexists(target)
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def _patch_schema(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: bytes) -> Path:
    schema_path = tmp_path / "patched-assessment.schema.json"
    schema_path.write_bytes(content)
    monkeypatch.setattr(writer, "_ASSESSMENT_SCHEMA_PATH", schema_path)
    return schema_path


def test_golden_inventory_has_the_expected_fourteen_writer_inputs() -> None:
    assert len(GOLDEN_PATHS) == 14


def test_writes_valid_assessment_as_exact_deterministic_json(tmp_path: Path) -> None:
    assessment = _golden_assessment()
    original = copy.deepcopy(assessment)
    target = tmp_path / "assessment.json"

    returned = write_heimserver_service_gate_assessment(
        assessment=assessment,
        output_path=target,
    )

    assert returned == target.resolve()
    assert returned.is_absolute()
    assert assessment == original
    assert json.loads(target.read_text(encoding="utf-8")) == original
    assert target.read_bytes() == _expected_bytes(original)
    assert target.read_bytes().endswith(b"\n")
    assert not target.read_bytes().endswith(b"\n\n")


@pytest.mark.parametrize("golden_path", GOLDEN_PATHS, ids=lambda path: path.name)
def test_all_golden_assessments_roundtrip_without_structure_changes(
    tmp_path: Path, golden_path: Path
) -> None:
    assessment = _load_json(golden_path)
    target = tmp_path / golden_path.name

    returned = write_heimserver_service_gate_assessment(
        assessment=assessment,
        output_path=target,
    )

    assert returned == target.resolve()
    assert json.loads(target.read_text(encoding="utf-8")) == assessment
    assert target.read_bytes() == _expected_bytes(assessment)


def test_input_insertion_order_does_not_change_output_bytes(tmp_path: Path) -> None:
    assessment = _golden_assessment()
    reordered = dict(reversed(list(assessment.items())))
    reordered["inputs"] = dict(reversed(list(assessment["inputs"].items())))
    reordered["subject"] = dict(reversed(list(assessment["subject"].items())))

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_heimserver_service_gate_assessment(assessment=assessment, output_path=first)
    write_heimserver_service_gate_assessment(assessment=reordered, output_path=second)

    assert first.read_bytes() == second.read_bytes()


def test_non_ascii_text_is_written_as_utf8_not_escape_sequences(tmp_path: Path) -> None:
    assessment = _golden_assessment()
    assessment["evidence"] = ["Pruefung: Gemüse und Maßstab"]
    target = tmp_path / "assessment.json"

    write_heimserver_service_gate_assessment(assessment=assessment, output_path=target)

    content = target.read_bytes()
    assert "Gemüse".encode("utf-8") in content
    assert b"Gem\\u00fcse" not in content
    assert content == _expected_bytes(assessment)


@pytest.mark.parametrize("bad_number", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected_by_strict_serialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_number: float
) -> None:
    _patch_schema(
        monkeypatch,
        tmp_path,
        b'{"$schema":"https://json-schema.org/draft/2020-12/schema"}',
    )
    target = tmp_path / "assessment.json"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment={"value": bad_number},
            output_path=target,
        )

    _assert_writer_error(exc, code="output_serialize_failed", stage="output_serialize")
    assert exc.value.__cause__ is not None
    _assert_no_target_or_temp(target)


def test_non_json_serializable_object_is_not_silently_stringified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_schema(
        monkeypatch,
        tmp_path,
        b'{"$schema":"https://json-schema.org/draft/2020-12/schema"}',
    )
    target = tmp_path / "assessment.json"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment={"value": object()},
            output_path=target,
        )

    _assert_writer_error(exc, code="output_serialize_failed", stage="output_serialize")
    assert exc.value.__cause__ is not None
    _assert_no_target_or_temp(target)


def test_existing_file_is_rejected_and_left_byte_exact(tmp_path: Path) -> None:
    target = tmp_path / "assessment.json"
    sentinel = b"sentinel\n"
    target.write_bytes(sentinel)

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(
        exc,
        code="output_exists",
        stage="output_path",
        path=target.resolve(),
    )
    assert target.read_bytes() == sentinel


def test_existing_directory_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "assessment.json"
    target.mkdir()

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="output_exists", stage="output_path", path=target)
    assert target.is_dir()


def test_existing_symlink_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("real", encoding="utf-8")
    target = tmp_path / "assessment.json"
    try:
        target.symlink_to(real)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="output_exists", stage="output_path", path=target)
    assert target.is_symlink()
    assert real.read_text(encoding="utf-8") == "real"


def test_dangling_symlink_is_rejected_as_collision(tmp_path: Path) -> None:
    target = tmp_path / "assessment.json"
    try:
        target.symlink_to(tmp_path / "missing-target.json")
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="output_exists", stage="output_path")
    assert os.path.lexists(target)
    assert not target.exists()


def test_missing_parent_is_rejected_and_not_created(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "assessment.json"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="invalid_output_path", stage="output_path")
    assert not target.parent.exists()
    assert not os.path.lexists(target)


def test_parent_that_is_file_is_rejected(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.write_text("not a directory", encoding="utf-8")
    target = parent / "assessment.json"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="invalid_output_path", stage="output_path")
    assert parent.read_text(encoding="utf-8") == "not a directory"


def test_embedded_nul_in_output_path_is_structured_writer_error(tmp_path: Path) -> None:
    target = str(tmp_path / "bad\0name.json")

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="invalid_output_path", stage="output_path")


def test_relative_output_path_is_resolved_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "out").mkdir()
    monkeypatch.chdir(tmp_path)

    returned = write_heimserver_service_gate_assessment(
        assessment=_golden_assessment(),
        output_path=Path("out") / "assessment.json",
    )

    assert returned == (tmp_path / "out" / "assessment.json").resolve()
    assert returned.read_bytes() == _expected_bytes(_golden_assessment())


def test_invalid_assessment_wins_over_existing_target_collision(tmp_path: Path) -> None:
    target = tmp_path / "assessment.json"
    target.write_bytes(b"sentinel")
    assessment = _golden_assessment()
    assessment["subject"]["host"] = ""

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=assessment,
            output_path=target,
        )

    _assert_writer_error(exc, code="output_schema_invalid", stage="output_schema")
    assert target.read_bytes() == b"sentinel"


def test_invalid_parent_wins_over_invalid_assessment(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "assessment.json"
    assessment = _golden_assessment()
    assessment["subject"]["host"] = ""

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=assessment,
            output_path=target,
        )

    _assert_writer_error(exc, code="invalid_output_path", stage="output_path")


def test_invalid_assessment_creates_no_file(tmp_path: Path) -> None:
    target = tmp_path / "assessment.json"
    assessment = _golden_assessment()
    assessment["unexpected-key"] = "SECRET_VALUE_SHOULD_NOT_LEAK"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=assessment,
            output_path=target,
        )

    error = _assert_writer_error(exc, code="output_schema_invalid", stage="output_schema")
    assert "SECRET_VALUE_SHOULD_NOT_LEAK" not in error.detail
    _assert_no_target_or_temp(target)


def test_missing_assessment_schema_is_contract_load_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(writer, "_ASSESSMENT_SCHEMA_PATH", tmp_path / "missing.schema.json")
    target = tmp_path / "assessment.json"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="contract_load_failed", stage="contract_load")
    assert exc.value.__cause__ is not None
    _assert_no_target_or_temp(target)


@pytest.mark.parametrize(
    ("content", "code", "stage", "expect_cause"),
    [
        (b"\xff", "contract_load_failed", "contract_load", True),
        (b"{bad json", "contract_load_failed", "contract_load", True),
        (
            b'{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","type":"object"}',
            "contract_load_failed",
            "contract_load",
            True,
        ),
        (b"true", "contract_schema_invalid", "contract_schema", False),
        (
            b'{"$schema":"https://json-schema.org/draft/2020-12/schema","type":123}',
            "contract_schema_invalid",
            "contract_schema",
            True,
        ),
    ],
    ids=[
        "invalid-utf8",
        "invalid-json",
        "duplicate-key",
        "boolean-schema",
        "meta-schema-invalid",
    ],
)
def test_schema_load_and_shape_failures_are_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    code: str,
    stage: str,
    expect_cause: bool,
) -> None:
    _patch_schema(monkeypatch, tmp_path, content)
    target = tmp_path / "assessment.json"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code=code, stage=stage)
    if expect_cause:
        assert exc.value.__cause__ is not None
    _assert_no_target_or_temp(target)


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef", "$recursiveRef"])
def test_schema_reference_keywords_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keyword: str
) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        keyword: "#",
    }
    _patch_schema(monkeypatch, tmp_path, json.dumps(schema).encode("utf-8"))
    target = tmp_path / "assessment.json"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="contract_schema_invalid", stage="contract_schema")
    assert keyword not in exc.value.detail
    _assert_no_target_or_temp(target)


def test_schema_in_output_directory_has_no_authority(tmp_path: Path) -> None:
    (tmp_path / ASSESSMENT_SCHEMA_NAME).write_text("{}", encoding="utf-8")
    target = tmp_path / "assessment.json"
    assessment = _golden_assessment()
    assessment["unexpected"] = "would pass a permissive local schema"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=assessment,
            output_path=target,
        )

    _assert_writer_error(exc, code="output_schema_invalid", stage="output_schema")
    _assert_no_target_or_temp(target)


def test_only_assessment_schema_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = writer._Path.read_bytes
    loaded: list[str] = []

    def guard(path: Path) -> bytes:
        loaded.append(path.name)
        if path.name != ASSESSMENT_SCHEMA_NAME:
            raise AssertionError(f"unexpected schema load: {path}")
        return original(path)

    monkeypatch.setattr(writer._Path, "read_bytes", guard)

    write_heimserver_service_gate_assessment(
        assessment=_golden_assessment(),
        output_path=tmp_path / "assessment.json",
    )

    assert loaded == [ASSESSMENT_SCHEMA_NAME]


def test_schema_diagnostics_do_not_leak_instance_values_or_keys(tmp_path: Path) -> None:
    target = tmp_path / "assessment.json"
    assessment = _golden_assessment()
    assessment["SECRET_UNTRUSTED_KEY"] = "SECRET_UNTRUSTED_VALUE"

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=assessment,
            output_path=target,
        )

    error = _assert_writer_error(exc, code="output_schema_invalid", stage="output_schema")
    assert "SECRET_UNTRUSTED_KEY" not in error.detail
    assert "SECRET_UNTRUSTED_VALUE" not in error.detail
    assert "absolute_path" not in error.detail
    assert "schema_path=" in error.detail


def test_mkstemp_failure_is_write_error_and_leaves_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "assessment.json"

    def fail_mkstemp(**_kwargs: Any) -> tuple[int, str]:
        raise OSError("mkstemp failed")

    monkeypatch.setattr(writer._tempfile, "mkstemp", fail_mkstemp)

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="output_write_failed", stage="output_write")
    assert exc.value.__cause__ is not None
    _assert_no_target_or_temp(target)


@pytest.mark.parametrize("message", ["write failed", "close failed"])
def test_temp_write_failures_remove_tempfile_and_create_no_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    target = tmp_path / "assessment.json"

    def fail_write(_fd: int, _payload: bytes) -> None:
        raise OSError(message)

    monkeypatch.setattr(writer, "_write_bytes_to_fd", fail_write)

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="output_write_failed", stage="output_write")
    assert exc.value.__cause__ is not None
    _assert_no_target_or_temp(target)


def test_publish_failure_removes_tempfile_and_leaves_target_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "assessment.json"

    def fail_replace(_src: Path | str, _dst: Path | str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(writer._os, "replace", fail_replace)

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="output_publish_failed", stage="output_publish")
    assert exc.value.__cause__ is not None
    _assert_no_target_or_temp(target)


def test_existing_sentinel_target_is_not_touched_even_if_replace_would_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "assessment.json"
    target.write_bytes(b"sentinel")

    def fail_replace(_src: Path | str, _dst: Path | str) -> None:
        raise AssertionError("replace must not be reached for an existing target")

    monkeypatch.setattr(writer._os, "replace", fail_replace)

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    _assert_writer_error(exc, code="output_exists", stage="output_path")
    assert target.read_bytes() == b"sentinel"


def test_error_attributes_are_exact_for_output_collision(tmp_path: Path) -> None:
    target = tmp_path / "assessment.json"
    target.write_text("exists", encoding="utf-8")

    with pytest.raises(HeimserverServiceGateWriteError) as exc:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    error = exc.value
    assert error.code == "output_exists"
    assert error.stage == "output_path"
    assert error.path == str(target.resolve())
    assert error.detail == "output target already exists"


def test_writer_public_api_is_limited_to_function_and_error_class() -> None:
    assert writer.__all__ == [
        "HeimserverServiceGateWriteError",
        "write_heimserver_service_gate_assessment",
    ]
    public = {name for name in vars(writer) if not name.startswith("_")}
    assert public == set(writer.__all__)


def test_writer_ast_boundary_excludes_producer_adapter_cli_runbook_and_runtime_actions() -> None:
    source_path = ROOT / "steuerboard" / "heimserver_service_gate_writer.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    prohibited_imports = {
        "steuerboard.heimserver_service_gate",
        "steuerboard.heimserver_service_gate_artifacts",
        "steuerboard.cli",
        "steuerboard.runbooks",
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "time",
        "datetime",
    }
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                calls.add(func.attr)

    assert not any(
        imported == prohibited or imported.startswith(f"{prohibited}.")
        for imported in imports
        for prohibited in prohibited_imports
    )
    assert "derive_heimserver_service_gate_assessment" not in calls
    assert "derive_heimserver_service_gate_assessment_from_refs" not in calls
    assert "mkdir" not in calls
    assert "chmod" not in calls
    assert "chown" not in calls
    assert "systemctl" not in source
    assert "tailscale" not in source
    assert "ssh" not in source.lower()
    assert "SCHEMA_MAP" not in source
    assert "glob" not in calls
    assert "rglob" not in calls
    assert "iterdir" not in calls
    assert "walk" not in calls
