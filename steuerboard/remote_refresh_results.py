from __future__ import annotations

from typing import Any


_ALLOWED_REMOTE_REFRESH_KEYS = {
    "schema_version",
    "refresh_id",
    "repo_ref",
    "operation",
    "remote_name",
    "started_at",
    "completed_at",
    "exit_code",
    "mutates_worktree",
    "mutates_refs",
    "mutates_remote",
    "remote_freshness",
    "command_trace_ref",
    "redacted",
    "boundary",
}

_ALLOWED_BOUNDARY_KEYS = {
    "does_not_pull",
    "does_not_merge",
    "does_not_switch",
    "does_not_reset",
    "does_not_clean",
    "does_not_authorise_pull",
}


def _require_non_empty_string(value: Any, field_name: str) -> str:
    """Validate and extract a non-empty, non-whitespace string field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")
    return value


def _require_integer_gte_zero(value: Any, field_name: str) -> int:
    """Validate and extract a non-negative integer field."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer >= 0")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _require_boolean_true(value: Any, field_name: str) -> bool:
    """Validate that a field is exactly true (not truthy, exactly True)."""
    if value is not True:
        raise ValueError(f"{field_name} must be exactly true")
    return value


def _require_boolean_false(value: Any, field_name: str) -> bool:
    """Validate that a field is exactly false (not falsy, exactly False)."""
    if value is not False:
        raise ValueError(f"{field_name} must be exactly false")
    return value


def load_and_validate_remote_refresh_result(
    remote_refresh: dict[str, Any],
) -> dict[str, Any]:
    """Load and validate a remote-refresh-result.v1 artifact for planner consumption.

    Enforces strict schema validation:
    - schema_version == "remote-refresh-result.v1"
    - refresh_id is a non-blank string
    - repo_ref is a non-blank string
    - operation == "git.fetch_origin_prune"
    - remote_name == "origin"
    - exit_code is an integer >= 0
    - mutates_worktree is false
    - mutates_remote is false
    - redacted is true
    - boundary exactly contains true values for:
      - does_not_pull
      - does_not_merge
      - does_not_switch
      - does_not_reset
      - does_not_clean
      - does_not_authorise_pull
    - remote_freshness is one of: fresh, stale, unknown, unavailable

    Returns the validated artifact (input dict, not copied).
    Raises ValueError for any validation failure.
    """
    if not isinstance(remote_refresh, dict):
        raise ValueError("remote_refresh must be an object")

    top_level_keys = set(remote_refresh)
    unknown_top_level = sorted(top_level_keys - _ALLOWED_REMOTE_REFRESH_KEYS)
    if unknown_top_level:
        raise ValueError(
            "remote-refresh-result contains unknown top-level fields: "
            f"{unknown_top_level}"
        )

    missing_top_level = sorted(_ALLOWED_REMOTE_REFRESH_KEYS - top_level_keys)
    if missing_top_level:
        raise ValueError(
            "remote-refresh-result is missing required top-level fields: "
            f"{missing_top_level}"
        )

    # Strict schema version check
    schema_version = remote_refresh.get("schema_version")
    if schema_version != "remote-refresh-result.v1":
        raise ValueError(
            f"schema_version must be 'remote-refresh-result.v1', got '{schema_version}'"
        )

    # Validate required string fields
    refresh_id = _require_non_empty_string(
        remote_refresh.get("refresh_id"), "refresh_id"
    )
    repo_ref = _require_non_empty_string(
        remote_refresh.get("repo_ref"), "repo_ref"
    )

    # Validate operation and remote_name constraints
    operation = remote_refresh.get("operation")
    if operation != "git.fetch_origin_prune":
        raise ValueError(
            f"operation must be 'git.fetch_origin_prune', got '{operation}'"
        )

    remote_name = remote_refresh.get("remote_name")
    if remote_name != "origin":
        raise ValueError(
            f"remote_name must be 'origin', got '{remote_name}'"
        )

    # Validate exit code
    exit_code = _require_integer_gte_zero(
        remote_refresh.get("exit_code"), "exit_code"
    )

    # Validate mutation constraints (fetch itself must not mutate worktree or remote refs)
    _require_boolean_false(
        remote_refresh.get("mutates_worktree"), "mutates_worktree"
    )
    _require_boolean_false(
        remote_refresh.get("mutates_remote"), "mutates_remote"
    )

    # Validate redaction status (planner input must be redacted)
    _require_boolean_true(
        remote_refresh.get("redacted"), "redacted"
    )

    # Validate boundary constraints strictly
    boundary = remote_refresh.get("boundary")
    if not isinstance(boundary, dict):
        raise ValueError("boundary must be an object")

    boundary_keys = set(boundary)
    unknown_boundary = sorted(boundary_keys - _ALLOWED_BOUNDARY_KEYS)
    if unknown_boundary:
        raise ValueError(
            f"boundary contains unknown fields: {unknown_boundary}"
        )

    missing_boundary = sorted(_ALLOWED_BOUNDARY_KEYS - boundary_keys)
    if missing_boundary:
        raise ValueError(
            f"boundary is missing required fields: {missing_boundary}"
        )

    if boundary_keys != _ALLOWED_BOUNDARY_KEYS:
        raise ValueError(
            "boundary must exactly match remote-refresh boundary markers"
        )

    for marker in _ALLOWED_BOUNDARY_KEYS:
        value = boundary.get(marker)
        _require_boolean_true(value, f"boundary.{marker}")

    # Validate remote_freshness state
    remote_freshness = remote_refresh.get("remote_freshness")
    if remote_freshness not in ("fresh", "stale", "unknown", "unavailable"):
        raise ValueError(
            f"remote_freshness must be one of (fresh, stale, unknown, unavailable), "
            f"got '{remote_freshness}'"
        )

    return remote_refresh


def is_remote_refresh_success(remote_refresh: dict[str, Any]) -> bool:
    """Check if a validated remote-refresh-result represents success.

    Success condition:
    - exit_code == 0
    - remote_freshness == "fresh"

    Assumes input has already passed load_and_validate_remote_refresh_result().
    """
    return (
        remote_refresh.get("exit_code") == 0 and
        remote_refresh.get("remote_freshness") == "fresh"
    )
