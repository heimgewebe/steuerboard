"""Phase 8D.0: Stage-D Execution Readiness artifact validator.

This module validates that an action-plan.v1, action-approval-validation.v1,
and run-evidence-chain.v1 together satisfy the Stage-D readiness conditions for
a single supported action (git-pull-ff-only).

Boundary contract:
- pure artifact validation; no subprocesses, no Git, no network, no mutation
- reads only the three explicitly passed artifact dicts
- validates all three inputs against their JSON Schemas
- supports only git-pull-ff-only in this slice
- emits action-execution-readiness.v1 as a readiness assessment artifact
- does NOT execute git pull, does NOT authorise actions, does NOT create a runner

Status semantics:
- ready      : all hard gates pass AND plan binding is contractually proven
- blocked    : at least one hard gate fails (rejected/expired approval, invalid chain)
- inconclusive: no hard failure but plan binding between pull-plan and read-only
               preflight chain cannot be contractually proven
               (reason: preflight_chain_plan_binding_unproven)
"""
from __future__ import annotations

import json
import os
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

_SUPPORTED_ACTIONS = frozenset({"git-pull-ff-only"})


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


def _write_readiness_atomic(target: Path, data: dict[str, Any]) -> None:
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


def validate_execution_readiness(
    *,
    action_plan: dict[str, Any],
    approval_validation: dict[str, Any],
    run_evidence_chain: dict[str, Any],
    readiness_out: str,
    preflight_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate Stage-D readiness and write action-execution-readiness.v1.

    Parameters
    ----------
    action_plan:
        A dict representing an action-plan.v1 artifact.
    approval_validation:
        A dict representing an action-approval-validation.v1 artifact.
    run_evidence_chain:
        A dict representing a run-evidence-chain.v1 artifact.
    readiness_out:
        Output path for the action-execution-readiness.v1 JSON artifact.
        Must not already exist; parent directory must exist.
    preflight_binding:
        Optional Phase 8D.1 action-preflight-binding.v1 artifact. When supplied,
        readiness verifies the binding artifact references the same plan and
        chain and records preflight_binding_ref in the readiness artifact.
        In the current artifact contract, binding_valid is not independently
        provable, so readiness remains inconclusive unless a future contract
        adds explicit proof material.

    Returns
    -------
    dict
        The action-execution-readiness.v1 artifact.

    Raises
    ------
    ValueError
        If any input artifact is schema-invalid, or if preconditions on
        the output path are not met, or if a supplied preflight binding does
        not reference the same plan and chain that readiness is validating.
    """
    # Validate all three inputs against their schemas first.
    _validate_against_schema(action_plan, "action-plan.v1.schema.json", "action-plan.v1")
    _validate_against_schema(
        approval_validation,
        "action-approval-validation.v1.schema.json",
        "action-approval-validation.v1",
    )
    _validate_against_schema(
        run_evidence_chain,
        "run-evidence-chain.v1.schema.json",
        "run-evidence-chain.v1",
    )
    if preflight_binding is not None:
        _validate_against_schema(
            preflight_binding,
            "action-preflight-binding.v1.schema.json",
            "action-preflight-binding.v1",
        )

    readiness_target = _require_output_path(readiness_out, "readiness_out")

    checks: list[dict[str, Any]] = []
    hard_failure_reasons: list[str] = []
    inconclusive_reasons: list[str] = []

    # -----------------------------------------------------------------------
    # Check 1: plan.action must be a supported action (git-pull-ff-only only
    #          in this slice).
    # -----------------------------------------------------------------------
    plan_action = action_plan.get("action", "")
    action_supported = plan_action in _SUPPORTED_ACTIONS
    _record_check(
        checks,
        check="plan_action_supported",
        passed=action_supported,
        expected="git-pull-ff-only",
        actual=str(plan_action),
    )
    if not action_supported:
        hard_failure_reasons.append("unsupported_action")

    # -----------------------------------------------------------------------
    # Check 2: approval_validation.binding_state == "binding_valid"
    # -----------------------------------------------------------------------
    binding_state = approval_validation.get("binding_state", "")
    approval_binding_valid = binding_state == "binding_valid"
    _record_check(
        checks,
        check="approval_validation_binding_valid",
        passed=approval_binding_valid,
        expected="binding_valid",
        actual=str(binding_state),
    )
    if not approval_binding_valid:
        hard_failure_reasons.append("approval_not_binding_valid")

    # -----------------------------------------------------------------------
    # Check 3: approval_validation.plan_ref must match plan.plan_id
    # -----------------------------------------------------------------------
    approval_plan_ref = approval_validation.get("plan_ref", "")
    plan_id = action_plan.get("plan_id", "")
    approval_plan_ref_match = approval_plan_ref == plan_id
    _record_check(
        checks,
        check="approval_validation_plan_ref_matches_plan",
        passed=approval_plan_ref_match,
        expected=str(plan_id),
        actual=str(approval_plan_ref),
    )
    if not approval_plan_ref_match:
        hard_failure_reasons.append("approval_plan_ref_mismatch")

    # -----------------------------------------------------------------------
    # Check 4: approval_validation.action must match plan.action
    # -----------------------------------------------------------------------
    approval_action = approval_validation.get("action", "")
    approval_action_match = approval_action == plan_action
    _record_check(
        checks,
        check="approval_validation_action_matches_plan",
        passed=approval_action_match,
        expected=str(plan_action),
        actual=str(approval_action),
    )
    if not approval_action_match:
        hard_failure_reasons.append("approval_action_mismatch")

    # -----------------------------------------------------------------------
    # Check 5: run_evidence_chain.status == "valid"
    # -----------------------------------------------------------------------
    chain_status = run_evidence_chain.get("status", "")
    chain_valid = chain_status == "valid"
    chain_inconclusive = chain_status == "inconclusive"
    _record_check(
        checks,
        check="run_evidence_chain_status_valid",
        passed=chain_valid,
        expected="valid",
        actual=str(chain_status),
    )
    if chain_status == "invalid":
        hard_failure_reasons.append("chain_invalid")
    elif chain_inconclusive:
        inconclusive_reasons.append("chain_inconclusive")

    # -----------------------------------------------------------------------
    # Check 6: run_evidence_chain.redaction_verified == true
    # -----------------------------------------------------------------------
    chain_redaction = run_evidence_chain.get("redaction_verified") is True
    _record_check(
        checks,
        check="run_evidence_chain_redaction_verified",
        passed=chain_redaction,
        expected="true",
        actual=json.dumps(run_evidence_chain.get("redaction_verified")),
    )
    if not chain_redaction:
        hard_failure_reasons.append("chain_redaction_unverified")

    # -----------------------------------------------------------------------
    # Check 7: Plan binding between the pull plan and the read-only preflight
    # chain.  Without a preflight-binding artifact, this slice cannot prove
    # binding contractually because run-evidence-chain.v1 fixes action to
    # "git-status-read-only".  With a Phase 8D.1 action-preflight-binding.v1
    # artifact, the binding state is consumed directly after the readiness
    # logic verifies that the binding references the same plan and chain.
    # -----------------------------------------------------------------------
    chain_id = run_evidence_chain.get("chain_id", "")
    chain_action = run_evidence_chain.get("action", "")
    chain_plan_ref = run_evidence_chain.get("plan_ref", "")

    if preflight_binding is None:
        # Without an explicit binding artifact, the binding remains
        # structurally unproven in this slice.
        plan_binding_proven = (chain_action == plan_action) and (chain_plan_ref == plan_id)
        _record_check(
            checks,
            check="preflight_chain_plan_binding_proven",
            passed=plan_binding_proven,
            expected=f"chain.action=={plan_action!r} and chain.plan_ref=={plan_id!r}",
            actual=f"chain.action=={chain_action!r} and chain.plan_ref=={chain_plan_ref!r}",
        )
        if not plan_binding_proven and not hard_failure_reasons:
            inconclusive_reasons.append("preflight_chain_plan_binding_unproven")
    else:
        # With an explicit binding artifact, require ref/action consistency
        # before consulting its binding_state.
        binding_plan_ref = preflight_binding.get("plan_ref", "")
        binding_chain_ref = preflight_binding.get("chain_ref", "")
        binding_plan_action = preflight_binding.get("plan_action", "")
        binding_chain_action = preflight_binding.get("chain_action", "")
        if binding_plan_ref != plan_id:
            raise ValueError(
                "preflight_binding.plan_ref must match action_plan.plan_id "
                f"(binding.plan_ref={binding_plan_ref!r}, plan.plan_id={plan_id!r})"
            )
        if binding_chain_ref != chain_id:
            raise ValueError(
                "preflight_binding.chain_ref must match run_evidence_chain.chain_id "
                f"(binding.chain_ref={binding_chain_ref!r}, chain.chain_id={chain_id!r})"
            )
        if binding_plan_action != plan_action:
            raise ValueError(
                "preflight_binding.plan_action must match action_plan.action "
                f"(binding.plan_action={binding_plan_action!r}, plan.action={plan_action!r})"
            )
        if binding_chain_action != chain_action:
            raise ValueError(
                "preflight_binding.chain_action must match run_evidence_chain.action "
                f"(binding.chain_action={binding_chain_action!r}, chain.action={chain_action!r})"
            )

        binding_state = preflight_binding.get("binding_state", "")
        binding_invalid = binding_state == "binding_invalid"
        # Phase 8D.2: trust binding_valid only when the binding artifact
        # carries the contract-defined proof object
        # `preflight_for_action_plan`.  The binding logic has already verified
        # that this proof matches the supplied pull plan, so readiness may
        # consume it directly without re-implementing the proof check.
        binding_proof = preflight_binding.get("preflight_for_action_plan")
        binding_proof_present = isinstance(binding_proof, dict)
        binding_proven = (binding_state == "binding_valid") and binding_proof_present
        _record_check(
            checks,
            check="preflight_chain_plan_binding_proven",
            passed=binding_proven,
            expected="binding_state==binding_valid with preflight_for_action_plan proof",
            actual=(
                "binding_state=={state!r}, preflight_for_action_plan={proof}".format(
                    state=binding_state,
                    proof="present" if binding_proof_present else "absent",
                )
            ),
        )
        if binding_invalid:
            hard_failure_reasons.append("preflight_binding_invalid")
        elif not binding_proven and not hard_failure_reasons:
            inconclusive_reasons.append("preflight_chain_plan_binding_unproven")

    # -----------------------------------------------------------------------
    # Determine final status.
    # -----------------------------------------------------------------------
    if hard_failure_reasons:
        status = "blocked"
        failure_reasons = _dedupe_preserve_order(hard_failure_reasons + inconclusive_reasons)
    elif inconclusive_reasons:
        status = "inconclusive"
        failure_reasons = _dedupe_preserve_order(inconclusive_reasons)
    else:
        status = "ready"
        failure_reasons = []

    # -----------------------------------------------------------------------
    # Collect source refs.
    # -----------------------------------------------------------------------
    source_refs = _dedupe_preserve_order(
        [
            *[ref for ref in action_plan.get("source_refs", []) if isinstance(ref, str)],
            "action-plan.v1",
            "action-approval-validation.v1",
            "run-evidence-chain.v1",
            *(
                ["action-preflight-binding.v1"]
                if preflight_binding is not None
                else []
            ),
        ]
    )

    preflight_binding_ref: str | None = None
    if preflight_binding is not None:
        preflight_binding_ref = str(preflight_binding.get("binding_id", "unknown"))

    readiness_material = {
        "plan_id": plan_id,
        "approval_validation_ref": approval_validation.get("validation_id", "unknown"),
        "chain_ref": run_evidence_chain.get("chain_id", "unknown"),
        "status": status,
        "failure_reasons": failure_reasons,
    }
    if preflight_binding_ref is not None:
        readiness_material["preflight_binding_ref"] = preflight_binding_ref
        readiness_material["preflight_binding_state"] = str(
            preflight_binding.get("binding_state", "unknown")
        )
    readiness_id = f"readiness-{canonical_json_sha256(readiness_material)}"

    artifact: dict[str, Any] = {
        "schema_version": "action-execution-readiness.v1",
        "readiness_id": readiness_id,
        "checked_at": _utc_rfc3339_now(),
        "action": str(plan_action) if plan_action else "unknown",
        "plan_ref": plan_id or "unknown",
        "approval_validation_ref": approval_validation.get("validation_id", "unknown"),
        "chain_ref": run_evidence_chain.get("chain_id", "unknown"),
        "status": status,
        "blocked_because": [r for r in hard_failure_reasons if r in {
            "unsupported_action",
            "approval_not_binding_valid",
            "approval_plan_ref_mismatch",
            "approval_action_mismatch",
            "chain_invalid",
            "chain_redaction_unverified",
            "preflight_binding_invalid",
        }],
        "checks": checks,
        "source_refs": source_refs,
        "boundary": {
            "does_not_execute": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
        },
    }
    if preflight_binding_ref is not None:
        artifact["preflight_binding_ref"] = preflight_binding_ref
    if failure_reasons:
        artifact["failure_reasons"] = failure_reasons

    _validate_against_schema(
        artifact,
        "action-execution-readiness.v1.schema.json",
        "action-execution-readiness.v1",
    )
    _write_readiness_atomic(readiness_target, artifact)
    return artifact
