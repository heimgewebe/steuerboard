from types import SimpleNamespace

from steuerboard.branch_drift import build_branch_drift_report


def test_distinct_nondefault_detached_and_unknown_states(monkeypatch):
    paths = ["/repos/feature", "/repos/detached", "/repos/unknown"]
    repos = [
        {"path": path, "is_git_repo": True, "scope": "scope_canonical", "scope_reason": "test", "git_toplevel": path}
        for path in paths
    ]
    values = {
        paths[0]: ("topic", "main"),
        paths[1]: (None, "main"),
        paths[2]: ("topic", None),
    }
    monkeypatch.setattr("steuerboard.branch_drift.load_local_config", lambda path: SimpleNamespace(host_name="test-host"))
    monkeypatch.setattr("steuerboard.branch_drift.build_inventory_from_config", lambda value: {"repos": repos})

    def observe(path):
        current, default = values[str(path)]
        return {"observed_state": {"is_git_repo": True, "current_branch": current, "default_branch_candidate": default, "default_branch_candidate_source": "unavailable" if default is None else "local_branch_heuristic", "dirty": False, "ahead": None, "behind": None}}

    monkeypatch.setattr("steuerboard.branch_drift.observe_repo", observe)
    report = build_branch_drift_report(config_path=None, warning_threshold=1)
    assert [item["classification"] for item in report["repos"]] == [
        "detached_head",
        "non_default_branch",
        "default_branch_unknown",
    ]
    assert report["warning_triggered"] is True
