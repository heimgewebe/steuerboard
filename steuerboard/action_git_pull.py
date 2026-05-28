"""Phase 8E: Stage-D approved git-pull-ff-only runner.

Boundary contract:
- The runner never trusts a pre-computed readiness artifact.
  It accepts the underlying artifacts (action plan, approval validation,
  run evidence chain, preflight binding) and internally reproduces the
  Stage-D readiness gate by calling validate_execution_readiness().
  Execution is allowed only when the reproduced status is "ready".
- Executes exactly one mutating Git subprocess call:
      git --no-optional-locks -C <repo-toplevel> pull --ff-only
  Read-only pre/post checks (status, rev-parse) are separate, non-mutating
  subprocess calls.
- No free shell, no shell=True, no merge, no rebase, no reset, no clean.
- All output files must not exist before the call; parents must exist.
- Output files are outside the inspected repository worktree.
- On any precondition failure: no output written, no Git mutation.
"""
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
except ModuleNotFoundError:  # pragma: no cover
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate  # type: ignore[no-redef]

from .action_execution_readiness import validate_execution_readiness
from .canonical_json import canonical_json_sha256

# The one and only mutating command suffix allowed by this runner.
# This is NOT a template.  No user-supplied command fragments are accepted.
# --no-optional-locks: inhibit advisory lock acquisition.
# pull --ff-only: fast-forward only; aborts if a merge would be required.
_GIT_PULL_FF_ONLY_ARGV = ("--no-optional-locks", "pull", "--ff-only")

_EXCERPT_LIMIT = 2000

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _utc_rfc3339_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_schema(filename: str) -> dict[str, Any]:
    cached = _SCHEMA_CACHE.get(filename)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent.parent / "schemas" / filename
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    _SCHEMA_CACHE[filename] = schema
    return schema


def _validate_against_schema(instance: Any, schema_filename: str, label: str) -> None:
    if not isinstance(instance, dict):
        raise ValueError(f"{label} must be a JSON object")
    try:
        jsonschema_validate(instance=instance, schema=_load_schema(schema_filename))
    except SchemaValidationError as exc:
        raise ValueError(f"{label} does not validate against schema: {exc}") from exc


def _require_output_path(path_str: str, param_name: str) -> Path:
    target = Path(path_str).expanduser().resolve(strict=False)
    if target.exists():
        raise ValueError(f"{param_name}: output file already exists: {target}")
    parent = target.parent.resolve(strict=False)
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"{param_name}: parent directory does not exist: {parent}")
    return parent / target.name


def _is_path_inside(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


# Pattern matching credential-like substrings in URLs (user:token@host).
_CREDENTIAL_RE = re.compile(r"(https?://)([^@/\s]+:[^@/\s]+@)", re.IGNORECASE)


def _redact_excerpt(value: str) -> str:
    """Remove credential-like patterns from excerpt text and truncate."""
    value = _CREDENTIAL_RE.sub(r"\1[REDACTED]@", value)
    return value.strip()[:_EXCERPT_LIMIT]


def _normalize_exit_code(returncode: int) -> int:
    if returncode < 0:
        return 128 + abs(returncode)
    return returncode


def _run_git(args: list[str]) -> tuple[int, str, str]:
    """Run a git sub-command.  Returns (exit_code, stdout, stderr).

    shell=False always.  stdin is closed.  The caller supplies the exact
    argument list; no user-controlled data reaches this function through
    the normal call sites.
    """
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        check=False,
        shell=False,
    )
    return (
        _normalize_exit_code(result.returncode),
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
    )


def _resolve_git_toplevel(repo_path: str) -> Path:
    """Return the resolved git toplevel for repo_path.

    Raises ValueError if the path is not inside a git repository.
    """
    resolved = Path(repo_path).expanduser().resolve()
    exit_code, stdout, _stderr = _run_git(
        ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"]
    )
    if exit_code != 0:
        raise ValueError(
            f"repo_path is not a valid git repository: {repo_path!r} "
            f"(git rev-parse --show-toplevel failed with exit code {exit_code})"
        )
    return Path(stdout.strip()).resolve()


def _write_three_artifacts_atomic(
    trace_target: Path,
    trace_data: dict[str, Any],
    run_result_target: Path,
    run_result_data: dict[str, Any],
    postcheck_target: Path,
    postcheck_data: dict[str, Any],
) -> None:
    """Write three artifacts via temp files with best-effort rollback.

    All three are staged into temp files first.  Only after all three are
    fully written are they committed in sequence with os.replace().  If any
    commit step fails, all previously committed targets are removed so the
    caller never observes partial output.  Any remaining temp files are
    cleaned up on error.
    """
    trace_tmp: Path | None = None
    run_result_tmp: Path | None = None
    postcheck_tmp: Path | None = None
    try:
        # Stage 1: write all three to temp files
        fd, t = tempfile.mkstemp(
            dir=trace_target.parent,
            prefix=f".{trace_target.name}.",
            suffix=".tmp",
        )
        trace_tmp = Path(t)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(trace_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")

        fd, t = tempfile.mkstemp(
            dir=run_result_target.parent,
            prefix=f".{run_result_target.name}.",
            suffix=".tmp",
        )
        run_result_tmp = Path(t)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(run_result_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            )

        fd, t = tempfile.mkstemp(
            dir=postcheck_target.parent,
            prefix=f".{postcheck_target.name}.",
            suffix=".tmp",
        )
        postcheck_tmp = Path(t)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(postcheck_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            )

        # Stage 2: commit — rolling back on each failure
        os.replace(trace_tmp, trace_target)
        trace_tmp = None
        try:
            os.replace(run_result_tmp, run_result_target)
            run_result_tmp = None
        except Exception:
            try:
                trace_target.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        try:
            os.replace(postcheck_tmp, postcheck_target)
            postcheck_tmp = None
        except Exception:
            try:
                trace_target.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                run_result_target.unlink(missing_ok=True)
            except OSError:
                pass
            raise
    except Exception:
        for tmp in (trace_tmp, run_result_tmp, postcheck_tmp):
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        raise


def run_git_pull_ff_only(
    *,
    action_plan: dict[str, Any],
    approval_validation: dict[str, Any],
    run_evidence_chain: dict[str, Any],
    preflight_binding: dict[str, Any],
    repo_path: str,
    command_trace_out: str,
    run_result_out: str,
    postcheck_out: str,
) -> dict[str, Any]:
    """Execute a Stage-D approved git-pull-ff-only run and write three output artifacts.

    The runner reproduces Stage-D readiness internally by calling
    validate_execution_readiness() with the four supplied artifacts.  A
    pre-computed readiness artifact is never consulted — this makes the
    security boundary explicit: only if the four underlying artifacts
    together prove ``status == "ready"`` will the pull be executed.

    Parameters
    ----------
    action_plan:
        action-plan.v1 artifact dict (action must be "git-pull-ff-only").
    approval_validation:
        action-approval-validation.v1 artifact dict.
    run_evidence_chain:
        run-evidence-chain.v1 artifact dict.
    preflight_binding:
        action-preflight-binding.v1 artifact dict.  Must carry
        ``binding_state == "binding_valid"`` and a
        ``preflight_for_action_plan`` proof object.
    repo_path:
        Explicit path to the local git repository to pull in.
    command_trace_out:
        Output path for command-trace.v1.  Must not exist; parent must exist.
    run_result_out:
        Output path for run-result.v1.  Must not exist; parent must exist.
    postcheck_out:
        Output path for run-postcheck.v1.  Must not exist; parent must exist.

    Returns
    -------
    dict
        The run-result.v1 artifact written to run_result_out.

    Raises
    ------
    ValueError
        On any precondition failure.  No output files are written on failure.
        No Git mutation occurs on failure.
    """
    # -----------------------------------------------------------------------
    # Precondition 1: schema-validate all four input artifacts.
    # -----------------------------------------------------------------------
    _validate_against_schema(action_plan, "action-plan.v1.schema.json", "action_plan")
    _validate_against_schema(
        approval_validation,
        "action-approval-validation.v1.schema.json",
        "approval_validation",
    )
    _validate_against_schema(
        run_evidence_chain,
        "run-evidence-chain.v1.schema.json",
        "run_evidence_chain",
    )
    _validate_against_schema(
        preflight_binding,
        "action-preflight-binding.v1.schema.json",
        "preflight_binding",
    )

    # -----------------------------------------------------------------------
    # Precondition 2: action must be git-pull-ff-only.
    # -----------------------------------------------------------------------
    plan_action = action_plan.get("action", "")
    if plan_action != "git-pull-ff-only":
        raise ValueError(
            f"action_plan.action must be 'git-pull-ff-only'; got {plan_action!r}"
        )

    # -----------------------------------------------------------------------
    # Precondition 3: preflight_binding must be binding_valid with proof.
    # -----------------------------------------------------------------------
    binding_state = preflight_binding.get("binding_state", "")
    if binding_state != "binding_valid":
        raise ValueError(
            f"preflight_binding.binding_state must be 'binding_valid'; got {binding_state!r}"
        )
    if not isinstance(preflight_binding.get("preflight_for_action_plan"), dict):
        raise ValueError(
            "preflight_binding must carry a preflight_for_action_plan proof object"
        )

    # Verify the proof object against the supplied action_plan without
    # delegating this responsibility to validate_execution_readiness().
    # A binding_valid state plus a present proof block is not sufficient;
    # the runner must confirm the proof binds exactly to this plan.
    _proof = preflight_binding["preflight_for_action_plan"]
    if _proof.get("plan_ref") != action_plan.get("plan_id"):
        raise ValueError(
            f"preflight_binding.preflight_for_action_plan.plan_ref "
            f"{_proof.get('plan_ref')!r} does not match "
            f"action_plan.plan_id {action_plan.get('plan_id')!r}"
        )
    if _proof.get("plan_action") != "git-pull-ff-only":
        raise ValueError(
            f"preflight_binding.preflight_for_action_plan.plan_action "
            f"must be 'git-pull-ff-only'; got {_proof.get('plan_action')!r}"
        )
    _expected_sha = canonical_json_sha256(action_plan)
    if _proof.get("plan_content_sha256") != _expected_sha:
        raise ValueError(
            "preflight_binding.preflight_for_action_plan.plan_content_sha256 "
            "does not match the canonical JSON sha256 of the supplied action_plan"
        )

    # -----------------------------------------------------------------------
    # Precondition 4: validate output paths.
    # -----------------------------------------------------------------------
    trace_target = _require_output_path(command_trace_out, "command_trace_out")
    run_result_target = _require_output_path(run_result_out, "run_result_out")
    postcheck_target = _require_output_path(postcheck_out, "postcheck_out")

    # All three output paths must be distinct; writing one must not clobber another.
    _seen_paths: dict[Path, str] = {}
    for _out_path, _out_label in [
        (trace_target, "command_trace_out"),
        (run_result_target, "run_result_out"),
        (postcheck_target, "postcheck_out"),
    ]:
        if _out_path in _seen_paths:
            raise ValueError(
                f"{_out_label} and {_seen_paths[_out_path]} resolve to the same file: "
                f"{_out_path}"
            )
        _seen_paths[_out_path] = _out_label

    # -----------------------------------------------------------------------
    # Precondition 5: resolve git toplevel.
    # -----------------------------------------------------------------------
    toplevel = _resolve_git_toplevel(repo_path)

    # -----------------------------------------------------------------------
    # Precondition 6: output files must not be inside the repository.
    # -----------------------------------------------------------------------
    for path, label in [
        (trace_target, "command_trace_out"),
        (run_result_target, "run_result_out"),
        (postcheck_target, "postcheck_out"),
    ]:
        if _is_path_inside(toplevel, path):
            raise ValueError(
                f"{label} must not be inside the repository worktree: {path}"
            )

    # -----------------------------------------------------------------------
    # Precondition 7: internally reproduce readiness — never trust a
    # pre-computed readiness artifact.  Only proceed if reproduced status
    # is "ready".
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_readiness_path = str(Path(tmp_dir) / "readiness.json")
        try:
            reproduced_readiness = validate_execution_readiness(
                action_plan=action_plan,
                approval_validation=approval_validation,
                run_evidence_chain=run_evidence_chain,
                preflight_binding=preflight_binding,
                readiness_out=tmp_readiness_path,
            )
        except ValueError as exc:
            raise ValueError(f"readiness reproduction failed: {exc}") from exc

    if reproduced_readiness["status"] != "ready":
        raise ValueError(
            "readiness gate not satisfied: reproduced status is "
            f"{reproduced_readiness['status']!r} (expected 'ready')"
        )

    # -----------------------------------------------------------------------
    # Precondition 8: pre-pull worktree must be clean.
    # -----------------------------------------------------------------------
    pre_status_exit, pre_status_stdout, pre_status_stderr = _run_git(
        ["git", "--no-optional-locks", "-C", str(toplevel), "status", "--porcelain=v1"]
    )
    if pre_status_exit != 0:
        raise ValueError(
            f"pre-pull worktree check failed: git status exited {pre_status_exit}"
        )
    if pre_status_stdout.strip():
        raise ValueError(
            "pre-pull worktree is not clean; aborting to avoid clobbering local changes"
        )

    # -----------------------------------------------------------------------
    # Precondition 9: read HEAD before pull.
    # -----------------------------------------------------------------------
    head_before_exit, head_before_stdout, _ = _run_git(
        ["git", "-C", str(toplevel), "rev-parse", "HEAD"]
    )
    if head_before_exit != 0:
        raise ValueError("failed to read HEAD before pull")
    head_before = head_before_stdout.strip()

    # -----------------------------------------------------------------------
    # Build stable identifiers.
    # -----------------------------------------------------------------------
    trace_id = f"trace-git-pull-ff-only-{uuid.uuid4()}"
    run_id = f"run-git-pull-ff-only-{uuid.uuid4()}"
    plan_id = action_plan.get("plan_id", "unknown")
    plan_content_sha256 = canonical_json_sha256(action_plan)

    # -----------------------------------------------------------------------
    # Execute the pull — exactly one command, no shell.
    # -----------------------------------------------------------------------
    pull_command = [
        "git",
        "--no-optional-locks",
        "-C",
        str(toplevel),
        "pull",
        "--ff-only",
    ]
    started_at = _utc_rfc3339_now()
    pull_exit, pull_stdout, pull_stderr = _run_git(pull_command)
    finished_at = _utc_rfc3339_now()

    stdout_excerpt = _redact_excerpt(pull_stdout)
    stderr_excerpt = _redact_excerpt(pull_stderr)

    trace_data: dict[str, Any] = {
        "schema_version": "command-trace.v1",
        "trace_id": trace_id,
        "command": pull_command,
        "exit_code": pull_exit,
        "stdout_excerpt": stdout_excerpt,
        "stderr_excerpt": stderr_excerpt,
        "redacted": True,
    }

    # -----------------------------------------------------------------------
    # Post-execution checks.
    # -----------------------------------------------------------------------
    postcheck_observations: list[str] = []
    postcheck_failure_reasons: list[str] = []

    if pull_exit != 0:
        # Hard failure — pull command itself failed.
        run_status = "failure"
        postcheck_status = "failed"
        postcheck_failure_reasons.append("pull_exit_code_nonzero")
        postcheck_observations.append(f"pull exit_code={pull_exit}")
    elif "already up to date" in pull_stdout.lower():
        # Phase 8E does not model "already up to date" as success.
        run_status = "success"
        postcheck_status = "inconclusive"
        postcheck_failure_reasons.append("already_up_to_date")
        postcheck_observations.append("pull succeeded but worktree was already up to date")
    else:
        # Pull claimed to have fetched changes — verify the fast-forward.
        head_after_exit, head_after_stdout, _ = _run_git(
            ["git", "-C", str(toplevel), "rev-parse", "HEAD"]
        )
        if head_after_exit != 0:
            run_status = "success"
            postcheck_status = "inconclusive"
            postcheck_failure_reasons.append("head_unreadable_after_pull")
        else:
            head_after = head_after_stdout.strip()
            if head_after == head_before:
                # HEAD did not advance but output was not "already up to date".
                run_status = "success"
                postcheck_status = "inconclusive"
                postcheck_failure_reasons.append("head_unchanged_after_pull")
                postcheck_observations.append(
                    f"head_before={head_before!r} head_after={head_after!r}"
                )
            else:
                # HEAD advanced — --ff-only prevents a locally created merge
                # commit; trust the flag and check only worktree cleanliness.
                post_status_exit, post_status_stdout, _ = _run_git(
                    [
                        "git",
                        "--no-optional-locks",
                        "-C",
                        str(toplevel),
                        "status",
                        "--porcelain=v1",
                    ]
                )
                if post_status_exit != 0:
                    run_status = "success"
                    postcheck_status = "inconclusive"
                    postcheck_failure_reasons.append("post_pull_status_check_failed")
                elif post_status_stdout.strip():
                    run_status = "failure"
                    postcheck_status = "failed"
                    postcheck_failure_reasons.append("worktree_not_clean_after_pull")
                    postcheck_observations.append("post-pull git status is non-empty")
                else:
                    # All checks passed — fast-forward confirmed.
                    run_status = "success"
                    postcheck_status = "passed"
                    postcheck_observations.append(f"head_before={head_before!r}")
                    postcheck_observations.append(f"head_after={head_after!r}")

    # -----------------------------------------------------------------------
    # Build run-result artifact.
    # -----------------------------------------------------------------------
    run_result_data: dict[str, Any] = {
        "schema_version": "run-result.v1",
        "run_id": run_id,
        "action": "git-pull-ff-only",
        "plan_ref": plan_id,
        "plan_content_sha256": plan_content_sha256,
        "status": run_status,
        "started_at": started_at,
        "finished_at": finished_at,
        "redaction_verified": True,
        "evidence_paths": [str(trace_target)],
    }
    if run_status != "success":
        run_result_data["blocked_reasons"] = postcheck_failure_reasons or [
            f"pull_failed_exit_code_{pull_exit}"
        ]

    # -----------------------------------------------------------------------
    # Build postcheck artifact.
    # -----------------------------------------------------------------------
    postcheck_id = f"postcheck-git-pull-ff-only-{uuid.uuid4()}"
    checked_at = _utc_rfc3339_now()
    postcheck_data: dict[str, Any] = {
        "schema_version": "run-postcheck.v1",
        "postcheck_id": postcheck_id,
        "run_id": run_id,
        "trace_ref": trace_id,
        "run_result_ref": run_id,
        "action": "git-pull-ff-only",
        "repo_toplevel": str(toplevel),
        "checked_at": checked_at,
        "status": postcheck_status,
        "observations": postcheck_observations,
        "redaction_verified": True,
        "source_refs": [
            "git.rev_parse",
            "git.status_porcelain",
            "run-result.v1",
            "command-trace.v1",
        ],
        "evidence_paths": [str(trace_target), str(run_result_target)],
    }
    if postcheck_failure_reasons:
        postcheck_data["failure_reasons"] = postcheck_failure_reasons

    # -----------------------------------------------------------------------
    # Validate output artifacts before touching the filesystem.
    # -----------------------------------------------------------------------
    _validate_against_schema(trace_data, "command-trace.v1.schema.json", "command-trace.v1")
    _validate_against_schema(run_result_data, "run-result.v1.schema.json", "run-result.v1")
    _validate_against_schema(
        postcheck_data, "run-postcheck.v1.schema.json", "run-postcheck.v1"
    )

    # -----------------------------------------------------------------------
    # Commit all three artifacts atomically.
    # -----------------------------------------------------------------------
    _write_three_artifacts_atomic(
        trace_target,
        trace_data,
        run_result_target,
        run_result_data,
        postcheck_target,
        postcheck_data,
    )

    return run_result_data
