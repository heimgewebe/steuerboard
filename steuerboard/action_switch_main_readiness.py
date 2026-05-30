"""Phase 9A: Switch-main Execution Readiness artifact validator.

This module validates that a ``switch-main-preflight-proof.v1`` is complete,
internally consistent, and content-bound to a specific ``switch-main``
``action-plan.v1``.  It emits a ``switch-main-readiness.v1`` verdict.

Phase 9A is the deliberate *proof belt* that must exist before any future
switch-main execution.  It is the switch-main analogue of the Phase 8D.0
``action-execution-readiness.v1`` pull gate.

Boundary contract:
- pure artifact validation; no subprocesses, no Git, no network, no mutation
- this module imports no subprocess surface and runs no git switch / checkout /
  merge / rebase / reset / clean
- reads only the two explicitly passed artifact dicts
- validates both inputs against their JSON Schemas before processing
- emits switch-main-readiness.v1 as a readiness assessment artifact only
- does NOT execute switch-main, does NOT switch branches, does NOT authorise
  actions, and does NOT create a runner

Status semantics:
- ready        : all hard gates pass AND all proof material is present and
                 consistent (plan binding proven, worktree clean, default
                 branch known == main, current branch known, branch lifecycle
                 proven or on main, remote/main fresh, ownership coherent)
- blocked      : at least one hard contradiction (plan binding mismatch,
                 unsupported plan action, dirty worktree, default branch not
                 main, branch not in origin/main or merged via PR (when on
                 non-default branch), stale remote main, ownership/path
                 split-brain)
- inconclusive : no hard contradiction but at least one piece of proof material
                 is unknown (e.g. repo_toplevel/current_branch/default_branch
                 absent, branch lifecycle unknown on non-default branch,
                 worktree state / remote freshness / ownership unknown)

A ``ready`` verdict is proof that a later switch *could* be evaluated; it is
never permission to switch.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from jsonschema import ValidationError as SchemaValidationError
    from jsonschema import validate as jsonschema_validate
except ModuleNotFoundError:  # pragma: no cover
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate

from .canonical_json import canonical_json_sha256

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}

# Phase 9A supports readiness assessment for exactly one planned action.
# Extending this set is a separate, explicitly reviewed phase slice.
_SUPPORTED_ACTIONS = frozenset({"switch-main"})

# The contractually expected default branch for a switch-main target.
# masterplan Phase 9 switch-main gate requires "Default Branch bekannt" and the
# action itself switches to *main*.
_EXPECTED_DEFAULT_BRANCH = "main"

# Hard-failure reasons; every entry is also a switch-main-readiness.v1
# blocked_because enum member, so a non-empty hard-failure list always yields a
# non-empty, schema-valid blocked_because array.
_BLOCKED_ENUM = frozenset(
    {
        "unsupported_action",
        "plan_ref_mismatch",
        "plan_action_mismatch",
        "plan_content_sha256_mismatch",
        "worktree_not_clean",
        "default_branch_not_main",
        "remote_main_stale",
        "ownership_conflict",
        "branch_lifecycle_unproven",
    }
)


def _utc_rfc3339_now() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _record_check(
    checks: list[dict[str, Any]],
    *,
    check: str,
    passed: bool,
    expected: str | None = None,
    actual: str | None = None,
) -> None:
    entry: dict[str, Any] = {"check": check, "passed": passed}
    if expected is not None:
        entry["expected"] = expected
    if actual is not None:
        entry["actual"] = actual
    checks.append(entry)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _write_readiness_atomic(target: Path, data: dict[str, Any]) -> None:
    tmp_path: Path | None = None
    try:
        fd, tmp = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
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


def _require_output_path(path_str: str, param_name: str) -> Path:
    target = Path(path_str).expanduser().resolve(strict=False)
    if target.exists():
        raise ValueError(f"{param_name}: output file already exists: {target}")
    if not target.parent.exists():
        raise ValueError(f"{param_name}: parent directory does not exist: {target.parent}")
    return target


def _known_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_switch_main_readiness(
    *,
    action_plan: dict[str, Any],
    preflight_proof: dict[str, Any],
    readiness_out: str,
) -> dict[str, Any]:
    """Validate switch-main readiness and write switch-main-readiness.v1.

    Parameters
    ----------
    action_plan:
        A dict representing an action-plan.v1 artifact whose ``action`` must be
        ``switch-main`` for any non-blocked readiness result.
    preflight_proof:
        A dict representing a switch-main-preflight-proof.v1 artifact carrying
        the plan binding and the observed repository-state claims.
    readiness_out:
        Output path for the switch-main-readiness.v1 JSON artifact. Must not
        already exist; parent directory must exist.

    Returns
    -------
    dict
        The switch-main-readiness.v1 artifact.

    Raises
    ------
    ValueError
        If either input artifact is schema-invalid, or if preconditions on the
        output path are not met.
    """
    _validate_against_schema(action_plan, "action-plan.v1.schema.json", "action-plan.v1")
    _validate_against_schema(
        preflight_proof,
        "switch-main-preflight-proof.v1.schema.json",
        "switch-main-preflight-proof.v1",
    )

    readiness_target = _require_output_path(readiness_out, "readiness_out")

    checks: list[dict[str, Any]] = []
    hard_failure_reasons: list[str] = []
    inconclusive_reasons: list[str] = []

    plan_action = action_plan.get("action", "")
    plan_id = action_plan.get("plan_id", "")

    # -- Gate 1: plan.action must be the supported switch-main action. --------
    action_supported = plan_action in _SUPPORTED_ACTIONS
    _record_check(
        checks,
        check="plan_action_supported",
        passed=action_supported,
        expected="switch-main",
        actual=str(plan_action),
    )
    if not action_supported:
        hard_failure_reasons.append("unsupported_action")

    # -- Gate 2: proof.plan_ref must match plan.plan_id. ----------------------
    proof_plan_ref = preflight_proof.get("plan_ref", "")
    plan_ref_match = proof_plan_ref == plan_id
    _record_check(
        checks,
        check="proof_plan_ref_matches_plan",
        passed=plan_ref_match,
        expected=str(plan_id),
        actual=str(proof_plan_ref),
    )
    if not plan_ref_match:
        hard_failure_reasons.append("plan_ref_mismatch")

    # -- Gate 3: proof.plan_action must match plan.action. --------------------
    proof_plan_action = preflight_proof.get("plan_action", "")
    plan_action_match = proof_plan_action == plan_action
    _record_check(
        checks,
        check="proof_plan_action_matches_plan",
        passed=plan_action_match,
        expected=str(plan_action),
        actual=str(proof_plan_action),
    )
    if not plan_action_match:
        hard_failure_reasons.append("plan_action_mismatch")

    # -- Gate 4: proof.plan_content_sha256 must equal canonical hash of plan. -
    expected_sha = canonical_json_sha256(action_plan)
    proof_sha = preflight_proof.get("plan_content_sha256", "")
    sha_match = proof_sha == expected_sha
    _record_check(
        checks,
        check="proof_plan_content_sha256_matches_plan",
        passed=sha_match,
        expected=expected_sha,
        actual=str(proof_sha),
    )
    if not sha_match:
        hard_failure_reasons.append("plan_content_sha256_mismatch")

    # -- Gate 5: repo_toplevel must be known (anchors the future switch). -----
    repo_toplevel = preflight_proof.get("repo_toplevel")
    repo_toplevel_known = _known_string(repo_toplevel)
    _record_check(
        checks,
        check="repo_toplevel_known",
        passed=repo_toplevel_known,
        expected="non-empty repo_toplevel",
        actual="present" if repo_toplevel_known else "absent",
    )
    if not repo_toplevel_known:
        inconclusive_reasons.append("repo_toplevel_unknown")

    # -- Gate 6: current branch must be known. --------------------------------
    current_branch = preflight_proof.get("current_branch")
    current_branch_known = _known_string(current_branch)
    _record_check(
        checks,
        check="current_branch_known",
        passed=current_branch_known,
        expected="non-empty current_branch",
        actual="present" if current_branch_known else "absent",
    )
    if not current_branch_known:
        inconclusive_reasons.append("current_branch_unknown")

    # -- Gate 7: default branch must be known and equal to main. --------------
    default_branch = preflight_proof.get("default_branch")
    if not _known_string(default_branch):
        _record_check(
            checks,
            check="default_branch_known",
            passed=False,
            expected=f"non-empty default_branch ({_EXPECTED_DEFAULT_BRANCH})",
            actual="absent",
        )
        inconclusive_reasons.append("default_branch_unknown")
    else:
        default_branch_is_main = default_branch == _EXPECTED_DEFAULT_BRANCH
        _record_check(
            checks,
            check="default_branch_is_main",
            passed=default_branch_is_main,
            expected=_EXPECTED_DEFAULT_BRANCH,
            actual=str(default_branch),
        )
        if not default_branch_is_main:
            hard_failure_reasons.append("default_branch_not_main")

    # -- Gate 8: branch lifecycle proof for non-default branches. ------
    # Only required when current_branch != "main"; absent on main branch.
    branch_lifecycle_proof = preflight_proof.get("branch_contains_origin_main_or_pr_merged")
    if current_branch_known:
        if current_branch == _EXPECTED_DEFAULT_BRANCH:
            # On main branch, no lifecycle proof needed
            _record_check(
                checks,
                check="branch_lifecycle_not_required",
                passed=True,
                expected="current_branch == main",
                actual=str(current_branch),
            )
        else:
            # On non-default branch, lifecycle proof is required
            if branch_lifecycle_proof is None:
                _record_check(
                    checks,
                    check="branch_lifecycle_proof",
                    passed=False,
                    expected="true or false (proof of branch lifecycle status)",
                    actual="unknown",
                )
                inconclusive_reasons.append("branch_lifecycle_unknown")
            else:
                # Strict True check ensures only boolean true is accepted as proven
                lifecycle_proven = branch_lifecycle_proof is True
                _record_check(
                    checks,
                    check="branch_lifecycle_proof",
                    passed=lifecycle_proven,
                    expected="true (branch in origin/main or merged via PR)",
                    actual=json.dumps(branch_lifecycle_proof),
                )
                if not lifecycle_proven:
                    hard_failure_reasons.append("branch_lifecycle_unproven")

    # -- Gate 9: worktree must be proven clean. -------------------------------
    worktree_clean = preflight_proof.get("worktree_clean")
    if worktree_clean is None:
        _record_check(
            checks,
            check="worktree_clean",
            passed=False,
            expected="true",
            actual="unknown",
        )
        inconclusive_reasons.append("worktree_state_unknown")
    else:
        worktree_is_clean = worktree_clean is True
        _record_check(
            checks,
            check="worktree_clean",
            passed=worktree_is_clean,
            expected="true",
            actual=json.dumps(worktree_clean),
        )
        if not worktree_is_clean:
            hard_failure_reasons.append("worktree_not_clean")

    # -- Gate 10: origin/main must be proven fresh. ----------------------------
    remote_main_fresh = preflight_proof.get("remote_main_fresh")
    if remote_main_fresh is None:
        _record_check(
            checks,
            check="remote_main_fresh",
            passed=False,
            expected="true",
            actual="unknown",
        )
        inconclusive_reasons.append("remote_freshness_unknown")
    else:
        remote_is_fresh = remote_main_fresh is True
        _record_check(
            checks,
            check="remote_main_fresh",
            passed=remote_is_fresh,
            expected="true",
            actual=json.dumps(remote_main_fresh),
        )
        if not remote_is_fresh:
            hard_failure_reasons.append("remote_main_stale")

    # -- Gate 11: ownership / path must be coherent (no split-brain). ---------
    ownership_ok = preflight_proof.get("ownership_ok")
    if ownership_ok is None:
        _record_check(
            checks,
            check="ownership_ok",
            passed=False,
            expected="true",
            actual="unknown",
        )
        inconclusive_reasons.append("ownership_unknown")
    else:
        ownership_is_ok = ownership_ok is True
        _record_check(
            checks,
            check="ownership_ok",
            passed=ownership_is_ok,
            expected="true",
            actual=json.dumps(ownership_ok),
        )
        if not ownership_is_ok:
            hard_failure_reasons.append("ownership_conflict")

    # -- Determine final status. ----------------------------------------------
    if hard_failure_reasons:
        status = "blocked"
        failure_reasons = _dedupe_preserve_order(hard_failure_reasons + inconclusive_reasons)
    elif inconclusive_reasons:
        status = "inconclusive"
        failure_reasons = _dedupe_preserve_order(inconclusive_reasons)
    else:
        status = "ready"
        failure_reasons = []

    blocked_because = _dedupe_preserve_order(
        [reason for reason in hard_failure_reasons if reason in _BLOCKED_ENUM]
    )

    source_refs = _dedupe_preserve_order(
        [
            *[ref for ref in preflight_proof.get("source_refs", []) if isinstance(ref, str)],
            "action-plan.v1",
            "switch-main-preflight-proof.v1",
        ]
    )

    proof_ref = str(preflight_proof.get("proof_id") or "unknown")

    readiness_material = {
        "action": str(plan_action) if plan_action else "unknown",
        "plan_ref": plan_id or "unknown",
        "plan_content_sha256": canonical_json_sha256(action_plan),
        "proof_ref": proof_ref,
        "proof_content_sha256": canonical_json_sha256(preflight_proof),
        "repo_toplevel": str(repo_toplevel) if repo_toplevel_known else None,
        "status": status,
        "blocked_because": blocked_because,
        "failure_reasons": failure_reasons,
        "checks": checks,
        "source_refs": source_refs,
    }
    readiness_id = f"switch-main-readiness-{canonical_json_sha256(readiness_material)}"

    artifact: dict[str, Any] = {
        "schema_version": "switch-main-readiness.v1",
        "readiness_id": readiness_id,
        "checked_at": _utc_rfc3339_now(),
        "action": str(plan_action) if plan_action else "unknown",
        "plan_ref": plan_id or "unknown",
        "proof_ref": proof_ref,
        "status": status,
        "blocked_because": blocked_because,
        "checks": checks,
        "source_refs": source_refs,
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }
    if repo_toplevel_known:
        artifact["repo_toplevel"] = str(repo_toplevel)
    if failure_reasons:
        artifact["failure_reasons"] = failure_reasons

    _validate_against_schema(
        artifact,
        "switch-main-readiness.v1.schema.json",
        "switch-main-readiness.v1",
    )
    _write_readiness_atomic(readiness_target, artifact)
    return artifact
