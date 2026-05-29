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

from .action_execution_readiness import validate_execution_readiness
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
# command is derived from this constant (see run_git_pull_ff_only) so the
# audited boundary and the real subprocess argv cannot drift apart.
# --no-optional-locks: inhibit advisory lock acquisition.
# pull --ff-only: fast-forward only; aborts if a merge would be required.
_GIT_PULL_FF_ONLY_ARGV = ("--no-optional-locks", "pull", "--ff-only")

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


def _is_already_up_to_date_output(stdout: str, stderr: str) -> bool:
    """Detect up-to-date pull output across common git wording variants."""
    text = f"{stdout}\n{stderr}".lower()
    return "already up to date" in text or "already up-to-date" in text


def _run_git(args: list[str]) -> tuple[int, str, str]:
    """Run a git sub-command.  Returns (normalized_exit_code, stdout, stderr).

    shell=False always.  stdin is closed.  Advisory locks are disabled via
    GIT_OPTIONAL_LOCKS=0 (belt-and-suspenders alongside --no-optional-locks),
    matching the read-only runner's convention.  Output is decoded as UTF-8
    with errors="replace" so non-UTF-8 git output never raises.  The caller
    supplies the exact argument list; no user-controlled data reaches this
    function through the normal call sites.
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
    """Execute a Stage-D approved git-pull-ff-only run and write three artifacts.

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
    pre_status_exit, pre_status_stdout, _pre_status_stderr = _run_git(
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
    # Execute the pull — exactly one command, no shell.  The argv is derived
    # from the audited boundary constant so it cannot drift from the test guard.
    # -----------------------------------------------------------------------
    pull_command = [
        "git",
        _GIT_PULL_FF_ONLY_ARGV[0],
        "-C",
        str(toplevel),
        *_GIT_PULL_FF_ONLY_ARGV[1:],
    ]
    started_at = _utc_rfc3339_now()
    pull_exit, pull_stdout, pull_stderr = _run_git(pull_command)
    finished_at = _utc_rfc3339_now()

    stdout_excerpt = _excerpt(_redact_text(pull_stdout))
    stderr_excerpt = _excerpt(_redact_text(pull_stderr))

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
    elif _is_already_up_to_date_output(pull_stdout, pull_stderr):
        # Phase 8E does not model "already up to date" as a confirmed pull.
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
