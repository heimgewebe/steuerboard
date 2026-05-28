"""Phase 8C: verify a read-only evidence chain without executing anything.

This module validates that action-plan.v1, command-trace.v1, run-result.v1,
and run-postcheck.v1 form one internally coherent read-only evidence chain.

Boundary contract:
- artifact-only validation; no subprocesses, no Git, no network
- validates all four inputs against their JSON Schemas
- supports only the git-status-read-only Phase 8A/8B pilot chain
- emits run-evidence-chain.v1 as evidence/validation, never as authorization
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from jsonschema import ValidationError as SchemaValidationError
    from jsonschema import validate as jsonschema_validate
except ModuleNotFoundError:  # pragma: no cover
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate

from .action_runs import _is_path_inside, _require_output_path, _utc_rfc3339_now
from .canonical_json import canonical_json_sha256

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}

_HARDENED_COMMAND_LEN = 6
_HARDENED_COMMAND_FIXED: dict[int, str] = {
    0: "git",
    1: "--no-optional-locks",
    2: "-C",
    4: "status",
    5: "--porcelain=v1",
}


def _load_schema(filename: str) -> dict[str, Any]:
    cached = _SCHEMA_CACHE.get(filename)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent.parent / "schemas" / filename
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    _SCHEMA_CACHE[filename] = schema
    return schema


def _validate_against_schema(instance: Any, schema_filename: str, label: str) -> None:
    if not isinstance(instance, dict):
        raise ValueError(f"{label} must be a JSON object")
    try:
        jsonschema_validate(instance=instance, schema=_load_schema(schema_filename))
    except SchemaValidationError as exc:
        raise ValueError(f"{label} does not validate against schema: {exc}") from exc


def _normalize_path_string(path_str: str) -> str:
    return str(Path(path_str).expanduser().resolve(strict=False))


def _validate_trace_command(command: Any) -> str:
    if not isinstance(command, list):
        raise ValueError("command-trace 'command' field must be an array")
    if len(command) != _HARDENED_COMMAND_LEN:
        raise ValueError(
            f"trace command must have exactly {_HARDENED_COMMAND_LEN} elements; got {len(command)}"
        )
    for idx, expected in _HARDENED_COMMAND_FIXED.items():
        if command[idx] != expected:
            raise ValueError(
                f"trace command[{idx}] must be {expected!r}; got {command[idx]!r}"
            )
    toplevel = command[3]
    if not isinstance(toplevel, str) or not toplevel:
        raise ValueError("trace command[3] (repo_toplevel) must be a non-empty string")
    return toplevel


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _record_check(
    checks: list[dict[str, Any]],
    *,
    check: str,
    passed: bool,
    expected: str | None = None,
    actual: str | None = None,
) -> None:
    entry: dict[str, Any] = {
        "check": check,
        "passed": passed,
    }
    if expected is not None:
        entry["expected"] = expected
    if actual is not None:
        entry["actual"] = actual
    checks.append(entry)


def _write_chain_atomic(target: Path, data: dict[str, Any]) -> None:
    tmp_path: Path | None = None
    try:
        fd, tmp = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        tmp_path = Path(tmp)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp_path, target)
        tmp_path = None
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def validate_run_evidence_chain(
    *,
    action_plan: dict[str, Any],
    command_trace: dict[str, Any],
    run_result: dict[str, Any],
    run_postcheck: dict[str, Any],
    action_plan_path: str,
    command_trace_path: str,
    run_result_path: str,
    run_postcheck_path: str,
    chain_out: str,
) -> dict[str, Any]:
    """Validate one Phase 8A/8B evidence chain and write run-evidence-chain.v1."""
    _validate_against_schema(action_plan, "action-plan.v1.schema.json", "action-plan.v1")
    _validate_against_schema(command_trace, "command-trace.v1.schema.json", "command-trace.v1")
    _validate_against_schema(run_result, "run-result.v1.schema.json", "run-result.v1")
    _validate_against_schema(run_postcheck, "run-postcheck.v1.schema.json", "run-postcheck.v1")

    chain_target = _require_output_path(chain_out, "chain_out")

    trace_repo_toplevel: str | None = None
    try:
        trace_repo_toplevel = _validate_trace_command(command_trace.get("command"))
    except ValueError:
        trace_repo_toplevel = None

    for repo_hint in (trace_repo_toplevel, run_postcheck.get("repo_toplevel")):
        if isinstance(repo_hint, str) and repo_hint:
            repo_root = Path(repo_hint).expanduser().resolve(strict=False)
            if _is_path_inside(repo_root, chain_target):
                raise ValueError("chain_out must not be inside the inspected repository")

    checks: list[dict[str, Any]] = []
    hard_failure_reasons: list[str] = []
    inconclusive_reasons: list[str] = []

    supported_action = action_plan["action"] == "git-status-read-only"
    _record_check(
        checks,
        check="action_plan_action_supported",
        passed=supported_action,
        expected="git-status-read-only",
        actual=str(action_plan.get("action")),
    )
    if not supported_action:
        hard_failure_reasons.append("unsupported_action")

    try:
        validated_trace_repo_toplevel = _validate_trace_command(command_trace["command"])
        trace_command_exact = True
    except ValueError as exc:
        validated_trace_repo_toplevel = None
        trace_command_exact = False
        trace_command_error = str(exc)
    else:
        trace_command_error = json.dumps(command_trace["command"], ensure_ascii=False)
    _record_check(
        checks,
        check="command_trace_command_exact",
        passed=trace_command_exact,
        expected="git --no-optional-locks -C <repo-toplevel> status --porcelain=v1",
        actual=trace_command_error,
    )
    if not trace_command_exact:
        hard_failure_reasons.append("trace_command_mismatch")

    trace_exit_code_ok = command_trace["exit_code"] == 0
    _record_check(
        checks,
        check="command_trace_exit_code_zero",
        passed=trace_exit_code_ok,
        expected="0",
        actual=str(command_trace.get("exit_code")),
    )
    if not trace_exit_code_ok:
        hard_failure_reasons.append("trace_exit_code_nonzero")

    trace_redacted = command_trace["redacted"] is True
    _record_check(
        checks,
        check="command_trace_redacted",
        passed=trace_redacted,
        expected="true",
        actual=json.dumps(command_trace.get("redacted")),
    )
    if not trace_redacted:
        hard_failure_reasons.append("trace_not_redacted")

    run_result_success = run_result["status"] == "success"
    _record_check(
        checks,
        check="run_result_status_success",
        passed=run_result_success,
        expected="success",
        actual=str(run_result.get("status")),
    )
    if not run_result_success:
        hard_failure_reasons.append("run_result_not_success")

    run_result_redaction = run_result["redaction_verified"] is True
    _record_check(
        checks,
        check="run_result_redaction_verified",
        passed=run_result_redaction,
        expected="true",
        actual=json.dumps(run_result.get("redaction_verified")),
    )
    if not run_result_redaction:
        hard_failure_reasons.append("run_result_redaction_unverified")

    run_ids_match = run_result["run_id"] == run_postcheck["run_id"]
    _record_check(
        checks,
        check="run_ids_match",
        passed=run_ids_match,
        expected=str(run_result.get("run_id")),
        actual=str(run_postcheck.get("run_id")),
    )
    if not run_ids_match:
        hard_failure_reasons.append("run_id_mismatch")

    normalized_trace_path = _normalize_path_string(command_trace_path)
    normalized_result_evidence = {
        _normalize_path_string(path)
        for path in run_result.get("evidence_paths", [])
        if isinstance(path, str) and path
    }
    trace_path_bound = normalized_trace_path in normalized_result_evidence
    _record_check(
        checks,
        check="run_result_includes_trace_path",
        passed=trace_path_bound,
        expected=normalized_trace_path,
        actual=json.dumps(sorted(normalized_result_evidence), ensure_ascii=False),
    )
    if not trace_path_bound:
        hard_failure_reasons.append("trace_path_missing_from_run_result")

    normalized_result_path = _normalize_path_string(run_result_path)
    normalized_postcheck_evidence = {
        _normalize_path_string(path)
        for path in run_postcheck.get("evidence_paths", [])
        if isinstance(path, str) and path
    }

    postcheck_trace_evidence_bound = normalized_trace_path in normalized_postcheck_evidence
    _record_check(
        checks,
        check="postcheck_includes_trace_path",
        passed=postcheck_trace_evidence_bound,
        expected=normalized_trace_path,
        actual=json.dumps(sorted(normalized_postcheck_evidence), ensure_ascii=False),
    )
    if not postcheck_trace_evidence_bound:
        hard_failure_reasons.append("postcheck_missing_trace_evidence_path")

    postcheck_result_evidence_bound = normalized_result_path in normalized_postcheck_evidence
    _record_check(
        checks,
        check="postcheck_includes_run_result_path",
        passed=postcheck_result_evidence_bound,
        expected=normalized_result_path,
        actual=json.dumps(sorted(normalized_postcheck_evidence), ensure_ascii=False),
    )
    if not postcheck_result_evidence_bound:
        hard_failure_reasons.append("postcheck_missing_run_result_evidence_path")

    postcheck_trace_matches = run_postcheck["trace_ref"] == command_trace["trace_id"]
    _record_check(
        checks,
        check="postcheck_trace_ref_matches_trace",
        passed=postcheck_trace_matches,
        expected=str(command_trace.get("trace_id")),
        actual=str(run_postcheck.get("trace_ref")),
    )
    if not postcheck_trace_matches:
        hard_failure_reasons.append("postcheck_trace_ref_mismatch")

    postcheck_result_matches = run_postcheck["run_result_ref"] == run_result["run_id"]
    _record_check(
        checks,
        check="postcheck_run_result_ref_matches_run_result",
        passed=postcheck_result_matches,
        expected=str(run_result.get("run_id")),
        actual=str(run_postcheck.get("run_result_ref")),
    )
    if not postcheck_result_matches:
        hard_failure_reasons.append("postcheck_run_result_ref_mismatch")

    postcheck_redaction = run_postcheck["redaction_verified"] is True
    _record_check(
        checks,
        check="postcheck_redaction_verified",
        passed=postcheck_redaction,
        expected="true",
        actual=json.dumps(run_postcheck.get("redaction_verified")),
    )
    if not postcheck_redaction:
        hard_failure_reasons.append("postcheck_redaction_unverified")

    # Plan-binding verification: run_result must carry plan_ref and
    # plan_content_sha256 that bind back to the action_plan it was produced from.
    # Absent fields => inconclusive (plan_binding_unavailable).
    # Present but mismatching => invalid (plan_ref_mismatch / plan_content_sha256_mismatch).
    run_result_plan_ref = run_result.get("plan_ref")
    run_result_plan_sha = run_result.get("plan_content_sha256")
    plan_ref_present = isinstance(run_result_plan_ref, str) and bool(run_result_plan_ref)
    plan_sha_present = isinstance(run_result_plan_sha, str) and bool(run_result_plan_sha)
    plan_binding_available = plan_ref_present and plan_sha_present
    _record_check(
        checks,
        check="plan_binding_available",
        passed=plan_binding_available,
        expected="run_result.plan_ref and run_result.plan_content_sha256",
        actual=json.dumps(
            {
                "plan_ref": run_result_plan_ref if plan_ref_present else None,
                "plan_content_sha256": run_result_plan_sha if plan_sha_present else None,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    if not plan_binding_available:
        inconclusive_reasons.append("plan_binding_unavailable")
    else:
        expected_plan_sha = canonical_json_sha256(action_plan)
        plan_ref_matches = run_result_plan_ref == action_plan["plan_id"]
        plan_sha_matches = run_result_plan_sha == expected_plan_sha
        _record_check(
            checks,
            check="run_result_plan_ref_matches_action_plan",
            passed=plan_ref_matches,
            expected=str(action_plan["plan_id"]),
            actual=str(run_result_plan_ref),
        )
        if not plan_ref_matches:
            hard_failure_reasons.append("plan_ref_mismatch")
        _record_check(
            checks,
            check="run_result_plan_content_sha256_matches_action_plan",
            passed=plan_sha_matches,
            expected=expected_plan_sha,
            actual=str(run_result_plan_sha),
        )
        if not plan_sha_matches:
            hard_failure_reasons.append("plan_content_sha256_mismatch")

    postcheck_status = run_postcheck["status"]
    postcheck_passed = postcheck_status == "passed"
    _record_check(
        checks,
        check="postcheck_status_passed_for_valid",
        passed=postcheck_passed,
        expected="passed",
        actual=str(postcheck_status),
    )
    if postcheck_status == "failed":
        hard_failure_reasons.append("postcheck_failed")
    elif postcheck_status == "inconclusive":
        inconclusive_reasons.append("postcheck_inconclusive")

    redaction_verified = trace_redacted and run_result_redaction and postcheck_redaction

    if hard_failure_reasons:
        status = "invalid"
        unique_failure_reasons = _dedupe_preserve_order(hard_failure_reasons + inconclusive_reasons)
    elif inconclusive_reasons:
        status = "inconclusive"
        unique_failure_reasons = _dedupe_preserve_order(inconclusive_reasons)
    else:
        status = "valid"
        unique_failure_reasons: list[str] = []

    source_refs = _dedupe_preserve_order(
        [
            *[ref for ref in action_plan.get("source_refs", []) if isinstance(ref, str)],
            *[ref for ref in run_postcheck.get("source_refs", []) if isinstance(ref, str)],
            "action-plan.v1",
            "command-trace.v1",
            "run-result.v1",
            "run-postcheck.v1",
        ]
    )

    evidence_paths = _dedupe_preserve_order(
        [
            _normalize_path_string(action_plan_path),
            normalized_trace_path,
            _normalize_path_string(run_result_path),
            _normalize_path_string(run_postcheck_path),
        ]
    )

    chain: dict[str, Any] = {
        "schema_version": "run-evidence-chain.v1",
        "chain_id": f"chain-{run_result['run_id']}",
        "checked_at": _utc_rfc3339_now(),
        "status": status,
        "action": "git-status-read-only",
        "plan_ref": action_plan["plan_id"],
        "trace_ref": command_trace["trace_id"],
        "run_result_ref": run_result["run_id"],
        "postcheck_ref": run_postcheck["postcheck_id"],
        "run_id": run_result["run_id"],
        "evidence_paths": evidence_paths,
        "source_refs": source_refs,
        "checks": checks,
        "redaction_verified": redaction_verified,
    }
    # Phase 8D.2: preserve preflight-target proof material from run-result into
    # the chain so downstream binding can verify it against the supplied pull
    # plan.  This is propagation only — the chain does not interpret the proof
    # against any pull plan; that is the job of action-preflight-binding.v1.
    preflight_for = run_result.get("preflight_for_action_plan")
    if isinstance(preflight_for, dict):
        plan_ref_value = preflight_for.get("plan_ref")
        plan_action_value = preflight_for.get("plan_action")
        plan_sha_value = preflight_for.get("plan_content_sha256")
        if (
            isinstance(plan_ref_value, str)
            and isinstance(plan_action_value, str)
            and isinstance(plan_sha_value, str)
        ):
            chain["preflight_for_action_plan"] = {
                "plan_ref": plan_ref_value,
                "plan_action": plan_action_value,
                "plan_content_sha256": plan_sha_value,
            }
    if status in {"invalid", "inconclusive"}:
        chain["failure_reasons"] = unique_failure_reasons

    _validate_against_schema(chain, "run-evidence-chain.v1.schema.json", "run-evidence-chain.v1")
    _write_chain_atomic(chain_target, chain)
    return chain