from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_FORBIDDEN_INDEX_KEYS = {
    "action",
    "plan_id",
    "would_run",
    "would_mutate",
    "command_trace",
    "run_result",
    "safe_actions",
    "safe_alternatives",
}

_ALLOWED_INDEX_TOP_LEVEL_KEYS = {
    "schema_version",
    "generated_at",
    "source_path",
    "reports",
    "boundary",
}

_ALLOWED_REPORT_ENTRY_KEYS = {
    "report_id",
    "run_id",
    "generated_at",
    "source_path",
}

_RFC3339_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

_BOUNDARY = {
    "does_not_execute": True,
    "does_not_mutate": True,
    "does_not_authorise_actions": True,
}


def _require_non_blank_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _require_date_time_string(value: Any, field_name: str) -> str:
    parsed = _require_string(value, field_name)
    if _RFC3339_DATE_TIME_RE.fullmatch(parsed) is None:
        raise ValueError(f"{field_name} must be a valid date-time")
    try:
        datetime.fromisoformat(parsed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid date-time") from exc
    return parsed


def _validate_known_keys(payload: dict[str, Any], allowed: set[str], field_name: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{field_name} contains unknown fields: {unknown}")


def load_omnipull_run_index(
    path: Path, *, source_path_ref: str | None = None
) -> dict[str, Any]:
    """Load and validate one omnipull-run-index.v1 JSON artifact.

    The adapter is strictly read-only: it accepts one explicit JSON path,
    validates required fields, rejects executor-like fields, and emits a
    bounded run-index object. It performs no filesystem discovery, no Git
    subprocess, no network access, and no auto-loading of referenced reports.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid omnipull run-index JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("omnipull run-index must be a JSON object")

    forbidden_present = sorted(_FORBIDDEN_INDEX_KEYS & set(raw))
    if forbidden_present:
        raise ValueError(
            f"omnipull run-index contains forbidden fields: {forbidden_present}"
        )

    _validate_known_keys(raw, _ALLOWED_INDEX_TOP_LEVEL_KEYS, "omnipull run-index")

    schema_version = raw.get("schema_version")
    if schema_version != "omnipull-run-index.v1":
        raise ValueError("schema_version must be omnipull-run-index.v1")

    generated_at = _require_date_time_string(raw.get("generated_at"), "generated_at")
    raw_source_path = raw.get("source_path")
    source_path = _require_non_blank_string(raw_source_path, "source_path")
    expected_source_path = source_path_ref if source_path_ref is not None else str(path)
    if raw_source_path != expected_source_path:
        raise ValueError("source_path must exactly match the loaded artifact path")

    boundary = raw.get("boundary")
    if not isinstance(boundary, dict):
        raise ValueError("boundary must be an object")
    if boundary != _BOUNDARY:
        raise ValueError("boundary must exactly match read-only boundary constants")

    reports_raw = raw.get("reports")
    if not isinstance(reports_raw, list):
        raise ValueError("reports must be a list")

    reports: list[dict[str, Any]] = []
    for index, item in enumerate(reports_raw):
        field_prefix = f"reports[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{field_prefix} must be an object")

        forbidden_in_entry = sorted(_FORBIDDEN_INDEX_KEYS & set(item))
        if forbidden_in_entry:
            raise ValueError(
                f"{field_prefix} contains forbidden fields: {forbidden_in_entry}"
            )

        _validate_known_keys(item, _ALLOWED_REPORT_ENTRY_KEYS, field_prefix)

        entry = {
            "report_id": _require_non_blank_string(
                item.get("report_id"), f"{field_prefix}.report_id"
            ),
            "run_id": _require_non_blank_string(
                item.get("run_id"), f"{field_prefix}.run_id"
            ),
            "generated_at": _require_date_time_string(
                item.get("generated_at"), f"{field_prefix}.generated_at"
            ),
            "source_path": _require_non_blank_string(
                item.get("source_path"), f"{field_prefix}.source_path"
            ),
        }
        reports.append(entry)

    normalized: dict[str, Any] = {
        "schema_version": "omnipull-run-index.v1",
        "generated_at": generated_at,
        "source_path": source_path,
        "reports": reports,
        "boundary": dict(_BOUNDARY),
    }

    return normalized


def select_latest_report(index: dict[str, Any]) -> dict[str, Any]:
    """Select the latest omnipull-report reference from an in-memory run-index.

    The latest report is determined entirely from the explicitly loaded index
    artifact. No filesystem discovery, no auto-loading of referenced report
    files, no Git, and no network access take place.

    Ordering rules:
      1. primary key: ``generated_at`` (descending — most recent wins)
      2. tie-break: ``run_id`` (lexicographically descending)

    Raises:
        ValueError: if ``reports`` is empty.
    """
    if not isinstance(index, dict):
        raise ValueError("run-index must be a dict")

    reports = index.get("reports")
    if not isinstance(reports, list):
        raise ValueError("run-index reports must be a list")

    if not reports:
        raise ValueError(
            "cannot select latest report: run-index reports list is empty"
        )

    def _sort_key(entry: Any) -> tuple[datetime, str]:
        if not isinstance(entry, dict):
            raise ValueError("run-index report entries must be objects")

        generated_at = _require_date_time_string(
            entry.get("generated_at"), "reports[].generated_at"
        )
        run_id = _require_non_blank_string(entry.get("run_id"), "reports[].run_id")
        return (datetime.fromisoformat(generated_at.replace("Z", "+00:00")), run_id)

    latest = max(reports, key=_sort_key)
    report_id = _require_non_blank_string(latest.get("report_id"), "reports[].report_id")
    run_id = _require_non_blank_string(latest.get("run_id"), "reports[].run_id")
    source_path = _require_non_blank_string(
        latest.get("source_path"), "reports[].source_path"
    )

    return {
        "schema_version": "omnipull-report-ref.v1",
        "report_id": report_id,
        "run_id": run_id,
        "source_path": source_path,
        "selected_by": "latest.generated_at",
    }
