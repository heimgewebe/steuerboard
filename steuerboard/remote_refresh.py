from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .inventory import explain_scope_from_config
from .local_config import load_local_config, require_operation_allowed


_BLOCKED_SCOPES = {
    "scope_backup",
    "scope_gdrive",
    "scope_shadow",
    "scope_unknown",
    "scope_excluded",
}

_FETCH_OPERATION = "git.fetch_origin_prune"
_FETCH_ARGS = ("fetch", "origin", "--prune")
_EXCERPT_LIMIT = 2000


def _utc_rfc3339_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _require_git_stdout(path: Path, field_name: str, *args: str) -> str:
    result = _run_git(path, *args)
    output = result.stdout.strip()
    if result.returncode != 0 or not output:
        raise ValueError(
            f"{field_name} is not readable: git {' '.join(args)} failed with exit code {result.returncode}"
        )
    return output


def _read_git_stdout_if_available(path: Path, *args: str) -> str | None:
    result = _run_git(path, *args)
    output = result.stdout.strip()
    if result.returncode != 0 or not output:
        return None
    return output


def _require_existing_parent_and_nonexistent_target(raw_path: str) -> Path:
    target = Path(raw_path).expanduser()
    parent = target.parent if str(target.parent) else Path(".")
    if not parent.exists() or not parent.is_dir():
        raise ValueError("command_trace_out parent directory must exist")
    if target.exists():
        raise ValueError("command_trace_out must not already exist")
    return target


def _normalize_exit_code(returncode: int) -> int:
    """Normalize subprocess returncode. Negative codes (signals) become 128 + abs(code)."""
    if returncode < 0:
        return 128 + abs(returncode)
    return returncode


def _redact_text(value: str) -> str:
    redacted = value
    redacted = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@", r"\1[REDACTED_USER]@", redacted)
    redacted = re.sub(
        r"\b(?!git@)([A-Za-z0-9._-]+)@([A-Za-z0-9._-]+:[^\s]+)",
        r"[REDACTED_USER]@\2",
        redacted,
    )
    redacted = re.sub(
        r"([?&](?:token|access_token|password|passwd|pwd)=)[^&\s]+",
        r"\1[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


def _excerpt(value: str) -> str:
    text = value.strip()
    if len(text) <= _EXCERPT_LIMIT:
        return text
    return text[:_EXCERPT_LIMIT]


def run_fetch_origin_prune(
    repo_path: str,
    config_path: str,
    assessment_id: str,
    command_trace_out: str,
) -> dict[str, Any]:
    """Run the bounded Stage-B fetch operation and emit remote-refresh-result.v1."""
    if not assessment_id.strip():
        raise ValueError("assessment_id must be a non-empty string")

    config = load_local_config(Path(config_path))
    require_operation_allowed(config, "remote-refresh.fetch-origin-prune")

    trace_target = _require_existing_parent_and_nonexistent_target(command_trace_out)

    repo_input = Path(repo_path).expanduser().resolve()
    worktree_check = _run_git(repo_input, "rev-parse", "--is-inside-work-tree")
    if worktree_check.returncode != 0 or worktree_check.stdout.strip() != "true":
        raise ValueError("repo path must resolve to a git worktree")

    repo_toplevel_text = _require_git_stdout(repo_input, "repo toplevel", "rev-parse", "--show-toplevel")
    repo_toplevel = Path(repo_toplevel_text)

    # Preflight: command_trace_out must be outside the target repository worktree
    trace_abs = trace_target.expanduser().resolve()
    repo_abs = repo_toplevel.resolve()
    try:
        trace_abs.relative_to(repo_abs)
    except ValueError:
        # trace_abs is outside repo_abs, which is correct
        pass
    else:
        # trace_abs is inside repo_abs, which would mutate the worktree after postcheck
        raise ValueError("command_trace_out must be outside the target repository worktree")

    scope_explanation = explain_scope_from_config(repo_toplevel, config)
    scope = scope_explanation["scope"]
    if scope in _BLOCKED_SCOPES:
        raise ValueError(f"repository scope is blocked for remote refresh: {scope}")
    if scope != "scope_canonical":
        raise ValueError(f"repository must be in canonical scope, got: {scope}")

    _require_git_stdout(repo_toplevel, "origin remote URL", "config", "--get", "remote.origin.url")
    head_before = _read_git_stdout_if_available(repo_toplevel, "rev-parse", "HEAD")
    branch_before = _require_git_stdout(repo_toplevel, "current branch", "branch", "--show-current")

    status_before_result = _run_git(repo_toplevel, "status", "--porcelain")
    if status_before_result.returncode != 0:
        raise ValueError("worktree porcelain status is not readable before fetch")
    status_before = status_before_result.stdout

    started_at = _utc_rfc3339_now()
    fetch_result = _run_git(repo_toplevel, *_FETCH_ARGS)
    completed_at = _utc_rfc3339_now()

    command = ["git", "-C", str(repo_toplevel), *_FETCH_ARGS]
    postcheck_messages: list[str] = []

    head_after = _read_git_stdout_if_available(repo_toplevel, "rev-parse", "HEAD")
    if head_before is not None and head_after is not None and head_after != head_before:
        postcheck_messages.append("postcheck_failure: HEAD changed during fetch-only stage")

    branch_after = _require_git_stdout(repo_toplevel, "postcheck current branch", "branch", "--show-current")
    if branch_after != branch_before:
        postcheck_messages.append("postcheck_failure: current branch changed during fetch-only stage")

    status_after_result = _run_git(repo_toplevel, "status", "--porcelain")
    if status_after_result.returncode != 0:
        postcheck_messages.append("postcheck_failure: worktree status unreadable after fetch")
    elif status_after_result.stdout != status_before:
        postcheck_messages.append("postcheck_failure: worktree status changed during fetch-only stage")

    exit_code = fetch_result.returncode
    mutates_refs = exit_code == 0

    stderr_for_trace = fetch_result.stderr
    if postcheck_messages:
        if exit_code == 0:
            exit_code = 96
        remote_freshness = "unavailable"
        mutates_refs = False
        extra = "\n".join(postcheck_messages)
        stderr_for_trace = f"{stderr_for_trace.rstrip()}\n{extra}".strip()

    # Normalize exit code (convert negative signal codes to positive)
    exit_code = _normalize_exit_code(exit_code)
    remote_freshness = "fresh" if exit_code == 0 else "unavailable"

    trace_payload = {
        "schema_version": "command-trace.v1",
        "trace_id": f"trace-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}",
        "command": command,
        "exit_code": exit_code,
        "stdout_excerpt": _excerpt(_redact_text(fetch_result.stdout)),
        "stderr_excerpt": _excerpt(_redact_text(stderr_for_trace)),
        "redacted": True,
    }

    try:
        trace_target.write_text(
            json.dumps(trace_payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        raise ValueError(f"failed to write command_trace_out: {e}") from e

    return {
        "schema_version": "remote-refresh-result.v1",
        "refresh_id": f"refresh-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}",
        "repo_ref": f"repo-{assessment_id}",
        "operation": _FETCH_OPERATION,
        "remote_name": "origin",
        "started_at": started_at,
        "completed_at": completed_at,
        "exit_code": exit_code,
        "mutates_worktree": False,
        "mutates_refs": mutates_refs,
        "mutates_remote": False,
        "remote_freshness": remote_freshness,
        "command_trace_ref": command_trace_out,
        "redacted": True,
        "boundary": {
            "does_not_pull": True,
            "does_not_merge": True,
            "does_not_switch": True,
            "does_not_reset": True,
            "does_not_clean": True,
            "does_not_authorise_pull": True,
        },
    }