from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.cli import build_parser
from steuerboard.inventory import build_favorites_report


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


def _write_config(
    path: Path,
    *,
    canonical_roots: list[Path],
    favorites: list[str] | None,
) -> Path:
    config: dict = {
        "schema_version": "local-config.v1",
        "host": {"name": "test-host"},
        "paths": {
            "canonical_repo_roots": [str(item.absolute()) for item in canonical_roots],
            "excluded_repo_roots": [],
        },
        "policy": {
            "allow_mutating_actions": False,
            "allow_branch_switch": False,
            "allow_network_fetch": False,
        },
    }
    if favorites is not None:
        config["preferences"] = {"favorite_repo_paths": favorites}
    config_path = path / "local-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def _schema() -> dict:
    return load_json(SCHEMAS_DIR / "repo-favorites.v1.schema.json")


def _validate(report: dict, name: str) -> None:
    validate_instance(report, _schema(), Path(name))


def test_favorites_report_is_empty_when_preferences_are_absent(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repos"
    _init_repo(canonical_root / "project")
    config_path = _write_config(
        tmp_path,
        canonical_roots=[canonical_root],
        favorites=None,
    )

    report = build_favorites_report(config_path=config_path)

    _validate(report, "favorites-empty.json")
    assert report["favorites"] == []
    assert report["missing_favorite_paths"] == []
    assert report["source_refs"][0] == "local_config.preferences.favorite_repo_paths"


def test_favorites_preserve_config_order_and_mark_missing(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repos"
    first_repo = canonical_root / "first"
    second_repo = canonical_root / "second"
    missing_repo = canonical_root / "missing"
    _init_repo(first_repo)
    _init_repo(second_repo)
    config_path = _write_config(
        tmp_path,
        canonical_roots=[canonical_root],
        favorites=[str(second_repo), str(missing_repo), str(first_repo)],
    )

    report = build_favorites_report(config_path=config_path)

    _validate(report, "favorites-mixed.json")
    assert [item["path"] for item in report["favorites"]] == [
        str(second_repo.absolute()),
        str(missing_repo.absolute()),
        str(first_repo.absolute()),
    ]
    assert [item["inventory_status"] for item in report["favorites"]] == [
        "present",
        "not_in_inventory",
        "present",
    ]
    assert report["favorites"][0]["scope"] == "scope_canonical"
    assert report["favorites"][1]["scope"] is None
    assert report["missing_favorite_paths"] == [str(missing_repo.absolute())]


def test_favorites_reject_normalized_duplicates(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    canonical_root = home / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    monkeypatch.setenv("HOME", str(home))
    config_path = _write_config(
        tmp_path,
        canonical_roots=[canonical_root],
        favorites=["~/repos/project", str(repo.absolute())],
    )

    with pytest.raises(ValueError, match="duplicate normalized paths"):
        build_favorites_report(config_path=config_path)


def test_favorites_expand_home_paths(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    canonical_root = home / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    monkeypatch.setenv("HOME", str(home))
    config_path = _write_config(
        tmp_path,
        canonical_roots=[canonical_root],
        favorites=["~/repos/project"],
    )

    report = build_favorites_report(config_path=config_path)

    assert report["favorites"][0]["path"] == str(repo.absolute())
    assert report["favorites"][0]["inventory_status"] == "present"


def test_missing_favorite_does_not_expand_inventory_discovery(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    outside = tmp_path / "outside" / "not-scanned"
    _init_repo(repo)
    _init_repo(outside)
    config_path = _write_config(
        tmp_path,
        canonical_roots=[canonical_root],
        favorites=[str(outside)],
    )

    report = build_favorites_report(config_path=config_path)

    assert report["favorites"][0]["inventory_status"] == "not_in_inventory"
    assert report["favorites"][0]["is_git_repo"] is None
    assert report["missing_favorite_paths"] == [str(outside.absolute())]


def test_favorites_cli_emits_schema_valid_json(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repos"
    repo = canonical_root / "project"
    _init_repo(repo)
    config_path = _write_config(
        tmp_path,
        canonical_roots=[canonical_root],
        favorites=[str(repo)],
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steuerboard",
            "inventory",
            "favorites",
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

    report = json.loads(result.stdout)
    _validate(report, "favorites-cli.json")
    assert report["favorites"][0]["inventory_status"] == "present"


def test_favorites_parser_preserves_parent_config_argument(tmp_path: Path) -> None:
    parent_config = tmp_path / "parent-config.json"
    child_config = tmp_path / "child-config.json"
    parser = build_parser()

    parent_args = parser.parse_args(
        ["inventory", "--config", str(parent_config), "favorites", "--json"]
    )
    assert parent_args.config == str(parent_config)

    child_args = parser.parse_args(
        [
            "inventory",
            "--config",
            str(parent_config),
            "favorites",
            "--config",
            str(child_config),
            "--json",
        ]
    )
    assert child_args.config == str(child_config)
