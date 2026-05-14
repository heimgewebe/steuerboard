from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any

from .inventory import explain_scope
from .observation import observe_repo


def _assessment_id(path: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%fZ")
    entropy = time_ns()
    digest = hashlib.sha256(f"{path}:{now}:{entropy}".encode("utf-8")).hexdigest()[:12]
    return f"assess-{now}-{digest}"


def assess_repo(path: Path, config_path: Path | None = None) -> dict[str, Any]:
    """Derive a read-only assessment from observation and scope for one local repo.

    No Git mutation, no network operation, no branch switch, no fetch.
    Assessment status is deterministic from Observation + Scope; runtime IDs remain time-dependent.
    """
    scope_path = path.expanduser()
    observation_path = scope_path.resolve()

    # --- Observe (read-only git probes only) ---
    observation = observe_repo(observation_path)
    obs_state = observation["observed_state"]

    # --- Scope classification (may be unavailable if no config exists) ---
    try:
        scope_explanation = explain_scope(scope_path, config_path=config_path)
        scope: str = scope_explanation["scope"]
        scope_source_refs: list[str] = scope_explanation["source_refs"]
    except FileNotFoundError:
        if config_path is not None:
            raise
        scope = "scope_unknown"
        scope_source_refs = ["local_config.unavailable"]

    # --- Combine source refs (observation + scope, deduplicated) ---
    source_refs: list[str] = list(observation["source_refs"])
    for ref in scope_source_refs:
        if ref not in source_refs:
            source_refs.append(ref)

    # --- Derive assessment status ---
    derived_status: list[str] = []
    skip_reasons: list[str] = []
    missing_evidence: list[str] = []

    is_git_repo: bool = obs_state.get("is_git_repo", False)

    if not is_git_repo:
        derived_status.append("not_git_repo")
        skip_reasons.append("not_git_repo")
        risk_level = "medium"
        decision_state = "action_blocked"
        confidence = 1.0

    elif scope != "scope_canonical":
        # Non-canonical scope: backup, gdrive, excluded, unknown.
        # Also collect dirty_worktree if observed — scope already blocks, but
        # derived_status is a list and should be complete.
        derived_status.append(scope)
        skip_reasons.append(scope)
        if obs_state.get("dirty", False):
            derived_status.append("dirty_worktree")
            skip_reasons.append("dirty_worktree")
        risk_level = "medium"
        decision_state = "action_blocked"
        confidence = 1.0

    else:
        # Canonical git repo — inspect git state
        dirty: bool = obs_state.get("dirty", False)
        current_branch: str | None = obs_state.get("current_branch")
        default_branch_candidate: str | None = obs_state.get("default_branch_candidate")

        if dirty:
            derived_status.append("dirty_worktree")
            skip_reasons.append("dirty_worktree")
            risk_level = "medium"
            decision_state = "action_blocked"
            confidence = 1.0

        elif current_branch is None:
            # Detached HEAD (git branch --show-current returns empty → None)
            derived_status.append("detached_head")
            skip_reasons.append("detached_head")
            risk_level = "medium"
            decision_state = "action_blocked"
            confidence = 1.0

        elif default_branch_candidate is None:
            # Default branch not determinable from observation
            derived_status.append("default_branch_unknown")
            skip_reasons.append("default_branch_unknown")
            missing_evidence.append("default_branch")
            risk_level = "medium"
            decision_state = "evidence_missing"
            confidence = 0.5

        elif current_branch != default_branch_candidate:
            # On a non-default branch, clean
            derived_status.append("non_default_branch")
            skip_reasons.append("non_default_branch")
            missing_evidence.append("branch_contains_origin_main_or_pr_merged")
            missing_evidence.append("fresh_origin_main")
            risk_level = "medium"
            decision_state = "evidence_missing"
            confidence = 0.9

        else:
            # Current branch matches observed default_branch_candidate.
            # The observation does not expose whether the candidate came from
            # refs/remotes/origin/HEAD (strong) or local heuristic fallback
            # (refs/heads/main|master|trunk). Mark as missing_evidence so
            # downstream consumers know the source quality is unverified.
            derived_status.append("clean_default_current")
            missing_evidence.append("default_branch_source")
            risk_level = "low"
            decision_state = "assessment_clear"
            confidence = 0.8

    return {
        "schema_version": "repo-assessment.v1",
        "assessment_id": _assessment_id(scope_path),
        "observation_ref": observation["observation_id"],
        "derived_status": derived_status,
        "source_refs": source_refs,
        "decision_state": decision_state,
        "risk_level": risk_level,
        "skip_reasons": skip_reasons,
        "missing_evidence": missing_evidence,
        "confidence": confidence,
    }
