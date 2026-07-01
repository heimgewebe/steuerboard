from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .inventory import build_inventory_from_config
from .local_config import LocalConfig, build_operational_profile_from_config, load_local_config
from .observation import observe_repo
from .omnipull_reports import load_omnipull_report
from .recent_problem_repos import build_recent_problem_repos

_CLASSIFICATIONS = (
    "on_default_branch",
    "non_default_branch",
    "detached_head",
    "default_branch_unknown",
    "observation_failed",
)
_MAX_RECENT_PROBLEM_LIMIT = 100
_BOUNDARY = {
    "does_not_execute": True,
    "does_not_mutate": True,
    "does_not_authorise_actions": True,
    "does_not_recommend_actions": True,
}
_DOES_NOT_PROVE = [
    "remote_freshness",
    "branch_safety",
    "action_readiness",
    "runtime_correctness",
    "repository_repair_required",
    "omnipull_report_completeness",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _rfc3339(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _operator_report_id(value: datetime) -> str:
    return f"operator-report-{value.strftime('%Y%m%d-%H%M%SZ')}"


def _validate_warning_threshold(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("branch_warning_threshold must be an integer")
    if not 1 <= value <= 1000:
        raise ValueError("branch_warning_threshold must be between 1 and 1000")


def _validate_recent_problem_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("recent_problem_limit must be an integer")
    if not 1 <= value <= _MAX_RECENT_PROBLEM_LIMIT:
        raise ValueError(f"recent_problem_limit must be between 1 and {_MAX_RECENT_PROBLEM_LIMIT}")


def _normalize_report_paths(paths: Sequence[str | Path]) -> list[str]:
    if isinstance(paths, (str, bytes)):
        raise ValueError("omnipull_report_paths must be a sequence of paths")

    normalized: list[str] = []
    seen: set[str] = set()
    for index, raw_path in enumerate(paths):
        text = str(raw_path)
        if not text or text != text.strip():
            raise ValueError(f"omnipull_report_paths[{index}] must be a non-blank path")
        if text in seen:
            raise ValueError(f"duplicate omnipull report path: {text}")
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_favorite_paths(config: LocalConfig) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in config.favorite_repo_paths:
        path_text = str(Path(raw_path).expanduser().absolute())
        if path_text in seen:
            raise ValueError("favorite_repo_paths contains duplicate normalized paths")
        seen.add(path_text)
        normalized.append(path_text)
    return normalized


def _build_favorites_section(config: LocalConfig, inventory: dict[str, Any]) -> dict[str, Any]:
    favorite_paths = _normalize_favorite_paths(config)
    if not favorite_paths:
        observed_at = _rfc3339(_utc_now())
        return {
            "schema_version": "repo-favorites.v1",
            "favorites_id": f"fav-{_utc_now().strftime('%Y%m%d-%H%M%SZ')}",
            "source_refs": ["local_config.preferences.favorite_repo_paths"],
            "observed_at": observed_at,
            "host": config.host_name,
            "favorites": [],
            "missing_favorite_paths": [],
        }

    repos_by_path = {repo["path"]: repo for repo in inventory["repos"]}
    favorites: list[dict[str, Any]] = []
    missing_favorite_paths: list[str] = []

    for path_text in favorite_paths:
        repo = repos_by_path.get(path_text)
        if repo is None:
            missing_favorite_paths.append(path_text)
            favorites.append(
                {
                    "path": path_text,
                    "inventory_status": "not_in_inventory",
                    "is_git_repo": None,
                    "scope": None,
                    "scope_reason": None,
                    "git_toplevel": None,
                }
            )
            continue

        favorites.append(
            {
                "path": path_text,
                "inventory_status": "present",
                "is_git_repo": repo["is_git_repo"],
                "scope": repo["scope"],
                "scope_reason": repo["scope_reason"],
                "git_toplevel": repo["git_toplevel"],
            }
        )

    return {
        "schema_version": "repo-favorites.v1",
        "favorites_id": f"fav-{_utc_now().strftime('%Y%m%d-%H%M%SZ')}",
        "source_refs": [
            "local_config.preferences.favorite_repo_paths",
            *inventory["source_refs"],
        ],
        "observed_at": inventory["observed_at"],
        "host": inventory["host"],
        "favorites": favorites,
        "missing_favorite_paths": missing_favorite_paths,
    }


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


def _build_branch_drift_section(
    config: LocalConfig,
    inventory: dict[str, Any],
    *,
    warning_threshold: int,
) -> dict[str, Any]:
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
                    "default_branch_candidate": observed_state.get("default_branch_candidate"),
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
    now = _utc_now()
    return {
        "schema_version": "repo-branch-drift.v1",
        "report_id": f"branch-drift-{now.strftime('%Y%m%d-%H%M%SZ')}",
        "observed_at": _rfc3339(now),
        "host": config.host_name,
        "warning_threshold": warning_threshold,
        "warning_triggered": counts["non_default_branch_count"] >= warning_threshold,
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
        "boundary": dict(_BOUNDARY),
    }


def _load_recent_problem_section(
    report_paths: list[str],
    *,
    recent_problem_limit: int,
) -> dict[str, Any] | None:
    if not report_paths:
        return None
    reports = [load_omnipull_report(Path(path), source_path_ref=path) for path in report_paths]
    return build_recent_problem_repos(reports, limit=recent_problem_limit)


def _summary(
    *,
    profile: dict[str, Any],
    favorites: dict[str, Any],
    branch_drift: dict[str, Any],
    recent_problem_repos: dict[str, Any] | None,
) -> dict[str, Any]:
    branch_counts = branch_drift["counts"]
    return {
        "effective_operations": profile["effective_operations"],
        "blocked_effective_operation_count": sum(
            1 for allowed in profile["effective_operations"].values() if not allowed
        ),
        "favorite_count": len(favorites["favorites"]),
        "missing_favorite_count": len(favorites["missing_favorite_paths"]),
        "branch_drift_warning_triggered": branch_drift["warning_triggered"],
        "evaluated_branch_repo_count": branch_counts["evaluated_repository_count"],
        "non_default_branch_count": branch_counts["non_default_branch_count"],
        "detached_head_count": branch_counts["detached_head_count"],
        "default_branch_unknown_count": branch_counts["default_branch_unknown_count"],
        "observation_failed_count": branch_counts["observation_failed_count"],
        "input_omnipull_report_count": 0
        if recent_problem_repos is None
        else recent_problem_repos["input_report_count"],
        "distinct_problem_repo_count": 0
        if recent_problem_repos is None
        else recent_problem_repos["distinct_problem_repo_count"],
        "returned_problem_repo_count": 0
        if recent_problem_repos is None
        else recent_problem_repos["returned_problem_repo_count"],
    }


def build_operator_report(
    *,
    config_path: Path | None = None,
    branch_warning_threshold: int,
    omnipull_report_paths: Sequence[str | Path] = (),
    recent_problem_limit: int = 20,
) -> dict[str, Any]:
    """Build a bounded read-only operator report for the current local profile.

    The report aggregates already bounded read-only surfaces: operational policy,
    favorite repository inventory status, local branch drift, and optionally
    explicitly supplied Omnipull problem reports. It does not discover Omnipull
    files, fetch remotes, mutate repositories, recommend repairs, or authorise
    actions.
    """
    _validate_warning_threshold(branch_warning_threshold)
    _validate_recent_problem_limit(recent_problem_limit)
    normalized_report_paths = _normalize_report_paths(omnipull_report_paths)

    config = load_local_config(config_path)
    inventory = build_inventory_from_config(config)
    profile = build_operational_profile_from_config(config)
    favorites = _build_favorites_section(config, inventory)
    branch_drift = _build_branch_drift_section(
        config,
        inventory,
        warning_threshold=branch_warning_threshold,
    )
    recent_problem_repos = _load_recent_problem_section(
        normalized_report_paths,
        recent_problem_limit=recent_problem_limit,
    )

    now = _utc_now()
    generated_at = _rfc3339(now)
    return {
        "schema_version": "operator-report.v1",
        "report_id": _operator_report_id(now),
        "generated_at": generated_at,
        "host": config.host_name,
        "config_path": str(config.source_path),
        "inputs": {
            "branch_warning_threshold": branch_warning_threshold,
            "omnipull_report_paths": normalized_report_paths,
            "recent_problem_limit": recent_problem_limit,
        },
        "summary": _summary(
            profile=profile,
            favorites=favorites,
            branch_drift=branch_drift,
            recent_problem_repos=recent_problem_repos,
        ),
        "operational_profile": profile,
        "favorites": favorites,
        "branch_drift": branch_drift,
        "recent_problem_repos": recent_problem_repos,
        "source_refs": [
            "local-config.v1.policy",
            "local_config.preferences.favorite_repo_paths",
            "local_config.paths.canonical_repo_roots",
            "repo-inventory.v1",
            "repo-observation.v1",
            "omnipull-report.v1.explicit_inputs",
        ],
        "does_not_prove": list(_DOES_NOT_PROVE),
        "boundary": dict(_BOUNDARY),
    }
