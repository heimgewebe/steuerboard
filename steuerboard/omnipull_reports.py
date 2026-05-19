from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .assessment_rules import EXISTING_FAILURE_CASE_IDS

_FORBIDDEN_REPORT_KEYS = {
    "action",
    "plan_id",
    "would_run",
    "would_mutate",
    "command_trace",
    "run_result",
    "safe_actions",
    "safe_alternatives",
}

_ALLOWED_TOP_LEVEL_KEYS = {
    "schema_version",
    "report_id",
    "run_id",
    "generated_at",
    "source_path",
    "repos",
    "boundary",
}

_ALLOWED_REPO_KEYS = {
    "repo_id",
    "path",
    "status",
    "skip_reasons",
    "source_refs",
    "freshness_refs",
    "falsification_refs",
    "missing_evidence",
}

_ALLOWED_STATUSES = {
    "non_default_branch",
    "dirty_worktree",
    "no_upstream",
    "remote_unreachable",
    "ff_only_not_possible",
    "default_branch_unknown",
    "repo_not_in_scope",
    "permission_denied",
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


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name} must be a list of non-blank strings")
        if item != item.strip():
            raise ValueError(
                f"{field_name} items must not have leading or trailing whitespace"
            )
        result.append(item)
    return result


def _require_non_empty_string_list(value: Any, field_name: str) -> list[str]:
    result = _require_string_list(value, field_name)
    if not result:
        raise ValueError(f"{field_name} must be a non-empty list of strings")
    return result


def _validate_falsification_refs(value: Any, field_name: str) -> list[str]:
    refs = _require_string_list(value, field_name)
    for ref in refs:
        prefix = "failure-case."
        if not ref.startswith(prefix):
            raise ValueError(f"{field_name} must use failure-case.* references")
        case_id = ref[len(prefix) :]
        if case_id not in EXISTING_FAILURE_CASE_IDS:
            raise ValueError(f"{field_name} contains unknown failure-case ref: {ref}")
    return refs


def _validate_known_keys(payload: dict[str, Any], allowed: set[str], field_name: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{field_name} contains unknown fields: {unknown}")


def load_omnipull_report(path: Path, *, source_path_ref: str | None = None) -> dict[str, Any]:
    """Load and validate one omnipull-report.v1 JSON artifact.

    This adapter is intentionally read-only: it accepts one explicit JSON path,
    validates required fields, rejects executor-like fields, and emits a bounded
    report object for steuerboard surfaces.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid omnipull report JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("omnipull report must be a JSON object")

    forbidden_present = sorted(_FORBIDDEN_REPORT_KEYS & set(raw))
    if forbidden_present:
        raise ValueError(f"omnipull report contains forbidden fields: {forbidden_present}")

    _validate_known_keys(raw, _ALLOWED_TOP_LEVEL_KEYS, "omnipull report")

    schema_version = raw.get("schema_version")
    if schema_version != "omnipull-report.v1":
        raise ValueError("schema_version must be omnipull-report.v1")

    report_id = _require_non_blank_string(raw.get("report_id"), "report_id")
    run_id = _require_non_blank_string(raw.get("run_id"), "run_id")
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

    repos_raw = raw.get("repos")
    if not isinstance(repos_raw, list):
        raise ValueError("repos must be a list")

    repos: list[dict[str, Any]] = []
    for index, item in enumerate(repos_raw):
        field_prefix = f"repos[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{field_prefix} must be an object")

        _validate_known_keys(item, _ALLOWED_REPO_KEYS, field_prefix)

        status = _require_non_blank_string(item.get("status"), f"{field_prefix}.status")
        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"{field_prefix}.status must be one of {sorted(_ALLOWED_STATUSES)}")

        repo = {
            "repo_id": _require_non_blank_string(item.get("repo_id"), f"{field_prefix}.repo_id"),
            "path": _require_non_blank_string(item.get("path"), f"{field_prefix}.path"),
            "status": status,
            "skip_reasons": _require_non_empty_string_list(
                item.get("skip_reasons"), f"{field_prefix}.skip_reasons"
            ),
            "source_refs": _require_non_empty_string_list(
                item.get("source_refs"), f"{field_prefix}.source_refs"
            ),
            "freshness_refs": _require_non_empty_string_list(
                item.get("freshness_refs"), f"{field_prefix}.freshness_refs"
            ),
            "falsification_refs": _validate_falsification_refs(
                item.get("falsification_refs"), f"{field_prefix}.falsification_refs"
            ),
            "missing_evidence": _require_string_list(
                item.get("missing_evidence"), f"{field_prefix}.missing_evidence"
            ),
        }
        if status not in repo["skip_reasons"]:
            raise ValueError(f"{field_prefix}.skip_reasons must include status {status!r}")
        repos.append(repo)

    normalized: dict[str, Any] = {
        "schema_version": "omnipull-report.v1",
        "report_id": report_id,
        "run_id": run_id,
        "generated_at": generated_at,
        "source_path": source_path,
        "repos": repos,
        "boundary": dict(_BOUNDARY),
    }

    return normalized
