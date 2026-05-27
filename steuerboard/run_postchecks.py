"""Phase 8B: run postcheck for bounded git-status-read-only evidence."""
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

_COMMAND_TRACE_SCHEMA: dict[str, Any] | None = None
_RUN_RESULT_SCHEMA: dict[str, Any] | None = None

_HARDENED_COMMAND_LEN = 6
_HARDENED_COMMAND_FIXED: dict[int, str] = {
    0: "git",
    1: "--no-optional-locks",
    2: "-C",
    4: "status",
    5: "--porcelain=v1",
}


def _load_schema(filename: str) -> dict[str, Any]:
    if filename == "command-trace.v1.schema.json":
        global _COMMAND_TRACE_SCHEMA
        if _COMMAND_TRACE_SCHEMA is None:
            path = Path(__file__).resolve().parent.parent / "schemas" / filename
            with path.open("r", encoding="utf-8") as handle:
                _COMMAND_TRACE_SCHEMA = json.load(handle)
        return _COMMAND_TRACE_SCHEMA
    if filename == "run-result.v1.schema.json":
        global _RUN_RESULT_SCHEMA
        if _RUN_RESULT_SCHEMA is None:
            path = Path(__file__).resolve().parent.parent / "schemas" / filename
            with path.open("r", encoding="utf-8") as handle:
                _RUN_RESULT_SCHEMA = json.load(handle)
        return _RUN_RESULT_SCHEMA
    path = Path(__file__).resolve().parent.parent / "schemas" / filename
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_against_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    if not isinstance(instance, dict):
        raise ValueError(f"{label} must be a JSON object")
    try:
        jsonschema_validate(instance=instance, schema=schema)
    except SchemaValidationError as exc:
        raise ValueError(f"{label} does not validate against schema: {exc}") from exc


def _validate_trace_command(command: Any) -> str:
    if not isinstance(command, list):
        raise ValueError("command-trace 'command' field must be an array")
    if len(command) != _HARDENED_COMMAND_LEN:
        raise ValueError(
            f"trace command must have exactly {_HARDENED_COMMAND_LEN} elements; got {len(command)}"
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
    tmp_path: Path | None = None
    try:
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
        tmp_path = Path(tmp)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
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
    return str(Path(path_str).expanduser().resolve(strict=False))


def run_read_only_postcheck(
    run_result: dict[str, Any],
    command_trace: dict[str, Any],
    repo_path: str,
    postcheck_out: str,
    command_trace_path: str,
    run_result_path: str,
) -> dict[str, Any]:
    """Validate a bounded read-only run and emit run-postcheck.v1."""
    _validate_against_schema(run_result, _load_schema("run-result.v1.schema.json"), "run-result.v1")
    _validate_against_schema(command_trace, _load_schema("command-trace.v1.schema.json"), "command-trace.v1")

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
        raise ValueError("run-result.v1 evidence_paths must include the provided command-trace path")

    trace_toplevel_str = _validate_trace_command(command_trace.get("command"))

    if run_result.get("redaction_verified") is not True:
        raise ValueError("run-result.v1 redaction_verified must be true")
    if command_trace.get("redacted") is not True:
        raise ValueError("command-trace.v1 redacted must be true")
    if command_trace.get("exit_code") != 0:
        raise ValueError("command-trace.v1 exit_code must be 0 for postcheck")
    if "stdout_excerpt" not in command_trace:
        raise ValueError("command-trace.v1 stdout_excerpt is required for postcheck comparison")
    original_excerpt = command_trace["stdout_excerpt"]
    if not isinstance(original_excerpt, str):
        raise ValueError("command-trace.v1 stdout_excerpt must be a string")
    original_maybe_truncated = len(original_excerpt) >= _EXCERPT_LIMIT

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
            f"repo_path resolves to {repo_toplevel!s} but trace command uses {trace_toplevel_path!s}; they must refer to the same git toplevel"
        )

    postcheck_target = _require_output_path(postcheck_out, "postcheck_out")
    if _is_path_inside(repo_toplevel, postcheck_target):
        raise ValueError("postcheck_out must not be inside the inspected repository")

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
        observations.append("stdout_excerpt_truncated: comparison limited to excerpt boundary")

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