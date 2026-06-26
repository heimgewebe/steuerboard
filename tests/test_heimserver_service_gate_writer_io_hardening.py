"""Focused regressions for writer path-like, encoding, and context-exit failures."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import steuerboard.heimserver_service_gate_writer as writer
from steuerboard.heimserver_service_gate_writer import (
    HeimserverServiceGateWriteError,
    write_heimserver_service_gate_assessment,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = (
    ROOT
    / "examples"
    / "heimserver-service-gate-assessments"
    / "golden-passed-single-service-fresh.json"
)


def _golden_assessment() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


class _ExplodingPathLike:
    def __init__(self, exception_type: type[Exception]) -> None:
        self._exception_type = exception_type

    def __fspath__(self) -> str:
        raise self._exception_type("path conversion failed")

    def __str__(self) -> str:
        return "exploding-path-like"


@pytest.mark.parametrize("exception_type", [RuntimeError, OSError])
def test_pathlike_conversion_errors_are_structured(
    exception_type: type[Exception],
) -> None:
    with pytest.raises(HeimserverServiceGateWriteError) as exc_info:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=_ExplodingPathLike(exception_type),  # type: ignore[arg-type]
        )

    error = exc_info.value
    assert error.code == "invalid_output_path"
    assert error.stage == "output_path"
    assert error.path == "exploding-path-like"
    assert isinstance(error.__cause__, exception_type)


def test_unpaired_surrogate_is_structured_serialization_error(tmp_path: Path) -> None:
    assessment = _golden_assessment()
    assessment["evidence"] = [chr(0xD800)]
    target = tmp_path / "assessment.json"

    with pytest.raises(HeimserverServiceGateWriteError) as exc_info:
        write_heimserver_service_gate_assessment(
            assessment=assessment,
            output_path=target,
        )

    error = exc_info.value
    assert error.code == "output_serialize_failed"
    assert error.stage == "output_serialize"
    assert isinstance(error.__cause__, UnicodeEncodeError)
    assert not target.exists()
    assert not os.path.lexists(target)
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


class _ExitFailingHandle:
    def __enter__(self) -> "_ExitFailingHandle":
        return self

    def write(self, payload: bytes) -> int:
        return len(payload)

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        raise OSError("close failed")


def test_context_exit_failure_removes_tempfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "assessment.json"

    def exit_failing_fdopen(_fd: int, mode: str) -> _ExitFailingHandle:
        assert mode == "wb"
        return _ExitFailingHandle()

    monkeypatch.setattr(writer._os, "fdopen", exit_failing_fdopen)

    with pytest.raises(HeimserverServiceGateWriteError) as exc_info:
        write_heimserver_service_gate_assessment(
            assessment=_golden_assessment(),
            output_path=target,
        )

    error = exc_info.value
    assert error.code == "output_write_failed"
    assert error.stage == "output_write"
    assert isinstance(error.__cause__, OSError)
    assert not target.exists()
    assert not os.path.lexists(target)
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []
