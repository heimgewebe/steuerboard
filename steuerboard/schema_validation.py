from __future__ import annotations

import re
from datetime import datetime
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when an instance does not validate against a JSON Schema subset."""


RFC3339_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _is_date_time(value: str) -> bool:
    if RFC3339_DATE_TIME_RE.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _type_matches(value: Any, expected: str) -> bool:
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
    raise SchemaValidationError(f"unsupported schema type {expected!r}")


def _validate(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    if "anyOf" in schema:
        errors: list[str] = []
        for index, subschema in enumerate(schema["anyOf"]):
            try:
                _validate(instance, subschema, path)
                break
            except SchemaValidationError as exc:
                errors.append(f"anyOf[{index}]: {exc}")
        else:
            raise SchemaValidationError(f"{path}: does not match anyOf ({'; '.join(errors)})")

    if "oneOf" in schema:
        matches = 0
        errors: list[str] = []
        for index, subschema in enumerate(schema["oneOf"]):
            try:
                _validate(instance, subschema, path)
                matches += 1
            except SchemaValidationError as exc:
                errors.append(f"oneOf[{index}]: {exc}")
        if matches != 1:
            raise SchemaValidationError(
                f"{path}: expected exactly one oneOf match, got {matches}; {'; '.join(errors)}"
            )

    if "allOf" in schema:
        for index, subschema in enumerate(schema["allOf"]):
            _validate(instance, subschema, f"{path}.allOf[{index}]")

    if "not" in schema:
        try:
            _validate(instance, schema["not"], f"{path}.not")
        except SchemaValidationError:
            pass
        else:
            raise SchemaValidationError(f"{path}: instance matches forbidden schema")

    if "if" in schema:
        try:
            _validate(instance, schema["if"], f"{path}.if")
            if_matches = True
        except SchemaValidationError:
            if_matches = False

        if if_matches and "then" in schema:
            _validate(instance, schema["then"], f"{path}.then")
        if not if_matches and "else" in schema:
            _validate(instance, schema["else"], f"{path}.else")

    if "const" in schema and instance != schema["const"]:
        raise SchemaValidationError(f"{path}: expected const {schema['const']!r}, got {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaValidationError(f"{path}: {instance!r} is not one of {schema['enum']!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_type_matches(instance, item) for item in expected_types):
            raise SchemaValidationError(f"{path}: expected type {expected_type!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise SchemaValidationError(
                f"{path}: string is shorter than minLength {schema['minLength']!r}"
            )
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise SchemaValidationError(
                f"{path}: string is longer than maxLength {schema['maxLength']!r}"
            )
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            raise SchemaValidationError(f"{path}: string does not match pattern {schema['pattern']!r}")
        if schema.get("format") == "date-time" and not _is_date_time(instance):
            raise SchemaValidationError(f"{path}: string is not a valid date-time")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise SchemaValidationError(
                f"{path}: {instance!r} is less than minimum {schema['minimum']!r}"
            )
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            raise SchemaValidationError(
                f"{path}: {instance!r} is less than or equal to exclusiveMinimum {schema['exclusiveMinimum']!r}"
            )
        if "maximum" in schema and instance > schema["maximum"]:
            raise SchemaValidationError(
                f"{path}: {instance!r} is greater than maximum {schema['maximum']!r}"
            )
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            raise SchemaValidationError(
                f"{path}: {instance!r} is greater than or equal to exclusiveMaximum {schema['exclusiveMaximum']!r}"
            )

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                raise SchemaValidationError(f"{path}: missing required property {key!r}")

        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in instance:
                _validate(instance[key], subschema, f"{path}.{key}")

        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise SchemaValidationError(f"{path}: unexpected additional properties {sorted(extra)!r}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise SchemaValidationError(f"{path}: array has fewer than minItems {schema['minItems']!r}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise SchemaValidationError(f"{path}: array has more than maxItems {schema['maxItems']!r}")
        if schema.get("uniqueItems") is True:
            seen = set()
            for item in instance:
                marker = repr(item)
                if marker in seen:
                    raise SchemaValidationError(f"{path}: array items are not unique")
                seen.add(marker)
        if "items" in schema:
            for index, item in enumerate(instance):
                _validate(item, schema["items"], f"{path}[{index}]")


def validate_instance(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate an instance against the subset of JSON Schema used at runtime.

    The validator is intentionally small and self-contained so runtime code
    does not depend on test scaffolding or optional third-party packages.
    """
    _validate(instance, schema, path)