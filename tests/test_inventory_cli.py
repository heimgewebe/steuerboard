from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.inventory import build_inventory


FORBIDDEN_INVENTORY_KEYS = {
    "risk_level",
    "decision_state",
    "safe_actions",
    "skip_reasons",
    "derived_status",
}

def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.email", "test@example.invalid"], path)
    _run(["git", "config", "user.name", "Test User"], path)
    _run(["git", "config", "commit.gpgsign", "false"], path)

def _write_local_config(path: Path, canonical_roots: list[Path], excluded_roots: list[Path]) -> Path:
    config = {
        "schema_version": "local-config.v1",
        "host": {"name": "test-host"},
        "paths": {
            "canonical_repo_roots": [str(item.absolute()) for item in canonical_roots],
            "excluded_repo_roots": [str(item.absolute()) for item in excluded_roots],
        },
        "policy": {
            "allow_mutating_actions": False,
            "allow_branch_switch": False,
            "allow_network_fetch": False,
        },
    }
    config_path = path / "local-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path

def _inventory_schema() -> dict:
    return load_json(SCHEMAS_DIR / "repo-inventory.v1.schema.json")

def _assert_inventory_invariants(inventory: dict, schema: dict, path: Path) -> None:
    validate_instance(inventory, schema, path)
    assert FORBIDDEN_INVENTORY_KEYS.isdisjoint(inventory)
    for repo in inventory["repos"]:
        assert FORBIDDEN_INVENTORY_KEYS.isdisjoint(repo)

def test_inventory_scope_canonical_repo(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)

    config_path = _write_local_config(tmp_path, [canonical_root], [])
    inventory = build_inventory(config_path=config_path)

    schema = _inventory_schema()
    _assert_inventory_invariants(inventory, schema, Path("inventory-canonical.json"))

    repo_entry = next(item for item in inventory["repos"] if item["path"] == str(repo.absolute()))
    assert repo_entry["is_git_repo"] is True
    assert repo_entry["scope"] == "scope_canonical"
    assert repo_entry["scope_reason"] == "under canonical_repo_roots"
    assert repo_entry["git_toplevel"] == str(repo.resolve())

def test_inventory_marks_excluded_root_without_walking(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    excluded_root = canonical_root / "excluded"
    _init_repo(excluded_root)

    config_path = _write_local_config(tmp_path, [canonical_root], [excluded_root])
    inventory = build_inventory(config_path=config_path)

    excluded_entry = next(item for item in inventory["repos"] if item["path"] == str(excluded_root.absolute()))
    assert excluded_entry["scope"] == "scope_excluded"
    assert excluded_entry["scope_reason"] == "under excluded_repo_roots (not walked)"
    assert excluded_entry["is_git_repo"] is True

def test_inventory_scope_backup_path(tmp_path: Path):
    canonical_root = tmp_path / "roots"
    repo = canonical_root / "backups" / "steuerboard"
    _init_repo(repo)

    config_path = _write_local_config(tmp_path, [canonical_root], [])
    inventory = build_inventory(config_path=config_path)

    repo_entry = next(item for item in inventory["repos"] if item["path"] == str(repo.absolute()))
    assert repo_entry["scope"] == "scope_backup"
    assert repo_entry["scope_reason"] == "path contains backup segment"

def test_inventory_scope_gdrive_path(tmp_path: Path):
    canonical_root = tmp_path / "roots"
    repo = canonical_root / "GDrive" / "repos" / "steuerboard"
    _init_repo(repo)

    config_path = _write_local_config(tmp_path, [canonical_root], [])
    inventory = build_inventory(config_path=config_path)

    repo_entry = next(item for item in inventory["repos"] if item["path"] == str(repo.absolute()))
    assert repo_entry["scope"] == "scope_gdrive"
    assert repo_entry["scope_reason"] == "path contains gdrive segment"

def test_inventory_marks_duplicate_toplevel_as_shadow(tmp_path: Path):
    canonical_root = tmp_path / "roots"
    repo = canonical_root / "steuerboard"
    _init_repo(repo)

    shadow_root = tmp_path / "shadow-link"
    try:
        os.symlink(repo, shadow_root, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink not available: {exc}")

    config_path = _write_local_config(tmp_path, [canonical_root, shadow_root], [])
    inventory = build_inventory(config_path=config_path)

    shadow_entries = [item for item in inventory["repos"] if item["scope"] == "scope_shadow"]
    assert shadow_entries
    assert any("duplicate git_toplevel" in item["scope_reason"] for item in shadow_entries)

def test_inventory_cli_emits_schema_valid_json(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)

    config_path = _write_local_config(tmp_path, [canonical_root], [])

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "inventory",
            "--config",
            str(config_path),
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    inventory = json.loads(result.stdout)
    schema = _inventory_schema()
    _assert_inventory_invariants(inventory, schema, Path("inventory-cli.json"))

def test_inventory_source_refs_include_required_inputs(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)

    config_path = _write_local_config(tmp_path, [canonical_root], [])
    inventory = build_inventory(config_path=config_path)

    assert "local_config.canonical_repo_roots" in inventory["source_refs"]
    assert "filesystem.walk" in inventory["source_refs"]
    assert "git.rev_parse.worktree" in inventory["source_refs"]

def test_inventory_duplicate_prefers_canonical_primary_over_backup_shadow(tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)

    backup_shadow = tmp_path / "backups-project"
    try:
        os.symlink(repo, backup_shadow, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink not available: {exc}")

    config_path = _write_local_config(tmp_path, [backup_shadow, canonical_root], [])
    inventory = build_inventory(config_path=config_path)

    canonical_entry = next(item for item in inventory["repos"] if item["path"] == str(repo.absolute()))
    backup_entry = next(
        item for item in inventory["repos"] if item["path"] == str(backup_shadow.absolute())
    )

    assert canonical_entry["scope"] == "scope_canonical"
    assert backup_entry["scope"] == "scope_backup"


def test_inventory_default_config_uses_xdg_config(monkeypatch, tmp_path: Path):
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)

    xdg_home = tmp_path / "xdg"
    config_dir = xdg_home / "steuerboard"
    config_dir.mkdir(parents=True)
    _write_local_config(config_dir, [canonical_root], [])

    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))

    inventory = build_inventory()
    repo_entry = next(item for item in inventory["repos"] if item["path"] == str(repo.absolute()))

    assert inventory["host"] == "test-host"
    assert repo_entry["scope"] == "scope_canonical"
