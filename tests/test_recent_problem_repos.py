from __future__ import annotations

import copy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from scripts.validate_examples import load_json, validate_instance
from steuerboard.omnipull_reports import OMNIPULL_REPORT_STATUSES, load_omnipull_report
from steuerboard.recent_problem_repos import build_recent_problem_repos

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "recent-problem-repos.v1.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "recent-problem-repos" / "multiple-reports.json"
REPORT_NAMES = (
    "non-default-branch.json",
    "dirty-worktree.json",
    "mixed-run.json",
)


def report_argument(name: str) -> str:
    return f"examples/omnipull-reports/{name}"


def load_report(name: str) -> dict:
    argument = report_argument(name)
    return load_omnipull_report(ROOT / argument, source_path_ref=argument)


def reports() -> list[dict]:
    return [load_report(name) for name in REPORT_NAMES]


def schema() -> dict:
    return load_json(SCHEMA_PATH)


def test_recent_problem_repos_matches_validated_example() -> None:
    result = build_recent_problem_repos(reports(), limit=3)

    assert result == load_json(EXAMPLE_PATH)
    validate_instance(result, schema(), Path("recent-problem-repos.json"))


def test_recent_problem_repos_selects_latest_occurrence_and_counts_history() -> None:
    result = build_recent_problem_repos(reports())

    assert result["input_report_count"] == 3
    assert result["distinct_problem_repo_count"] == 5
    assert result["returned_problem_repo_count"] == 5
    assert [item["repo_id"] for item in result["problem_repos"]] == [
        "heimgewebe/steuerboard",
        "heimgewebe/legacy-no-upstream",
        "heimgewebe/fleet-shadow-copy",
        "heimgewebe/remote-mainline",
        "heimgewebe/unknown-default",
    ]

    steuerboard = result["problem_repos"][0]
    assert steuerboard["occurrence_count"] == 3
    assert steuerboard["last_problem_at"] == "2026-05-16T09:32:00Z"
    assert steuerboard["status"] == "non_default_branch"
    assert steuerboard["report_id"] == "omnipull-report-example-mixed-run"


def test_recent_problem_repos_is_independent_of_input_report_order() -> None:
    report_list = reports()

    assert build_recent_problem_repos(report_list, limit=4) == build_recent_problem_repos(
        list(reversed(report_list)), limit=4
    )


def test_recent_problem_repos_preserves_latest_report_order_for_timestamp_ties() -> None:
    result = build_recent_problem_repos(reports(), limit=3)

    assert [item["repo_id"] for item in result["problem_repos"]] == [
        "heimgewebe/steuerboard",
        "heimgewebe/legacy-no-upstream",
        "heimgewebe/fleet-shadow-copy",
    ]


def test_recent_problem_repos_uses_lexical_report_tie_breakers() -> None:
    older_tie = load_report("dirty-worktree.json")
    newer_tie = copy.deepcopy(older_tie)

    older_tie.update(
        generated_at="2026-05-16T10:00:00Z",
        report_id="report-a",
        run_id="run-a",
        source_path="reports/a.json",
    )
    newer_tie.update(
        generated_at="2026-05-16T10:00:00Z",
        report_id="report-b",
        run_id="run-b",
        source_path="reports/b.json",
    )
    newer_tie["repos"][0]["status"] = "no_upstream"
    newer_tie["repos"][0]["skip_reasons"] = ["no_upstream"]

    selected = build_recent_problem_repos([newer_tie, older_tie])["problem_repos"][0]

    assert selected["run_id"] == "run-b"
    assert selected["report_id"] == "report-b"
    assert selected["status"] == "no_upstream"
    assert selected["occurrence_count"] == 2


def test_recent_problem_repos_limit_does_not_hide_total_count() -> None:
    result = build_recent_problem_repos(reports(), limit=2)

    assert result["limit"] == 2
    assert result["distinct_problem_repo_count"] == 5
    assert result["returned_problem_repo_count"] == 2
    assert len(result["problem_repos"]) == 2


def test_recent_problem_repos_accepts_explicit_empty_report() -> None:
    report = load_report("dirty-worktree.json")
    report.update(report_id="empty-report", run_id="empty-run", source_path="reports/empty.json")
    report["repos"] = []

    result = build_recent_problem_repos([report])

    assert result["distinct_problem_repo_count"] == 0
    assert result["returned_problem_repo_count"] == 0
    assert result["problem_repos"] == []


@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
def test_recent_problem_repos_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(ValueError, match="limit must"):
        build_recent_problem_repos(reports(), limit=limit)  # type: ignore[arg-type]


def test_recent_problem_repos_requires_at_least_one_report() -> None:
    with pytest.raises(ValueError, match="at least one omnipull report"):
        build_recent_problem_repos([])


def test_recent_problem_repos_rejects_duplicate_source_report() -> None:
    report = load_report("dirty-worktree.json")

    with pytest.raises(ValueError, match="duplicate omnipull report source_path"):
        build_recent_problem_repos([report, copy.deepcopy(report)])


def test_recent_problem_repos_rejects_duplicate_report_identity() -> None:
    first = load_report("dirty-worktree.json")
    second = copy.deepcopy(first)
    second["source_path"] = "reports/copied-report.json"

    with pytest.raises(ValueError, match="duplicate omnipull report identity"):
        build_recent_problem_repos([first, second])


def test_recent_problem_repos_rejects_duplicate_repo_id_within_report() -> None:
    report = load_report("dirty-worktree.json")
    report["repos"].append(copy.deepcopy(report["repos"][0]))

    with pytest.raises(ValueError, match="contains duplicate repo_id"):
        build_recent_problem_repos([report])


def test_recent_problem_repos_rejects_malformed_normalized_repo() -> None:
    report = load_report("dirty-worktree.json")
    del report["repos"][0]["path"]

    with pytest.raises(ValueError, match=r"repos\[0\]\.path must be a non-blank string"):
        build_recent_problem_repos([report])


def test_recent_problem_repos_does_not_mutate_input_reports() -> None:
    report_list = reports()
    original = copy.deepcopy(report_list)

    build_recent_problem_repos(report_list, limit=3)

    assert report_list == original


def test_recent_problem_repos_schema_statuses_match_omnipull_contract() -> None:
    status_schema = schema()["properties"]["problem_repos"]["items"]["properties"]["status"]

    assert set(status_schema["enum"]) == set(OMNIPULL_REPORT_STATUSES)


def test_recent_problem_repos_schema_rejects_softened_boundary() -> None:
    payload = load_json(EXAMPLE_PATH)
    payload["boundary"]["does_not_mutate"] = False

    with pytest.raises(ValidationError):
        Draft202012Validator(schema()).validate(payload)


def test_recent_problem_repos_schema_rejects_unknown_status() -> None:
    payload = load_json(EXAMPLE_PATH)
    payload["problem_repos"][0]["status"] = "probably_fine"

    with pytest.raises(ValidationError):
        Draft202012Validator(schema()).validate(payload)
