from types import SimpleNamespace

import pytest

from steuerboard.branch_drift import build_branch_drift_report


def _install(monkeypatch, count):
    config = SimpleNamespace(host_name="test-host")
    repos = [
        {
            "path": f"/repos/{index}",
            "is_git_repo": True,
            "scope": "scope_canonical",
            "scope_reason": "test",
            "git_toplevel": f"/repos/{index}",
        }
        for index in range(count)
    ]
    monkeypatch.setattr("steuerboard.branch_drift.load_local_config", lambda path: config)
    monkeypatch.setattr(
        "steuerboard.branch_drift.build_inventory_from_config",
        lambda received: {"repos": repos},
    )
    monkeypatch.setattr(
        "steuerboard.branch_drift.observe_repo",
        lambda path: {
            "observed_state": {
                "is_git_repo": True,
                "current_branch": "feature",
                "default_branch_candidate": "main",
                "default_branch_candidate_source": "local_branch_heuristic",
                "dirty": False,
                "ahead": 0,
                "behind": 0,
            }
        },
    )


@pytest.mark.parametrize(("threshold", "expected"), [(1, True), (2, True), (3, False)])
def test_explicit_threshold(monkeypatch, threshold, expected):
    _install(monkeypatch, 2)
    report = build_branch_drift_report(config_path=None, warning_threshold=threshold)
    assert report["warning_triggered"] is expected


@pytest.mark.parametrize("threshold", [0, 1001, True, 1.5, "2"])
def test_invalid_threshold(threshold):
    with pytest.raises(ValueError, match="warning_threshold"):
        build_branch_drift_report(config_path=None, warning_threshold=threshold)
