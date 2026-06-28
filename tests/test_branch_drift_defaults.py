from types import SimpleNamespace

from steuerboard.branch_drift import build_branch_drift_report


def test_main_master_and_trunk_are_each_valid_defaults(monkeypatch):
    paths = ["/repos/main", "/repos/master", "/repos/trunk"]
    repos = [
        {
            "path": path,
            "is_git_repo": True,
            "scope": "scope_canonical",
            "scope_reason": "test",
            "git_toplevel": path,
        }
        for path in paths
    ]
    config = SimpleNamespace(host_name="test-host")
    monkeypatch.setattr("steuerboard.branch_drift.load_local_config", lambda path: config)
    monkeypatch.setattr(
        "steuerboard.branch_drift.build_inventory_from_config",
        lambda value: {"repos": repos},
    )

    def observe(path):
        branch = str(path).rsplit("/", 1)[-1]
        return {
            "observed_state": {
                "is_git_repo": True,
                "current_branch": branch,
                "default_branch_candidate": branch,
                "default_branch_candidate_source": "local_branch_heuristic",
                "dirty": False,
                "ahead": 0,
                "behind": 0,
            }
        }

    monkeypatch.setattr("steuerboard.branch_drift.observe_repo", observe)
    report = build_branch_drift_report(config_path=None, warning_threshold=1)
    assert [item["classification"] for item in report["repos"]] == [
        "on_default_branch",
        "on_default_branch",
        "on_default_branch",
    ]
    assert report["warning_triggered"] is False
