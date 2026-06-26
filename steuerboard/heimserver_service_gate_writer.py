"""Safe writer for Heimserver-Service-Gate assessment artifacts.

The writer persists one already produced assessment. It validates against the
canonical checkout schema, serializes deterministic strict JSON bytes, stages
those bytes in the target directory, and publishes with ``os.replace()``.

It does not load input artifacts, call producer or adapter code, invent a
filename, create parent directories, or claim race-free no-clobber or crash
durability.
"""

from __future__ import annotations

import json as _json
import os as _os
import tempfile as _tempfile
from collections.abc import Mapping as _Mapping
from pathlib import Path as _Path
from typing import Any as _Any

from jsonschema import Draft202012Validator as _Draft202012Validator
from jsonschema.exceptions import SchemaError as _SchemaError
from jsonschema.exceptions import ValidationError as _ValidationError

try:
    del annotations
except NameError:
    pass

__all__ = [
    "HeimserverServiceGateWriteError",
    "write_heimserver_service_gate_assessment",
]

_SCHEMAS_DIR = _Path(__file__).resolve().parent.parent / "schemas"
_ASSESSMENT_SCHEMA_PATH = (
    _SCHEMAS_DIR / "heimserver-service-gate-assessment.v1.schema.json"
)
_FORBIDDEN_REFERENCE_KEYWORDS = ("$ref", "$dynamicRef", "$recursiveRef")


class HeimserverServiceGateWriteError(ValueError):
    """Raised for technical failures at the assessment writer boundary."""

    def __init__(
        self,
        *,
        code: str,
        stage: str,
        path: str | None,
        detail: str,
    ) -> None:
        self.code = code
        self.stage = stage
        self.path = path
        self.detail = detail

        message = f"[{code}] at stage {stage!r}"
        if path is not None:
            message += f" (path={path!r})"
        message += f": {detail}"
        super().__init__(message)


class _StrictJsonError(ValueError):
    """Internal strict-JSON violation."""


def _error(
    *, code: str, stage: str, path: str | None, detail: str
) -> HeimserverServiceGateWriteError:
    return HeimserverServiceGateWriteError(
        code=code,
        stage=stage,
        path=path,
        detail=detail,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, _Any]]) -> dict[str, _Any]:
    result: dict[str, _Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError("duplicate object key")
        result[key] = value
    return result


def _reject_non_finite_constant(_constant: str) -> _Any:
    raise _StrictJsonError("non-finite JSON number")


def _strict_json_loads(text: str) -> _Any:
    return _json.loads(
        text,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite_constant,
    )


def _json_pointer(parts: _Any) -> str:
    pointer = ""
    for part in parts:
        token = str(part).replace("~", "~0").replace("/", "~1")
        pointer += "/" + token
    return pointer or "/"


def _schema_error_detail(error: _ValidationError) -> str:
    keyword = str(error.validator)
    schema_path = _json_pointer(error.absolute_schema_path)
    return f"schema validation failed (keyword={keyword!r}, schema_path={schema_path!r})"


def _schema_contract_error_detail(error: _SchemaError) -> str:
    keyword = str(getattr(error, "validator", "unknown"))
    schema_path = _json_pointer(getattr(error, "absolute_schema_path", ()))
    return (
        "canonical assessment schema is not a valid Draft 2020-12 schema "
        f"(keyword={keyword!r}, schema_path={schema_path!r})"
    )


def _snapshot_json_like(value: _Any) -> _Any:
    if isinstance(value, _Mapping):
        return {key: _snapshot_json_like(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snapshot_json_like(item) for item in value]
    return value


def _first_error(
    validator: _Draft202012Validator, instance: _Any
) -> _ValidationError | None:
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_schema_path),
            str(error.validator),
        ),
    )
    return errors[0] if errors else None


def _path_text(value: _Any) -> str | None:
    try:
        return str(value)
    except (TypeError, ValueError, RuntimeError, OSError):
        return None


def _resolve_output_path(output_path: _Any) -> _Path:
    raw_path = _path_text(output_path)
    try:
        candidate = _Path(output_path)
    except (TypeError, ValueError, RuntimeError, OSError) as exc:
        raise _error(
            code="invalid_output_path",
            stage="output_path",
            path=raw_path,
            detail="output_path must be a path-like value",
        ) from exc

    try:
        expanded = candidate.expanduser()
        expanded_text = str(expanded)
    except (TypeError, ValueError, RuntimeError, OSError) as exc:
        raise _error(
            code="invalid_output_path",
            stage="output_path",
            path=raw_path,
            detail="output_path could not be expanded",
        ) from exc

    if "\x00" in expanded_text:
        raise _error(
            code="invalid_output_path",
            stage="output_path",
            path=expanded_text,
            detail="output_path contains an embedded NUL byte",
        )

    try:
        resolved_parent = expanded.parent.resolve(strict=False)
        parent_exists = resolved_parent.exists()
        parent_is_dir = resolved_parent.is_dir()
    except (TypeError, ValueError, RuntimeError, OSError) as exc:
        raise _error(
            code="invalid_output_path",
            stage="output_path",
            path=expanded_text,
            detail="output parent could not be resolved or inspected",
        ) from exc

    target = resolved_parent / expanded.name
    if not parent_exists:
        raise _error(
            code="invalid_output_path",
            stage="output_path",
            path=str(target),
            detail="output parent directory does not exist",
        )
    if not parent_is_dir:
        raise _error(
            code="invalid_output_path",
            stage="output_path",
            path=str(target),
            detail="output parent is not a directory",
        )
    return target


def _target_entry_exists(target: _Path) -> bool:
    try:
        return _os.path.lexists(target)
    except (TypeError, ValueError, RuntimeError, OSError) as exc:
        raise _error(
            code="invalid_output_path",
            stage="output_path",
            path=str(target),
            detail="output target could not be inspected",
        ) from exc


def _require_target_absent(target: _Path) -> None:
    if _target_entry_exists(target):
        raise _error(
            code="output_exists",
            stage="output_path",
            path=str(target),
            detail="output target already exists",
        )


def _load_assessment_schema(output_path: str) -> _Any:
    try:
        raw_bytes = _ASSESSMENT_SCHEMA_PATH.read_bytes()
    except OSError as exc:
        raise _error(
            code="contract_load_failed",
            stage="contract_load",
            path=output_path,
            detail="canonical assessment schema could not be read",
        ) from exc

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error(
            code="contract_load_failed",
            stage="contract_load",
            path=output_path,
            detail="canonical assessment schema is not valid UTF-8",
        ) from exc

    try:
        return _strict_json_loads(text)
    except _StrictJsonError as exc:
        raise _error(
            code="contract_load_failed",
            stage="contract_load",
            path=output_path,
            detail=f"canonical assessment schema is not valid strict JSON: {exc}",
        ) from exc
    except _json.JSONDecodeError as exc:
        raise _error(
            code="contract_load_failed",
            stage="contract_load",
            path=output_path,
            detail=(
                "canonical assessment schema has invalid JSON syntax at "
                f"line {exc.lineno} column {exc.colno}"
            ),
        ) from exc


def _assert_reference_free(schema: _Any, output_path: str) -> None:
    stack: list[_Any] = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, _Mapping):
            for key, value in node.items():
                if key in _FORBIDDEN_REFERENCE_KEYWORDS:
                    raise _error(
                        code="contract_schema_invalid",
                        stage="contract_schema",
                        path=output_path,
                        detail=(
                            "canonical assessment schema contains unsupported "
                            "reference keyword"
                        ),
                    )
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)


def _check_assessment_schema(schema: _Any, output_path: str) -> None:
    if isinstance(schema, bool) or not isinstance(schema, _Mapping):
        raise _error(
            code="contract_schema_invalid",
            stage="contract_schema",
            path=output_path,
            detail=(
                "canonical assessment schema must be a JSON object schema, "
                "not a boolean"
            ),
        )
    try:
        _Draft202012Validator.check_schema(schema)
    except _SchemaError as exc:
        raise _error(
            code="contract_schema_invalid",
            stage="contract_schema",
            path=output_path,
            detail=_schema_contract_error_detail(exc),
        ) from exc
    _assert_reference_free(schema, output_path)


def _serialize_snapshot(snapshot: _Any, output_path: str) -> bytes:
    try:
        text = (
            _json.dumps(
                snapshot,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )
        return text.encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise _error(
            code="output_serialize_failed",
            stage="output_serialize",
            path=output_path,
            detail="assessment could not be serialized as strict UTF-8 JSON",
        ) from exc


def _write_bytes_to_fd(fd: int, payload: bytes) -> None:
    with _os.fdopen(fd, "wb") as handle:
        handle.write(payload)


def _remove_tempfile(temp_path: _Path | None) -> None:
    if temp_path is None:
        return
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass


def write_heimserver_service_gate_assessment(
    *,
    assessment: _Mapping[str, _Any],
    output_path: _Path,
) -> _Path:
    """Persist one assessment as deterministic validated JSON bytes."""
    target = _resolve_output_path(output_path)
    target_text = str(target)

    schema = _load_assessment_schema(target_text)
    _check_assessment_schema(schema, target_text)

    snapshot = _snapshot_json_like(assessment)
    validator = _Draft202012Validator(schema)
    validation_error = _first_error(validator, snapshot)
    if validation_error is not None:
        raise _error(
            code="output_schema_invalid",
            stage="output_schema",
            path=target_text,
            detail=_schema_error_detail(validation_error),
        )

    serialized_bytes = _serialize_snapshot(snapshot, target_text)
    _require_target_absent(target)

    fd: int | None = None
    temp_path: _Path | None = None
    published = False
    try:
        try:
            fd, temp_name = _tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
            )
            temp_path = _Path(temp_name)
        except OSError as exc:
            raise _error(
                code="output_write_failed",
                stage="output_write",
                path=target_text,
                detail="temporary output file could not be created",
            ) from exc

        try:
            _write_bytes_to_fd(fd, serialized_bytes)
            fd = None
        except OSError as exc:
            if fd is not None:
                try:
                    _os.close(fd)
                except OSError:
                    pass
                fd = None
            raise _error(
                code="output_write_failed",
                stage="output_write",
                path=target_text,
                detail="temporary output file could not be fully written",
            ) from exc

        _require_target_absent(target)
        try:
            _os.replace(temp_path, target)
            published = True
            temp_path = None
        except OSError as exc:
            raise _error(
                code="output_publish_failed",
                stage="output_publish",
                path=target_text,
                detail="temporary output file could not be published",
            ) from exc
    finally:
        if fd is not None:
            try:
                _os.close(fd)
            except OSError:
                pass
        if not published:
            _remove_tempfile(temp_path)

    return target
