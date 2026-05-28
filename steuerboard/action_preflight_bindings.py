"""Phase 8D.1: Action Preflight Binding artifact bridge.

This module implements the pure artifact-level binding between a
git-pull-ff-only action-plan.v1 and a git-status-read-only run-evidence-chain.v1.
It exists to make the preflight relationship explicit and auditable.

Boundary contract:
- pure artifact validation; no subprocesses, no Git, no network, no mutation
- reads only the two explicitly passed artifact dicts
- validates both inputs against their JSON Schemas
- emits action-preflight-binding.v1 as a binding assessment artifact
- does NOT execute git pull, does NOT authorise actions, does NOT create a runner

Status semantics:
- binding_valid        : the chain provably belongs to the supplied pull plan
                         from contract-defined fields. Not achievable in the
                         current slice (see binding_cannot_be_proven_from_supplied_artifacts).
- binding_invalid      : at least one hard gate fails (unsupported plan action,
                         unsupported chain action, chain invalid, chain redaction
                         not verified, or binding material is present but mismatches).
- binding_inconclusive : no hard failure, but the contract-defined fields exposed
                         by the chain artifact do not contain a binding key that
                         ties the chain to the supplied pull plan. The honest
                         result for the current run-evidence-chain.v1 contract
                         (which fixes action to git-status-read-only and exposes
                         plan_ref only for the status plan).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from jsonschema import ValidationError as SchemaValidationError
    from jsonschema import validate as jsonschema_validate
except ModuleNotFoundError:  # pragma: no cover
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate

from .canonical_json import canonical_json_sha256

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}

_SUPPORTED_PLAN_ACTIONS = frozenset({"git-pull-ff-only"})
_SUPPORTED_CHAIN_ACTIONS = frozenset({"git-status-read-only"})

_SCHEMA_SAFE_LINE_RE = re.compile(r"^\S(?:.*\S)?$")


def _utc_rfc3339_now() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _sanitize_reason(reason: str) -> str:
    sanitized = " ".join(str(reason).split())
    return sanitized if sanitized else "unknown_error"


def _record_check(
    checks: list[dict[str, Any]],
    *,
    check: str,
    passed: bool,
    expected: str | None = None,
    actual: str | None = None,
) -> None:
    entry: dict[str, Any] = {"check": check, "passed": passed}
    if expected is not None:
        entry["expected"] = expected
    if actual is not None:
        entry["actual"] = actual
    checks.append(entry)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _write_binding_atomic(target: Path, data: dict[str, Any]) -> None:
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


def _require_output_path(path_str: str, param_name: str) -> Path:
    target = Path(path_str).expanduser().resolve(strict=False)
    if target.exists():
        raise ValueError(f"{param_name}: output file already exists: {target}")
    if not target.parent.exists():
        raise ValueError(f"{param_name}: parent directory does not exist: {target.parent}")
    return target


def bind_preflight_to_action(
    *,
    action_plan: dict[str, Any],
    run_evidence_chain: dict[str, Any],
    binding_out: str,
) -> dict[str, Any]:
    """Bind one git-pull-ff-only action-plan to one git-status-read-only chain.

    Parameters
    ----------
    action_plan:
        A dict representing an action-plan.v1 artifact (must declare
        action == "git-pull-ff-only" for any non-blocked binding result).
    run_evidence_chain:
        A dict representing a run-evidence-chain.v1 artifact (must declare
        action == "git-status-read-only" by schema).
    binding_out:
        Output path for the action-preflight-binding.v1 JSON artifact.
        Must not already exist; parent directory must exist.

    Returns
    -------
    dict
        The action-preflight-binding.v1 artifact.

    Raises
    ------
    ValueError
        If either input artifact is schema-invalid, or if preconditions on
        the output path are not met.
    """
    _validate_against_schema(action_plan, "action-plan.v1.schema.json", "action-plan.v1")
    _validate_against_schema(
        run_evidence_chain,
        "run-evidence-chain.v1.schema.json",
        "run-evidence-chain.v1",
    )

    binding_target = _require_output_path(binding_out, "binding_out")

    checks: list[dict[str, Any]] = []
    blocked_because: list[str] = []
    inconclusive_reasons: list[str] = []

    plan_action_raw = action_plan.get("action", "")
    plan_action = str(plan_action_raw) if plan_action_raw else "unknown"
    plan_id_raw = action_plan.get("plan_id", "")
    plan_id = str(plan_id_raw) if plan_id_raw else "unknown"

    chain_action_raw = run_evidence_chain.get("action", "")
    chain_action = str(chain_action_raw) if chain_action_raw else "unknown"
    chain_id_raw = run_evidence_chain.get("chain_id", "")
    chain_id = str(chain_id_raw) if chain_id_raw else "unknown"

    plan_action_supported = plan_action in _SUPPORTED_PLAN_ACTIONS
    _record_check(
        checks,
        check="plan_action_supported",
        passed=plan_action_supported,
        expected="git-pull-ff-only",
        actual=plan_action,
    )
    if not plan_action_supported:
        blocked_because.append("unsupported_plan_action")

    chain_action_supported = chain_action in _SUPPORTED_CHAIN_ACTIONS
    _record_check(
        checks,
        check="chain_action_supported",
        passed=chain_action_supported,
        expected="git-status-read-only",
        actual=chain_action,
    )
    if not chain_action_supported:
        blocked_because.append("unsupported_chain_action")

    chain_status = run_evidence_chain.get("status", "")
    chain_status_valid = chain_status == "valid"
    _record_check(
        checks,
        check="chain_status_valid",
        passed=chain_status_valid,
        expected="valid",
        actual=str(chain_status),
    )
    if chain_status == "invalid":
        blocked_because.append("chain_invalid")

    chain_redaction = run_evidence_chain.get("redaction_verified") is True
    _record_check(
        checks,
        check="chain_redaction_verified",
        passed=chain_redaction,
        expected="true",
        actual=json.dumps(run_evidence_chain.get("redaction_verified")),
    )
    if not chain_redaction:
        blocked_because.append("chain_redaction_unverified")

    # Binding-key gate.
    # The current run-evidence-chain.v1 contract fixes action to
    # "git-status-read-only" and exposes only plan_ref pointing to the
    # status plan, not to the pull plan. There is no contract-defined field
    # that ties the chain to the supplied pull plan.
    # As a result, contractual proof of binding cannot be established from
    # the supplied artifacts alone. Refuse to fake the bridge: emit
    # binding_inconclusive instead.
    chain_plan_ref = str(run_evidence_chain.get("plan_ref", ""))
    binding_basis_match = (chain_action == plan_action) and (chain_plan_ref == plan_id)
    _record_check(
        checks,
        check="binding_basis_from_contract_fields",
        passed=binding_basis_match,
        expected=(
            f"chain.action=={plan_action!r} and chain.plan_ref=={plan_id!r}"
        ),
        actual=(
            f"chain.action=={chain_action!r} and chain.plan_ref=={chain_plan_ref!r}"
        ),
    )

    only_chain_status_inconclusive_or_other = chain_status == "inconclusive"
    if only_chain_status_inconclusive_or_other:
        inconclusive_reasons.append("chain_inconclusive")

    # If no hard blocked reason has been recorded yet, and the binding basis
    # cannot be established from contract-defined fields, the honest result
    # is binding_inconclusive with binding_cannot_be_proven_from_supplied_artifacts.
    binding_basis_proven = (
        plan_action_supported
        and chain_action_supported
        and chain_status_valid
        and chain_redaction
        and binding_basis_match
    )

    if not binding_basis_proven and not blocked_because:
        inconclusive_reasons.append("binding_cannot_be_proven_from_supplied_artifacts")

    if blocked_because:
        binding_state = "binding_invalid"
        failure_reasons = _dedupe_preserve_order(blocked_because + inconclusive_reasons)
    elif inconclusive_reasons:
        binding_state = "binding_inconclusive"
        failure_reasons = _dedupe_preserve_order(inconclusive_reasons)
    else:
        binding_state = "binding_valid"
        failure_reasons = []

    sanitized_failure_reasons = [_sanitize_reason(r) for r in failure_reasons]
    # All emitted reasons must satisfy ^\S(?:.*\S)?$.
    for reason in sanitized_failure_reasons:
        if not _SCHEMA_SAFE_LINE_RE.fullmatch(reason):
            raise ValueError(f"internal: emitted reason is not schema-safe: {reason!r}")

    source_refs = _dedupe_preserve_order(
        [
            *[ref for ref in action_plan.get("source_refs", []) if isinstance(ref, str)],
            "action-plan.v1",
            "run-evidence-chain.v1",
        ]
    )

    binding_material = {
        "plan_ref": plan_id,
        "plan_action": plan_action,
        "chain_ref": chain_id,
        "chain_action": chain_action,
        "binding_state": binding_state,
        "blocked_because": list(blocked_because),
        "failure_reasons": list(sanitized_failure_reasons),
    }
    binding_id = f"preflight-binding-{canonical_json_sha256(binding_material)}"

    artifact: dict[str, Any] = {
        "schema_version": "action-preflight-binding.v1",
        "binding_id": binding_id,
        "checked_at": _utc_rfc3339_now(),
        "plan_ref": plan_id if plan_id else "unknown",
        "plan_action": plan_action if plan_action else "unknown",
        "chain_ref": chain_id if chain_id else "unknown",
        "chain_action": chain_action if chain_action else "unknown",
        "binding_state": binding_state,
        "blocked_because": list(blocked_because),
        "checks": checks,
        "source_refs": source_refs,
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }
    if sanitized_failure_reasons:
        artifact["failure_reasons"] = sanitized_failure_reasons

    _validate_against_schema(
        artifact,
        "action-preflight-binding.v1.schema.json",
        "action-preflight-binding.v1",
    )
    _write_binding_atomic(binding_target, artifact)
    return artifact
