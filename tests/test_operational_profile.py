from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from scripts.validate_examples import ROOT, SCHEMAS_DIR, load_json, validate_instance
from steuerboard.local_config import (
    OperationalPolicy,
    build_operational_profile,
    load_local_config,
    operation_allowed,
    require_operation_allowed,
)
from steuerboard.remote_refresh import run_fetch_origin_prune

PROFILE_SCHEMA_PATH = SCHEMAS_DIR / "operational-profile.v1.schema.json"
LOCAL_CONFIG_SCHEMA_PATH = SCHEMAS_DIR / "local-config.v1.schema.json"
PROFILE_EXAMPLE_PATH = ROOT / "examples" / "operational-profiles" / "heim-pc.json"


def _write_config(
    tmp_path: Path,
    *,
    allow_mutating_actions: bool,
    allow_branch_switch: bool,
    allow_network_fetch: bool,
) -> Path:
    config = {
        "schema_version": "local-config.v1",
        "host": {"name": "test-host"},
        "paths": {
            "canonical_repo_roots": [str(tmp_path)],
            "excluded_repo_roots": [],
        },
        "preferences": {"favorite_repo_paths": []},
        "policy": {
            "allow_mutating_actions": allow_mutating_actions,
            "allow_branch_switch": allow_branch_switch,
            "allow_network_fetch": allow_network_fetch,
        },
    }
    path = tmp_path / "local-config.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def _cli(arguments: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "steuerboard", *arguments],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_local_config_schema_requires_complete_policy() -> None:
    payload = load_json(ROOT / "examples" / "local-configs" / "heim-pc.json")
    del payload["policy"]["allow_network_fetch"]

    with pytest.raises(ValidationError):
        Draft202012Validator(load_json(LOCAL_CONFIG_SCHEMA_PATH)).validate(payload)


def test_local_config_schema_rejects_whitespace_only_paths() -> None:
    payload = load_json(ROOT / "examples" / "local-configs" / "heim-pc.json")
    payload["paths"]["canonical_repo_roots"] = ["   "]

    with pytest.raises(ValidationError):
        Draft202012Validator(load_json(LOCAL_CONFIG_SCHEMA_PATH)).validate(payload)


def test_operational_profile_example_validates() -> None:
    validate_instance(
        load_json(PROFILE_EXAMPLE_PATH),
        load_json(PROFILE_SCHEMA_PATH),
        PROFILE_EXAMPLE_PATH,
    )


def test_profile_show_derives_effective_operation_gates(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        allow_mutating_actions=False,
        allow_branch_switch=True,
        allow_network_fetch=True,
    )

    profile = build_operational_profile(config_path)

    assert profile["host"] == "test-host"
    assert profile["config_path"] == str(config_path.absolute())
    assert profile["effective_operations"] == {
        "remote-refresh.fetch-origin-prune": True,
        "action.run-git-pull-ff-only": False,
        "action.run-switch-main": False,
    }
    assert profile["boundary"] == {
        "does_not_execute": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
    }
    validate_instance(profile, load_json(PROFILE_SCHEMA_PATH), Path("profile.json"))


def test_profile_show_cli_emits_schema_valid_json(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        allow_mutating_actions=True,
        allow_branch_switch=False,
        allow_network_fetch=True,
    )

    result = _cli(
        ["profile", "show", "--config", str(config_path), "--json"],
        cwd=ROOT,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["effective_operations"]["action.run-git-pull-ff-only"] is True
    assert payload["effective_operations"]["action.run-switch-main"] is False
    validate_instance(payload, load_json(PROFILE_SCHEMA_PATH), Path("profile-cli.json"))


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (OperationalPolicy(False, False, False), (False, False, False)),
        (OperationalPolicy(False, True, True), (True, False, False)),
        (OperationalPolicy(True, False, True), (True, True, False)),
        (OperationalPolicy(True, True, False), (False, False, True)),
        (OperationalPolicy(True, True, True), (True, True, True)),
    ],
)
def test_operational_policy_matrix(
    policy: OperationalPolicy,
    expected: tuple[bool, bool, bool],
) -> None:
    operations = (
        "remote-refresh.fetch-origin-prune",
        "action.run-git-pull-ff-only",
        "action.run-switch-main",
    )

    assert tuple(operation_allowed(policy, operation) for operation in operations) == expected


@pytest.mark.parametrize(
    "missing_field",
    [
        "allow_mutating_actions",
        "allow_branch_switch",
        "allow_network_fetch",
    ],
)
def test_local_config_requires_complete_policy(tmp_path: Path, missing_field: str) -> None:
    config_path = _write_config(
        tmp_path,
        allow_mutating_actions=False,
        allow_branch_switch=False,
        allow_network_fetch=False,
    )
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    del payload["policy"][missing_field]
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="policy is missing required fields"):
        load_local_config(config_path)


def test_require_operation_allowed_names_all_denied_requirements(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        allow_mutating_actions=False,
        allow_branch_switch=False,
        allow_network_fetch=False,
    )
    config = load_local_config(config_path)

    with pytest.raises(ValueError) as exc_info:
        require_operation_allowed(config, "action.run-git-pull-ff-only")

    assert str(exc_info.value) == (
        "operational policy blocks action.run-git-pull-ff-only: "
        "allow_mutating_actions=false, allow_network_fetch=false"
    )


def test_remote_refresh_policy_denial_precedes_git_probe_and_output(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        allow_mutating_actions=False,
        allow_branch_switch=False,
        allow_network_fetch=False,
    )
    non_git_path = tmp_path / "not-a-repository"
    non_git_path.mkdir()
    trace_path = tmp_path / "trace.json"

    with pytest.raises(
        ValueError,
        match=r"operational policy blocks remote-refresh\.fetch-origin-prune",
    ):
        run_fetch_origin_prune(
            repo_path=str(non_git_path),
            config_path=str(config_path),
            assessment_id="assessment-policy-denied",
            command_trace_out=str(trace_path),
        )

    assert not trace_path.exists()


def test_pull_cli_policy_denial_precedes_artifact_loading_and_writes_nothing(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        allow_mutating_actions=False,
        allow_branch_switch=False,
        allow_network_fetch=True,
    )
    trace_out = tmp_path / "trace.json"
    result_out = tmp_path / "result.json"
    postcheck_out = tmp_path / "postcheck.json"

    result = _cli(
        [
            "action",
            "run-git-pull-ff-only",
            str(tmp_path / "missing-plan.json"),
            "--config",
            str(config_path),
            "--approval-validation",
            str(tmp_path / "missing-approval.json"),
            "--run-evidence-chain",
            str(tmp_path / "missing-chain.json"),
            "--preflight-binding",
            str(tmp_path / "missing-binding.json"),
            "--repo-path",
            str(tmp_path / "missing-repo"),
            "--command-trace-out",
            str(trace_out),
            "--run-result-out",
            str(result_out),
            "--postcheck-out",
            str(postcheck_out),
            "--json",
        ],
        cwd=ROOT,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["blocked_reasons"] == [
        "operational policy blocks action.run-git-pull-ff-only: allow_mutating_actions=false"
    ]
    assert not trace_out.exists()
    assert not result_out.exists()
    assert not postcheck_out.exists()
    assert "Traceback" not in result.stderr


def test_switch_cli_policy_denial_precedes_artifact_loading_and_writes_nothing(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        allow_mutating_actions=True,
        allow_branch_switch=False,
        allow_network_fetch=True,
    )
    trace_out = tmp_path / "trace.json"
    result_out = tmp_path / "result.json"
    postcheck_out = tmp_path / "postcheck.json"

    result = _cli(
        [
            "action",
            "run-switch-main",
            str(tmp_path / "missing-plan.json"),
            "--config",
            str(config_path),
            "--approval-validation",
            str(tmp_path / "missing-approval.json"),
            "--switch-main-readiness",
            str(tmp_path / "missing-readiness.json"),
            "--repo-path",
            str(tmp_path / "missing-repo"),
            "--command-trace-out",
            str(trace_out),
            "--run-result-out",
            str(result_out),
            "--postcheck-out",
            str(postcheck_out),
            "--json",
        ],
        cwd=ROOT,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["blocked_reasons"] == [
        "operational policy blocks action.run-switch-main: allow_branch_switch=false"
    ]
    assert not trace_out.exists()
    assert not result_out.exists()
    assert not postcheck_out.exists()
    assert "Traceback" not in result.stderr


def test_operational_profile_schema_rejects_authorising_boundary() -> None:
    payload = load_json(PROFILE_EXAMPLE_PATH)
    payload["boundary"]["does_not_authorise_actions"] = False

    with pytest.raises(ValidationError):
        Draft202012Validator(load_json(PROFILE_SCHEMA_PATH)).validate(payload)
