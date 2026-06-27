from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from .omnipull_reports import OMNIPULL_REPORT_STATUSES

_SELECTION_RULE = "latest_problem_per_repo.generated_at_desc"
_BOUNDARY = {
    "does_not_execute": True,
    "does_not_mutate": True,
    "does_not_authorise_actions": True,
}
_MAX_LIMIT = 100


def _parse_generated_at(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a date-time string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid date-time") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _require_non_blank_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")
    return value


def _require_string_list(
    value: Any,
    field_name: str,
    *,
    non_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    result = [_require_non_blank_string(item, field_name) for item in value]
    if non_empty and not result:
        raise ValueError(f"{field_name} must be a non-empty list of strings")
    return result


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit < 1 or limit > _MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}")
    return limit


def _candidate_key(candidate: dict[str, Any]) -> tuple[datetime, str, str, str]:
    return (
        candidate["_generated_at"],
        candidate["run_id"],
        candidate["report_id"],
        candidate["report_source_path"],
    )


def build_recent_problem_repos(
    reports: Sequence[dict[str, Any]],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Select the latest explicit Omnipull problem occurrence per repository.

    ``reports`` must contain normalized ``omnipull-report.v1`` objects, such as
    values returned by :func:`steuerboard.omnipull_reports.load_omnipull_report`.
    The function performs no discovery and reads no files. Repository identity is
    the report's ``repo_id``; the path and status come from the selected latest
    occurrence. Equal timestamps use run id, report id, and source path as
    descending lexical tie-breakers.
    """
    validated_limit = _validate_limit(limit)
    if not isinstance(reports, Sequence) or isinstance(reports, (str, bytes)):
        raise ValueError("reports must be a sequence of omnipull-report objects")
    if not reports:
        raise ValueError("at least one omnipull report is required")

    seen_source_paths: set[str] = set()
    seen_report_ids: set[tuple[str, str]] = set()
    report_refs: list[dict[str, Any]] = []
    occurrences_by_repo: dict[str, list[dict[str, Any]]] = {}

    for report_index, report in enumerate(reports):
        prefix = f"reports[{report_index}]"
        if not isinstance(report, dict):
            raise ValueError(f"{prefix} must be an object")
        if report.get("schema_version") != "omnipull-report.v1":
            raise ValueError(f"{prefix}.schema_version must be omnipull-report.v1")
        if report.get("boundary") != _BOUNDARY:
            raise ValueError(f"{prefix}.boundary must match the read-only boundary")

        report_id = _require_non_blank_string(report.get("report_id"), f"{prefix}.report_id")
        run_id = _require_non_blank_string(report.get("run_id"), f"{prefix}.run_id")
        generated_at = _require_non_blank_string(
            report.get("generated_at"), f"{prefix}.generated_at"
        )
        generated_at_value = _parse_generated_at(generated_at, f"{prefix}.generated_at")
        source_path = _require_non_blank_string(report.get("source_path"), f"{prefix}.source_path")

        if source_path in seen_source_paths:
            raise ValueError(f"duplicate omnipull report source_path: {source_path}")
        seen_source_paths.add(source_path)

        report_identity = (report_id, run_id)
        if report_identity in seen_report_ids:
            raise ValueError(
                f"duplicate omnipull report identity: report_id={report_id}, run_id={run_id}"
            )
        seen_report_ids.add(report_identity)

        repos = report.get("repos")
        if not isinstance(repos, list):
            raise ValueError(f"{prefix}.repos must be a list")

        report_refs.append(
            {
                "report_id": report_id,
                "run_id": run_id,
                "generated_at": generated_at,
                "source_path": source_path,
                "_generated_at": generated_at_value,
            }
        )

        seen_repo_ids: set[str] = set()
        for repo_index, repo in enumerate(repos):
            repo_prefix = f"{prefix}.repos[{repo_index}]"
            if not isinstance(repo, dict):
                raise ValueError(f"{repo_prefix} must be an object")
            repo_id = _require_non_blank_string(repo.get("repo_id"), f"{repo_prefix}.repo_id")
            if repo_id in seen_repo_ids:
                raise ValueError(f"{prefix}.repos contains duplicate repo_id: {repo_id}")
            seen_repo_ids.add(repo_id)

            repo_path = _require_non_blank_string(repo.get("path"), f"{repo_prefix}.path")
            status = _require_non_blank_string(repo.get("status"), f"{repo_prefix}.status")
            if status not in OMNIPULL_REPORT_STATUSES:
                raise ValueError(
                    f"{repo_prefix}.status must be one of {sorted(OMNIPULL_REPORT_STATUSES)}"
                )
            skip_reasons = _require_string_list(
                repo.get("skip_reasons"),
                f"{repo_prefix}.skip_reasons",
                non_empty=True,
            )
            if status not in skip_reasons:
                raise ValueError(f"{repo_prefix}.skip_reasons must include status {status!r}")

            occurrence = {
                "repo_id": repo_id,
                "path": repo_path,
                "status": status,
                "skip_reasons": skip_reasons,
                "source_refs": _require_string_list(
                    repo.get("source_refs"),
                    f"{repo_prefix}.source_refs",
                    non_empty=True,
                ),
                "freshness_refs": _require_string_list(
                    repo.get("freshness_refs"),
                    f"{repo_prefix}.freshness_refs",
                    non_empty=True,
                ),
                "falsification_refs": _require_string_list(
                    repo.get("falsification_refs"),
                    f"{repo_prefix}.falsification_refs",
                ),
                "missing_evidence": _require_string_list(
                    repo.get("missing_evidence"),
                    f"{repo_prefix}.missing_evidence",
                ),
                "last_problem_at": generated_at,
                "report_id": report_id,
                "run_id": run_id,
                "report_source_path": source_path,
                "_generated_at": generated_at_value,
                "_repo_index": repo_index,
            }
            occurrences_by_repo.setdefault(repo_id, []).append(occurrence)

    problem_repos: list[dict[str, Any]] = []
    for repo_id, occurrences in occurrences_by_repo.items():
        latest = max(occurrences, key=_candidate_key)
        problem_repos.append(
            {key: value for key, value in latest.items() if key != "_generated_at"}
            | {"occurrence_count": len(occurrences)}
        )

    # Stable sort: newest report first; repositories from the same selected
    # report retain that report's original order instead of gaining an invented
    # severity ranking.
    problem_repos.sort(key=lambda item: item["repo_id"])
    problem_repos.sort(key=lambda item: item.pop("_repo_index"))
    problem_repos.sort(
        key=lambda item: (
            _parse_generated_at(item["last_problem_at"], "problem_repos[].last_problem_at"),
            item["run_id"],
            item["report_id"],
            item["report_source_path"],
        ),
        reverse=True,
    )

    report_refs.sort(
        key=lambda item: (
            item["_generated_at"],
            item["run_id"],
            item["report_id"],
            item["source_path"],
        ),
        reverse=True,
    )
    normalized_report_refs = [
        {key: value for key, value in report_ref.items() if key != "_generated_at"}
        for report_ref in report_refs
    ]

    distinct_count = len(problem_repos)
    selected = problem_repos[:validated_limit]
    return {
        "schema_version": "recent-problem-repos.v1",
        "selected_by": _SELECTION_RULE,
        "limit": validated_limit,
        "input_report_count": len(normalized_report_refs),
        "distinct_problem_repo_count": distinct_count,
        "returned_problem_repo_count": len(selected),
        "source_reports": normalized_report_refs,
        "problem_repos": selected,
        "boundary": dict(_BOUNDARY),
    }
