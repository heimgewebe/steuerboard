from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from scripts.validate_examples import load_json, validate_instance
from steuerboard.cli import build_parser, main
from steuerboard.local_config import LocalConfig, OperationalPolicy
from steuerboard.operator_report import build_operator_report

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "operator-report.v1.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "operator-reports" / "daily.json"


def _config() -> LocalConfig:
    return LocalConfig(
        source_path=Path("/tmp/local-config.json"),
        host_name="test-host",
        canonical_repo_roots=(Path("/repos"),),
        excluded_repo_roots=(),
        favorite_repo_paths=("/repos/favorite", "/repos/missing"),
        policy=OperationalPolicy(
            allow_mutating_actions=False,
            allow_branch_switch=False,
            allow_network_fetch=True,
        ),
    )


def _inventory() -> dict:
    return {
        "schema_version": "repo-inventory.v1",
        "inventory_id": "inv-test",
        "source_refs": [
            "local_config.canonical_repo_roots",
            "local_config.excluded_repo_roots",
            "filesystem.walk",
            "git.rev_parse.worktree",
        ],
        "observed_at": "2026-06-29T06:00:00Z",
        "host": "test-host",
        "repos": [
            {
                "path": "/repos/favorite",
                "is_git_repo": True,
                "scope": "scope_canonical",
                "scope_reason": "under canonical_repo_roots",
                "git_toplevel": "/repos/favorite",
            },
            {
                "path": "/repos/feature",
                "is_git_repo": True,
                "scope": "scope_canonical",
                "scope_reason": "under canonical_repo_roots",
                "git_toplevel": "/repos/feature",
            },
            {
                "path": "/repos/not-git",
                "is_git_repo": False,
                "scope": "scope_canonical",
                "scope_reason": "under canonical_repo_roots",
                "git_toplevel": None,
            },
        ],
    }


def _profile() -> dict:
    return {
        "schema_version": "operational-profile.v1",
        "generated_at": "2026-06-29T06:00:00Z",
        "host": "test-host",
        "config_path": "/tmp/local-config.json",
        "policy": {
            "allow_mutating_actions": False,
            "allow_branch_switch": False,
            "allow_network_fetch": True,
        },
        "effective_operations": {
            "remote-refresh.fetch-origin-prune": True,
            "action.run-git-pull-ff-only": False,
            "action.run-switch-main": False,
        },
        "source_refs": ["local-config.v1.policy"],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }


def test_operator_report_example_is_schema_valid() -> None:
    validate_instance(load_json(EXAMPLE_PATH), load_json(SCHEMA_PATH), Path("operator-report.json"))


def test_operator_report_aggregates_policy_favorites_branch_drift_and_recent_problems(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "steuerboard.operator_report._utc_now",
        lambda: datetime(2026, 6, 29, 6, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr("steuerboard.operator_report.load_local_config", lambda path: _config())
    monkeypatch.setattr("steuerboard.operator_report.build_inventory_from_config", lambda config: _inventory())
    monkeypatch.setattr("steuerboard.operator_report.build_operational_profile_from_config", lambda config: _profile())

    observations = {
        "/repos/favorite": {
            "repo_id": "heimgewebe/favorite",
            "observed_state": {
                "is_git_repo": True,
                "current_branch": "main",
                "default_branch_candidate": "main",
                "default_branch_candidate_source": "local_branch_heuristic",
                "dirty": False,
                "ahead": None,
                "behind": None,
            },
        },
        "/repos/feature": {
            "repo_id": "heimgewebe/feature",
            "observed_state": {
                "is_git_repo": True,
                "current_branch": "topic",
                "default_branch_candidate": "main",
                "default_branch_candidate_source": "local_branch_heuristic",
                "dirty": True,
                "ahead": None,
                "behind": None,
            },
        },
    }
    monkeypatch.setattr("steuerboard.operator_report.observe_repo", lambda path: observations[str(path)])
    monkeypatch.setattr(
        "steuerboard.operator_report.load_omnipull_report",
        lambda path, *, source_path_ref: {"source_path": source_path_ref},
    )
    monkeypatch.setattr(
        "steuerboard.operator_report.build_recent_problem_repos",
        lambda reports, *, limit: {
            "schema_version": "recent-problem-repos.v1",
            "input_report_count": len(reports),
            "distinct_problem_repo_count": 2,
            "returned_problem_repo_count": min(limit, 2),
            "problem_repos": [],
            "boundary": {
                "does_not_execute": True,
                "does_not_mutate": True,
                "does_not_authorise_actions": True,
            },
        },
    )

    report = build_operator_report(
        config_path=Path("/tmp/local-config.json"),
        branch_warning_threshold=1,
        omnipull_report_paths=["reports/a.json", "reports/b.json"],
        recent_problem_limit=1,
    )

    validate_instance(report, load_json(SCHEMA_PATH), Path("operator-report-generated.json"))
    assert report["report_id"] == "operator-report-20260629-060000Z"
    assert report["summary"]["blocked_effective_operation_count"] == 2
    assert report["summary"]["favorite_count"] == 2
    assert report["summary"]["missing_favorite_count"] == 1
    assert report["summary"]["branch_drift_warning_triggered"] is True
    assert report["summary"]["non_default_branch_count"] == 1
    assert report["summary"]["input_omnipull_report_count"] == 2
    assert report["summary"]["returned_problem_repo_count"] == 1
    assert report["favorites"]["favorites"][0]["inventory_status"] == "present"
    assert report["favorites"]["favorites"][1]["inventory_status"] == "not_in_inventory"
    assert [repo["classification"] for repo in report["branch_drift"]["repos"]] == [
        "on_default_branch",
        "non_default_branch",
    ]
    assert report["boundary"] == {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
        "does_not_recommend_actions": True,
    }


def test_operator_report_without_omnipull_reports_uses_null_recent_problem_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "steuerboard.operator_report._utc_now",
        lambda: datetime(2026, 6, 29, 6, 0, tzinfo=timezone.utc),
    )
    config = LocalConfig(
        source_path=Path("/tmp/local-config.json"),
        host_name="test-host",
        canonical_repo_roots=(Path("/repos"),),
        excluded_repo_roots=(),
        favorite_repo_paths=(),
        policy=OperationalPolicy(False, False, True),
    )
    monkeypatch.setattr("steuerboard.operator_report.load_local_config", lambda path: config)
    monkeypatch.setattr(
        "steuerboard.operator_report.build_inventory_from_config",
        lambda value: _inventory() | {"repos": []},
    )
    monkeypatch.setattr("steuerboard.operator_report.build_operational_profile_from_config", lambda config: _profile())
    monkeypatch.setattr(
        "steuerboard.operator_report.load_omnipull_report",
        lambda *args, **kwargs: pytest.fail("no implicit Omnipull report loading is allowed"),
    )

    report = build_operator_report(
        config_path=None,
        branch_warning_threshold=3,
    )

    validate_instance(report, load_json(SCHEMA_PATH), Path("operator-report-no-recent.json"))
    assert report["recent_problem_repos"] is None
    assert report["inputs"]["omnipull_report_paths"] == []
    assert report["summary"]["input_omnipull_report_count"] == 0
    assert report["summary"]["distinct_problem_repo_count"] == 0


@pytest.mark.parametrize("value", [0, 1001, True, "2"])
def test_operator_report_rejects_invalid_branch_warning_threshold(value: object) -> None:
    with pytest.raises(ValueError, match="branch_warning_threshold"):
        build_operator_report(branch_warning_threshold=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0, 101, False, "2"])
def test_operator_report_rejects_invalid_recent_problem_limit(value: object) -> None:
    with pytest.raises(ValueError, match="recent_problem_limit"):
        build_operator_report(
            branch_warning_threshold=1,
            recent_problem_limit=value,  # type: ignore[arg-type]
        )


def test_operator_report_rejects_duplicate_omnipull_report_paths() -> None:
    with pytest.raises(ValueError, match="duplicate omnipull report path"):
        build_operator_report(
            branch_warning_threshold=1,
            omnipull_report_paths=["reports/a.json", "reports/a.json"],
        )


def test_operator_report_parser_requires_threshold() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["operator", "report", "--json"])


def test_operator_report_cli_emits_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_report(**kwargs: object) -> dict:
        assert kwargs["branch_warning_threshold"] == 4
        assert kwargs["omnipull_report_paths"] == ["reports/a.json"]
        assert kwargs["recent_problem_limit"] == 2
        return load_json(EXAMPLE_PATH)

    monkeypatch.setattr("steuerboard.cli.build_operator_report", fake_report)

    result = main(
        [
            "operator",
            "report",
            "--branch-warning-threshold",
            "4",
            "--omnipull-report",
            "reports/a.json",
            "--recent-problem-limit",
            "2",
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "operator-report.v1"
