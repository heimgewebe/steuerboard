from types import SimpleNamespace

from steuerboard.branch_drift import build_branch_drift_report


def test_single_snapshot_filters_noncanonical(monkeypatch):
    calls = {"load": 0, "inventory": 0, "observed": []}
    repos = [
        {"path": "/kept", "scope": "scope_canonical", "is_git_repo": True, "git_toplevel": "/kept"},
        {"path": "/skip", "scope": "scope_excluded", "is_git_repo": True, "git_toplevel": "/skip"},
    ]
    config = SimpleNamespace(host_name="host")
    monkeypatch.setattr("steuerboard.branch_drift.load_local_config", lambda path: calls.__setitem__("load", calls["load"] + 1) or config)
    monkeypatch.setattr("steuerboard.branch_drift.build_inventory_from_config", lambda value: calls.__setitem__("inventory", calls["inventory"] + 1) or {"repos": repos})

    def observe(path):
        calls["observed"].append(str(path))
        return {"observed_state": {"is_git_repo": True, "current_branch": "main", "default_branch_candidate": "main", "default_branch_candidate_source": "local_branch_heuristic", "dirty": False, "ahead": 0, "behind": 0}}

    monkeypatch.setattr("steuerboard.branch_drift.observe_repo", observe)
    build_branch_drift_report(config_path=None, warning_threshold=1)
    assert calls == {"load": 1, "inventory": 1, "observed": ["/kept"]}
