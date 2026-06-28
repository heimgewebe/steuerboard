from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .inventory import build_inventory_from_config
from .local_config import load_local_config
from .observation import observe_repo


_CLASSIFICATIONS = (
    "on_default_branch",
    "non_default_branch",
    "detached_head",
    "default_branch_unknown",
    "observation_failed",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _rfc3339(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _validate_warning_threshold(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("warning_threshold must be an integer")
    if not 1 <= value <= 1000:
        raise ValueError("warning_threshold must be between 1 and 1000")


def _classify_observation(observation: dict[str, Any]) -> str:
    observed_state = observation.get("observed_state")
    if not isinstance(observed_state, dict) or observed_state.get("is_git_repo") is not True:
        return "observation_failed"

    current_branch = observed_state.get("current_branch")
    default_branch = observed_state.get("default_branch_candidate")
    if current_branch is None:
        return "detached_head"
    if default_branch is None:
        return "default_branch_unknown"
    if current_branch == default_branch:
        return "on_default_branch"
    return "non_default_branch"


def _failed_repo_entry(repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": repo["path"],
        "git_toplevel": repo["git_toplevel"],
        "repo_id": None,
        "current_branch": None,
        "default_branch_candidate": None,
        "default_branch_candidate_source": None,
        "dirty": None,
        "ahead": None,
        "behind": None,
        "classification": "observation_failed",
    }


def build_branch_drift_report(
    *,
    config_path: Path | None,
    warning_threshold: int,
) -> dict[str, Any]:
    """Build a bounded, read-only summary of local default-branch drift.

    The report reuses the existing inventory and repository-observation models.
    It does not fetch remote state, mutate repositories, recommend a repair, or
    authorise an action. ``warning_threshold`` is explicit user policy, not an
    inferred severity rule.
    """
    _validate_warning_threshold(warning_threshold)

    config = load_local_config(config_path)
    inventory = build_inventory_from_config(config)
    eligible_repos = [
        repo
        for repo in inventory["repos"]
        if repo["scope"] == "scope_canonical"
        and repo["is_git_repo"] is True
        and isinstance(repo.get("git_toplevel"), str)
        and repo["git_toplevel"]
    ]
    eligible_repos.sort(key=lambda item: item["path"])

    repo_entries: list[dict[str, Any]] = []
    counts = {f"{classification}_count": 0 for classification in _CLASSIFICATIONS}

    for repo in eligible_repos:
        try:
            observation = observe_repo(Path(repo["git_toplevel"]))
        except OSError:
            entry = _failed_repo_entry(repo)
        else:
            classification = _classify_observation(observation)
            if classification == "observation_failed":
                entry = _failed_repo_entry(repo)
            else:
                observed_state = observation["observed_state"]
                entry = {
                    "path": repo["path"],
                    "git_toplevel": repo["git_toplevel"],
                    "repo_id": observation.get("repo_id"),
                    "current_branch": observed_state.get("current_branch"),
                    "default_branch_candidate": observed_state.get(
                        "default_branch_candidate"
                    ),
                    "default_branch_candidate_source": observed_state.get(
                        "default_branch_candidate_source"
                    ),
                    "dirty": observed_state.get("dirty"),
                    "ahead": observed_state.get("ahead"),
                    "behind": observed_state.get("behind"),
                    "classification": classification,
                }

        counts[f"{entry['classification']}_count"] += 1
        repo_entries.append(entry)

    counts["evaluated_repository_count"] = len(repo_entries)
    non_default_count = counts["non_default_branch_count"]
    now = _utc_now()

    return {
        "schema_version": "repo-branch-drift.v1",
        "report_id": f"branch-drift-{now.strftime('%Y%m%d-%H%M%SZ')}",
        "observed_at": _rfc3339(now),
        "host": config.host_name,
        "warning_threshold": warning_threshold,
        "warning_triggered": non_default_count >= warning_threshold,
        "counts": counts,
        "repos": repo_entries,
        "source_refs": [
            "local_config.paths.canonical_repo_roots",
            "repo-inventory.v1",
            "repo-observation.v1",
            "git.default_branch_candidate",
        ],
        "does_not_prove": [
            "remote_freshness",
            "branch_safety",
            "remediation_required",
        ],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
            "does_not_recommend_actions": True,
        },
    }
