from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from jsonschema import ValidationError as SchemaValidationError
    from jsonschema import validate as jsonschema_validate
except ModuleNotFoundError:  # pragma: no cover - exercised by subprocess test environments
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate


# Phase 8A allowlist: exactly one bounded read-only pilot action.
# Extending this set requires a new phase slice and explicit review.
PHASE_8A_ALLOWLIST: frozenset[str] = frozenset({"git-status-read-only"})

# Mutating actions that must never reach the Phase 8A runner.
# Belt-and-suspenders: even if the allowlist check would also catch these,
# the mutating set is named explicitly to make the boundary visible.
MUTATING_ACTIONS: frozenset[str] = frozenset({
    "git-pull-ff-only",
    "switch-main",
})

_EXCERPT_LIMIT = 2000

# Exact, immutable command suffix for the git-status-read-only pilot.
# This is NOT a template. No user-supplied command fragments are accepted.
# --no-optional-locks: inhibit any advisory lock acquisition (belt-and-suspenders
#                      on top of GIT_OPTIONAL_LOCKS=0 in the environment).
# --porcelain=v1: stable machine-readable format, version-pinned.
_GIT_STATUS_COMMAND = ("--no-optional-locks", "status", "--porcelain=v1")

# Lazily-loaded action-plan schema.  Loaded once, cached here.
_ACTION_PLAN_SCHEMA: dict[str, Any] | None = None


def _get_action_plan_schema() -> dict[str, Any]:
    """Return the action-plan.v1 JSON Schema, loading it once from disk."""
    global _ACTION_PLAN_SCHEMA
    if _ACTION_PLAN_SCHEMA is None:
        schema_path = (
            Path(__file__).resolve().parent.parent / "schemas" / "action-plan.v1.schema.json"
        )
        with schema_path.open("r", encoding="utf-8") as fh:
            _ACTION_PLAN_SCHEMA = json.load(fh)
    return _ACTION_PLAN_SCHEMA


def _utc_rfc3339_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_output_path(raw: str, label: str) -> Path:
    """Return resolved Path; raise ValueError if parent missing or target exists."""
    target = Path(raw).expanduser().resolve()
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"{label} parent directory must exist")
    if target.exists():
        raise ValueError(f"{label} must not already exist")
    return target


def _excerpt(value: str) -> str:
    """Return at most _EXCERPT_LIMIT characters of stripped text."""
    return value.strip()[:_EXCERPT_LIMIT]


def _redact_text(value: str) -> str:
    """Apply basic URL-credential redaction to a text excerpt."""
    redacted = value
    # Redact credentials embedded in URL userinfo (scheme://user@host or user@host:path)
    redacted = re.sub(
        r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@",
        r"\1[REDACTED_USER]@",
        redacted,
    )
    redacted = re.sub(
        r"\b(?!git@)([A-Za-z0-9._-]+)@([A-Za-z0-9._-]+:[^\s]+)",
        r"[REDACTED_USER]@\2",
        redacted,
    )
    # Redact query-string token parameters
    redacted = re.sub(
        r"([?&](?:token|access_token|password|passwd|pwd)=)[^&\s]+",
        r"\1[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


def _normalize_exit_code(returncode: int) -> int:
    if returncode < 0:
        return 128 + abs(returncode)
    return returncode


def _validate_action_plan_schema(action_plan: Any) -> str:
    """Validate action_plan fully against action-plan.v1 JSON Schema; return the action string.

    Raises ValueError if validation fails.
    """
    if not isinstance(action_plan, dict):
        raise ValueError("action_plan must be a JSON object")
    schema = _get_action_plan_schema()
    try:
        jsonschema_validate(instance=action_plan, schema=schema)
    except SchemaValidationError as exc:
        raise ValueError(
            f"action_plan does not validate against action-plan.v1: {exc}"
        ) from exc
    action = action_plan["action"]
    return action


def _write_artifacts_atomic(
    trace_target: Path,
    trace_data: dict[str, Any],
    run_result_target: Path,
    run_result_data: dict[str, Any],
) -> None:
    """Write trace and run-result atomically using temp files + os.replace().

    Both artifacts are written to temp files first.  Only after both are fully
    written are they committed with os.replace().  If the second replace fails,
    the first output is removed again so the final state never contains a half
    completed pair.  Any remaining temp files are cleaned up on error.
    """
    trace_tmp: Path | None = None
    run_result_tmp: Path | None = None
    try:
        # --- Stage 1: write both to temp files ---
        fd1, tmp1 = tempfile.mkstemp(
            dir=trace_target.parent,
            prefix=f".{trace_target.name}.",
            suffix=".tmp",
        )
        trace_tmp = Path(tmp1)
        with os.fdopen(fd1, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(trace_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")

        fd2, tmp2 = tempfile.mkstemp(
            dir=run_result_target.parent,
            prefix=f".{run_result_target.name}.",
            suffix=".tmp",
        )
        run_result_tmp = Path(tmp2)
        with os.fdopen(fd2, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(run_result_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            )

        # --- Stage 2: commit both, rolling back the first replace if needed ---
        os.replace(trace_tmp, trace_target)
        trace_tmp = None  # ownership transferred to trace_target
        try:
            os.replace(run_result_tmp, run_result_target)
        except Exception:
            try:
                trace_target.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        run_result_tmp = None  # ownership transferred to run_result_target
    except Exception:
        # Clean up any temp files that were not yet committed.
        if trace_tmp is not None:
            try:
                trace_tmp.unlink(missing_ok=True)
            except OSError:
                pass
        if run_result_tmp is not None:
            try:
                run_result_tmp.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def run_read_only_action(
    action_plan: dict[str, Any],
    repo_path: str,
    command_trace_out: str,
    run_result_out: str,
) -> dict[str, Any]:
    """Execute a Phase 8A read-only action and produce command-trace.v1 + run-result.v1.

    Boundary contract:
    - Only actions in PHASE_8A_ALLOWLIST are executed.
    - MUTATING_ACTIONS are explicitly rejected before the allowlist check.
    - No free shell, no sudo, no network, no git mutation commands.
    - Output files must not exist before the call; parents must exist.
    - Both artifacts are written via temp-files + os.replace().
      Temp files are cleaned up on any failure; no orphaned partial artifacts are left.
      On any precondition failure, no output file is written.

    Returns the run-result.v1 dict.
    """
    # --- Precondition: full schema validation of action plan ---
    action = _validate_action_plan_schema(action_plan)

    # --- Precondition: explicit mutating-action block (belt-and-suspenders) ---
    if action in MUTATING_ACTIONS:
        raise ValueError(
            f"action '{action}' is a mutating action and is blocked by the Phase 8A runner"
        )

    # --- Precondition: allowlist check ---
    if action not in PHASE_8A_ALLOWLIST:
        raise ValueError(
            f"action '{action}' is not in the Phase 8A read-only allowlist"
        )

    # --- Precondition: validate output paths before touching the filesystem ---
    trace_target = _require_output_path(command_trace_out, "command_trace_out")
    run_result_target = _require_output_path(run_result_out, "run_result_out")

    # --- Precondition: repo path must be a git worktree ---
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

    # Resolve the toplevel to use a canonical absolute path in the trace command.
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
    repo_toplevel = Path(toplevel_result.stdout.strip())

    # --- Execute the bounded command ---
    # The command is fully hard-coded. No user-supplied fragments are inserted.
    command: list[str] = ["git", "--no-optional-locks", "-C", str(repo_toplevel), "status", "--porcelain=v1"]

    trace_id = f"trace-read-only-{uuid.uuid4().hex[:16]}"
    run_id = f"run-read-only-{uuid.uuid4().hex[:16]}"

    started_at = _utc_rfc3339_now()
    proc = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    finished_at = _utc_rfc3339_now()

    exit_code = _normalize_exit_code(proc.returncode)

    stdout_excerpt = _excerpt(_redact_text(proc.stdout))
    stderr_excerpt = _excerpt(_redact_text(proc.stderr))

    trace: dict[str, Any] = {
        "schema_version": "command-trace.v1",
        "trace_id": trace_id,
        "command": command,
        "exit_code": exit_code,
        "stdout_excerpt": stdout_excerpt,
        "stderr_excerpt": stderr_excerpt,
        "redacted": True,
    }

    status = "success" if exit_code == 0 else "failure"

    run_result: dict[str, Any] = {
        "schema_version": "run-result.v1",
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "redaction_verified": True,
        "evidence_paths": [str(trace_target)],
    }

    # --- Write outputs atomically ---
    # Both artifacts are written to temp files in their target directories first.
    # Only after both temp files are fully flushed are they committed via os.replace().
    # On any exception during this phase the finally block deletes all temp files,
    # ensuring no orphaned partial artifacts are left on disk.
    _write_artifacts_atomic(trace_target, trace, run_result_target, run_result)

    return run_result
