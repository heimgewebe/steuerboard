"""Phase 9B: Stage-D approved switch-main runner.

Boundary contract:
- The runner consumes a Phase 9A ``switch-main-readiness.v1`` verdict and an
  ``action-approval-validation.v1`` binding, both pinned to the exact
  ``switch-main`` ``action-plan.v1``.  Execution is allowed only when the
  readiness ``status`` is ``ready`` and the approval ``binding_state`` is
  ``binding_valid`` for the same plan.
- ``ready`` readiness is not approval; approval is not execution.  The runner
  requires both, then re-derives the mutation-critical live repository state
  immediately before switching (resolved toplevel matches the readiness
  ``repo_toplevel``; current branch is known and not detached; worktree is
  clean; when the live branch is not ``main`` the readiness must prove
  ``branch_lifecycle_proof``).  It never fetches: ``origin/main`` freshness and
  ownership coherence are trusted from the readiness artifact, exactly as the
  Phase 9A contract specifies.
- Executes exactly one mutating Git subprocess call:
      git --no-optional-locks -C <repo-toplevel> switch main
  Read-only pre/post checks (rev-parse, status) are separate, non-mutating
  subprocess calls.
- No free shell, no shell=True.  No checkout, merge, rebase, reset, clean,
  pull, fetch, push, or branch deletion.
- All output files must not exist before the call; parents must exist; the
  three paths must be distinct and outside the inspected repository worktree.
- On any precondition failure: no output written, no Git mutation.
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
except ModuleNotFoundError:  # pragma: no cover - exercised by subprocess test environments
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate

from .action_runs import (
    _excerpt,
    _is_path_inside,
    _normalize_exit_code,
    _redact_text,
    _require_output_path,
    _utc_rfc3339_now,
)
from .canonical_json import canonical_json_sha256

# The one and only mutating git argument vector allowed by this runner; the
# "-C <repo-toplevel>" selector is inserted at call time.  This is NOT a
# template: no user-supplied command fragments are ever accepted.  The executed
# command is derived from this constant (see run_switch_main) so the audited
# boundary and the real subprocess argv cannot drift apart.
# --no-optional-locks: inhibit advisory lock acquisition (matches the pull and
#                      status runners).
# switch main: move HEAD to the local default branch; never deletes a branch,
#              never resolves conflicts, never touches the remote.
_GIT_SWITCH_MAIN_ARGV = ("--no-optional-locks", "switch", "main")

# The contractually fixed target branch for switch-main.
_TARGET_BRANCH = "main"

# The single action this runner supports.  Extending this is a separate,
# explicitly reviewed phase slice.
_SUPPORTED_ACTION = "switch-main"

# Name of the readiness check whose ``expected`` value carries the canonical
# plan content hash that Phase 9A bound the readiness verdict to.
_PLAN_CONTENT_CHECK = "proof_plan_content_sha256_matches_plan"

# Name of the readiness check that proves it is safe to leave a non-main branch.
_BRANCH_LIFECYCLE_CHECK = "branch_lifecycle_proof"

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


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


def _run_git(args: list[str]) -> tuple[int, str, str]:
    """Run a git sub-command.  Returns (normalized_exit_code, stdout, stderr).

    shell=False always.  stdin is closed.  Advisory locks are disabled via
    GIT_OPTIONAL_LOCKS=0 (belt-and-suspenders alongside --no-optional-locks),
    matching the pull/read-only runners' convention.  Output is decoded as
    UTF-8 with errors="replace" so non-UTF-8 git output never raises.  The
    caller supplies the exact argument list; no user-controlled data reaches
    this function through the normal call sites.
    """
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        check=False,
        shell=False,
        env=env,
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


def _current_branch(toplevel: Path) -> tuple[int, str]:
    """Return (exit_code, branch_name) from a read-only rev-parse.

    On a detached HEAD git returns the literal string ``HEAD``; the caller
    treats that as "current branch unknown".
    """
    exit_code, stdout, _stderr = _run_git(
        ["git", "-C", str(toplevel), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    return exit_code, stdout.strip()


def _worktree_status(toplevel: Path) -> tuple[int, str]:
    """Return (exit_code, porcelain_stdout) from a read-only status check."""
    exit_code, stdout, _stderr = _run_git(
        ["git", "--no-optional-locks", "-C", str(toplevel), "status", "--porcelain=v1"]
    )
    return exit_code, stdout


def _readiness_check(readiness: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Return the first ``checks`` entry with the given name, or None."""
    for entry in readiness.get("checks", []):
        if isinstance(entry, dict) and entry.get("check") == name:
            return entry
    return None


def _write_artifacts_atomic(items: list[tuple[Path, dict[str, Any]]]) -> None:
    """Write several artifacts atomically with rollback on partial failure.

    Each (target, data) pair is first staged into a temp file in the target's
    directory.  Only after every artifact is fully staged are they committed in
    order with os.replace().  If any commit fails, every already-committed
    target is unlinked and any uncommitted temp files are removed, so a caller
    never observes a partial set of output files.
    """
    staged: list[tuple[Path, Path]] = []  # (tmp, target)
    committed: list[Path] = []
    try:
        for target, data in items:
            fd, tmp = tempfile.mkstemp(
                dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
                )
            staged.append((Path(tmp), target))
        for tmp, target in staged:
            os.replace(tmp, target)
            committed.append(target)
    except Exception:
        for target in committed:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        committed_set = set(committed)
        for tmp, target in staged:
            if target not in committed_set:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        raise


def run_switch_main(
    *,
    action_plan: dict[str, Any],
    approval_validation: dict[str, Any],
    switch_main_readiness: dict[str, Any],
    repo_path: str,
    command_trace_out: str,
    run_result_out: str,
    postcheck_out: str,
) -> dict[str, Any]:
    """Execute a Stage-D approved switch-main run and write three artifacts.

    The runner consumes a Phase 9A ``switch-main-readiness.v1`` verdict directly
    (it does not recompute it from a preflight proof) but never trusts it
    blindly: it pins the readiness and the approval to the exact supplied plan,
    requires ``status == ready`` and ``binding_state == binding_valid``, and
    re-derives the mutation-critical live state immediately before the switch.

    Parameters
    ----------
    action_plan:
        action-plan.v1 artifact dict (action must be "switch-main").
    approval_validation:
        action-approval-validation.v1 artifact dict.  Must carry
        ``binding_state == "binding_valid"`` for this exact plan.
    switch_main_readiness:
        switch-main-readiness.v1 artifact dict.  Must carry ``status ==
        "ready"`` and bind to this exact plan.
    repo_path:
        Explicit path to the local git repository to switch in.
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
    # Precondition 1: schema-validate all three input artifacts.
    # -----------------------------------------------------------------------
    _validate_against_schema(action_plan, "action-plan.v1.schema.json", "action_plan")
    _validate_against_schema(
        approval_validation,
        "action-approval-validation.v1.schema.json",
        "approval_validation",
    )
    _validate_against_schema(
        switch_main_readiness,
        "switch-main-readiness.v1.schema.json",
        "switch_main_readiness",
    )

    # -----------------------------------------------------------------------
    # Precondition 2: action must be switch-main.
    # -----------------------------------------------------------------------
    plan_action = action_plan.get("action", "")
    if plan_action != _SUPPORTED_ACTION:
        raise ValueError(
            f"action_plan.action must be {_SUPPORTED_ACTION!r}; got {plan_action!r}"
        )
    plan_id = action_plan.get("plan_id", "")
    plan_content_sha256 = canonical_json_sha256(action_plan)

    # -----------------------------------------------------------------------
    # Precondition 3: approval validation must be binding_valid for this plan.
    # ``ready`` readiness is not approval — this gate is independent.
    # -----------------------------------------------------------------------
    binding_state = approval_validation.get("binding_state", "")
    if binding_state != "binding_valid":
        raise ValueError(
            f"approval_validation.binding_state must be 'binding_valid'; got {binding_state!r}"
        )
    if approval_validation.get("plan_ref") != plan_id:
        raise ValueError(
            f"approval_validation.plan_ref {approval_validation.get('plan_ref')!r} "
            f"does not match action_plan.plan_id {plan_id!r}"
        )
    if approval_validation.get("action") != _SUPPORTED_ACTION:
        raise ValueError(
            f"approval_validation.action must be {_SUPPORTED_ACTION!r}; "
            f"got {approval_validation.get('action')!r}"
        )

    # -----------------------------------------------------------------------
    # Precondition 4: readiness must be ready and bound to this exact plan.
    # The content hash binding is read from the Phase 9A check whose
    # ``expected`` value is canonical_json_sha256(plan); a ``ready`` verdict
    # guarantees that check passed, but we re-verify it against THIS plan so a
    # readiness computed for a different plan content cannot be substituted.
    # -----------------------------------------------------------------------
    if switch_main_readiness.get("action") != _SUPPORTED_ACTION:
        raise ValueError(
            f"switch_main_readiness.action must be {_SUPPORTED_ACTION!r}; "
            f"got {switch_main_readiness.get('action')!r}"
        )
    if switch_main_readiness.get("plan_ref") != plan_id:
        raise ValueError(
            f"switch_main_readiness.plan_ref {switch_main_readiness.get('plan_ref')!r} "
            f"does not match action_plan.plan_id {plan_id!r}"
        )
    readiness_status = switch_main_readiness.get("status", "")
    if readiness_status != "ready":
        raise ValueError(
            "readiness gate not satisfied: switch_main_readiness.status is "
            f"{readiness_status!r} (expected 'ready')"
        )
    content_check = _readiness_check(switch_main_readiness, _PLAN_CONTENT_CHECK)
    if content_check is None or content_check.get("passed") is not True:
        raise ValueError(
            "switch_main_readiness does not carry a passed "
            f"{_PLAN_CONTENT_CHECK!r} check"
        )
    if content_check.get("expected") != plan_content_sha256:
        raise ValueError(
            "plan_content_sha256_mismatch: switch_main_readiness was not computed "
            "for the supplied action_plan content"
        )

    readiness_repo_toplevel = switch_main_readiness.get("repo_toplevel")
    if not isinstance(readiness_repo_toplevel, str) or not readiness_repo_toplevel.strip():
        raise ValueError(
            "switch_main_readiness.repo_toplevel must be a non-empty string for a "
            "ready verdict"
        )

    # -----------------------------------------------------------------------
    # Precondition 5: validate output paths (must not exist; parents exist).
    # -----------------------------------------------------------------------
    trace_target = _require_output_path(command_trace_out, "command_trace_out")
    run_result_target = _require_output_path(run_result_out, "run_result_out")
    postcheck_target = _require_output_path(postcheck_out, "postcheck_out")

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
    # Precondition 6: resolve git toplevel and bind it to the readiness artifact.
    # -----------------------------------------------------------------------
    toplevel = _resolve_git_toplevel(repo_path)
    toplevel_str = str(toplevel)
    if toplevel_str != readiness_repo_toplevel:
        raise ValueError(
            f"repo_toplevel_mismatch: readiness repo_toplevel "
            f"{readiness_repo_toplevel!r} does not match resolved repo_toplevel "
            f"{toplevel_str!r}"
        )

    # -----------------------------------------------------------------------
    # Precondition 7: output files must not be inside the repository worktree.
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
    # Precondition 8: re-derive the current branch live (must be known).
    # -----------------------------------------------------------------------
    branch_exit, branch_before = _current_branch(toplevel)
    if branch_exit != 0 or not branch_before:
        raise ValueError("failed to read current branch before switch")
    if branch_before == "HEAD":
        raise ValueError(
            "current branch unknown (detached HEAD); refusing to switch"
        )

    # -----------------------------------------------------------------------
    # Precondition 9: re-derive worktree cleanliness live (must be clean).
    # -----------------------------------------------------------------------
    pre_status_exit, pre_status_stdout = _worktree_status(toplevel)
    if pre_status_exit != 0:
        raise ValueError(
            f"pre-switch worktree check failed: git status exited {pre_status_exit}"
        )
    if pre_status_stdout.strip():
        raise ValueError(
            "pre-switch worktree is not clean; aborting to avoid clobbering local changes"
        )

    # -----------------------------------------------------------------------
    # Precondition 10: when leaving a non-main branch, the readiness must prove
    # the branch lifecycle gate (it is safe to leave the current branch).  A
    # readiness computed while on ``main`` carries no such proof and therefore
    # cannot authorise switching away from a live non-main branch.
    # -----------------------------------------------------------------------
    if branch_before != _TARGET_BRANCH:
        lifecycle_check = _readiness_check(switch_main_readiness, _BRANCH_LIFECYCLE_CHECK)
        if lifecycle_check is None or lifecycle_check.get("passed") is not True:
            raise ValueError(
                "branch_lifecycle_unproven: live current branch is "
                f"{branch_before!r} (not 'main') but switch_main_readiness does not "
                f"carry a passed {_BRANCH_LIFECYCLE_CHECK!r} check"
            )

    # -----------------------------------------------------------------------
    # Build stable identifiers.
    # -----------------------------------------------------------------------
    trace_id = f"trace-switch-main-{uuid.uuid4()}"
    run_id = f"run-switch-main-{uuid.uuid4()}"

    # -----------------------------------------------------------------------
    # Execute the switch — exactly one command, no shell.  The argv is derived
    # from the audited boundary constant so it cannot drift from the test guard.
    # -----------------------------------------------------------------------
    switch_command = [
        "git",
        _GIT_SWITCH_MAIN_ARGV[0],
        "-C",
        str(toplevel),
        *_GIT_SWITCH_MAIN_ARGV[1:],
    ]
    started_at = _utc_rfc3339_now()
    switch_exit, switch_stdout, switch_stderr = _run_git(switch_command)
    finished_at = _utc_rfc3339_now()

    trace_data: dict[str, Any] = {
        "schema_version": "command-trace.v1",
        "trace_id": trace_id,
        "command": switch_command,
        "exit_code": switch_exit,
        "stdout_excerpt": _excerpt(_redact_text(switch_stdout)),
        "stderr_excerpt": _excerpt(_redact_text(switch_stderr)),
        "redacted": True,
    }

    # -----------------------------------------------------------------------
    # Post-execution checks: branch == main and worktree still clean.
    # -----------------------------------------------------------------------
    postcheck_observations: list[str] = [f"branch_before={branch_before!r}"]
    postcheck_failure_reasons: list[str] = []

    if switch_exit != 0:
        run_status = "failure"
        postcheck_status = "failed"
        postcheck_failure_reasons.append("switch_exit_code_nonzero")
        postcheck_observations.append(f"switch exit_code={switch_exit}")
    else:
        branch_after_exit, branch_after = _current_branch(toplevel)
        if branch_after_exit != 0 or not branch_after:
            run_status = "success"
            postcheck_status = "inconclusive"
            postcheck_failure_reasons.append("branch_unreadable_after_switch")
        elif branch_after != _TARGET_BRANCH:
            run_status = "failure"
            postcheck_status = "failed"
            postcheck_failure_reasons.append("not_on_main_after_switch")
            postcheck_observations.append(f"branch_after={branch_after!r}")
        else:
            post_status_exit, post_status_stdout = _worktree_status(toplevel)
            if post_status_exit != 0:
                run_status = "success"
                postcheck_status = "inconclusive"
                postcheck_failure_reasons.append("post_switch_status_check_failed")
                postcheck_observations.append(f"branch_after={branch_after!r}")
            elif post_status_stdout.strip():
                run_status = "failure"
                postcheck_status = "failed"
                postcheck_failure_reasons.append("worktree_not_clean_after_switch")
                postcheck_observations.append("post-switch git status is non-empty")
            else:
                run_status = "success"
                postcheck_status = "passed"
                postcheck_observations.append(f"branch_after={branch_after!r}")

    # -----------------------------------------------------------------------
    # Build run-result artifact.
    # -----------------------------------------------------------------------
    run_result_data: dict[str, Any] = {
        "schema_version": "run-result.v1",
        "run_id": run_id,
        "action": _SUPPORTED_ACTION,
        "plan_ref": plan_id,
        "plan_content_sha256": plan_content_sha256,
        "status": run_status,
        "started_at": started_at,
        "finished_at": finished_at,
        "redaction_verified": True,
        "evidence_paths": [str(trace_target)],
    }
    # Note: blocked_reasons is reserved for status == "blocked" (precondition
    # failures that prevent execution).  A "failure" status means the switch was
    # attempted but the result was negative; those reasons belong in the
    # postcheck's failure_reasons, not in run-result.blocked_reasons.

    # -----------------------------------------------------------------------
    # Build postcheck artifact.
    # -----------------------------------------------------------------------
    postcheck_id = f"postcheck-switch-main-{uuid.uuid4()}"
    postcheck_data: dict[str, Any] = {
        "schema_version": "run-postcheck.v1",
        "postcheck_id": postcheck_id,
        "run_id": run_id,
        "trace_ref": trace_id,
        "run_result_ref": run_id,
        "action": _SUPPORTED_ACTION,
        "repo_toplevel": toplevel_str,
        "checked_at": _utc_rfc3339_now(),
        "status": postcheck_status,
        "observations": postcheck_observations,
        "redaction_verified": True,
        "source_refs": [
            "git.rev_parse_abbrev_ref_head",
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
    # Commit all three artifacts atomically (rollback on partial failure).
    # -----------------------------------------------------------------------
    _write_artifacts_atomic(
        [
            (trace_target, trace_data),
            (run_result_target, run_result_data),
            (postcheck_target, postcheck_data),
        ]
    )

    return run_result_data
