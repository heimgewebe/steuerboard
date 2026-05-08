#!/usr/bin/env python3
"""Validate Phase 0b JSON examples against their schemas.

This is validation scaffolding only. It does not scan repositories, run Git, or
execute steuerboard actions.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "examples"
SCHEMAS_DIR = ROOT / "schemas"

SCHEMA_MAP = {
    "failure-cases": SCHEMAS_DIR / "falsification-case.v1.schema.json",
}


class ValidationError(Exception):
    """Raised when the built-in minimal validator finds an invalid example."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_schema_paths() -> list[Path]:
    return sorted(SCHEMAS_DIR.glob("*.schema.json"))


def _is_jsonschema_available() -> bool:
    return importlib.util.find_spec("jsonschema") is not None


def _type_matches(value: Any, expected: str) -> bool:
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
    return True


def _is_date_time(value: str) -> bool:
    if not value.endswith("Z") and "+" not in value[10:] and "-" not in value[10:]:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def minimal_validate(instance: Any, schema: dict[str, Any], path: str = "$.") -> None:
    """Validate the small JSON Schema subset used by this repository.

    The project declares Draft 2020-12 schemas. If the external `jsonschema`
    package is installed, `validate_instance` uses it. This fallback keeps Phase
    0b self-checking in minimal environments while covering the keywords used by
    the committed schemas.
    """
    if "const" in schema and instance != schema["const"]:
        raise ValidationError(f"{path} expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ValidationError(f"{path} expected one of {schema['enum']!r}, got {instance!r}")
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _type_matches(instance, expected_type):
        raise ValidationError(f"{path} expected type {expected_type}, got {type(instance).__name__}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise ValidationError(f"{path} is shorter than minLength {schema['minLength']}")
        if "pattern" in schema:
            import re
            if re.search(schema["pattern"], instance) is None:
                raise ValidationError(f"{path} does not match pattern {schema['pattern']!r}")
        if schema.get("format") == "date-time" and not _is_date_time(instance):
            raise ValidationError(f"{path} is not a valid date-time")

    if isinstance(instance, int) and "minimum" in schema and instance < schema["minimum"]:
        raise ValidationError(f"{path} is smaller than minimum {schema['minimum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise ValidationError(f"{path} has fewer items than minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                minimal_validate(item, item_schema, f"{path}[{index}]")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                raise ValidationError(f"{path} missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise ValidationError(f"{path} has additional properties {sorted(extra)!r}")
        for key, value in instance.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                minimal_validate(value, child_schema, f"{path}{key}.")


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
