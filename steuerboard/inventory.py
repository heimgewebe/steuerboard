from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_SCOPES = {
    "scope_canonical",
    "scope_shadow",
    "scope_backup",
    "scope_gdrive",
    "scope_unknown",
    "scope_excluded",
}


@dataclass(frozen=True)
class LocalConfig:
    host_name: str
    canonical_repo_roots: tuple[Path, ...]
    excluded_repo_roots: tuple[Path, ...]


@dataclass(frozen=True)
class GitProbe:
    is_git_repo: bool
    git_toplevel: str | None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_config_path() -> Path:
    return _repo_root() / "examples" / "local-configs" / "heim-pc.json"


def _rfc3339_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _inventory_id() -> str:
    return f"inv-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}"


def _load_local_config(config_path: Path | None) -> LocalConfig:
    path = config_path or _default_config_path()
    data = json.loads(path.read_text(encoding="utf-8"))

    host_name = data["host"]["name"]
    paths = data.get("paths", {})
    canonical_repo_roots = tuple(
        Path(item).expanduser().absolute() for item in paths.get("canonical_repo_roots", [])
    )
    excluded_repo_roots = tuple(
        Path(item).expanduser().absolute() for item in paths.get("excluded_repo_roots", [])
    )

    return LocalConfig(
        host_name=host_name,
        canonical_repo_roots=canonical_repo_roots,
        excluded_repo_roots=excluded_repo_roots,
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _run_git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _probe_git(path: Path) -> GitProbe:
    worktree = _run_git(path, "rev-parse", "--is-inside-work-tree")
    if worktree.returncode != 0 or worktree.stdout.strip() != "true":
        return GitProbe(is_git_repo=False, git_toplevel=None)

    toplevel = _run_git(path, "rev-parse", "--show-toplevel")
    if toplevel.returncode != 0:
        return GitProbe(is_git_repo=True, git_toplevel=None)

    return GitProbe(is_git_repo=True, git_toplevel=toplevel.stdout.strip())


def _is_excluded(path: Path, excluded_roots: tuple[Path, ...]) -> bool:
    return any(_is_relative_to(path, root) for root in excluded_roots)


def _is_gdrive(path: Path) -> bool:
    return any(part.lower() == "gdrive" for part in path.parts)


def _is_backup(path: Path) -> bool:
    return any("backup" in part.lower() for part in path.parts)


def _classify_scope(path: Path, config: LocalConfig) -> tuple[str, str]:
    if _is_excluded(path, config.excluded_repo_roots):
        return "scope_excluded", "under excluded_repo_roots"
    if _is_gdrive(path):
        return "scope_gdrive", "path contains gdrive segment"
    if _is_backup(path):
        return "scope_backup", "path contains backup segment"
    if any(_is_relative_to(path, root) for root in config.canonical_repo_roots):
        return "scope_canonical", "under canonical_repo_roots"
    return "scope_unknown", "outside configured roots"


def _find_git_repos_under(root: Path, excluded_roots: tuple[Path, ...]) -> list[Path]:
    found: list[Path] = []

    if not root.exists() or not root.is_dir():
        return found

    root_path = root.expanduser().absolute()

    if _is_excluded(root_path, excluded_roots):
        return found

    for current, dirs, files in os.walk(root_path, topdown=True):
        current_path = Path(current)

        if _is_excluded(current_path, excluded_roots):
            dirs[:] = []
            continue

        dirs[:] = [
            name
            for name in dirs
            if not _is_excluded((current_path / name).absolute(), excluded_roots)
        ]

        if ".git" in dirs or ".git" in files:
            found.append(current_path)
            dirs[:] = []

    return found


def _mark_shadow_duplicates(repos: list[dict[str, Any]]) -> None:
    by_toplevel: dict[str, list[dict[str, Any]]] = {}
    for repo in repos:
        if not repo["is_git_repo"] or not repo.get("git_toplevel"):
            continue
        by_toplevel.setdefault(repo["git_toplevel"], []).append(repo)

    for duplicates in by_toplevel.values():
        if len(duplicates) < 2:
            continue

        duplicates.sort(key=lambda item: item["path"])
        primary = duplicates[0]
        for repo in duplicates[1:]:
            if repo["scope"] in {"scope_excluded", "scope_gdrive", "scope_backup"}:
                continue
            repo["scope"] = "scope_shadow"
            repo["scope_reason"] = f"duplicate git_toplevel with {primary['path']}"


def build_inventory(config_path: Path | None = None) -> dict[str, Any]:
    config = _load_local_config(config_path)

    repos: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()

    for root in config.canonical_repo_roots:
        for repo_path in _find_git_repos_under(root, config.excluded_repo_roots):
            normalized = repo_path.expanduser().absolute()
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            probe = _probe_git(normalized)
            scope, scope_reason = _classify_scope(normalized, config)
            repos.append(
                {
                    "path": str(normalized),
                    "is_git_repo": probe.is_git_repo,
                    "scope": scope,
                    "scope_reason": scope_reason,
                    "git_toplevel": probe.git_toplevel,
                }
            )

    for excluded_root in config.excluded_repo_roots:
        normalized = excluded_root.expanduser().absolute()
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        probe = _probe_git(normalized)
        repos.append(
            {
                "path": str(normalized),
                "is_git_repo": probe.is_git_repo,
                "scope": "scope_excluded",
                "scope_reason": "under excluded_repo_roots (not walked)",
                "git_toplevel": probe.git_toplevel,
            }
        )

    _mark_shadow_duplicates(repos)
    repos.sort(key=lambda item: item["path"])

    for repo in repos:
        if repo["scope"] not in ALLOWED_SCOPES:
            raise ValueError(f"unknown scope: {repo['scope']}")

    source_refs = [
        "local_config.canonical_repo_roots",
        "local_config.excluded_repo_roots",
        "filesystem.walk",
        "git.rev_parse.worktree",
    ]

    return {
        "schema_version": "repo-inventory.v1",
        "inventory_id": _inventory_id(),
        "source_refs": source_refs,
        "observed_at": _rfc3339_now(),
        "host": config.host_name,
        "repos": repos,
    }
