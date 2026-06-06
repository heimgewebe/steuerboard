"""Phase 11D — Read-only Runbook Runner.

Implements read-only runbook kinds:
- repo-sync-gate
- dns-gate
- ssh-gate
- tailscale-preflight

Architecture rule (Observation != Derivation != Decision != Action):
- A runbook sequences observations and derivations only.
- It does not collapse them into action.
- It does not authorise, execute, or permit any mutating operation.

Authority model:
- A runbook result is derived diagnostic material, not canonical state.
- It is not an approval, not execution permission, not a Stage-D gate substitute.

Boundary:
- No mutating Git operations.
- No subprocess with shell=True.
- No os.system.
- No generic command runner.
- Calls existing Python functions directly (observe_repo, assess_repo).
- Atomic writes via temp-file + os.replace, cleaned up on failure.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any

from .assessment import assess_repo
from .observation import observe_repo

try:
    from jsonschema import ValidationError as SchemaValidationError
    from jsonschema import validate as jsonschema_validate
except ModuleNotFoundError:  # pragma: no cover
    from .schema_validation import SchemaValidationError, validate_instance as jsonschema_validate

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

_RUNBOOK_PLAN_SCHEMA: dict[str, Any] | None = None
_RUNBOOK_RESULT_SCHEMA: dict[str, Any] | None = None
_RUNBOOK_STEP_TRACE_SCHEMA: dict[str, Any] | None = None
_SERVER_FACTS_SCHEMA: dict[str, Any] | None = None

# Allowed runbook kinds in Phase 11E.
SUPPORTED_RUNBOOK_KINDS: frozenset[str] = frozenset({
    "repo-sync-gate", "dns-gate", "ssh-gate", "tailscale-preflight", "server-facts-snapshot",
})


def _load_schema(name: str) -> dict[str, Any]:
    schema_path = _SCHEMAS_DIR / f"{name}.schema.json"
    with schema_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _get_runbook_plan_schema() -> dict[str, Any]:
    global _RUNBOOK_PLAN_SCHEMA
    if _RUNBOOK_PLAN_SCHEMA is None:
        _RUNBOOK_PLAN_SCHEMA = _load_schema("runbook-plan.v1")
    return _RUNBOOK_PLAN_SCHEMA


def _get_runbook_result_schema() -> dict[str, Any]:
    global _RUNBOOK_RESULT_SCHEMA
    if _RUNBOOK_RESULT_SCHEMA is None:
        _RUNBOOK_RESULT_SCHEMA = _load_schema("runbook-result.v1")
    return _RUNBOOK_RESULT_SCHEMA


def _get_runbook_step_trace_schema() -> dict[str, Any]:
    global _RUNBOOK_STEP_TRACE_SCHEMA
    if _RUNBOOK_STEP_TRACE_SCHEMA is None:
        _RUNBOOK_STEP_TRACE_SCHEMA = _load_schema("runbook-step-trace.v1")
    return _RUNBOOK_STEP_TRACE_SCHEMA


def _get_server_facts_schema() -> dict[str, Any]:
    global _SERVER_FACTS_SCHEMA
    if _SERVER_FACTS_SCHEMA is None:
        _SERVER_FACTS_SCHEMA = _load_schema("server-facts.v1")
    return _SERVER_FACTS_SCHEMA


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _result_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%fZ")
    entropy = time_ns()
    digest = hashlib.sha256(f"rbresult:{now}:{entropy}".encode("utf-8")).hexdigest()[:12]
    return f"rbresult-{now}-{digest}"


def _trace_id(step_id: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%fZ")
    entropy = time_ns()
    digest = hashlib.sha256(f"rbtrace:{step_id}:{now}:{entropy}".encode("utf-8")).hexdigest()[:12]
    return f"rbtrace-{step_id}-{now}-{digest}"


def _merge_source_refs(*groups: Any) -> list[str]:
    """Merge source_refs preserving insertion order and uniqueness."""
    merged_refs: list[str] = []
    seen_refs: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for ref in group:
            if not isinstance(ref, str):
                continue
            clean_ref = ref.strip()
            if not clean_ref:
                continue
            if clean_ref in seen_refs:
                continue
            seen_refs.add(clean_ref)
            merged_refs.append(clean_ref)
    return merged_refs


def _require_output_path(raw: str, label: str) -> Path:
    """Return resolved Path; raise ValueError if parent missing or target exists."""
    candidate = Path(raw).expanduser()
    target = candidate.resolve()
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"{label} parent directory must exist")
    if target.exists():
        raise ValueError(f"{label} must not already exist")
    return parent.resolve(strict=True) / target.name


def _resolve_repo_worktree_root(repo_path_raw: str) -> Path:
    repo_path = Path(repo_path_raw).expanduser().resolve()
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--show-toplevel"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError:
        completed = None

    if completed and completed.returncode == 0 and completed.stdout.strip():
        return Path(completed.stdout.strip()).expanduser().resolve()

    observation = observe_repo(repo_path)
    repo_toplevel = observation.get("repo_toplevel")
    if isinstance(repo_toplevel, str) and repo_toplevel.strip():
        return Path(repo_toplevel).expanduser().resolve()
    return repo_path


def _resolve_git_marker_worktree_root(repo_path_raw: str) -> Path:
    """Resolve repository worktree root by walking parents for a ``.git`` marker.

    Returns the closest ancestor containing ``.git`` (file or directory), or the
    resolved input path when no marker is found.
    """
    repo_path = Path(repo_path_raw).expanduser().resolve()
    cursor = repo_path if repo_path.is_dir() else repo_path.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / ".git").exists():
            return candidate
    return repo_path


def _ensure_outputs_outside_worktree(
    repo_worktree_root: Path,
    result_out: Path,
    command_trace_out: Path,
) -> None:
    for label, output_path in (("result_out", result_out), ("command_trace_out", command_trace_out)):
        try:
            output_path.relative_to(repo_worktree_root)
        except ValueError:
            continue
        raise ValueError(
            f"{label} must be outside repository worktree for read_only runbook: {output_path}"
        )


def _validate_plan_preconditions(
    runbook_plan: dict[str, Any],
    result_out: Path,
    command_trace_out: Path,
) -> None:
    """Validate preconditions before any execution begins.

    Raises ValueError for any precondition failure.
    No output files are written on precondition failure.
    """
    # 1. Schema-validate runbook plan
    try:
        jsonschema_validate(runbook_plan, _get_runbook_plan_schema())
    except (SchemaValidationError, Exception) as exc:
        raise ValueError(f"runbook_plan schema validation failed: {exc}") from exc

    # 2. Only explicitly supported read-only runbook kinds are allowed.
    runbook_kind = runbook_plan.get("runbook_kind", "")
    if runbook_kind not in SUPPORTED_RUNBOOK_KINDS:
        raise ValueError(
            f"unsupported runbook_kind {runbook_kind!r}; "
            f"supported runbook kinds: {sorted(SUPPORTED_RUNBOOK_KINDS)}"
        )

    # 3. Mode must be read_only
    mode = runbook_plan.get("mode", "")
    if mode != "read_only":
        raise ValueError(
            f"mode must be read_only, got {mode!r}"
        )

    # 4. Output paths must be distinct
    if result_out == command_trace_out:
        raise ValueError(
            "result_out and command_trace_out must be different paths"
        )


# ---------------------------------------------------------------------------
# Repo-sync-gate step checks (derivation only — no mutation, no subprocess)
# ---------------------------------------------------------------------------

def check_is_git_repo(observation: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the is-git-repo check."""
    obs_state = observation.get("observed_state")
    if not isinstance(obs_state, dict):
        return "inconclusive", "Git repository status is unknown."
    is_git = obs_state.get("is_git_repo")
    if is_git is True:
        return "passed", "Path is a git repository."
    if is_git is False:
        return "blocked", "Path is not a git repository."
    return "inconclusive", "Git repository status is unknown."


def check_worktree_clean(observation: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the worktree-clean check."""
    obs_state = observation.get("observed_state")
    if not isinstance(obs_state, dict):
        return "inconclusive", "Worktree cleanliness is unknown."
    dirty = obs_state.get("dirty")
    if dirty is False:
        return "passed", "Worktree is clean."
    if dirty is True:
        return "blocked", "Worktree is dirty (uncommitted changes present)."
    return "inconclusive", "Worktree cleanliness is unknown."


def check_not_detached_head(observation: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the not-detached-head check.

    Note: In repo-observation.v1, ``current_branch is None`` is an explicit
    detached-HEAD observation, so this check remains a hard block.
    """
    obs_state = observation.get("observed_state")
    if not isinstance(obs_state, dict):
        return "inconclusive", "Git repository status is unknown; HEAD check skipped."
    is_git = obs_state.get("is_git_repo")
    if is_git is not True:
        if is_git is False:
            return "inconclusive", "Not a git repository; HEAD check skipped."
        return "inconclusive", "Git repository status is unknown; HEAD check skipped."
    if "current_branch" not in obs_state:
        return "inconclusive", "Current branch is unknown; HEAD check inconclusive."
    current_branch_raw = obs_state.get("current_branch")
    if current_branch_raw is None:
        return "blocked", "HEAD is detached."
    if not isinstance(current_branch_raw, str):
        return "inconclusive", "Current branch is unknown; HEAD check inconclusive."
    current_branch = current_branch_raw.strip()
    if current_branch:
        return "passed", f"HEAD is on branch {current_branch!r}."
    return "inconclusive", "Current branch is unknown; HEAD check inconclusive."


def check_on_default_branch(observation: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the on-default-branch check.

    Detached HEAD does not answer "on default branch", so this check is
    inconclusive rather than blocked and relies on check_not_detached_head for
    the hard block.
    """
    obs_state = observation.get("observed_state")
    if not isinstance(obs_state, dict):
        return "inconclusive", "Git repository status is unknown; branch check skipped."
    is_git = obs_state.get("is_git_repo")
    if is_git is not True:
        if is_git is False:
            return "inconclusive", "Not a git repository; branch check skipped."
        return "inconclusive", "Git repository status is unknown; branch check skipped."
    current_branch_raw = obs_state.get("current_branch")
    if current_branch_raw is None:
        return "inconclusive", "HEAD is detached; default branch check skipped."
    if not isinstance(current_branch_raw, str):
        return "inconclusive", "Current branch is unknown."
    current_branch = current_branch_raw.strip()
    if not current_branch:
        return "inconclusive", "Current branch is unknown."
    default_candidate_raw = obs_state.get("default_branch_candidate")
    if not isinstance(default_candidate_raw, str):
        return "inconclusive", "Default branch candidate is unknown."
    default_candidate = default_candidate_raw.strip()
    if not default_candidate:
        return "inconclusive", "Default branch candidate is unknown."
    if current_branch == default_candidate:
        return "passed", f"Current branch {current_branch!r} matches default branch candidate {default_candidate!r}."
    return "blocked", (
        f"Current branch {current_branch!r} does not match default branch candidate {default_candidate!r}."
    )


def check_decision_state(assessment: dict[str, Any]) -> tuple[str, str]:
    """Return (step_status, label_note) for the decision-state check.

    Mapping:
    - assessment_clear  -> passed
    - evidence_missing  -> inconclusive (not hard-blocked, but not clear either)
    - action_blocked    -> blocked (do NOT soften)
    """
    decision_state = assessment.get("decision_state", "")
    if decision_state == "assessment_clear":
        return "passed", "Assessment decision_state is assessment_clear."
    if decision_state == "evidence_missing":
        return "inconclusive", "Assessment decision_state is evidence_missing."
    if decision_state == "action_blocked":
        return "blocked", "Assessment decision_state is action_blocked."
    return "inconclusive", f"Assessment decision_state is unknown or missing: {decision_state!r}."


def _validate_step_trace(entry: dict[str, Any]) -> None:
    """Validate a step trace entry against the runbook-step-trace.v1 schema.

    Raises ValueError if validation fails.
    """
    try:
        jsonschema_validate(entry, _get_runbook_step_trace_schema())
    except (SchemaValidationError, Exception) as exc:
        raise ValueError(f"step trace entry failed schema validation: {exc}") from exc


def _validate_result(result: dict[str, Any]) -> None:
    """Validate the result dict against the runbook-result.v1 schema.

    Raises ValueError if validation fails.
    """
    try:
        jsonschema_validate(result, _get_runbook_result_schema())
    except (SchemaValidationError, Exception) as exc:
        raise ValueError(f"runbook result failed schema validation: {exc}") from exc


def _derive_overall_status(steps: list[dict[str, Any]]) -> str:
    """Derive overall runbook status from step statuses.

    Rules:
    - Any blocked step -> overall blocked (do NOT soften)
    - Any inconclusive step (no blocked) -> overall inconclusive
    - All passed -> overall passed
    """
    statuses = [step["status"] for step in steps]
    if "blocked" in statuses:
        return "blocked"
    if "inconclusive" in statuses:
        return "inconclusive"
    return "passed"


def _build_repo_sync_short_assessment(
    overall_status: str,
    steps: list[dict[str, Any]],
    assessment: dict[str, Any],
) -> str:
    """Build repo-sync-gate short assessment text."""
    derived_status = assessment.get("derived_status", [])
    decision_state = assessment.get("decision_state", "unknown")
    missing_evidence = assessment.get("missing_evidence", [])

    if overall_status == "passed":
        return (
            f"Repo-sync-gate passed. "
            f"Repository assessment: decision_state={decision_state!r}, "
            f"derived_status={derived_status!r}. "
            f"All local preflight checks passed. "
            f"Remote freshness evidence may still be missing (expected for a read-only local gate)."
        )
    if overall_status == "blocked":
        blocked_steps = [s["step_id"] for s in steps if s["status"] == "blocked"]
        return (
            f"Repo-sync-gate blocked. "
            f"Assessment decision_state={decision_state!r}, derived_status={derived_status!r}. "
            f"Blocked at steps: {blocked_steps!r}. "
            f"No mutating action is authorised."
        )
    # inconclusive
    return (
        f"Repo-sync-gate inconclusive. "
        f"Assessment decision_state={decision_state!r}, derived_status={derived_status!r}, "
        f"missing_evidence={missing_evidence!r}. "
        f"Cannot determine sync readiness without additional evidence. No action authorised."
    )


def _build_short_assessment(
    overall_status: str,
    steps: list[dict[str, Any]],
    assessment: dict[str, Any],
) -> str:
    """Backward-compatible alias for existing tests/hooks."""
    return _build_repo_sync_short_assessment(overall_status, steps, assessment)


def _normalize_ip_values(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped:
            continue
        try:
            stripped = str(ipaddress.ip_address(stripped))
        except ValueError:
            pass
        normalized.append(stripped)
    return sorted(set(normalized))


def _redact_dns_error(exc: BaseException) -> str:
    message = str(exc).strip()
    compact = message.replace("\n", " ")
    if len(compact) > 120:
        compact = compact[:117] + "..."
    if compact:
        return f"{exc.__class__.__name__}: {compact}"
    return exc.__class__.__name__


def _resolve_dns(hostname: str, record_type: str) -> tuple[str, list[str], str | None]:
    family = socket.AF_INET if record_type == "A" else socket.AF_INET6
    try:
        addrinfo = socket.getaddrinfo(hostname, None, family=family, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        error_code = exc.args[0] if exc.args else None
        not_found_codes = {socket.EAI_NONAME}
        nodata = getattr(socket, "EAI_NODATA", None)
        if nodata is not None:
            not_found_codes.add(nodata)
        if error_code in not_found_codes:
            return "not_found", [], None
        return "error", [], _redact_dns_error(exc)
    except OSError as exc:
        return "error", [], _redact_dns_error(exc)

    observed: list[str] = []
    for entry in addrinfo:
        sockaddr = entry[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            continue
        ip_raw = sockaddr[0]
        if isinstance(ip_raw, str):
            observed.append(ip_raw)
    deduped = _normalize_ip_values(observed)
    if not deduped:
        return "not_found", [], None
    return "ok", deduped, None


def _run_dns_gate(
    runbook_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    checks_raw = runbook_plan.get("dns_checks")
    runbook_id = runbook_plan["runbook_id"]
    source_ref = "local DNS truth"
    steps: list[dict[str, Any]] = []
    step_traces: list[dict[str, Any]] = []

    if not isinstance(checks_raw, list) or len(checks_raw) == 0:
        step_id = "step-dns-no-checks"
        t0 = _utc_now()
        t1 = _utc_now()
        label = "DNS check set is missing or empty (reason_code=dns_no_checks)."
        steps.append({"step_id": step_id, "label": label, "status": "inconclusive", "source_ref": source_ref})
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id),
            "runbook_ref": runbook_id,
            "step_id": step_id,
            "operation": "steuerboard.runbooks._run_dns_gate",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": "inconclusive",
            "redaction_verified": True,
        })
        short = (
            "DNS-gate inconclusive. No dns_checks were available for evaluation. "
            "No mutation and no action authorisation occurred."
        )
        return steps, step_traces, "inconclusive", short

    required_statuses: list[str] = []
    blocked_required_ids: list[str] = []
    inconclusive_required_ids: list[str] = []
    passed_required_ids: list[str] = []

    for index, check in enumerate(checks_raw):
        step_id = f"step-dns-check-{index + 1:03d}"
        t0 = _utc_now()
        status = "inconclusive"
        reason_code = "dns_resolution_error"
        check_id = f"dns-check-{index + 1}"
        hostname = ""
        record_type = ""
        expected_values_norm: list[str] = []
        observed_values: list[str] = []
        required_flag = False
        error_note = ""

        if isinstance(check, dict):
            check_id_raw = check.get("check_id")
            if isinstance(check_id_raw, str) and check_id_raw.strip():
                check_id = check_id_raw.strip()
            hostname_raw = check.get("hostname")
            if isinstance(hostname_raw, str):
                hostname = hostname_raw.strip()
            record_type_raw = check.get("record_type")
            if isinstance(record_type_raw, str):
                record_type = record_type_raw.strip()
            required_flag = bool(check.get("required") is True)
            expected_raw = check.get("expected_values")
            if isinstance(expected_raw, list):
                expected_values_norm = _normalize_ip_values(
                    [item for item in expected_raw if isinstance(item, str)]
                )

        if record_type not in {"A", "AAAA"}:
            status = "inconclusive"
            reason_code = "dns_unsupported_record_type"
        elif not hostname or not expected_values_norm:
            status = "inconclusive"
            reason_code = "dns_resolution_error"
        else:
            resolve_status, observed_values, error_note = _resolve_dns(hostname, record_type)
            if resolve_status == "ok":
                if observed_values == expected_values_norm:
                    status = "passed"
                    reason_code = "dns_expected_values_matched"
                else:
                    status = "blocked"
                    reason_code = "dns_expected_values_mismatch"
            elif resolve_status == "not_found":
                status = "blocked"
                reason_code = "dns_name_not_resolved"
            else:
                status = "inconclusive"
                reason_code = "dns_resolution_error"

        label = (
            f"DNS check {check_id!r}: hostname={hostname!r}, record_type={record_type!r}, "
            f"expected_values={expected_values_norm!r}, observed_values={observed_values!r}, "
            f"required={required_flag!r}, reason_code={reason_code}"
        )
        if error_note:
            label = f"{label}, error={error_note!r}"

        t1 = _utc_now()
        steps.append({"step_id": step_id, "label": label, "status": status, "source_ref": source_ref})
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id),
            "runbook_ref": runbook_id,
            "step_id": step_id,
            "operation": "steuerboard.runbooks._resolve_dns",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": status,
            "redaction_verified": True,
        })

        if required_flag:
            required_statuses.append(status)
            if status == "passed":
                passed_required_ids.append(check_id)
            elif status == "blocked":
                blocked_required_ids.append(check_id)
            else:
                inconclusive_required_ids.append(check_id)

    if not required_statuses:
        overall_status = "inconclusive"
    elif "inconclusive" in required_statuses:
        overall_status = "inconclusive"
    elif "blocked" in required_statuses:
        overall_status = "blocked"
    else:
        overall_status = "passed"

    if overall_status == "passed":
        short_assessment = (
            f"DNS-gate passed. Required checks passed={passed_required_ids!r}. "
            "This is a local resolver diagnosis at check time, not global DNS truth."
        )
    elif overall_status == "blocked":
        short_assessment = (
            f"DNS-gate blocked. Required checks blocked={blocked_required_ids!r}. "
            "Observed DNS responses did not match expected values."
        )
    else:
        short_assessment = (
            f"DNS-gate inconclusive. Required checks inconclusive={inconclusive_required_ids!r}. "
            "Resolver evidence was incomplete or unavailable for a reliable verdict."
        )

    return steps, step_traces, overall_status, short_assessment


# ---------------------------------------------------------------------------
# SSH-gate TCP check (read_only — no ssh, no subprocess, no shell)
# ---------------------------------------------------------------------------

def _redact_network_error(exc: BaseException) -> str:
    message = str(exc).strip()
    compact = message.replace("\n", " ")
    if len(compact) > 120:
        compact = compact[:117] + "..."
    if compact:
        return f"{exc.__class__.__name__}: {compact}"
    return exc.__class__.__name__


def _classify_tcp_os_error(exc: OSError) -> tuple[str, str]:
    """Classify an OSError from socket.create_connection into blocked or inconclusive.

    Known network-unreachability errno codes map to blocked.
    Ambiguous or local-socket errors map to inconclusive.
    """
    import errno as _errno

    BLOCKED_ERRNOS = {
        getattr(_errno, "ECONNREFUSED", None),
        getattr(_errno, "ETIMEDOUT", None),
        getattr(_errno, "ENETUNREACH", None),
        getattr(_errno, "EHOSTUNREACH", None),
        getattr(_errno, "ENETDOWN", None),
        getattr(_errno, "EHOSTDOWN", None),
    }
    BLOCKED_ERRNOS.discard(None)

    code = exc.errno
    if code is not None and code in BLOCKED_ERRNOS:
        return "blocked", _redact_network_error(exc)
    return "inconclusive", _redact_network_error(exc)


def _check_tcp_connectivity(host: str, port: int, timeout_seconds: float) -> tuple[str, str | None]:
    """Attempt a TCP connection to (host, port) and return (status, error_note).

    Status values:
    - "ok"           — connection established and closed cleanly
    - "blocked"      — connection refused, timed out, or host/network unreachable
    - "inconclusive" — local socket error that cannot be classified as reachability failure
    """
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return "ok", None
    except TimeoutError as exc:
        return "blocked", _redact_network_error(exc)
    except ConnectionRefusedError as exc:
        return "blocked", _redact_network_error(exc)
    except socket.timeout as exc:
        return "blocked", _redact_network_error(exc)
    except socket.gaierror as exc:
        code = exc.args[0] if exc.args else None
        if code in {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", None)}:
            return "blocked", _redact_network_error(exc)
        return "inconclusive", _redact_network_error(exc)
    except OSError as exc:
        return _classify_tcp_os_error(exc)


def _ip_matches_expected_prefixes(ip: str, prefixes: list[str]) -> tuple[bool, str | None]:
    """Check whether an IP matches any configured CIDR prefix."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False, None
    for prefix in prefixes:
        try:
            network = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            return False, prefix
        if addr in network:
            return True, None
    return False, None


def _resolve_host_for_tailscale(host: str) -> tuple[str, list[str], str | None]:
    """Resolve a host for tailscale-preflight checks."""
    try:
        addrinfo = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        error_code = exc.args[0] if exc.args else None
        not_found_codes = {socket.EAI_NONAME}
        nodata = getattr(socket, "EAI_NODATA", None)
        if nodata is not None:
            not_found_codes.add(nodata)
        if error_code in not_found_codes:
            return "not_found", [], None
        return "error", [], _redact_dns_error(exc)
    except OSError as exc:
        return "error", [], _redact_dns_error(exc)

    observed: list[str] = []
    for entry in addrinfo:
        sockaddr = entry[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            continue
        ip_raw = sockaddr[0]
        if isinstance(ip_raw, str):
            observed.append(ip_raw)
    deduped = _normalize_ip_values(observed)
    if not deduped:
        return "not_found", [], None
    return "ok", deduped, None


def _run_tailscale_preflight(
    runbook_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    """Evaluate tailscale_checks via local overlay resolution and optional TCP probes."""
    checks_raw = runbook_plan.get("tailscale_checks")
    runbook_id = runbook_plan["runbook_id"]
    source_ref = "local overlay reachability"
    steps: list[dict[str, Any]] = []
    step_traces: list[dict[str, Any]] = []

    if not isinstance(checks_raw, list) or len(checks_raw) == 0:
        step_id = "step-tailscale-no-checks"
        t0 = _utc_now()
        t1 = _utc_now()
        label = "Tailscale-preflight check set is missing or empty (reason_code=tailscale_no_checks)."
        steps.append({"step_id": step_id, "label": label, "status": "inconclusive", "source_ref": source_ref})
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id),
            "runbook_ref": runbook_id,
            "step_id": step_id,
            "operation": "steuerboard.runbooks._run_tailscale_preflight",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": "inconclusive",
            "redaction_verified": True,
        })
        short = (
            "Tailscale-preflight inconclusive. No tailscale_checks were available for evaluation. "
            "No mutation and no action authorisation occurred."
        )
        return steps, step_traces, "inconclusive", short

    required_statuses: list[str] = []
    blocked_required_ids: list[str] = []
    inconclusive_required_ids: list[str] = []
    passed_required_ids: list[str] = []

    for index, check in enumerate(checks_raw):
        step_id = f"step-tailscale-check-{index + 1:03d}"
        t0 = _utc_now()
        status = "inconclusive"
        reason_code = "tailscale_invalid_check"
        check_id = f"tailscale-check-{index + 1}"
        host = ""
        required_flag = False
        error_note: str | None = None
        observed_ips: list[str] = []

        if not isinstance(check, dict):
            label = (
                f"Tailscale-preflight check {check_id!r}: invalid check entry (not a dict), "
                f"reason_code={reason_code}"
            )
            t1 = _utc_now()
            steps.append({"step_id": step_id, "label": label, "status": status, "source_ref": source_ref})
            step_traces.append({
                "schema_version": "runbook-step-trace.v1",
                "trace_id": _trace_id(step_id),
                "runbook_ref": runbook_id,
                "step_id": step_id,
                "operation": "steuerboard.runbooks._run_tailscale_preflight",
                "capability_class": "read_only",
                "started_at": t0,
                "finished_at": t1,
                "status": status,
                "redaction_verified": True,
            })
            continue

        check_id_raw = check.get("check_id")
        if isinstance(check_id_raw, str) and check_id_raw.strip():
            check_id = check_id_raw.strip()
        host_raw = check.get("host")
        if isinstance(host_raw, str):
            host = host_raw.strip()
        required_flag = bool(check.get("required") is True)
        expected_prefixes_raw = check.get("expected_ip_prefixes")
        expected_prefixes: list[str] = []
        invalid_expected_prefixes: list[str] = []
        if isinstance(expected_prefixes_raw, list):
            for p in expected_prefixes_raw:
                if not isinstance(p, str):
                    invalid_expected_prefixes.append(repr(p))
                    continue
                stripped = p.strip()
                if not stripped:
                    invalid_expected_prefixes.append(repr(p))
                    continue
                try:
                    ipaddress.ip_network(stripped, strict=False)
                    expected_prefixes.append(stripped)
                except ValueError:
                    invalid_expected_prefixes.append(stripped)
        expected_values_raw = check.get("expected_ip_values")
        expected_values_norm: list[str] = []
        invalid_expected_values: list[str] = []
        if isinstance(expected_values_raw, list):
            for value in expected_values_raw:
                if not isinstance(value, str):
                    invalid_expected_values.append(repr(value))
                    continue
                stripped = value.strip()
                if not stripped:
                    invalid_expected_values.append(repr(value))
                    continue
                try:
                    expected_values_norm.append(str(ipaddress.ip_address(stripped)))
                except ValueError:
                    invalid_expected_values.append(stripped)
            expected_values_norm = sorted(set(expected_values_norm))
        port_raw = check.get("port")
        port: int | None = None
        if isinstance(port_raw, int) and 1 <= port_raw <= 65535:
            port = port_raw
        timeout_seconds = 2.0
        timeout_raw = check.get("timeout_seconds")
        if isinstance(timeout_raw, (int, float)):
            timeout_seconds = float(timeout_raw)

        if invalid_expected_prefixes:
            status = "inconclusive"
            reason_code = "tailscale_invalid_prefix"
            error_note = f"invalid expected_ip_prefixes: {sorted(set(invalid_expected_prefixes))!r}"
        elif invalid_expected_values:
            status = "inconclusive"
            reason_code = "tailscale_invalid_expected_ip_values"
            error_note = f"invalid expected_ip_values: {sorted(set(invalid_expected_values))!r}"
        elif not host:
            status = "inconclusive"
            reason_code = "tailscale_invalid_check"
        else:
            resolve_status, observed_ips, error_note = _resolve_host_for_tailscale(host)
            if resolve_status == "not_found":
                status = "blocked"
                reason_code = "tailscale_resolution_failed"
            elif resolve_status == "error":
                status = "inconclusive"
                reason_code = "tailscale_resolution_failed"
            else:
                status = "passed"
                reason_code = "tailscale_resolution_succeeded"

                if expected_values_norm:
                    observed_norm = _normalize_ip_values(observed_ips)
                    matched_values = [ip for ip in observed_norm if ip in expected_values_norm]
                    if matched_values:
                        status = "passed"
                        reason_code = "tailscale_expected_ip_matched"
                    else:
                        status = "blocked"
                        reason_code = "tailscale_expected_ip_mismatch"

                if expected_prefixes and status != "blocked":
                    observed_norm = _normalize_ip_values(observed_ips)
                    prefix_match = False
                    invalid_prefix = None
                    for ip in observed_norm:
                        matched, bad_prefix = _ip_matches_expected_prefixes(ip, expected_prefixes)
                        if bad_prefix is not None:
                            invalid_prefix = bad_prefix
                            break
                        if matched:
                            prefix_match = True
                            break
                    if invalid_prefix is not None:
                        status = "inconclusive"
                        reason_code = "tailscale_invalid_prefix"
                        error_note = f"invalid prefix: {invalid_prefix!r}"
                    elif prefix_match:
                        status = "passed"
                        reason_code = "tailscale_expected_prefix_matched"
                    else:
                        status = "blocked"
                        reason_code = "tailscale_expected_prefix_mismatch"

                if port is not None and status == "passed":
                    tcp_status, tcp_error = _check_tcp_connectivity(host, port, timeout_seconds)
                    if tcp_status == "ok":
                        status = "passed"
                        reason_code = "tailscale_tcp_connect_succeeded"
                    elif tcp_status == "blocked":
                        status = "blocked"
                        reason_code = "tailscale_tcp_connect_failed"
                        error_note = tcp_error
                    else:
                        status = "inconclusive"
                        reason_code = "tailscale_tcp_connect_inconclusive"
                        error_note = tcp_error

        label = (
            f"Tailscale-preflight check {check_id!r}: host={host!r}, "
            f"observed_ips={observed_ips!r}, expected_ip_prefixes={expected_prefixes!r}, "
            f"expected_ip_values={expected_values_norm!r}, port={port!r}, timeout_seconds={timeout_seconds!r}, "
            f"required={required_flag!r}, reason_code={reason_code}"
        )
        if error_note:
            label = f"{label}, error={error_note!r}"

        t1 = _utc_now()
        steps.append({"step_id": step_id, "label": label, "status": status, "source_ref": source_ref})
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id),
            "runbook_ref": runbook_id,
            "step_id": step_id,
            "operation": "steuerboard.runbooks._run_tailscale_preflight",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": status,
            "redaction_verified": True,
        })

        if required_flag:
            required_statuses.append(status)
            if status == "passed":
                passed_required_ids.append(check_id)
            elif status == "blocked":
                blocked_required_ids.append(check_id)
            else:
                inconclusive_required_ids.append(check_id)

    if not required_statuses:
        overall_status = "inconclusive"
    elif "inconclusive" in required_statuses:
        overall_status = "inconclusive"
    elif "blocked" in required_statuses:
        overall_status = "blocked"
    else:
        overall_status = "passed"

    if overall_status == "passed":
        short_assessment = (
            f"Tailscale-preflight passed. Required checks passed={passed_required_ids!r}. "
            "This is local overlay reachability at check time, not proof that Tailscale is correctly authenticated or configured."
        )
    elif overall_status == "blocked":
        short_assessment = (
            f"Tailscale-preflight blocked. Required checks blocked={blocked_required_ids!r}. "
            "One or more configured overlay targets were not locally reachable or resolvable."
        )
    else:
        short_assessment = (
            f"Tailscale-preflight inconclusive. Required checks inconclusive={inconclusive_required_ids!r}. "
            "Local overlay reachability evidence was incomplete or indeterminate."
        )

    return steps, step_traces, overall_status, short_assessment


def _run_ssh_gate(
    runbook_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    """Evaluate ssh_checks from the runbook plan via TCP-only reachability probes.

    No SSH subprocess, no authentication, no remote commands, no key access.
    """
    checks_raw = runbook_plan.get("ssh_checks")
    runbook_id = runbook_plan["runbook_id"]
    source_ref = "local TCP reachability"
    steps: list[dict[str, Any]] = []
    step_traces: list[dict[str, Any]] = []

    if not isinstance(checks_raw, list) or len(checks_raw) == 0:
        step_id = "step-ssh-no-checks"
        t0 = _utc_now()
        t1 = _utc_now()
        label = "SSH check set is missing or empty (reason_code=ssh_no_checks)."
        steps.append({"step_id": step_id, "label": label, "status": "inconclusive", "source_ref": source_ref})
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id),
            "runbook_ref": runbook_id,
            "step_id": step_id,
            "operation": "steuerboard.runbooks._run_ssh_gate",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": "inconclusive",
            "redaction_verified": True,
        })
        short = (
            "SSH-gate inconclusive. No ssh_checks were available for evaluation. "
            "No mutation and no action authorisation occurred."
        )
        return steps, step_traces, "inconclusive", short

    required_statuses: list[str] = []
    blocked_required_ids: list[str] = []
    inconclusive_required_ids: list[str] = []
    passed_required_ids: list[str] = []

    for index, check in enumerate(checks_raw):
        step_id = f"step-ssh-check-{index + 1:03d}"
        t0 = _utc_now()
        status = "inconclusive"
        reason_code = "ssh_invalid_check"
        check_id = f"ssh-check-{index + 1}"
        host = ""
        port = 0
        timeout_seconds = 2.0
        required_flag = False
        error_note: str | None = None

        if not isinstance(check, dict):
            label = (
                f"SSH check {check_id!r}: invalid check entry (not a dict), "
                f"reason_code={reason_code}"
            )
            t1 = _utc_now()
            steps.append({"step_id": step_id, "label": label, "status": status, "source_ref": source_ref})
            step_traces.append({
                "schema_version": "runbook-step-trace.v1",
                "trace_id": _trace_id(step_id),
                "runbook_ref": runbook_id,
                "step_id": step_id,
                "operation": "steuerboard.runbooks._check_tcp_connectivity",
                "capability_class": "read_only",
                "started_at": t0,
                "finished_at": t1,
                "status": status,
                "redaction_verified": True,
            })
            # Non-dict checks never count as required — treat as inconclusive non-required
            continue

        check_id_raw = check.get("check_id")
        if isinstance(check_id_raw, str) and check_id_raw.strip():
            check_id = check_id_raw.strip()
        host_raw = check.get("host")
        if isinstance(host_raw, str):
            host = host_raw.strip()
        port_raw = check.get("port")
        if isinstance(port_raw, int):
            port = port_raw
        timeout_raw = check.get("timeout_seconds")
        if isinstance(timeout_raw, (int, float)):
            timeout_seconds = float(timeout_raw)
        required_flag = bool(check.get("required") is True)

        if not host or not isinstance(port_raw, int) or port < 1 or port > 65535:
            status = "inconclusive"
            reason_code = "ssh_invalid_check"
        else:
            tcp_status, error_note = _check_tcp_connectivity(host, port, timeout_seconds)
            if tcp_status == "ok":
                status = "passed"
                reason_code = "ssh_tcp_connect_succeeded"
            elif tcp_status == "blocked":
                status = "blocked"
                reason_code = "ssh_tcp_connect_failed"
            else:
                status = "inconclusive"
                reason_code = "ssh_tcp_connect_inconclusive"

        label = (
            f"SSH check {check_id!r}: host={host!r}, port={port!r}, "
            f"timeout_seconds={timeout_seconds!r}, required={required_flag!r}, "
            f"reason_code={reason_code}"
        )
        if error_note:
            label = f"{label}, error={error_note!r}"

        t1 = _utc_now()
        steps.append({"step_id": step_id, "label": label, "status": status, "source_ref": source_ref})
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id),
            "runbook_ref": runbook_id,
            "step_id": step_id,
            "operation": "steuerboard.runbooks._check_tcp_connectivity",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": status,
            "redaction_verified": True,
        })

        if required_flag:
            required_statuses.append(status)
            if status == "passed":
                passed_required_ids.append(check_id)
            elif status == "blocked":
                blocked_required_ids.append(check_id)
            else:
                inconclusive_required_ids.append(check_id)

    if not required_statuses:
        overall_status = "inconclusive"
    elif "inconclusive" in required_statuses:
        overall_status = "inconclusive"
    elif "blocked" in required_statuses:
        overall_status = "blocked"
    else:
        overall_status = "passed"

    if overall_status == "passed":
        short_assessment = (
            f"SSH-gate passed. Required checks passed={passed_required_ids!r}. "
            "This is local TCP reachability at check time, not proof of SSH login success."
        )
    elif overall_status == "blocked":
        short_assessment = (
            f"SSH-gate blocked. Required checks blocked={blocked_required_ids!r}. "
            "One or more configured SSH endpoints were not reachable."
        )
    else:
        short_assessment = (
            f"SSH-gate inconclusive. Required checks inconclusive={inconclusive_required_ids!r}. "
            "TCP reachability evidence was incomplete or locally indeterminate."
        )

    return steps, step_traces, overall_status, short_assessment


# ---------------------------------------------------------------------------
# Server-facts Snapshot (read_only — no subprocess, no shell, no network)
# ---------------------------------------------------------------------------

import platform as _platform
import sys as _sys


def _facts_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%fZ")
    entropy = time_ns()
    digest = hashlib.sha256(f"server-facts:{now}:{entropy}".encode("utf-8")).hexdigest()[:12]
    return f"server-facts-{now}-{digest}"


def _collect_server_facts(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect read-only host and runtime facts.

    All data is obtained via Python stdlib only — no subprocess, no shell,
    no network probes, no service manager interaction.
    """
    if options is None:
        options = {}
    include_fqdn = options.get("include_fqdn", True)
    include_process_context = options.get("include_process_context", True)

    hostname_raw = _platform.node()
    fqdn: str | None = None
    if include_fqdn:
        try:
            fqdn = socket.getfqdn()
        except Exception:  # noqa: BLE001
            fqdn = None

    try:
        uid = os.getuid()
    except AttributeError:
        uid = None
    try:
        gid = os.getgid()
    except AttributeError:
        gid = None

    return {
        "schema_version": "server-facts.v1",
        "facts_id": _facts_id(),
        "generated_at": _utc_now(),
        "collector": {
            "name": "steuerboard.server_facts",
            "version": "1.0.0",
        },
        "host": {
            "hostname": hostname_raw,
            "fqdn": fqdn,
            "platform_system": _platform.system(),
            "platform_release": _platform.release(),
            "platform_version": _platform.version(),
            "machine": _platform.machine(),
            "processor": _platform.processor(),
        },
        "runtime": {
            "python_version": _sys.version,
            "executable_basename": os.path.basename(_sys.executable) if _sys.executable else None,
        },
        "process_context": {
            "cwd_basename": os.path.basename(os.getcwd()) if include_process_context else None,
            "uid": uid if include_process_context else None,
            "gid": gid if include_process_context else None,
            "is_root": (uid == 0) if (include_process_context and uid is not None) else False,
        },
        "boundaries": {
            "read_only": True,
            "used_subprocess": False,
            "used_shell": False,
            "used_network_probe": False,
            "used_service_manager": False,
            "included_environment": False,
            "included_secrets": False,
        },
        "warnings": [],
        "notes": ["server-facts v1 snapshot — read-only host and runtime observation"],
    }


def _run_server_facts_snapshot(
    runbook_plan: dict[str, Any],
    server_facts_out: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str, Path | None]:
    """Execute a server-facts-snapshot runbook and return steps, traces, status, assessment, and facts_path.

    Parameters
    ----------
    runbook_plan:
        Parsed runbook-plan.v1 dict.
    server_facts_out:
        Output path for server-facts.v1 JSON. Must not exist. Parent must exist.

    Returns
    -------
    tuple of (steps, step_traces, overall_status, short_assessment, facts_path_or_None)
    """
    runbook_id = runbook_plan["runbook_id"]
    source_ref = "server-facts.v1"
    steps: list[dict[str, Any]] = []
    step_traces: list[dict[str, Any]] = []
    options = runbook_plan.get("server_facts_options")

    # Step 1: Collect facts
    step_id_collect = "step-server-facts-collect"
    t0 = _utc_now()
    facts: dict[str, Any] = {}
    collect_status = "passed"
    collect_reason = "server_facts_snapshot_written"
    try:
        facts = _collect_server_facts(options)
    except Exception as exc:  # noqa: BLE001
        collect_status = "inconclusive"
        collect_reason = "server_facts_snapshot_inconclusive"
        label = f"Server-facts collection failed: {exc!r}, reason_code={collect_reason}"
        t1 = _utc_now()
        steps.append({"step_id": step_id_collect, "label": label, "status": "inconclusive", "source_ref": source_ref})
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_collect),
            "runbook_ref": runbook_id,
            "step_id": step_id_collect,
            "operation": "steuerboard.runbooks._collect_server_facts",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": "inconclusive",
            "redaction_verified": True,
        })
        short = (
            "Server-facts snapshot inconclusive. Facts collection failed. "
            "Result written with inconclusive status."
        )
        return steps, step_traces, "inconclusive", short, None

    t1 = _utc_now()
    steps.append({"step_id": step_id_collect, "label": "Collect host and runtime facts", "status": "passed", "source_ref": source_ref})
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_collect),
        "runbook_ref": runbook_id,
        "step_id": step_id_collect,
        "operation": "steuerboard.runbooks._collect_server_facts",
        "capability_class": "read_only",
        "started_at": t0,
        "finished_at": t1,
        "status": "passed",
        "redaction_verified": True,
    })

    # Step 2: Write server-facts.json
    step_id_write = "step-server-facts-write"
    t0 = _utc_now()
    write_status = "passed"
    write_reason = "server_facts_snapshot_written"
    tmp_path: Path | None = None
    try:
        # Validate facts against schema
        try:
            jsonschema_validate(facts, _get_server_facts_schema())
        except (SchemaValidationError, Exception) as exc:
            write_status = "inconclusive"
            write_reason = "server_facts_schema_invalid"
            raise ValueError(f"server-facts schema validation failed: {exc}") from exc

        # Atomic write to server_facts_out
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json.tmp",
            dir=server_facts_out.parent,
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(json.dumps(facts, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp_path, server_facts_out)
        tmp_path = None
    except Exception as exc:  # noqa: BLE001
        write_status = "inconclusive"
        write_reason = "server_facts_write_failed"
        label = f"Server-facts write failed: {exc!r}, reason_code={write_reason}"
        t1 = _utc_now()
        steps.append({"step_id": step_id_write, "label": label, "status": "inconclusive", "source_ref": source_ref})
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_write),
            "runbook_ref": runbook_id,
            "step_id": step_id_write,
            "operation": "steuerboard.runbooks._run_server_facts_snapshot",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": "inconclusive",
            "redaction_verified": True,
        })
        # Clean up tmp if leftover
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

        overall_status = _derive_overall_status(steps)
        warnings_count = len(facts.get("warnings", [])) if facts else 0
        short = (
            f"Server-facts snapshot inconclusive. "
            f"Schema validation or write failed (reason_code={write_reason}). "
            f"Warnings: {warnings_count}."
        )
        return steps, step_traces, overall_status, short, None

    t1 = _utc_now()
    steps.append({"step_id": step_id_write, "label": "Write server-facts.json artefact", "status": "passed", "source_ref": source_ref})
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_write),
        "runbook_ref": runbook_id,
        "step_id": step_id_write,
        "operation": "steuerboard.runbooks._run_server_facts_snapshot",
        "capability_class": "read_only",
        "started_at": t0,
        "finished_at": t1,
        "status": "passed",
        "redaction_verified": True,
    })

    # Step 3: Result
    step_id_result = "step-server-facts-result"
    t0 = _utc_now()
    t1 = _utc_now()
    steps.append({"step_id": step_id_result, "label": "Derive runbook result", "status": "passed", "source_ref": source_ref})
    step_traces.append({
        "schema_version": "runbook-step-trace.v1",
        "trace_id": _trace_id(step_id_result),
        "runbook_ref": runbook_id,
        "step_id": step_id_result,
        "operation": "steuerboard.runbooks.run_runbook",
        "capability_class": "read_only",
        "started_at": t0,
        "finished_at": t1,
        "status": "passed",
        "redaction_verified": True,
    })

    overall_status = _derive_overall_status(steps)
    warnings_count = len(facts.get("warnings", [])) if facts else 0
    short = (
        f"Server-facts snapshot generated: {server_facts_out.name} is schema-valid, "
        f"{warnings_count} warnings."
    )

    return steps, step_traces, overall_status, short, server_facts_out


def run_runbook(
    runbook_plan: dict[str, Any],
    result_out: str,
    command_trace_out: str,
) -> dict[str, Any]:
    """Execute a read-only runbook and write result + trace artifacts.

    Parameters
    ----------
    runbook_plan:
        Parsed runbook-plan.v1 dict. Must be schema-valid.
    result_out:
        Output path for runbook-result.v1 JSON. Must not exist. Parent must exist.
    command_trace_out:
        Output path for runbook-step-trace.v1 JSONL. Must not exist. Parent must exist.

    Returns
    -------
    dict
        The runbook-result.v1 artifact.

    Raises
    ------
    ValueError
        On any precondition failure (invalid plan, wrong kind, mode, path conflict).
        No output files are written on precondition failure.
    """
    # --- Resolve and validate output paths first (precondition, no writes yet) ---
    result_path = _require_output_path(result_out, "result_out")
    trace_path = _require_output_path(command_trace_out, "command_trace_out")

    # --- Validate plan schema, kind, mode, path distinctness ---
    _validate_plan_preconditions(runbook_plan, result_path, trace_path)
    runbook_kind = runbook_plan["runbook_kind"]
    if runbook_kind == "repo-sync-gate":
        repo_worktree_root = _resolve_repo_worktree_root(str(runbook_plan["repo_path"]))
    else:
        repo_worktree_root = _resolve_git_marker_worktree_root(str(runbook_plan["repo_path"]))
    _ensure_outputs_outside_worktree(repo_worktree_root, result_path, trace_path)

    # --- Execution begins here ---
    runbook_id = runbook_plan["runbook_id"]
    repo_path_str = runbook_plan["repo_path"]
    started_at = _utc_now()
    steps: list[dict[str, Any]] = []
    step_traces: list[dict[str, Any]] = []
    facts_path: Path | None = None

    BOUNDARY = {
        "does_not_execute_mutating_actions": True,
        "does_not_mutate": True,
        "does_not_authorise_actions": True,
        "read_only_or_dry_run_only": True,
    }

    if runbook_kind == "repo-sync-gate":
        # --- Step 1: observe_repo (read_only) ---
        step_id_observe = "step-observe-repo"
        t0 = _utc_now()
        observation: dict[str, Any] = {}
        observe_status = "passed"
        try:
            observation = observe_repo(Path(repo_path_str))
        except Exception:  # noqa: BLE001
            observe_status = "inconclusive"
            observation = {
                "observed_state": {},
                "observation_id": "observe-failed",
                "source_refs": [],
            }
        t1 = _utc_now()
        steps.append({
            "step_id": step_id_observe,
            "label": "Observe repository state",
            "status": observe_status,
            "source_ref": "repo-observation.v1",
        })
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_observe),
            "runbook_ref": runbook_id,
            "step_id": step_id_observe,
            "operation": "steuerboard.observation.observe_repo",
            "capability_class": "read_only",
            "started_at": t0,
            "finished_at": t1,
            "status": observe_status,
            "redaction_verified": True,
        })

        # --- Step 2: assess_repo (derivation_only) ---
        step_id_assess = "step-derive-assessment"
        t0 = _utc_now()
        assessment: dict[str, Any] = {}
        assess_status = "passed"
        try:
            assessment = assess_repo(Path(repo_path_str))
        except Exception:  # noqa: BLE001
            assess_status = "inconclusive"
            assessment = {
                "decision_state": "evidence_missing",
                "derived_status": [],
                "missing_evidence": ["observation_failed"],
                "skip_reasons": [],
            }
        t1 = _utc_now()
        steps.append({
            "step_id": step_id_assess,
            "label": "Derive repo assessment",
            "status": assess_status,
            "source_ref": "repo-assessment.v1",
        })
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_assess),
            "runbook_ref": runbook_id,
            "step_id": step_id_assess,
            "operation": "steuerboard.assessment.assess_repo",
            "capability_class": "derivation_only",
            "started_at": t0,
            "finished_at": t1,
            "status": assess_status,
            "redaction_verified": True,
        })

        # --- Step 3: check_is_git_repo (derivation_only) ---
        step_id_isgit = "step-check-is-git-repo"
        t0 = _utc_now()
        isgit_status, _ = check_is_git_repo(observation)
        t1 = _utc_now()
        steps.append({
            "step_id": step_id_isgit,
            "label": "Check: path is a git repository",
            "status": isgit_status,
        })
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_isgit),
            "runbook_ref": runbook_id,
            "step_id": step_id_isgit,
            "operation": "steuerboard.runbooks.check_is_git_repo",
            "capability_class": "derivation_only",
            "started_at": t0,
            "finished_at": t1,
            "status": isgit_status,
            "redaction_verified": True,
        })

        # --- Step 4: check_worktree_clean (derivation_only) ---
        step_id_clean = "step-check-worktree-clean"
        t0 = _utc_now()
        clean_status, _ = check_worktree_clean(observation)
        t1 = _utc_now()
        steps.append({
            "step_id": step_id_clean,
            "label": "Check: worktree is clean",
            "status": clean_status,
        })
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_clean),
            "runbook_ref": runbook_id,
            "step_id": step_id_clean,
            "operation": "steuerboard.runbooks.check_worktree_clean",
            "capability_class": "derivation_only",
            "started_at": t0,
            "finished_at": t1,
            "status": clean_status,
            "redaction_verified": True,
        })

        # --- Step 5: check_not_detached_head (derivation_only) ---
        step_id_head = "step-check-not-detached-head"
        t0 = _utc_now()
        head_status, _ = check_not_detached_head(observation)
        t1 = _utc_now()
        steps.append({
            "step_id": step_id_head,
            "label": "Check: HEAD is not detached",
            "status": head_status,
        })
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_head),
            "runbook_ref": runbook_id,
            "step_id": step_id_head,
            "operation": "steuerboard.runbooks.check_not_detached_head",
            "capability_class": "derivation_only",
            "started_at": t0,
            "finished_at": t1,
            "status": head_status,
            "redaction_verified": True,
        })

        # --- Step 6: check_on_default_branch (derivation_only) ---
        step_id_branch = "step-check-on-default-branch"
        t0 = _utc_now()
        branch_status, _ = check_on_default_branch(observation)
        t1 = _utc_now()
        steps.append({
            "step_id": step_id_branch,
            "label": "Check: current branch is default branch candidate",
            "status": branch_status,
        })
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_branch),
            "runbook_ref": runbook_id,
            "step_id": step_id_branch,
            "operation": "steuerboard.runbooks.check_on_default_branch",
            "capability_class": "derivation_only",
            "started_at": t0,
            "finished_at": t1,
            "status": branch_status,
            "redaction_verified": True,
        })

        # --- Step 7: check_decision_state (derivation_only) ---
        step_id_decision = "step-check-decision-state"
        t0 = _utc_now()
        decision_status, _ = check_decision_state(assessment)
        t1 = _utc_now()
        steps.append({
            "step_id": step_id_decision,
            "label": "Check: assessment decision_state is not action_blocked",
            "status": decision_status,
        })
        step_traces.append({
            "schema_version": "runbook-step-trace.v1",
            "trace_id": _trace_id(step_id_decision),
            "runbook_ref": runbook_id,
            "step_id": step_id_decision,
            "operation": "steuerboard.runbooks.check_decision_state",
            "capability_class": "derivation_only",
            "started_at": t0,
            "finished_at": t1,
            "status": decision_status,
            "redaction_verified": True,
        })

        # --- Derive overall status ---
        overall_status = _derive_overall_status(steps)

        # --- Build short assessment ---
        short_assessment = _build_repo_sync_short_assessment(overall_status, steps, assessment)

        # --- Merge source_refs from plan, observation, and assessment ---
        all_source_refs = _merge_source_refs(
            runbook_plan.get("source_refs", []),
            observation.get("source_refs", []),
            assessment.get("source_refs", []),
        )
    elif runbook_kind == "dns-gate":
        steps, step_traces, overall_status, short_assessment = _run_dns_gate(
            runbook_plan=runbook_plan,
        )
        all_source_refs = _merge_source_refs(
            runbook_plan.get("source_refs", []),
            ["local DNS truth"],
        )
    elif runbook_kind == "ssh-gate":
        steps, step_traces, overall_status, short_assessment = _run_ssh_gate(
            runbook_plan=runbook_plan,
        )
        all_source_refs = _merge_source_refs(
            runbook_plan.get("source_refs", []),
            ["local TCP reachability"],
        )
    elif runbook_kind == "tailscale-preflight":
        steps, step_traces, overall_status, short_assessment = _run_tailscale_preflight(
            runbook_plan=runbook_plan,
        )
        all_source_refs = _merge_source_refs(
            runbook_plan.get("source_refs", []),
            ["local overlay reachability"],
        )
    elif runbook_kind == "server-facts-snapshot":
        server_facts_out = trace_path.parent / "server-facts.json"
        steps, step_traces, overall_status, short_assessment, facts_path = _run_server_facts_snapshot(
            runbook_plan=runbook_plan,
            server_facts_out=server_facts_out,
        )
        all_source_refs = _merge_source_refs(
            runbook_plan.get("source_refs", []),
            ["server-facts.v1"],
        )
    else:  # pragma: no cover - schema/preconditions already guard this path
        raise ValueError(f"unsupported runbook_kind {runbook_kind!r}")

    finished_at = _utc_now()

    # --- Build runbook-result.v1 ---
    evidence_paths: list[str] = [str(trace_path)]
    if runbook_kind == "server-facts-snapshot" and facts_path is not None:
        evidence_paths.append(str(facts_path))
    result: dict[str, Any] = {
        "schema_version": "runbook-result.v1",
        "result_id": _result_id(),
        "runbook_ref": runbook_id,
        "runbook_kind": runbook_kind,
        "status": overall_status,
        "started_at": started_at,
        "finished_at": finished_at,
        "repo_path": repo_path_str,
        "short_assessment": short_assessment,
        "steps": steps,
        "evidence_paths": evidence_paths,
        "source_refs": all_source_refs,
        "redaction_verified": True,
        "boundary": BOUNDARY,
    }

    # --- Atomic write: temp files -> os.replace ---
    trace_tmp_path: Path | None = None
    result_tmp_path: Path | None = None
    committed_targets: list[Path] = []
    try:
        # Write trace JSONL to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".jsonl.tmp",
            dir=trace_path.parent,
            delete=False,
        ) as trace_tmp:
            trace_tmp_path = Path(trace_tmp.name)
            for entry in step_traces:
                _validate_step_trace(entry)
                trace_tmp.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

        # Validate result before writing
        _validate_result(result)

        # Write result JSON to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json.tmp",
            dir=result_path.parent,
            delete=False,
        ) as result_tmp:
            result_tmp_path = Path(result_tmp.name)
            result_tmp.write(
                json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            )

        # Commit atomically; track each committed target so we can roll back on
        # partial failure (e.g. second os.replace fails after first succeeds).
        os.replace(trace_tmp_path, trace_path)
        trace_tmp_path = None
        committed_targets.append(trace_path)
        os.replace(result_tmp_path, result_path)
        result_tmp_path = None
        committed_targets.append(result_path)

    except Exception:
        # Clean up temp files that were never promoted.
        for tmp in (trace_tmp_path, result_tmp_path):
            if tmp is not None and tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        # Clean up any already-committed target files so no partial output
        # remains on disk when the overall operation fails.
        for target in committed_targets:
            try:
                os.unlink(target)
            except OSError:
                pass
        raise

    return result
