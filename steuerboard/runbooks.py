"""Phase 11A — Read-only Runbook Runner.

Implements the repo-sync-gate runbook kind only.

Architecture rule (Observation != Derivation != Decision != Action):
- A runbook sequences observations and derivations only.
- It does not collapse them into action.
- It does not authorise, execute, or permit any mutating operation.

Authority model:
- A runbook result is derived diagnostic material, not canonical state.
- It is not an approval, not execution permission, not a Stage-D gate substitute.

Boundary:
- No mutating Git operations.
- No subprocess with shell=True.
- No os.system.
- No generic command runner.
- Calls existing Python functions directly (observe_repo, assess_repo).
- Atomic writes via temp-file + os.replace, cleaned up on failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any

from .assessment import assess_repo
from .observation import observe_repo

try:
    from jsonschema import ValidationError as SchemaValidationError
    from jsonschema import validate as jsonschema_validate
except ModuleNotFoundError:  # pragma: no cover
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

_RUNBOOK_PLAN_SCHEMA: dict[str, Any] | None = None
_RUNBOOK_RESULT_SCHEMA: dict[str, Any] | None = None
_RUNBOOK_STEP_TRACE_SCHEMA: dict[str, Any] | None = None

# Allowed runbook kinds in Phase 11A.
PHASE_11A_RUNBOOK_KINDS: frozenset[str] = frozenset({"repo-sync-gate"})


def _load_schema(name: str) -> dict[str, Any]:
    schema_path = _SCHEMAS_DIR / f"{name}.schema.json"
    with schema_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _get_runbook_plan_schema() -> dict[str, Any]:
    global _RUNBOOK_PLAN_SCHEMA
    if _RUNBOOK_PLAN_SCHEMA is None:
        _RUNBOOK_PLAN_SCHEMA = _load_schema("runbook-plan.v1")
    return _RUNBOOK_PLAN_SCHEMA


def _get_runbook_result_schema() -> dict[str, Any]:
    global _RUNBOOK_RESULT_SCHEMA
    if _RUNBOOK_RESULT_SCHEMA is None:
        _RUNBOOK_RESULT_SCHEMA = _load_schema("runbook-result.v1")
    return _RUNBOOK_RESULT_SCHEMA


def _get_runbook_step_trace_schema() -> dict[str, Any]:
    global _RUNBOOK_STEP_TRACE_SCHEMA
    if _RUNBOOK_STEP_TRACE_SCHEMA is None:
        _RUNBOOK_STEP_TRACE_SCHEMA = _load_schema("runbook-step-trace.v1")
    return _RUNBOOK_STEP_TRACE_SCHEMA


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _result_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%fZ")
    entropy = time_ns()
    digest = hashlib.sha256(f"rbresult:{now}:{entropy}".encode("utf-8")).hexdigest()[:12]
    return f"rbresult-{now}-{digest}"


def _trace_id(step_id: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%fZ")
    entropy = time_ns()
    digest = hashlib.sha256(f"rbtrace:{step_id}:{now}:{entropy}".encode("utf-8")).hexdigest()[:12]
    return f"rbtrace-{step_id}-{now}-{digest}"


def _merge_source_refs(*groups: Any) -> list[str]:
    """Merge source_refs preserving insertion order and uniqueness."""
    merged_refs: list[str] = []
    seen_refs: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for ref in group:
            if not isinstance(ref, str):
                continue
            clean_ref = ref.strip()
            if not clean_ref:
                continue
            if clean_ref in seen_refs:
                continue
            seen_refs.add(clean_ref)
            merged_refs.append(clean_ref)
    return merged_refs


def _require_output_path(raw: str, label: str) -> Path:
    """Return resolved Path; raise ValueError if parent missing or target exists."""
    candidate = Path(raw).expanduser()
    target = candidate.resolve()
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"{label} parent directory must exist")
    if target.exists():
        raise ValueError(f"{label} must not already exist")
    return parent.resolve(strict=True) / target.name


def _resolve_repo_worktree_root(repo_path_raw: str) -> Path:
    repo_path = Path(repo_path_raw).expanduser().resolve()
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--show-toplevel"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError:
        completed = None

    if completed and completed.returncode == 0 and completed.stdout.strip():
        return Path(completed.stdout.strip()).expanduser().resolve()

    observation = observe_repo(repo_path)
    repo_toplevel = observation.get("repo_toplevel")
    if isinstance(repo_toplevel, str) and repo_toplevel.strip():
        return Path(repo_toplevel).expanduser().resolve()
    return repo_path


def _ensure_outputs_outside_worktree(
    repo_worktree_root: Path,
    result_out: Path,
    command_trace_out: Path,
) -> None:
    for label, output_path in (("result_out", result_out), ("command_trace_out", command_trace_out)):
        try:
            output_path.relative_to(repo_worktree_root)
        except ValueError:
            continue
        raise ValueError(
            f"{label} must be outside repository worktree for read_only runbook: {output_path}"
        )


def _validate_plan_preconditions(
    runbook_plan: dict[str, Any],
    result_out: Path,
    command_trace_out: Path,
) -> None:
    """Validate preconditions before any execution begins.

    Raises ValueError for any precondition failure.
    No output files are written on precondition failure.
    """
    # 1. Schema-validate runbook plan
    try:
        jsonschema_validate(runbook_plan, _get_runbook_plan_schema())
    except (SchemaValidationError, Exception) as exc:
        raise ValueError(f"runbook_plan schema validation failed: {exc}") from exc

    # 2. Only repo-sync-gate is allowed in Phase 11A
    runbook_kind = runbook_plan.get("runbook_kind", "")
    if runbook_kind not in PHASE_11A_RUNBOOK_KINDS:
        raise ValueError(
            f"unsupported runbook_kind {runbook_kind!r}; "
            f"Phase 11A supports only: {sorted(PHASE_11A_RUNBOOK_KINDS)}"
        )

    # 3. Mode must be read_only
    mode = runbook_plan.get("mode", "")
    if mode != "read_only":
        raise ValueError(
            f"mode must be read_only, got {mode!r}"
        )

    # 4. Output paths must be distinct
    if result_out == command_trace_out:
        raise ValueError(
            "result_out and command_trace_out must be different paths"
        )


# ---------------------------------------------------------------------------
# Repo-sync-gate step checks (derivation only — no mutation, no subprocess)
# ---------------------------------------------------------------------------

def check_is_git_repo(observation: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the is-git-repo check."""
    obs_state = observation.get("observed_state")
    if not isinstance(obs_state, dict):
        return "inconclusive", "Git repository status is unknown."
    is_git = obs_state.get("is_git_repo")
    if is_git is True:
        return "passed", "Path is a git repository."
    if is_git is False:
        return "blocked", "Path is not a git repository."
    return "inconclusive", "Git repository status is unknown."


def check_worktree_clean(observation: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the worktree-clean check."""
    obs_state = observation.get("observed_state")
    if not isinstance(obs_state, dict):
        return "inconclusive", "Worktree cleanliness is unknown."
    dirty = obs_state.get("dirty")
    if dirty is False:
        return "passed", "Worktree is clean."
    if dirty is True:
        return "blocked", "Worktree is dirty (uncommitted changes present)."
    return "inconclusive", "Worktree cleanliness is unknown."


def check_not_detached_head(observation: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the not-detached-head check.

    Note: In repo-observation.v1, ``current_branch is None`` is an explicit
    detached-HEAD observation, so this check remains a hard block.
    """
    obs_state = observation.get("observed_state")
    if not isinstance(obs_state, dict):
        return "inconclusive", "Git repository status is unknown; HEAD check skipped."
    is_git = obs_state.get("is_git_repo")
    if is_git is not True:
        if is_git is False:
            return "inconclusive", "Not a git repository; HEAD check skipped."
        return "inconclusive", "Git repository status is unknown; HEAD check skipped."
    current_branch_raw = obs_state.get("current_branch")
    if current_branch_raw is None:
        return "blocked", "HEAD is detached."
    if not isinstance(current_branch_raw, str):
        return "inconclusive", "Current branch is unknown; HEAD check inconclusive."
    current_branch = current_branch_raw.strip()
    if current_branch:
        return "passed", f"HEAD is on branch {current_branch!r}."
    return "inconclusive", "Current branch is unknown; HEAD check inconclusive."


def check_on_default_branch(observation: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the on-default-branch check.

    Detached HEAD does not answer "on default branch", so this check is
    inconclusive rather than blocked and relies on check_not_detached_head for
    the hard block.
    """
    obs_state = observation.get("observed_state")
    if not isinstance(obs_state, dict):
        return "inconclusive", "Git repository status is unknown; branch check skipped."
    is_git = obs_state.get("is_git_repo")
    if is_git is not True:
        if is_git is False:
            return "inconclusive", "Not a git repository; branch check skipped."
        return "inconclusive", "Git repository status is unknown; branch check skipped."
    current_branch_raw = obs_state.get("current_branch")
    if current_branch_raw is None:
        return "inconclusive", "HEAD is detached; default branch check skipped."
    if not isinstance(current_branch_raw, str):
        return "inconclusive", "Current branch is unknown."
    current_branch = current_branch_raw.strip()
    if not current_branch:
        return "inconclusive", "Current branch is unknown."
    default_candidate_raw = obs_state.get("default_branch_candidate")
    if not isinstance(default_candidate_raw, str):
        return "inconclusive", "Default branch candidate is unknown."
    default_candidate = default_candidate_raw.strip()
    if not default_candidate:
        return "inconclusive", "Default branch candidate is unknown."
    if current_branch == default_candidate:
        return "passed", f"Current branch {current_branch!r} matches default branch candidate {default_candidate!r}."
    return "blocked", (
        f"Current branch {current_branch!r} does not match default branch candidate {default_candidate!r}."
    )


def check_decision_state(assessment: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the decision-state check.

    Mapping:
    - assessment_clear  -> passed
    - evidence_missing  -> inconclusive (not hard-blocked, but not clear either)
    - action_blocked    -> blocked (do NOT soften)
    """
    decision_state = assessment.get("decision_state", "")
    if decision_state == "assessment_clear":
        return "passed", "Assessment decision_state is assessment_clear."
    if decision_state == "evidence_missing":
        return "inconclusive", "Assessment decision_state is evidence_missing."
    if decision_state == "action_blocked":
        return "blocked", "Assessment decision_state is action_blocked."
    return "inconclusive", f"Assessment decision_state is unknown or missing: {decision_state!r}."


def _validate_step_trace(entry: dict[str, Any]) -> None:
    """Validate a step trace entry against the runbook-step-trace.v1 schema.

    Raises ValueError if validation fails.
    """
    try:
        jsonschema_validate(entry, _get_runbook_step_trace_schema())
    except (SchemaValidationError, Exception) as exc:
        raise ValueError(f"step trace entry failed schema validation: {exc}") from exc


def _validate_result(result: dict[str, Any]) -> None:
    """Validate the result dict against the runbook-result.v1 schema.

    Raises ValueError if validation fails.
    """
    try:
        jsonschema_validate(result, _get_runbook_result_schema())
    except (SchemaValidationError, Exception) as exc:
        raise ValueError(f"runbook result failed schema validation: {exc}") from exc


def _derive_overall_status(steps: list[dict[str, Any]]) -> str:
    """Derive overall runbook status from step statuses.

    Rules:
    - Any blocked step -> overall blocked (do NOT soften)
    - Any inconclusive step (no blocked) -> overall inconclusive
    - All passed -> overall passed
    """
    statuses = [step["status"] for step in steps]
    if "blocked" in statuses:
        return "blocked"
    if "inconclusive" in statuses:
        return "inconclusive"
    return "passed"


def _build_short_assessment(
    overall_status: str,
    steps: list[dict[str, Any]],
    runbook_kind: str,
    assessment: dict[str, Any],
) -> str:
    """Build a short human-readable assessment string."""
    derived_status = assessment.get("derived_status", [])
    decision_state = assessment.get("decision_state", "unknown")
    missing_evidence = assessment.get("missing_evidence", [])

    if overall_status == "passed":
        return (
            f"Repo-sync-gate passed. "
            f"Repository assessment: decision_state={decision_state!r}, "
            f"derived_status={derived_status!r}. "
            f"All local preflight checks passed. "
            f"Remote freshness evidence may still be missing (expected for a read-only local gate)."
        )
    if overall_status == "blocked":
        blocked_steps = [s["step_id"] for s in steps if s["status"] == "blocked"]
        return (
            f"Repo-sync-gate blocked. "
            f"Assessment decision_state={decision_state!r}, derived_status={derived_status!r}. "
            f"Blocked at steps: {blocked_steps!r}. "
            f"No mutating action is authorised."
        )
    # inconclusive
    return (
        f"Repo-sync-gate inconclusive. "
        f"Assessment decision_state={decision_state!r}, derived_status={derived_status!r}, "
        f"missing_evidence={missing_evidence!r}. "
        f"Cannot determine sync readiness without additional evidence. No action authorised."
    )


def run_runbook(
    runbook_plan: dict[str, Any],
    result_out: str,
    command_trace_out: str,
) -> dict[str, Any]:
    """Execute a read-only runbook and write result + trace artifacts.

    Parameters
    ----------
    runbook_plan:
        Parsed runbook-plan.v1 dict. Must be schema-valid.
    result_out:
        Output path for runbook-result.v1 JSON. Must not exist. Parent must exist.
    command_trace_out:
        Output path for runbook-step-trace.v1 JSONL. Must not exist. Parent must exist.

    Returns
    -------
    dict
        The runbook-result.v1 artifact.

    Raises
    ------
    ValueError
        On any precondition failure (invalid plan, wrong kind, mode, path conflict).
        No output files are written on precondition failure.
    """
    # --- Resolve and validate output paths first (precondition, no writes yet) ---
    result_path = _require_output_path(result_out, "result_out")
    trace_path = _require_output_path(command_trace_out, "command_trace_out")

    # --- Validate plan schema, kind, mode, path distinctness ---
    _validate_plan_preconditions(runbook_plan, result_path, trace_path)
    repo_worktree_root = _resolve_repo_worktree_root(str(runbook_plan["repo_path"]))
    _ensure_outputs_outside_worktree(repo_worktree_root, result_path, trace_path)

    # --- Execution begins here ---
    runbook_id = runbook_plan["runbook_id"]
    repo_path_str = runbook_plan["repo_path"]
    runbook_kind = runbook_plan["runbook_kind"]
    started_at = _utc_now()
    steps: list[dict[str, Any]] = []
    step_traces: list[dict[str, Any]] = []

    BOUNDARY = {
        "does_not_execute_mutating_actions": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
        "read_only_or_dry_run_only": True,
    }

    # --- Step 1: observe_repo (read_only) ---
    step_id_observe = "step-observe-repo"
    t0 = _utc_now()
    observation: dict[str, Any] = {}
    observe_status = "passed"
    try:
        observation = observe_repo(Path(repo_path_str))
    except Exception:  # noqa: BLE001
        observe_status = "inconclusive"
        observation = {
            "observed_state": {},
            "observation_id": "observe-failed",
            "source_refs": [],
        }
    t1 = _utc_now()
    steps.append({
        "step_id": step_id_observe,
        "label": "Observe repository state",
        "status": observe_status,
        "source_ref": "repo-observation.v1",
    })
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_observe),
        "runbook_ref": runbook_id,
        "step_id": step_id_observe,
        "operation": "steuerboard.observation.observe_repo",
        "capability_class": "read_only",
        "started_at": t0,
        "finished_at": t1,
        "status": observe_status,
        "redaction_verified": True,
    })

    # --- Step 2: assess_repo (derivation_only) ---
    step_id_assess = "step-derive-assessment"
    t0 = _utc_now()
    assessment: dict[str, Any] = {}
    assess_status = "passed"
    try:
        assessment = assess_repo(Path(repo_path_str))
    except Exception:  # noqa: BLE001
        assess_status = "inconclusive"
        assessment = {
            "decision_state": "evidence_missing",
            "derived_status": [],
            "missing_evidence": ["observation_failed"],
            "skip_reasons": [],
        }
    t1 = _utc_now()
    steps.append({
        "step_id": step_id_assess,
        "label": "Derive repo assessment",
        "status": assess_status,
        "source_ref": "repo-assessment.v1",
    })
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_assess),
        "runbook_ref": runbook_id,
        "step_id": step_id_assess,
        "operation": "steuerboard.assessment.assess_repo",
        "capability_class": "derivation_only",
        "started_at": t0,
        "finished_at": t1,
        "status": assess_status,
        "redaction_verified": True,
    })

    # --- Step 3: check_is_git_repo (derivation_only) ---
    step_id_isgit = "step-check-is-git-repo"
    t0 = _utc_now()
    isgit_status, _ = check_is_git_repo(observation)
    t1 = _utc_now()
    steps.append({
        "step_id": step_id_isgit,
        "label": "Check: path is a git repository",
        "status": isgit_status,
    })
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_isgit),
        "runbook_ref": runbook_id,
        "step_id": step_id_isgit,
        "operation": "steuerboard.runbooks.check_is_git_repo",
        "capability_class": "derivation_only",
        "started_at": t0,
        "finished_at": t1,
        "status": isgit_status,
        "redaction_verified": True,
    })

    # --- Step 4: check_worktree_clean (derivation_only) ---
    step_id_clean = "step-check-worktree-clean"
    t0 = _utc_now()
    clean_status, _ = check_worktree_clean(observation)
    t1 = _utc_now()
    steps.append({
        "step_id": step_id_clean,
        "label": "Check: worktree is clean",
        "status": clean_status,
    })
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_clean),
        "runbook_ref": runbook_id,
        "step_id": step_id_clean,
        "operation": "steuerboard.runbooks.check_worktree_clean",
        "capability_class": "derivation_only",
        "started_at": t0,
        "finished_at": t1,
        "status": clean_status,
        "redaction_verified": True,
    })

    # --- Step 5: check_not_detached_head (derivation_only) ---
    step_id_head = "step-check-not-detached-head"
    t0 = _utc_now()
    head_status, _ = check_not_detached_head(observation)
    t1 = _utc_now()
    steps.append({
        "step_id": step_id_head,
        "label": "Check: HEAD is not detached",
        "status": head_status,
    })
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_head),
        "runbook_ref": runbook_id,
        "step_id": step_id_head,
        "operation": "steuerboard.runbooks.check_not_detached_head",
        "capability_class": "derivation_only",
        "started_at": t0,
        "finished_at": t1,
        "status": head_status,
        "redaction_verified": True,
    })

    # --- Step 6: check_on_default_branch (derivation_only) ---
    step_id_branch = "step-check-on-default-branch"
    t0 = _utc_now()
    branch_status, _ = check_on_default_branch(observation)
    t1 = _utc_now()
    steps.append({
        "step_id": step_id_branch,
        "label": "Check: current branch is default branch candidate",
        "status": branch_status,
    })
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_branch),
        "runbook_ref": runbook_id,
        "step_id": step_id_branch,
        "operation": "steuerboard.runbooks.check_on_default_branch",
        "capability_class": "derivation_only",
        "started_at": t0,
        "finished_at": t1,
        "status": branch_status,
        "redaction_verified": True,
    })

    # --- Step 7: check_decision_state (derivation_only) ---
    step_id_decision = "step-check-decision-state"
    t0 = _utc_now()
    decision_status, _ = check_decision_state(assessment)
    t1 = _utc_now()
    steps.append({
        "step_id": step_id_decision,
        "label": "Check: assessment decision_state is not action_blocked",
        "status": decision_status,
    })
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_decision),
        "runbook_ref": runbook_id,
        "step_id": step_id_decision,
        "operation": "steuerboard.runbooks.check_decision_state",
        "capability_class": "derivation_only",
        "started_at": t0,
        "finished_at": t1,
        "status": decision_status,
        "redaction_verified": True,
    })

    finished_at = _utc_now()

    # --- Derive overall status ---
    overall_status = _derive_overall_status(steps)

    # --- Build short assessment ---
    short_assessment = _build_short_assessment(overall_status, steps, runbook_kind, assessment)

    # --- Merge source_refs from plan, observation, and assessment ---
    all_source_refs = _merge_source_refs(
        runbook_plan.get("source_refs", []),
        observation.get("source_refs", []),
        assessment.get("source_refs", []),
    )

    # --- Build runbook-result.v1 ---
    result: dict[str, Any] = {
        "schema_version": "runbook-result.v1",
        "result_id": _result_id(),
        "runbook_ref": runbook_id,
        "runbook_kind": runbook_kind,
        "status": overall_status,
        "started_at": started_at,
        "finished_at": finished_at,
        "repo_path": repo_path_str,
        "short_assessment": short_assessment,
        "steps": steps,
        "evidence_paths": [str(trace_path)],
        "source_refs": all_source_refs,
        "redaction_verified": True,
        "boundary": BOUNDARY,
    }

    # --- Atomic write: temp files -> os.replace ---
    trace_tmp_path: Path | None = None
    result_tmp_path: Path | None = None
    committed_targets: list[Path] = []
    try:
        # Write trace JSONL to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".jsonl.tmp",
            dir=trace_path.parent,
            delete=False,
        ) as trace_tmp:
            trace_tmp_path = Path(trace_tmp.name)
            for entry in step_traces:
                _validate_step_trace(entry)
                trace_tmp.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

        # Validate result before writing
        _validate_result(result)

        # Write result JSON to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json.tmp",
            dir=result_path.parent,
            delete=False,
        ) as result_tmp:
            result_tmp_path = Path(result_tmp.name)
            result_tmp.write(
                json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            )

        # Commit atomically; track each committed target so we can roll back on
        # partial failure (e.g. second os.replace fails after first succeeds).
        os.replace(trace_tmp_path, trace_path)
        trace_tmp_path = None
        committed_targets.append(trace_path)
        os.replace(result_tmp_path, result_path)
        result_tmp_path = None
        committed_targets.append(result_path)

    except Exception:
        # Clean up temp files that were never promoted.
        for tmp in (trace_tmp_path, result_tmp_path):
            if tmp is not None and tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        # Clean up any already-committed target files so no partial output
        # remains on disk when the overall operation fails.
        for target in committed_targets:
            try:
                os.unlink(target)
            except OSError:
                pass
        raise

    return result
