"""Safe artifact input adapter for the Heimserver-Service-Gate producer (Phase 11F-I).

This module is the first controlled bridge that makes the pure in-memory producer
``steuerboard.heimserver_service_gate.derive_heimserver_service_gate_assessment``
reachable through explicit, artifact-root-relative artifact references.

The adapter owns exactly the technical loading boundary and nothing else:

* it checks exactly three ``input_refs``;
* it resolves each referenced file safely inside one allowed ``artifact_root``
  (no absolute paths, no ``..`` traversal, no symlink escape from the root);
* it reads each file's raw bytes exactly once;
* it binds the declared SHA-256 to those exact bytes;
* it decodes the same bytes strictly as UTF-8 and then strict JSON
  (rejecting duplicate object keys and non-finite ``NaN``/``Infinity`` numbers);
* it validates the three payloads against the canonical Draft 2020-12 schemas;
* it calls the unchanged producer exactly once;
* it validates the producer's assessment against the assessment schema;
* it returns the assessment as an independent in-memory dictionary.

Contract authority: the canonical schemas are always loaded from the steuerboard
checkout (``_SCHEMAS_DIR``), never from ``artifact_root``, so a caller cannot
smuggle a weakened replacement schema next to the artifacts. The four canonical
schemas must be self-contained (no ``$ref``/``$dynamicRef``/``$recursiveRef``) so
no reference resolution can occur, the assessment ``inputs`` subschema is probed
for adapter compatibility, and each loaded payload passes a narrow producer
preimage-shape guard. ``artifact_root`` need not be a git repository.

Error boundary: technical loading failures are raised as
:class:`HeimserverServiceGateArtifactError`. They are never translated into
assessment reason codes, and the producer's own domain ``ValueError``\\s are not
caught or re-wrapped here.

Threat model: the adapter defends against static path escape and ordinary
misconfiguration. It does **not** claim full protection against a concurrently
acting actor with write access inside the artifact root (a TOCTOU mutation
between path check and ``read_bytes()`` needs only write permission on that
root, not system privileges). Small local steuerboard artifacts are read fully
into memory; this slice intentionally introduces no file-size limit. This
adapter assumes the current steuerboard checkout / local-install layout
(code-relative top-level ``schemas/``); it performs no packaging reform.

Diagnostics: schema-validation failures report only the failing schema keyword
and the trusted schema-side path; artifact instance values and untrusted JSON
keys are never placed in the exception detail. The declared reference path is
intentionally retained in the structured ``path`` attribute.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from steuerboard.heimserver_service_gate import (
    derive_heimserver_service_gate_assessment,
)

__all__ = [
    "HeimserverServiceGateArtifactError",
    "derive_heimserver_service_gate_assessment_from_refs",
]

# Canonical schemas always come from the steuerboard checkout, never from the
# caller-supplied artifact root. This is the contract-authority boundary.
_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

_REQUIRED_INPUTS = (
    "server_facts_ref",
    "expectation_ref",
    "service_evidence_ref",
)

_INPUT_SCHEMAS = {
    "server_facts_ref": "server-facts.v1.schema.json",
    "expectation_ref": "heimserver-service-expectation.v1.schema.json",
    "service_evidence_ref": "heimserver-service-evidence.v1.schema.json",
}

_ASSESSMENT_SCHEMA_FILENAME = "heimserver-service-gate-assessment.v1.schema.json"

# Canonical schemas are loaded and checked up front, in a fixed,
# caller-independent order: the three input contracts followed by the
# assessment output contract.
_CANONICAL_SCHEMA_FILENAMES = (
    _INPUT_SCHEMAS["server_facts_ref"],
    _INPUT_SCHEMAS["expectation_ref"],
    _INPUT_SCHEMAS["service_evidence_ref"],
    _ASSESSMENT_SCHEMA_FILENAME,
)

# Diagnostic details never carry whole payloads or file contents.
_MAX_DETAIL_CHARS = 200

# This adapter accepts only self-contained, reference-free canonical schemas, so
# jsonschema never performs reference resolution (which could reach the network).
# Local references would require a deliberate later slice with an offline registry.
_FORBIDDEN_REFERENCE_KEYWORDS = ("$ref", "$dynamicRef", "$recursiveRef")


class HeimserverServiceGateArtifactError(ValueError):
    """Raised for any technical failure while loading service-gate artifacts.

    The error never represents a domain assessment outcome: the producer's own
    derivation ``ValueError``\\s are intentionally left to propagate unchanged.

    Machine-checkable attributes: ``code``, ``stage``, ``input_name``, ``path``.
    """

    def __init__(
        self,
        *,
        code: str,
        stage: str,
        input_name: str | None = None,
        path: str | None = None,
        detail: str,
    ) -> None:
        self.code = code
        self.stage = stage
        self.input_name = input_name
        self.path = path
        self.detail = detail

        message = f"[{code}] at stage {stage!r}"
        if input_name is not None:
            message += f" for {input_name}"
        if path is not None:
            message += f" (path={path!r})"
        message += f": {detail}"
        super().__init__(message)


class _StrictJsonError(ValueError):
    """Internal strict-JSON violation (duplicate key or non-finite number)."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            # Value-free: the offending key may come from an untrusted artifact.
            raise _StrictJsonError("duplicate object key")
        result[key] = value
    return result


def _reject_non_finite_constant(constant: str) -> Any:
    # Value-free: do not echo the rejected token from an untrusted artifact.
    raise _StrictJsonError("non-finite JSON number")


def _strict_json_loads(text: str) -> Any:
    """Parse JSON strictly, rejecting duplicate object keys and non-finite numbers."""
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite_constant,
    )


def _short(text: str) -> str:
    """Collapse and truncate a diagnostic string so payloads cannot leak."""
    collapsed = " ".join(text.split())
    if len(collapsed) > _MAX_DETAIL_CHARS:
        return collapsed[: _MAX_DETAIL_CHARS - 3] + "..."
    return collapsed


def _plain_json_copy(value: Any) -> Any:
    """Deep-copy into plain JSON-like containers (``dict``/``list``) for validation."""
    if isinstance(value, Mapping):
        return {key: _plain_json_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json_copy(item) for item in value]
    return value


def _first_error(
    validator: Draft202012Validator, instance: Any
) -> ValidationError | None:
    """Return the deterministically first schema error, or ``None`` if valid."""
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            tuple(str(part) for part in error.absolute_schema_path),
            error.message,
        ),
    )
    return errors[0] if errors else None


def _json_pointer(parts: Any) -> str:
    """Encode schema-path components as a JSON Pointer (RFC 6901)."""
    pointer = ""
    for part in parts:
        token = str(part).replace("~", "~0").replace("/", "~1")
        pointer += "/" + token
    return pointer or "/"


def _safe_schema_error_detail(error: ValidationError) -> str:
    """Build a diagnostic from trusted structure only.

    The instance value, the offending property name, ``error.message``, and
    ``repr(instance)`` may all originate from an untrusted artifact and are
    therefore never included. Only the failing schema keyword and the
    schema-side path (from the canonical schema) are emitted. ``absolute_path``
    is deliberately avoided because its components can be untrusted JSON keys.
    """
    keyword = str(error.validator)
    schema_path = _json_pointer(error.absolute_schema_path)
    return f"schema validation failed (keyword={keyword!r}, schema_path={schema_path!r})"


def _canonical_schema_path(filename: str) -> Path:
    return _SCHEMAS_DIR / filename


def _load_canonical_schemas() -> dict[str, Any]:
    """Load the four canonical schemas from ``_SCHEMAS_DIR`` in fixed order."""
    schemas: dict[str, Any] = {}
    for filename in _CANONICAL_SCHEMA_FILENAMES:
        schema_path = _canonical_schema_path(filename)
        try:
            raw_bytes = schema_path.read_bytes()
        except OSError as exc:
            raise HeimserverServiceGateArtifactError(
                code="contract_load_failed",
                stage="contract_load",
                path=filename,
                detail=f"canonical schema could not be read: {_short(str(exc))}",
            ) from exc
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HeimserverServiceGateArtifactError(
                code="contract_load_failed",
                stage="contract_load",
                path=filename,
                detail="canonical schema is not valid UTF-8",
            ) from exc
        try:
            schemas[filename] = _strict_json_loads(text)
        except (_StrictJsonError, json.JSONDecodeError) as exc:
            raise HeimserverServiceGateArtifactError(
                code="contract_load_failed",
                stage="contract_load",
                path=filename,
                detail=f"canonical schema is not valid strict JSON: {_short(str(exc))}",
            ) from exc
    return schemas


def _assert_schema_is_self_contained(*, schema: Any, filename: str) -> None:
    """Reject ``$ref``/``$dynamicRef``/``$recursiveRef`` anywhere in a schema.

    Guarantees the claimed offline behaviour: a reference-free schema can never
    trigger jsonschema reference resolution. The referenced URI is intentionally
    not echoed in the error detail.
    """
    stack: list[Any] = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in _FORBIDDEN_REFERENCE_KEYWORDS:
                    raise HeimserverServiceGateArtifactError(
                        code="contract_schema_invalid",
                        stage="contract_schema",
                        path=filename,
                        detail="canonical schema contains unsupported reference keyword",
                    )
                stack.append(value)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)


def _check_canonical_schemas(schemas: Mapping[str, Any]) -> None:
    """Validate that each canonical schema is itself usable by this adapter.

    ``check_schema`` only proves valid-JSON-Schema-ness, and a boolean schema
    (e.g. ``true``) passes it while being structurally incompatible with this
    adapter's contract authority. Each canonical schema must therefore be a
    JSON object (mapping) schema and must be self-contained (reference-free).
    """
    for filename in _CANONICAL_SCHEMA_FILENAMES:
        schema = schemas[filename]
        if not isinstance(schema, Mapping):
            raise HeimserverServiceGateArtifactError(
                code="contract_schema_invalid",
                stage="contract_schema",
                path=filename,
                detail="canonical schema must be a JSON object schema, not a boolean",
            )
        _assert_schema_is_self_contained(schema=schema, filename=filename)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise HeimserverServiceGateArtifactError(
                code="contract_schema_invalid",
                stage="contract_schema",
                path=filename,
                detail=(
                    "canonical schema is not a valid Draft 2020-12 schema: "
                    f"{_short(exc.message)}"
                ),
            ) from exc


def _extract_inputs_subschema(
    assessment_schema: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Extract ``properties.inputs`` from the assessment schema, structurally.

    A meta-schema-valid assessment contract may still lack a usable
    ``properties.inputs`` mapping (e.g. ``{"type": "object"}`` or a boolean
    schema). Such contracts are rejected as ``contract_schema_invalid`` rather
    than allowed to raise a raw ``KeyError``/``TypeError``. This is a technical
    adapter-compatibility check only; it does not duplicate the schema's
    semantic contract (required fields, reason-code rules, status rules).
    """
    if not isinstance(assessment_schema, Mapping):
        raise HeimserverServiceGateArtifactError(
            code="contract_schema_invalid",
            stage="contract_schema",
            path=_ASSESSMENT_SCHEMA_FILENAME,
            detail="assessment schema must be a JSON object schema",
        )
    properties = assessment_schema.get("properties")
    if not isinstance(properties, Mapping):
        raise HeimserverServiceGateArtifactError(
            code="contract_schema_invalid",
            stage="contract_schema",
            path=_ASSESSMENT_SCHEMA_FILENAME,
            detail="assessment schema is missing a mapping 'properties'",
        )
    inputs_subschema = properties.get("inputs")
    if not isinstance(inputs_subschema, Mapping):
        raise HeimserverServiceGateArtifactError(
            code="contract_schema_invalid",
            stage="contract_schema",
            path=_ASSESSMENT_SCHEMA_FILENAME,
            detail="assessment schema 'properties.inputs' must be a mapping subschema",
        )
    return inputs_subschema


def _inputs_compatibility_probes() -> tuple[dict[str, Any], list[Any]]:
    """One must-accept probe and several must-reject probes for the inputs subschema.

    These are consumer-driven behaviour probes, not a syntactic mirror of the
    schema. They encode exactly the reference shapes the adapter/producer can and
    cannot consume.
    """
    valid_ref = {"path": "artifact.json", "sha256": "0" * 64}

    def base() -> dict[str, Any]:
        return {name: dict(valid_ref) for name in _REQUIRED_INPUTS}

    def replace_ref(input_name: str, value: Any) -> dict[str, Any]:
        probe = base()
        probe[input_name] = value
        return probe

    valid = base()

    # Top-level structure probes (once).
    invalid: list[Any] = [{}]
    for input_name in _REQUIRED_INPUTS:
        invalid.append({k: dict(valid_ref) for k in _REQUIRED_INPUTS if k != input_name})
    extra = base()
    extra["extra_ref"] = dict(valid_ref)
    invalid.append(extra)

    # Nested per-reference malformations, applied symmetrically to every
    # canonical reference name (not only server_facts_ref).
    nested_bad_values: list[Any] = [
        None,
        "x",
        {"sha256": "0" * 64},
        {"path": "artifact.json"},
        {"path": "artifact.json", "sha256": "0" * 64, "extra": 1},
        {"path": "", "sha256": "0" * 64},
        {"path": "artifact.json", "sha256": "0" * 63},
        {"path": "artifact.json", "sha256": "A" * 64},
        {"path": "artifact.json", "sha256": "g" * 64},
    ]
    for input_name in _REQUIRED_INPUTS:
        for bad_value in nested_bad_values:
            invalid.append(replace_ref(input_name, copy.deepcopy(bad_value)))

    return valid, invalid


def _assert_inputs_subschema_compatible(inputs_subschema: Mapping[str, Any]) -> None:
    """Probe the assessment ``inputs`` subschema for adapter compatibility.

    A meta-schema-valid but too-weak subschema (e.g. ``{}``) would accept
    reference shapes the adapter cannot consume, later causing raw indexing
    errors. If the subschema rejects the canonical valid reference set, or
    accepts any adapter-incompatible shape, the canonical contract is unusable
    for this adapter -> ``contract_schema_invalid``. Probe instances are never
    placed in the error detail.
    """
    validator = Draft202012Validator(inputs_subschema)
    valid_probe, invalid_probes = _inputs_compatibility_probes()
    if _first_error(validator, valid_probe) is not None:
        raise HeimserverServiceGateArtifactError(
            code="contract_schema_invalid",
            stage="contract_schema",
            path=_ASSESSMENT_SCHEMA_FILENAME,
            detail="assessment 'inputs' subschema rejects a canonical valid reference set",
        )
    for probe in invalid_probes:
        if _first_error(validator, probe) is None:
            raise HeimserverServiceGateArtifactError(
                code="contract_schema_invalid",
                stage="contract_schema",
                path=_ASSESSMENT_SCHEMA_FILENAME,
                detail=(
                    "assessment 'inputs' subschema accepts an adapter-incompatible "
                    "reference shape"
                ),
            )


def _is_lower_hex64(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _assert_input_refs_form(candidate: Any) -> None:
    """Defensive contract-sanity guard on the actual ``input_refs``.

    Runs after JSON-schema validation, before any indexing. If the inputs
    subschema accepted a value this guard rejects, the canonical assessment
    contract is adapter-incompatible, so the failure is ``contract_schema_invalid``
    (not ``invalid_input_refs``). No payload values are placed in the detail.
    """

    def _fail(input_name: str | None, detail: str) -> "HeimserverServiceGateArtifactError":
        return HeimserverServiceGateArtifactError(
            code="contract_schema_invalid",
            stage="contract_schema",
            path=_ASSESSMENT_SCHEMA_FILENAME,
            input_name=input_name,
            detail=detail,
        )

    if not isinstance(candidate, Mapping):
        raise _fail(None, "input_refs is not a mapping after schema validation")
    if set(candidate.keys()) != set(_REQUIRED_INPUTS):
        raise _fail(None, "input_refs key set does not match the required references")
    for name in _REQUIRED_INPUTS:
        ref = candidate[name]
        if not isinstance(ref, Mapping):
            raise _fail(name, "reference is not a mapping")
        if set(ref.keys()) != {"path", "sha256"}:
            raise _fail(name, "reference does not have exactly 'path' and 'sha256'")
        path_value = ref["path"]
        if not isinstance(path_value, str) or not path_value:
            raise _fail(name, "reference 'path' is not a non-empty string")
        if not _is_lower_hex64(ref["sha256"]):
            raise _fail(name, "reference 'sha256' is not a 64-char lowercase hex string")


def _assert_producer_preimage_shape(*, input_name: str, payload: Any) -> None:
    """Verify the minimal structure the producer indexes/iterates directly.

    A too-weak input schema could pass a payload that the pure producer would
    then index into (e.g. ``server_facts["host"]["hostname"]``,
    ``expectation["host"]``, ``service_evidence["observed_at"]``) or iterate
    (``service_name``/``expected_role``/``evidence_status`` per element and a
    present Evidence ``evidence`` field as a list), raising a raw
    ``KeyError``/``TypeError``. If a payload passed its schema but
    violates this technically-required shape, the canonical schema is
    adapter-incompatible -> ``contract_schema_invalid``.

    Only the producer's direct preimage accesses are checked. The producer's own
    domain ``ValueError`` rules (e.g. ``freshness_status`` values) are not
    duplicated, and no payload values are echoed.
    """
    schema_file = _INPUT_SCHEMAS[input_name]

    def _fail(detail: str) -> "HeimserverServiceGateArtifactError":
        return HeimserverServiceGateArtifactError(
            code="contract_schema_invalid",
            stage="contract_schema",
            path=schema_file,
            input_name=input_name,
            detail=detail,
        )

    def _check_service_list(
        value: Any,
        required_keys: tuple[str, ...],
        label: str,
        *,
        list_keys: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(value, list):
            raise _fail(f"{label} is not a list")
        for element in value:
            if not isinstance(element, Mapping):
                raise _fail(f"{label} contains a non-object element")
            for key in required_keys:
                if key not in element:
                    raise _fail(f"{label} element is missing '{key}'")
            # The producer uses service_name as a set/dict key; a non-string
            # value (e.g. a list/object accepted by a too-weak schema) would
            # otherwise raise a raw unhashable-type TypeError in the producer.
            if not isinstance(element["service_name"], str):
                raise _fail(f"{label} element has a non-string 'service_name'")
            # Optional consumer-specific container checks stay deliberately
            # narrower than the canonical schema. The producer defaults a
            # missing evidence field to [], but directly iterates a present one.
            for key in list_keys:
                if key in element and not isinstance(element[key], list):
                    raise _fail(f"{label} element has a non-list '{key}'")

    if not isinstance(payload, Mapping):
        raise _fail("payload is not an object")

    if input_name == "server_facts_ref":
        host = payload.get("host")
        if not isinstance(host, Mapping):
            raise _fail("server_facts.host is not an object")
        if "hostname" not in host:
            raise _fail("server_facts.host is missing 'hostname'")
    elif input_name == "expectation_ref":
        if "host" not in payload:
            raise _fail("expectation is missing 'host'")
        if "expected_services" in payload:
            _check_service_list(
                payload["expected_services"],
                ("service_name", "expected_role"),
                "expectation.expected_services",
            )
    elif input_name == "service_evidence_ref":
        if "host" not in payload:
            raise _fail("service_evidence is missing 'host'")
        if "observed_at" not in payload:
            raise _fail("service_evidence is missing 'observed_at'")
        if "services" in payload:
            _check_service_list(
                payload["services"],
                ("service_name", "evidence_status"),
                "service_evidence.services",
                list_keys=("evidence",),
            )


def _validate_artifact_root(artifact_root: Any) -> Path:
    """Resolve and validate the allowed artifact root (no git calls)."""
    try:
        candidate = Path(artifact_root)
    except TypeError as exc:
        raise HeimserverServiceGateArtifactError(
            code="invalid_artifact_root",
            stage="artifact_root",
            detail="artifact_root must be a path-like value",
        ) from exc
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HeimserverServiceGateArtifactError(
            code="invalid_artifact_root",
            stage="artifact_root",
            detail="artifact_root does not exist",
        ) from exc
    except OSError as exc:
        raise HeimserverServiceGateArtifactError(
            code="invalid_artifact_root",
            stage="artifact_root",
            detail=f"artifact_root could not be resolved ({type(exc).__name__})",
        ) from exc
    except (ValueError, RuntimeError) as exc:
        # ValueError: embedded NUL byte. RuntimeError: symlink loop (reproduced
        # for input paths; the same resolve() call backs the artifact root).
        raise HeimserverServiceGateArtifactError(
            code="invalid_artifact_root",
            stage="artifact_root",
            detail=f"artifact_root could not be safely resolved ({type(exc).__name__})",
        ) from exc
    if not resolved.is_dir():
        raise HeimserverServiceGateArtifactError(
            code="invalid_artifact_root",
            stage="artifact_root",
            detail="artifact_root is not a directory",
        )
    return resolved


def _validate_input_refs(
    input_refs: Any, inputs_subschema: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Validate the caller's ``input_refs`` against the canonical ``inputs`` subschema.

    The subschema is taken verbatim from the assessment schema; it is never
    weakened or duplicated. Returns a canonical-order plain-dict copy preserving
    the lexical ``path`` and ``sha256`` values.
    """
    if not isinstance(input_refs, Mapping):
        raise HeimserverServiceGateArtifactError(
            code="invalid_input_refs",
            stage="input_refs",
            detail="input_refs must be a mapping",
        )
    candidate = _plain_json_copy(input_refs)
    validator = Draft202012Validator(inputs_subschema)
    error = _first_error(validator, candidate)
    if error is not None:
        # Only ever surface a canonical ref name; never an untrusted caller key.
        first_part = str(error.absolute_path[0]) if error.absolute_path else None
        input_name = first_part if first_part in _REQUIRED_INPUTS else None
        raise HeimserverServiceGateArtifactError(
            code="invalid_input_refs",
            stage="input_refs",
            input_name=input_name,
            detail=_safe_schema_error_detail(error),
        )
    # Defensive contract-sanity guard before any indexing: if the subschema let a
    # malformed value through, that is a contract defect, not a caller error.
    _assert_input_refs_form(candidate)
    return {name: dict(candidate[name]) for name in _REQUIRED_INPUTS}


def _resolve_safe_path(input_name: str, path_str: str, resolved_root: Path) -> Path:
    """Resolve a declared reference path safely inside ``resolved_root``."""
    raw = Path(path_str)
    if raw.is_absolute():
        raise HeimserverServiceGateArtifactError(
            code="unsafe_path",
            stage="path",
            input_name=input_name,
            path=path_str,
            detail="absolute paths are not allowed",
        )
    if ".." in raw.parts:
        raise HeimserverServiceGateArtifactError(
            code="unsafe_path",
            stage="path",
            input_name=input_name,
            path=path_str,
            detail="parent-directory traversal '..' is not allowed",
        )
    candidate = resolved_root / raw
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HeimserverServiceGateArtifactError(
            code="file_missing",
            stage="path",
            input_name=input_name,
            path=path_str,
            detail="referenced artifact does not exist",
        ) from exc
    except OSError as exc:
        raise HeimserverServiceGateArtifactError(
            code="unsafe_path",
            stage="path",
            input_name=input_name,
            path=path_str,
            detail=f"referenced path could not be resolved ({type(exc).__name__})",
        ) from exc
    except (ValueError, RuntimeError) as exc:
        # ValueError: embedded NUL byte. RuntimeError: symlink loop. Both are
        # raised by resolve() on a declared reference path and must not leak as
        # raw Python exceptions through the adapter boundary.
        raise HeimserverServiceGateArtifactError(
            code="unsafe_path",
            stage="path",
            input_name=input_name,
            path=path_str,
            detail=f"referenced path could not be safely resolved ({type(exc).__name__})",
        ) from exc
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise HeimserverServiceGateArtifactError(
            code="unsafe_path",
            stage="path",
            input_name=input_name,
            path=path_str,
            detail="resolved target escapes the artifact root",
        ) from exc
    if not resolved.is_file():
        raise HeimserverServiceGateArtifactError(
            code="not_regular_file",
            stage="path",
            input_name=input_name,
            path=path_str,
            detail="referenced target is not a regular file",
        )
    return resolved


def _load_input_payload(
    input_name: str,
    ref: Mapping[str, Any],
    resolved_root: Path,
    validator: Draft202012Validator,
) -> Any:
    """Resolve, read-once, hash-bind, decode, parse, and schema-check one input."""
    path_str = ref["path"]
    expected_sha256 = ref["sha256"]

    resolved_path = _resolve_safe_path(input_name, path_str, resolved_root)

    try:
        raw_bytes = resolved_path.read_bytes()
    except OSError as exc:
        raise HeimserverServiceGateArtifactError(
            code="read_failed",
            stage="read",
            input_name=input_name,
            path=path_str,
            detail=f"artifact could not be read ({type(exc).__name__})",
        ) from exc

    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise HeimserverServiceGateArtifactError(
            code="hash_mismatch",
            stage="hash",
            input_name=input_name,
            path=path_str,
            detail=(
                f"declared sha256 {expected_sha256} does not match "
                f"artifact-byte sha256 {actual_sha256}"
            ),
        )

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HeimserverServiceGateArtifactError(
            code="invalid_utf8",
            stage="utf8_decode",
            input_name=input_name,
            path=path_str,
            detail="artifact bytes are not valid UTF-8",
        ) from exc

    try:
        payload = _strict_json_loads(text)
    except _StrictJsonError as exc:
        # Strict-decoder messages are already value-free.
        raise HeimserverServiceGateArtifactError(
            code="invalid_json",
            stage="json_decode",
            input_name=input_name,
            path=path_str,
            detail=f"artifact JSON rejected: {exc}",
        ) from exc
    except json.JSONDecodeError as exc:
        # Emit only the position, never the full default message which could
        # echo untrusted content.
        raise HeimserverServiceGateArtifactError(
            code="invalid_json",
            stage="json_decode",
            input_name=input_name,
            path=path_str,
            detail=f"invalid JSON syntax at line {exc.lineno} column {exc.colno}",
        ) from exc

    error = _first_error(validator, payload)
    if error is not None:
        raise HeimserverServiceGateArtifactError(
            code="input_schema_invalid",
            stage="input_schema",
            input_name=input_name,
            path=path_str,
            detail=_safe_schema_error_detail(error),
        )
    # The payload passed its canonical schema; verify the minimal structure the
    # producer indexes directly. A violation here means the schema is too weak.
    _assert_producer_preimage_shape(input_name=input_name, payload=payload)
    return payload


def derive_heimserver_service_gate_assessment_from_refs(
    *,
    artifact_root: Path,
    input_refs: Mapping[str, Any],
) -> dict[str, Any]:
    """Safely load three referenced artifacts and derive the service-gate assessment.

    ``artifact_root`` is the only allowed location for the three input artifacts.
    The canonical schemas are loaded from the steuerboard checkout, not from
    ``artifact_root``.

    Deterministic failure priority (caller mapping/filesystem order never
    changes the first error):

    1. artifact root
    2. load the four canonical schemas (fixed order)
    3. check the four canonical schemas
    4. shape/contract of ``input_refs``
    5. ``server_facts_ref``
    6. ``expectation_ref``
    7. ``service_evidence_ref``
    8. producer call (its domain errors propagate unchanged)
    9. output schema

    Per input: lexical path -> resolution + root inclusion -> regular file ->
    read -> hash -> UTF-8 -> JSON -> input schema.

    Raises :class:`HeimserverServiceGateArtifactError` for technical loading
    failures. Returns a deep, independent copy of the validated assessment.
    """
    resolved_root = _validate_artifact_root(artifact_root)

    schemas = _load_canonical_schemas()
    _check_canonical_schemas(schemas)

    assessment_schema = schemas[_ASSESSMENT_SCHEMA_FILENAME]
    inputs_subschema = _extract_inputs_subschema(assessment_schema)
    _assert_inputs_subschema_compatible(inputs_subschema)

    canonical_refs = _validate_input_refs(input_refs, inputs_subschema)

    input_validators = {
        name: Draft202012Validator(schemas[_INPUT_SCHEMAS[name]])
        for name in _REQUIRED_INPUTS
    }

    payloads: dict[str, Any] = {}
    for name in _REQUIRED_INPUTS:
        payloads[name] = _load_input_payload(
            name, canonical_refs[name], resolved_root, input_validators[name]
        )

    # The producer stays pure and unchanged. Its own domain ValueErrors are not
    # caught or translated into HeimserverServiceGateArtifactError here.
    assessment = derive_heimserver_service_gate_assessment(
        server_facts=payloads["server_facts_ref"],
        expectation=payloads["expectation_ref"],
        service_evidence=payloads["service_evidence_ref"],
        input_refs=canonical_refs,
    )

    output_validator = Draft202012Validator(assessment_schema)
    output_error = _first_error(output_validator, assessment)
    if output_error is not None:
        raise HeimserverServiceGateArtifactError(
            code="output_schema_invalid",
            stage="output_schema",
            detail=_safe_schema_error_detail(output_error),
        )

    return copy.deepcopy(assessment)
