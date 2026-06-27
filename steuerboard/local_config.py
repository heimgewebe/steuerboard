from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_POLICY_FIELDS = (
    "allow_mutating_actions",
    "allow_branch_switch",
    "allow_network_fetch",
)
_OPERATION_REQUIREMENTS = {
    "remote-refresh.fetch-origin-prune": ("allow_network_fetch",),
    "action.run-git-pull-ff-only": (
        "allow_mutating_actions",
        "allow_network_fetch",
    ),
    "action.run-switch-main": (
        "allow_mutating_actions",
        "allow_branch_switch",
    ),
}


@dataclass(frozen=True)
class OperationalPolicy:
    allow_mutating_actions: bool
    allow_branch_switch: bool
    allow_network_fetch: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "allow_mutating_actions": self.allow_mutating_actions,
            "allow_branch_switch": self.allow_branch_switch,
            "allow_network_fetch": self.allow_network_fetch,
        }


@dataclass(frozen=True)
class LocalConfig:
    source_path: Path
    host_name: str
    canonical_repo_roots: tuple[Path, ...]
    excluded_repo_roots: tuple[Path, ...]
    favorite_repo_paths: tuple[str, ...]
    policy: OperationalPolicy


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def user_config_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(xdg_config_home).expanduser() if xdg_config_home else Path.home() / ".config"
    return config_home / "steuerboard" / "local-config.json"


def checkout_example_config_path() -> Path:
    return _repo_root() / "examples" / "local-configs" / "heim-pc.json"


def default_config_candidates() -> tuple[Path, ...]:
    return (user_config_path(), checkout_example_config_path())


def default_config_path() -> Path:
    for candidate in default_config_candidates():
        if candidate.exists():
            return candidate
    return user_config_path()


def _require_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], field_name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{field_name} contains unknown fields: {unknown}")


def _require_non_blank_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")
    return value


def _require_path_list(value: Any, field_name: str) -> tuple[Path, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    paths: list[Path] = []
    for index, item in enumerate(value):
        path_text = _require_non_blank_string(item, f"{field_name}[{index}]")
        paths.append(Path(path_text).expanduser().absolute())
    return tuple(paths)


def _require_string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{field_name}[{index}] must be a non-empty string")
        if item != item.strip():
            raise ValueError(f"{field_name}[{index}] must not have leading or trailing whitespace")
        result.append(item)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(result)


def _load_policy(value: Any) -> OperationalPolicy:
    policy = _require_object(value, "local-config policy")
    _reject_unknown_keys(policy, set(_POLICY_FIELDS), "local-config policy")

    missing = [field for field in _POLICY_FIELDS if field not in policy]
    if missing:
        raise ValueError(f"local-config policy is missing required fields: {missing}")

    values: dict[str, bool] = {}
    for field in _POLICY_FIELDS:
        raw = policy[field]
        if not isinstance(raw, bool):
            raise ValueError(f"local-config policy.{field} must be a boolean")
        values[field] = raw

    return OperationalPolicy(**values)


def load_local_config(config_path: Path | None = None) -> LocalConfig:
    path = config_path.expanduser().absolute() if config_path else default_config_path()
    if not path.exists():
        candidates = ", ".join(str(candidate) for candidate in default_config_candidates())
        raise FileNotFoundError(
            f"local-config.v1 JSON not found; pass --config or create one of: {candidates}"
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid local-config.v1 JSON: {exc}") from exc

    root = _require_object(data, "local-config")
    _reject_unknown_keys(
        root,
        {"schema_version", "host", "paths", "preferences", "policy"},
        "local-config",
    )
    if root.get("schema_version") != "local-config.v1":
        raise ValueError("local-config schema_version must be local-config.v1")

    host = _require_object(root.get("host"), "local-config host")
    _reject_unknown_keys(host, {"name"}, "local-config host")
    host_name = _require_non_blank_string(host.get("name"), "local-config host.name")

    paths = _require_object(root.get("paths"), "local-config paths")
    _reject_unknown_keys(
        paths,
        {"canonical_repo_roots", "excluded_repo_roots"},
        "local-config paths",
    )
    canonical_repo_roots = _require_path_list(
        paths.get("canonical_repo_roots", []),
        "local-config paths.canonical_repo_roots",
    )
    excluded_repo_roots = _require_path_list(
        paths.get("excluded_repo_roots", []),
        "local-config paths.excluded_repo_roots",
    )

    preferences = _require_object(root.get("preferences", {}), "local-config preferences")
    _reject_unknown_keys(preferences, {"favorite_repo_paths"}, "local-config preferences")
    favorite_repo_paths = _require_string_list(
        preferences.get("favorite_repo_paths", []),
        "local-config preferences.favorite_repo_paths",
    )

    return LocalConfig(
        source_path=path,
        host_name=host_name,
        canonical_repo_roots=canonical_repo_roots,
        excluded_repo_roots=excluded_repo_roots,
        favorite_repo_paths=favorite_repo_paths,
        policy=_load_policy(root.get("policy")),
    )


def operation_allowed(policy: OperationalPolicy, operation: str) -> bool:
    required = _OPERATION_REQUIREMENTS.get(operation)
    if required is None:
        raise ValueError(f"unknown operational policy operation: {operation}")
    values = policy.as_dict()
    return all(values[field] for field in required)


def require_operation_allowed(config: LocalConfig, operation: str) -> None:
    required = _OPERATION_REQUIREMENTS.get(operation)
    if required is None:
        raise ValueError(f"unknown operational policy operation: {operation}")
    values = config.policy.as_dict()
    denied = [field for field in required if not values[field]]
    if denied:
        details = ", ".join(f"{field}=false" for field in denied)
        raise ValueError(f"operational policy blocks {operation}: {details}")


def build_operational_profile(config_path: Path | None = None) -> dict[str, Any]:
    config = load_local_config(config_path)
    policy = config.policy
    generated_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    return {
        "schema_version": "operational-profile.v1",
        "generated_at": generated_at,
        "host": config.host_name,
        "config_path": str(config.source_path),
        "policy": policy.as_dict(),
        "effective_operations": {
            operation: operation_allowed(policy, operation) for operation in _OPERATION_REQUIREMENTS
        },
        "source_refs": ["local-config.v1.policy"],
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }
