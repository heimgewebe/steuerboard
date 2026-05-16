from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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

_BOUNDARY = {
    "does_not_execute": True,
    "does_not_mutate": True,
    "does_not_authorise_actions": True,
}


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must be a list of strings")
        result.append(item)
    return result


def load_omnipull_report(path: Path) -> dict[str, Any]:
    """Load and normalize one omnipull-report.v1 JSON artifact.

    This adapter is intentionally read-only: it accepts one explicit JSON path,
    validates required fields, strips executor-like fields, and emits a bounded
    report object for steuerboard surfaces.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid omnipull report JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("omnipull report must be a JSON object")

    schema_version = raw.get("schema_version")
    if schema_version != "omnipull-report.v1":
        raise ValueError("schema_version must be omnipull-report.v1")

    report_id = _require_non_empty_string(raw.get("report_id"), "report_id")
    run_id = _require_non_empty_string(raw.get("run_id"), "run_id")
    generated_at = _require_string(raw.get("generated_at"), "generated_at")
    source_path = _require_string(raw.get("source_path"), "source_path")

    repos_raw = raw.get("repos")
    if not isinstance(repos_raw, list):
        raise ValueError("repos must be a list")

    repos: list[dict[str, Any]] = []
    for index, item in enumerate(repos_raw):
        field_prefix = f"repos[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{field_prefix} must be an object")

        repo = {
            "repo_id": _require_string(item.get("repo_id"), f"{field_prefix}.repo_id"),
            "path": _require_string(item.get("path"), f"{field_prefix}.path"),
            "status": _require_string(item.get("status"), f"{field_prefix}.status"),
            "skip_reasons": _require_string_list(
                item.get("skip_reasons"), f"{field_prefix}.skip_reasons"
            ),
            "source_refs": _require_string_list(item.get("source_refs"), f"{field_prefix}.source_refs"),
            "freshness_refs": _require_string_list(
                item.get("freshness_refs"), f"{field_prefix}.freshness_refs"
            ),
            "falsification_refs": _require_string_list(
                item.get("falsification_refs"), f"{field_prefix}.falsification_refs"
            ),
            "missing_evidence": _require_string_list(
                item.get("missing_evidence"), f"{field_prefix}.missing_evidence"
            ),
        }
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

    for key in _FORBIDDEN_REPORT_KEYS:
        normalized.pop(key, None)

    return normalized
