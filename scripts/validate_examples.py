#!/usr/bin/env python3
"""Validate Phase 0b JSON examples against their schemas.

This is validation scaffolding only. It does not scan repositories, run Git, or
execute steuerboard actions.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "examples"
SCHEMAS_DIR = ROOT / "schemas"

SCHEMA_MAP = {
    "action-capabilities": SCHEMAS_DIR / "action-capability.v1.schema.json",
    "action-approvals": SCHEMAS_DIR / "action-approval.v1.schema.json",
    "action-plans": SCHEMAS_DIR / "action-plan.v1.schema.json",
    "assessment-explanations": SCHEMAS_DIR / "repo-assessment-explanation.v1.schema.json",
    "assessments": SCHEMAS_DIR / "repo-assessment.v1.schema.json",
    "duplicates": SCHEMAS_DIR / "repo-duplicates.v1.schema.json",
    "evidence": SCHEMAS_DIR / "command-trace.v1.schema.json",
    "failure-cases": SCHEMAS_DIR / "falsification-case.v1.schema.json",
    "inventories": SCHEMAS_DIR / "repo-inventory.v1.schema.json",
    "local-configs": SCHEMAS_DIR / "local-config.v1.schema.json",
    "omnipull-report-refs": SCHEMAS_DIR / "omnipull-report-ref.v1.schema.json",
    "omnipull-reports": SCHEMAS_DIR / "omnipull-report.v1.schema.json",
    "omnipull-run-indexes": SCHEMAS_DIR / "omnipull-run-index.v1.schema.json",
    "observations": SCHEMAS_DIR / "repo-observation.v1.schema.json",
    "redaction-policies": SCHEMAS_DIR / "redaction-policy.v1.schema.json",
    "remote-refresh-results": SCHEMAS_DIR / "remote-refresh-result.v1.schema.json",
    "run-indexes": SCHEMAS_DIR / "run-index.v1.schema.json",
    "run-results": SCHEMAS_DIR / "run-result.v1.schema.json",
    "scope-explanations": SCHEMAS_DIR / "scope-explanation.v1.schema.json",
    "source-refs": SCHEMAS_DIR / "source-ref.v1.schema.json",
}

RFC3339_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class ValidationError(Exception):
    """Raised when the built-in minimal validator finds an invalid example."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_schema_paths() -> list[Path]:
    return sorted(SCHEMAS_DIR.glob("*.schema.json"))


def _is_jsonschema_available() -> bool:
    return importlib.util.find_spec("jsonschema") is not None


def _type_matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_type_matches(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _is_date_time(value: str) -> bool:
    if RFC3339_DATE_TIME_RE.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def minimal_validate(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Small fallback validator for the schema subset used by this repository.

    This is intentionally not a full JSON Schema implementation. It enforces the
    contract primitives used by repo examples when the external jsonschema
    package is unavailable.
    """
    import re

    def type_matches(value: Any, expected: str) -> bool:
        if expected == "object":
            return isinstance(value, dict)
        if expected == "array":
            return isinstance(value, list)
        if expected == "string":
            return isinstance(value, str)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "null":
            return value is None
        raise ValidationError(f"{path}: unsupported schema type {expected!r}")

    if "anyOf" in schema:
        errors: list[str] = []
        matched_anyof = False
        for index, subschema in enumerate(schema["anyOf"]):
            try:
                minimal_validate(instance, subschema, path)
                matched_anyof = True
                break
            except ValidationError as exc:
                errors.append(f"anyOf[{index}]: {exc}")
        if not matched_anyof:
            raise ValidationError(f"{path}: does not match anyOf ({'; '.join(errors)})")

    if "oneOf" in schema:
        matches = 0
        errors: list[str] = []
        for index, subschema in enumerate(schema["oneOf"]):
            try:
                minimal_validate(instance, subschema, path)
                matches += 1
            except ValidationError as exc:
                errors.append(f"oneOf[{index}]: {exc}")
        if matches != 1:
            raise ValidationError(f"{path}: expected exactly one oneOf match, got {matches}; {'; '.join(errors)}")

    if "allOf" in schema:
        for index, subschema in enumerate(schema["allOf"]):
            minimal_validate(instance, subschema, f"{path}.allOf[{index}]")

    if "not" in schema:
        try:
            minimal_validate(instance, schema["not"], f"{path}.not")
        except ValidationError:
            pass
        else:
            raise ValidationError(f"{path}: instance matches forbidden schema")

    if "if" in schema:
        try:
            minimal_validate(instance, schema["if"], f"{path}.if")
            if_matches = True
        except ValidationError:
            if_matches = False

        if if_matches and "then" in schema:
            minimal_validate(instance, schema["then"], f"{path}.then")
        if not if_matches and "else" in schema:
            minimal_validate(instance, schema["else"], f"{path}.else")

    if "const" in schema and instance != schema["const"]:
        raise ValidationError(f"{path}: expected const {schema['const']!r}, got {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        raise ValidationError(f"{path}: {instance!r} is not one of {schema['enum']!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(type_matches(instance, item) for item in expected_types):
            raise ValidationError(f"{path}: expected type {expected_type!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise ValidationError(f"{path}: string is shorter than minLength {schema['minLength']!r}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise ValidationError(f"{path}: string is longer than maxLength {schema['maxLength']!r}")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            raise ValidationError(f"{path}: string does not match pattern {schema['pattern']!r}")
        if schema.get("format") == "date-time" and not _is_date_time(instance):
            raise ValidationError(f"{path}: string is not a valid date-time")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise ValidationError(f"{path}: {instance!r} is less than minimum {schema['minimum']!r}")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ValidationError(f"{path}: {instance!r} is greater than maximum {schema['maximum']!r}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                raise ValidationError(f"{path}: missing required property {key!r}")

        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in instance:
                minimal_validate(instance[key], subschema, f"{path}.{key}")

        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise ValidationError(f"{path}: unexpected additional properties {sorted(extra)!r}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise ValidationError(f"{path}: array has fewer than minItems {schema['minItems']!r}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise ValidationError(f"{path}: array has more than maxItems {schema['maxItems']!r}")
        if schema.get("uniqueItems") is True:
            seen = set()
            for item in instance:
                marker = repr(item)
                if marker in seen:
                    raise ValidationError(f"{path}: array items are not unique")
                seen.add(marker)
        if "items" in schema:
            for index, item in enumerate(instance):
                minimal_validate(item, schema["items"], f"{path}[{index}]")

def validate_schema(schema: dict[str, Any], schema_path: Path) -> None:
    if not _is_jsonschema_available():
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ValidationError(f"{schema_path}: missing Draft 2020-12 $schema")
        if "type" not in schema:
            raise ValidationError(f"{schema_path}: missing top-level type")
        return

    from jsonschema import Draft202012Validator, SchemaError  # type: ignore

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValidationError(f"{schema_path}: invalid Draft 2020-12 schema: {exc.message}") from exc


def validate_schemas() -> list[Path]:
    validated: list[Path] = []
    for schema_path in iter_schema_paths():
        validate_schema(load_json(schema_path), schema_path)
        validated.append(schema_path)
    return validated


def validate_instance(instance: Any, schema: dict[str, Any], example_path: Path) -> None:
    if not _is_jsonschema_available():
        minimal_validate(instance, schema)
        return

    from jsonschema import Draft202012Validator, FormatChecker  # type: ignore

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise ValidationError(f"{example_path}: {messages}")


def iter_example_schema_pairs() -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for category, schema_path in SCHEMA_MAP.items():
        for example_path in sorted((EXAMPLES_DIR / category).glob("*.json")):
            pairs.append((example_path, schema_path))
    return pairs


def validate_examples() -> list[Path]:
    validated: list[Path] = []
    for example_path, schema_path in iter_example_schema_pairs():
        instance = load_json(example_path)
        schema = load_json(schema_path)
        validate_schema(schema, schema_path)
        validate_instance(instance, schema, example_path)
        validated.append(example_path)
    return validated


def main() -> int:
    try:
        validated_schemas = validate_schemas()
        validated_examples = validate_examples()
    except Exception as exc:  # noqa: BLE001 - CLI should print validation failure clearly.
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    for path in validated_schemas:
        print(f"ok {path.relative_to(ROOT)}")
    for path in validated_examples:
        print(f"ok {path.relative_to(ROOT)}")
    print(f"validated {len(validated_schemas)} schema(s)")
    print(f"validated {len(validated_examples)} example(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
