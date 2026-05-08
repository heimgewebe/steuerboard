from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class GitResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def _run_git(path: Path, *args: str) -> GitResult:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"

    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return GitResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def _git_stdout_or_none(path: Path, *args: str) -> str | None:
    result = _run_git(path, *args)
    if result.returncode != 0 or result.stdout == "":
        return None
    return result.stdout


def _worktree_check(path: Path) -> GitResult:
    return _run_git(path, "rev-parse", "--is-inside-work-tree")


def _is_successful_worktree_check(result: GitResult) -> bool:
    return result.returncode == 0 and result.stdout == "true"


def _parse_ahead_behind(path: Path) -> tuple[int | None, int | None]:
    result = _run_git(path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    if result.returncode != 0:
        return None, None

    parts = result.stdout.split()
    if len(parts) != 2:
        return None, None

    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def _default_branch_candidate(path: Path) -> str | None:
    origin_head = _git_stdout_or_none(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if origin_head:
        return origin_head.removeprefix("origin/")

    for branch in ("main", "master", "trunk"):
        result = _run_git(path, "show-ref", "--verify", f"refs/heads/{branch}")
        if result.returncode == 0:
            return branch

    return None



def _netloc_without_userinfo(remote_url: str) -> str | None:
    try:
        parts = urlsplit(remote_url)
        port = f":{parts.port}" if parts.port is not None else ""
    except ValueError:
        return None

    if not parts.hostname:
        return None

    return f"{parts.hostname}{port}"


def _redact_remote_url(remote_url: str | None) -> str | None:
    if not remote_url:
        return None

    # SCP-like SSH remotes such as git@github.com:org/repo.git are not URL userinfo.
    if "://" not in remote_url:
        return remote_url

    try:
        parts = urlsplit(remote_url)
    except ValueError:
        return "[REDACTED_REMOTE_URL]"

    has_userinfo = parts.username is not None or parts.password is not None
    if not has_userinfo:
        return remote_url

    # HTTPS userinfo can contain tokens. Password-bearing URLs are always unsafe.
    if parts.scheme in {"http", "https"} or parts.password is not None:
        netloc = _netloc_without_userinfo(remote_url)
        if netloc is None:
            return "[REDACTED_REMOTE_URL]"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    return remote_url

def _repo_id_from_remote(remote_url: str | None) -> str | None:
    if not remote_url:
        return None

    value = remote_url.removesuffix(".git")
    prefixes = (
        "git@github.com:",
        "ssh://git@github.com/",
        "https://github.com/",
    )

    for prefix in prefixes:
        if value.startswith(prefix):
            return value.removeprefix(prefix)

    return None


def _observation_id(path: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"obs-{now}-{digest}"


def observe_repo(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    worktree_check = _worktree_check(resolved)
    is_repo = _is_successful_worktree_check(worktree_check)

    if not is_repo:
        return {
            "schema_version": "repo-observation.v1",
            "observation_id": _observation_id(resolved),
            "source_refs": ["git.rev_parse.worktree"],
            "observed_state": {
                "path": str(resolved),
                "is_git_repo": False,
                "git_metadata_present_at_observed_path": (resolved / ".git").exists(),
                "git_worktree_check_exit_code": worktree_check.returncode,
                "git_worktree_check_stdout": worktree_check.stdout,
                "git_worktree_check_stderr": worktree_check.stderr,
                "git_status_exit_code": None,
            },
        }

    source_refs = [
        "git.rev_parse.worktree",
        "git.current_branch",
        "git.rev_parse.head",
        "git.rev_parse.toplevel",
        "git.status.porcelain",
        "git.upstream",
        "git.ahead_behind",
        "git.remote.origin.url",
        "git.default_branch_candidate",
    ]

    status_result = _run_git(resolved, "status", "--porcelain")
    git_toplevel = _git_stdout_or_none(resolved, "rev-parse", "--show-toplevel")
    current_branch = _git_stdout_or_none(resolved, "branch", "--show-current")
    head_sha = _git_stdout_or_none(resolved, "rev-parse", "HEAD")
    upstream = _git_stdout_or_none(
        resolved,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}",
    )
    ahead, behind = _parse_ahead_behind(resolved)
    raw_remote_url = _git_stdout_or_none(resolved, "remote", "get-url", "origin")
    remote_url = _redact_remote_url(raw_remote_url)
    default_branch = _default_branch_candidate(resolved)

    observed_state: dict[str, Any] = {
        "path": str(resolved),
        "is_git_repo": True,
        "git_metadata_present_at_observed_path": (resolved / ".git").exists(),
        "git_toplevel": git_toplevel,
        "git_worktree_check_exit_code": worktree_check.returncode,
        "current_branch": current_branch,
        "head_sha": head_sha,
        "dirty": status_result.stdout != "",
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "remote_url": remote_url,
        "default_branch_candidate": default_branch,
        "git_status_exit_code": status_result.returncode,
    }

    repo_id = _repo_id_from_remote(remote_url)

    observation: dict[str, Any] = {
        "schema_version": "repo-observation.v1",
        "observation_id": _observation_id(resolved),
        "source_refs": source_refs,
        "observed_state": observed_state,
    }

    if repo_id:
        observation["repo_id"] = repo_id

    return observation
