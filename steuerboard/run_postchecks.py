"""Phase 8B: Run Postcheck — read-only postcheck for bounded git-status-read-only runs.

Boundary contract:
- Validates run-result.v1 and command-trace.v1 artifacts against schemas.
- Runs only hard-coded read-only git commands: rev-parse preflight checks
    plus one productive git status recheck.
- Compares new status output against the original trace excerpt.
- No mutation, no pull, no fetch, no free shell, no generic subprocess.
- Output file must not exist; parent must exist.
- Output must be outside the inspected repository worktree.
- No approval runner. No network.

This is a pure evidence artifact — not an authorisation mechanism.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

try:
    from jsonschema import ValidationError as SchemaValidationError
    from jsonschema import validate as jsonschema_validate
except ModuleNotFoundError:  # pragma: no cover
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate

from .action_runs import (
    _EXCERPT_LIMIT,
    _excerpt,
    _is_path_inside,
    _redact_text,
    _require_output_path,
    _utc_rfc3339_now,
)

# Lazily-loaded schemas
_COMMAND_TRACE_SCHEMA: dict[str, Any] | None = None
_RUN_RESULT_SCHEMA: dict[str, Any] | None = None

# Exact hardened command structure for the git-status-read-only pilot.
# Full array: ["git", "--no-optional-locks", "-C", <repo_toplevel>, "status", "--porcelain=v1"]
# Position 3 (<repo_toplevel>) is variable; all others are fixed.
_HARDENED_COMMAND_LEN = 6
_HARDENED_COMMAND_FIXED: dict[int, str] = {
    0: "git",
    1: "--no-optional-locks",
    2: "-C",
    4: "status",
    5: "--porcelain=v1",
}


def _load_command_trace_schema() -> dict[str, Any]:
    global _COMMAND_TRACE_SCHEMA
    if _COMMAND_TRACE_SCHEMA is None:
        path = (
            Path(__file__).resolve().parent.parent
            / "schemas"
            / "command-trace.v1.schema.json"
        )
        with path.open("r", encoding="utf-8") as fh:
            _COMMAND_TRACE_SCHEMA = json.load(fh)
    return _COMMAND_TRACE_SCHEMA


def _load_run_result_schema() -> dict[str, Any]:
    global _RUN_RESULT_SCHEMA
    if _RUN_RESULT_SCHEMA is None:
        path = (
            Path(__file__).resolve().parent.parent
            / "schemas"
            / "run-result.v1.schema.json"
        )
        with path.open("r", encoding="utf-8") as fh:
            _RUN_RESULT_SCHEMA = json.load(fh)
    return _RUN_RESULT_SCHEMA


def _validate_against_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    """Validate instance against schema; raise ValueError on failure."""
    if not isinstance(instance, dict):
        raise ValueError(f"{label} must be a JSON object")
    try:
        jsonschema_validate(instance=instance, schema=schema)
    except SchemaValidationError as exc:
        raise ValueError(f"{label} does not validate against schema: {exc}") from exc


def _validate_trace_command(command: Any) -> str:
    """Validate that the trace command is exactly the hardened git status command.

    Returns the repo_toplevel string (command[3]).
    Raises ValueError on any structural or value mismatch.
    """
    if not isinstance(command, list):
        raise ValueError("command-trace 'command' field must be an array")
    if len(command) != _HARDENED_COMMAND_LEN:
        raise ValueError(
            f"trace command must have exactly {_HARDENED_COMMAND_LEN} elements; "
            f"got {len(command)}"
        )
    for idx, expected in _HARDENED_COMMAND_FIXED.items():
        if command[idx] != expected:
            raise ValueError(
                f"trace command[{idx}] must be {expected!r}; got {command[idx]!r}"
            )
    toplevel = command[3]
    if not isinstance(toplevel, str) or not toplevel:
        raise ValueError("trace command[3] (repo_toplevel) must be a non-empty string")
    return toplevel


def _write_postcheck_atomic(target: Path, data: dict[str, Any]) -> None:
    """Write postcheck artifact via temp file + os.replace() for atomicity."""
    tmp_path: Path | None = None
    try:
        fd, tmp = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        tmp_path = Path(tmp)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp_path, target)
        tmp_path = None
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _normalize_path_string(path_str: str) -> str:
    """Normalize a path string for stable evidence-path comparisons."""
    return str(Path(path_str).expanduser().resolve(strict=False))


def run_read_only_postcheck(
    run_result: dict[str, Any],
    command_trace: dict[str, Any],
    repo_path: str,
    postcheck_out: str,
    command_trace_path: str,
    run_result_path: str,
) -> dict[str, Any]:
    """Execute a Phase 8B read-only postcheck for a git-status-read-only run.

    Validates run-result.v1 and command-trace.v1 against their schemas, runs
    bounded read-only git preflight checks (`rev-parse`), re-runs exactly one
    productive `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
    command, and compares the new output against the original trace excerpt.

    Parameters
    ----------
    run_result:
        Parsed run-result.v1 JSON object.
    command_trace:
        Parsed command-trace.v1 JSON object.
    repo_path:
        Explicit path to the git worktree to re-check.
    postcheck_out:
        Output path for the run-postcheck.v1 artifact. Must not exist; parent must exist.
    command_trace_path:
        Path string of the command_trace input file (recorded in evidence_paths).
    run_result_path:
        Path string of the run_result input file (recorded in evidence_paths).

    Returns
    -------
    dict
        The run-postcheck.v1 artifact dict (also written to postcheck_out).

    Raises
    ------
    ValueError
        On any precondition failure. No output is written on failure.
    """
    # --- Validate input artifacts against schemas ---
    _validate_against_schema(run_result, _load_run_result_schema(), "run-result.v1")
    _validate_against_schema(command_trace, _load_command_trace_schema(), "command-trace.v1")

    # --- Bind run-result + command-trace to the same successful Phase 8A run ---
    if run_result.get("status") != "success":
        raise ValueError("run-result.v1 status must be 'success' for postcheck")

    evidence_paths = run_result.get("evidence_paths")
    if not isinstance(evidence_paths, list):
        raise ValueError("run-result.v1 evidence_paths must be present for postcheck binding")

    normalized_trace_input = _normalize_path_string(command_trace_path)
    normalized_evidence_paths = {
        _normalize_path_string(entry)
        for entry in evidence_paths
        if isinstance(entry, str) and entry
    }
    if normalized_trace_input not in normalized_evidence_paths:
        raise ValueError(
            "run-result.v1 evidence_paths must include the provided command-trace path"
        )

    # --- Validate trace command is exactly the hardened git status command ---
    trace_toplevel_str = _validate_trace_command(command_trace.get("command"))

    # --- Validate redaction on both artifacts ---
    if run_result.get("redaction_verified") is not True:
        raise ValueError("run-result.v1 redaction_verified must be true")
    if command_trace.get("redacted") is not True:
        raise ValueError("command-trace.v1 redacted must be true")
    if command_trace.get("exit_code") != 0:
        raise ValueError("command-trace.v1 exit_code must be 0 for postcheck")

    if "stdout_excerpt" not in command_trace:
        raise ValueError(
            "command-trace.v1 stdout_excerpt is required for postcheck comparison"
        )
    original_excerpt = command_trace["stdout_excerpt"]
    if not isinstance(original_excerpt, str):
        raise ValueError("command-trace.v1 stdout_excerpt must be a string")
    # Phase 8A trace does not carry an explicit truncation flag, so treat
    # excerpts at the boundary as potentially truncated.
    original_maybe_truncated = len(original_excerpt) >= _EXCERPT_LIMIT

    # --- Resolve repo_path and cross-check against trace toplevel ---
    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        raise ValueError(f"repo_path does not exist or is not a directory: {repo_path}")

    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"

    worktree_check = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if worktree_check.returncode != 0 or worktree_check.stdout.strip() != "true":
        raise ValueError(f"repo_path must resolve to a git worktree: {repo_path}")

    toplevel_result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if toplevel_result.returncode != 0 or not toplevel_result.stdout.strip():
        raise ValueError("cannot resolve git toplevel for repo_path")

    repo_toplevel = Path(toplevel_result.stdout.strip()).resolve()
    trace_toplevel_path = Path(trace_toplevel_str).resolve()
    if repo_toplevel != trace_toplevel_path:
        raise ValueError(
            f"repo_path resolves to {repo_toplevel!s} but trace command uses "
            f"{trace_toplevel_path!s}; they must refer to the same git toplevel"
        )

    # --- Validate postcheck output path ---
    postcheck_target = _require_output_path(postcheck_out, "postcheck_out")

    # Output paths must lie outside the inspected repository worktree.
    if _is_path_inside(repo_toplevel, postcheck_target):
        raise ValueError("postcheck_out must not be inside the inspected repository")

    # --- Re-run the bounded read-only git status command ---
    # The command is fully hard-coded. No user-supplied fragments are inserted.
    recheck_command: list[str] = [
        "git",
        "--no-optional-locks",
        "-C",
        str(repo_toplevel),
        "status",
        "--porcelain=v1",
    ]

    proc = subprocess.run(
        recheck_command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    new_excerpt = _excerpt(_redact_text(proc.stdout))
    new_stdout_truncated = len(proc.stdout) > _EXCERPT_LIMIT

    observations: list[str] = []
    failure_reasons: list[str] = []

    if new_stdout_truncated or original_maybe_truncated:
        observations.append(
            "stdout_excerpt_truncated: comparison limited to excerpt boundary"
        )

    if proc.returncode != 0:
        status = "inconclusive"
        failure_reasons.append("postcheck_command_failed")
        stderr_excerpt = _excerpt(_redact_text(proc.stderr))
        if stderr_excerpt:
            observations.append(f"postcheck_stderr_excerpt={stderr_excerpt}")
    elif new_stdout_truncated or original_maybe_truncated:
        status = "inconclusive"
        failure_reasons.append("stdout_excerpt_truncated")
    elif new_excerpt == original_excerpt:
        status = "passed"
    else:
        status = "failed"
        failure_reasons.append("worktree_changed_after_run")

    checked_at = _utc_rfc3339_now()
    postcheck_id = f"postcheck-read-only-{uuid.uuid4().hex[:16]}"
    run_id = run_result["run_id"]
    trace_ref = command_trace["trace_id"]

    evidence: list[str] = []
    if command_trace_path:
        evidence.append(command_trace_path)
    if run_result_path:
        evidence.append(run_result_path)

    postcheck: dict[str, Any] = {
        "schema_version": "run-postcheck.v1",
        "postcheck_id": postcheck_id,
        "run_id": run_id,
        "trace_ref": trace_ref,
        "run_result_ref": run_id,
        "action": "git-status-read-only",
        "repo_toplevel": str(repo_toplevel),
        "checked_at": checked_at,
        "status": status,
        "observations": observations,
        "redaction_verified": True,
        "source_refs": ["git.status_porcelain", "run-result.v1", "command-trace.v1"],
        "evidence_paths": evidence,
    }

    if failure_reasons:
        postcheck["failure_reasons"] = failure_reasons

    _write_postcheck_atomic(postcheck_target, postcheck)
    return postcheck
