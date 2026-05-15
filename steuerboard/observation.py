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


def _default_branch_candidate(path: Path) -> tuple[str | None, str]:
    origin_head = _git_stdout_or_none(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if origin_head:
        return origin_head.removeprefix("origin/"), "remote_origin_head"

    for branch in ("main", "master", "trunk"):
        result = _run_git(path, "show-ref", "--verify", f"refs/heads/{branch}")
        if result.returncode == 0:
            return branch, "local_branch_heuristic"

    return None, "unavailable"


def _netloc_without_userinfo(remote_url: str) -> str | None:
    try:
        parts = urlsplit(remote_url)
        port = f":{parts.port}" if parts.port is not None else ""
    except ValueError:
        return None

    if not parts.hostname:
        return None

    return f"{parts.hostname}{port}"


def _strip_query_fragment(value: str) -> str:
    return value.split("#", 1)[0].split("?", 1)[0]


def _redact_scp_like_remote(remote_url: str) -> str:
    stripped = _strip_query_fragment(remote_url)

    if "@" not in stripped:
        return stripped

    user, rest = stripped.split("@", 1)
    if user == "git":
        return stripped

    return f"[REDACTED_USER]@{rest}"


def _redact_remote_url(remote_url: str | None) -> str | None:
    if not remote_url:
        return None

    # SCP-like SSH remotes such as git@github.com:org/repo.git are not URL userinfo.
    # Query and fragment data are still stripped because they can carry secrets.
    # Non-git SSH usernames are redacted because auth identities can be sensitive.
    if "://" not in remote_url:
        return _redact_scp_like_remote(remote_url)

    try:
        parts = urlsplit(remote_url)
    except ValueError:
        return "[REDACTED_REMOTE_URL]"

    netloc = _netloc_without_userinfo(remote_url)
    if netloc is None:
        return "[REDACTED_REMOTE_URL]"

    # Remote identity does not need query or fragment data. Both can carry secrets.
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _repo_id_from_remote(remote_url: str | None) -> str | None:
    if not remote_url:
        return None

    value = remote_url.removesuffix(".git")
    prefixes = (
        "git@github.com:",
        "ssh://git@github.com/",
        "ssh://github.com/",
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
        "git.default_branch_candidate_source",
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
    raw_remote_url = _git_stdout_or_none(resolved, "config", "--get", "remote.origin.url")
    remote_url = _redact_remote_url(raw_remote_url)
    default_branch, default_branch_source = _default_branch_candidate(resolved)

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
        "default_branch_candidate_source": default_branch_source,
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
