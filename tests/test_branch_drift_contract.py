from __future__ import annotations

import ast
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.branch_drift import build_branch_drift_report


def test_schema_example_is_valid_and_strict() -> None:
    schema = load_json(SCHEMAS_DIR / "repo-branch-drift.v1.schema.json")
    example = load_json(ROOT / "examples/branch-drift/mixed.json")
    validate_instance(example, schema, Path("mixed.json"))

    invalid = copy.deepcopy(example)
    invalid["unexpected"] = True
    with pytest.raises(Exception):
        validate_instance(invalid, schema, Path("invalid-top.json"))

    invalid = copy.deepcopy(example)
    invalid["repos"][0]["unexpected"] = True
    with pytest.raises(Exception):
        validate_instance(invalid, schema, Path("invalid-repo.json"))

    invalid = copy.deepcopy(example)
    invalid["boundary"]["does_not_mutate"] = False
    with pytest.raises(Exception):
        validate_instance(invalid, schema, Path("invalid-boundary.json"))


def test_observation_failure_stays_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = {
        "path": "/repos/project",
        "is_git_repo": True,
        "scope": "scope_canonical",
        "scope_reason": "test",
        "git_toplevel": "/repos/project",
    }
    monkeypatch.setattr(
        "steuerboard.branch_drift.load_local_config",
        lambda path: SimpleNamespace(host_name="test-host"),
    )
    monkeypatch.setattr(
        "steuerboard.branch_drift.build_inventory_from_config",
        lambda config: {"repos": [repo]},
    )

    def fail(path: Path) -> dict:
        raise OSError("git unavailable")

    monkeypatch.setattr("steuerboard.branch_drift.observe_repo", fail)
    report = build_branch_drift_report(config_path=None, warning_threshold=1)
    assert report["repos"][0]["classification"] == "observation_failed"
    assert report["warning_triggered"] is False


def test_module_has_no_direct_process_or_network_surface() -> None:
    tree = ast.parse((ROOT / "steuerboard/branch_drift.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint({"subprocess", "socket", "urllib", "requests", "httpx"})
