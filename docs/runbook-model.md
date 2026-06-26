# Runbook Model

## Purpose

Phases 11A through 11E and 11F-K introduce read-only runbooks: repeatable local check sequences over existing steuerboard artifacts and read-only/derivation-only functions.

A runbook is an operational checklist, not an action executor.

## Architecture rule

Observation != Derivation != Decision != Action

A runbook may sequence observations and derivations. It must not collapse them into action.

## Authority model

A runbook result is derived diagnostic material.
It is not canonical repository state.
It is not an approval.
It is not permission to execute.
It is not a substitute for Stage-D readiness/approval gates.

## Phase 11 scope

Phase 11A status: implemented.
- repo-sync-gate

Phase 11B status: implemented.
- dns-gate

Phase 11C status: implemented.
- ssh-gate

Phase 11D status: implemented.
- tailscale-preflight

Phase 11E status: implemented.
- server-facts-snapshot

Phase 11F-K status: implemented.
- heimserver-service-gate

Implemented runbook kinds:
- repo-sync-gate
- dns-gate
- ssh-gate
- tailscale-preflight
- server-facts-snapshot
- heimserver-service-gate

Allowed:
- observe repository state read-only
- derive repo assessment using existing assessment logic
- resolve DNS names via local system resolver for read-only diagnostics
- resolve configured overlay/Tailscale targets via local resolver and optional TCP checks for diagnostics
- emit runbook-result.v1
- emit runbook-step-trace.v1 JSONL
- include evidence paths and short assessment
- collect a read-only host/runtime snapshot and write `server-facts.json` alongside result and trace (server-facts-snapshot only)
- load explicit hash-bound service-gate input artifacts, derive an artifact-only assessment, and write `heimserver-service-gate-assessment.json` alongside result and trace (heimserver-service-gate only)

Forbidden:
- git switch
- git pull
- git fetch
- git reset
- git clean
- git merge
- git rebase
- git push
- branch delete
- shell=True
- subprocess DNS tools as runtime dependency (dig/nslookup/getent)
- free shell
- generic command runner
- Stage-D executor calls
- backend/server/UI trigger

## repo-sync-gate semantics

The runbook answers:
"Is this repository locally in a state where the existing steuerboard sync-related assessment can be understood and evidenced?"

It does not synchronize.
It does not fetch freshness.
It does not switch.
It does not pull.
It checks local diagnosis conditions only.
`passed` means local diagnosis looked unblocked at check time.
`passed` does not prove remote freshness.
`passed` is not permission for pull, switch, or any Stage-D executor.

## dns-gate semantics

The runbook answers:
"Can the local system resolver resolve configured DNS names to the expected values at check time?"

It is local DNS diagnostic material, not global DNS truth.
It does not change resolver configuration and does not restart resolver services.
For dns-gate, `repo_path` is currently a context anchor only; it is not a Git gate precondition.

Status rules:
- `passed`: all required DNS checks were evaluated and matched expected values.
- `blocked`: at least one required DNS check was evaluated and mismatched expected values (including unresolved names).
- `inconclusive`: required DNS checks could not be evaluated reliably (resolver error, unsupported input, or missing checks).

Boundary:
- no DNS configuration mutation
- no subprocess DNS execution path for runbook evaluation
- no shell=True
- no os.system
- no Stage-D executor call
- no action authorisation

## ssh-gate semantics

The runbook answers:
"Can a TCP connection to the configured host:port be established at check time?"

ssh-gate is purely a TCP reachability check. The name refers to checking whether the SSH port is open, not to SSH authentication, key exchange, or remote command execution.

It does not invoke ssh. It does not authenticate. It does not read SSH keys or agent sockets. It does not send any SSH protocol material. It does not execute remote commands. It only attempts a TCP connection using Python stdlib `socket.create_connection` and immediately closes the socket on success.

For ssh-gate, `repo_path` is currently a context anchor only; it is not a Git gate precondition.

Status rules:
- `passed`: all required TCP checks established a connection (port is open and reachable).
- `blocked`: at least one required TCP check failed with a definitive network refusal or timeout (port is closed, filtered, or unreachable).
- `inconclusive`: required TCP checks could not produce a definitive verdict (unknown socket error, no checks defined, or invalid check input).

Reason codes:
- `ssh_tcp_connect_succeeded`: TCP connection was successfully established.
- `ssh_tcp_connect_failed`: TCP connection was refused or timed out.
- `ssh_tcp_connect_inconclusive`: TCP connection failed with an indeterminate error.
- `ssh_no_checks`: no ssh_checks were defined in the plan (produces inconclusive).
- `ssh_invalid_check`: a check entry was malformed (produces inconclusive).

Boundary:
- no ssh subprocess invocation
- no SSH authentication or key handling
- no remote command execution
- no subprocess execution of any kind
- no shell=True
- no os.system
- no Stage-D executor call
- no action authorisation

## Output contract

The runbook must write:
- runbook-result.v1
- runbook-step-trace.v1 JSONL

Precondition failures write no `--result-out` or `--command-trace-out` files.
For CLI precondition failures, stdout may carry a schema-compatible blocked diagnostic sentinel with exit code 1.
That stdout sentinel is diagnostic material for a failed CLI invocation, not a successfully generated runbook result artifact.
If plan input is invalid, sentinel fields may use schema-compatibility fallbacks (for example `runbook_kind: "repo-sync-gate"`); those fallback values are not validated claims about the input plan.
The sentinel never authorises Stage-D execution, action execution, sync, pull, or switch.

## Status semantics

Use:
- passed
- blocked
- inconclusive

Do not invent permissive statuses.
Do not soften blocked or inconclusive into permissive language.

## Phase 11 vs future phases

`server-facts-snapshot` is the fifth concrete read-only runbook kind (Phase 11E), implemented.

`heimserver-service-gate` is the sixth concrete read-only runbook kind (Phase 11F-K), implemented over the existing artifact adapter, pure producer, and assessment writer. See `docs/heimserver-service-gate-model.md`.

It must not be confused with `server-facts-snapshot`: server-facts observes host/runtime metadata; the service gate consumes an explicit three-artifact set and derives an artifact-only assessment. Neither performs a live service-manager check.

Additional runbook kinds and any live-check service-gate extension remain future-gated.


## heimserver-service-gate semantics

The runbook answers:
"Do the three explicitly referenced and hash-bound artifacts satisfy the Heimserver-Service-Gate assessment contract?"

It calls the existing safe adapter and writer boundaries. It does not reimplement their path, hash, strict-JSON, schema, producer, or deterministic-serialization contracts.

Input:
- `service_gate_inputs.artifact_root`
- `service_gate_inputs.input_refs`, passed unchanged to `derive_heimserver_service_gate_assessment_from_refs()`

Output:
- `runbook-result.v1`
- `runbook-step-trace.v1` JSONL
- `heimserver-service-gate-assessment.v1`, written to `heimserver-service-gate-assessment.json` in the same directory as the trace output

Status rules:
- `passed`: the adapter derived a valid `passed` assessment and the complete output set was written.
- `blocked`: the adapter derived a valid `blocked` assessment and the complete output set was written.
- `inconclusive`: the assessment itself is inconclusive, or a technical adapter/writer failure prevented a trustworthy assessment artifact.

Technical adapter/writer codes remain technical diagnostics. They are not mapped into the assessment's `service_gate_*` reason-code namespace. Untrusted payload values are not copied into runbook diagnostics.

Output collision protection:
- `heimserver-service-gate-assessment.json` must not collide with result or trace;
- every target must be outside the repository worktree;
- existing files, directories, symlinks, and dangling symlinks at the assessment target are rejected before execution;
- a later result/trace failure removes an already committed assessment so no incomplete output set remains.

Boundary:
- artifact-derived only; no automatic artifact discovery
- no live service probe, network probe, port scan, service-manager query, subprocess, shell, SSH, Tailscale CLI/API, or `systemctl`
- no service mutation or repair
- no Stage-D action or action authorisation
- `passed` does not prove live service state, reachability, runtime correctness, or service-role fulfilment

## server-facts-snapshot semantics

The runbook answers:
"What are the read-only host/runtime facts of this machine at check time?"

The runbook collects a snapshot of host/runtime attributes using Python stdlib metadata access:
- hostname via `platform.node()`
- platform system, release, version, machine, and processor via `platform`
- Python version via `sys.version`
- Python executable basename via `sys.executable`
- optional process context: current working-directory basename, uid, gid, and root flag where available
- FQDN: **not collected** — no `socket.getfqdn()` call, no DNS reverse lookup

Output:
- `runbook-result.v1` — standard result artifact
- `runbook-step-trace.v1` JSONL — standard trace artifact
- `server-facts.v1` — the collected facts artifact, written to `server-facts.json` in the same trace output directory

Status rules:
- `passed`: facts were collected, schema-validated, and written successfully.
- `blocked`: preconditions failed (invalid plan, unsupported options).
- `inconclusive`: facts collection itself failed with an unexpected error, the collected facts failed schema validation, or the facts artifact could not be written.

Reason codes:
- `server_facts_snapshot_inconclusive`: `_collect_server_facts` raised an unexpected error.
- `server_facts_schema_invalid`: the collected facts dict failed `server-facts.v1` schema validation.
- `server_facts_write_failed`: the schema-valid facts could not be atomically written to `server-facts.json`.

Boundary:
- no subprocess execution
- no shell invocation
- no `os.system`
- no network probe
- no `socket.getfqdn()` — FQDN is explicitly not collected; the schema only accepts `include_process_context`, no `include_fqdn` option
- no SSH
- no Tailscale
- no `systemctl`
- no daemon/service management
- no service evaluation
- no service gate
- no Stage-D action
- no Stage-D executor call
- no action authorisation

Output collision protection:
- `server-facts.json` must not collide with `result_out` — rejected if paths resolve identically
- `server-facts.json` must not collide with `command_trace_out` — rejected if paths resolve identically
- `server-facts.json` must not already exist — rejected to prevent overwriting pre-existing facts artifacts

Rollback:
- If facts are committed to `server-facts.json` but a subsequent step fails (e.g. result or trace write), the `server-facts.json` artifact is removed to prevent orphaned incomplete output sets.

## tailscale-preflight semantics

The runbook answers:
"Are configured overlay/Tailscale targets locally resolvable at check time, and reachable via TCP when a port is configured?"

- `passed`: each configured required Tailscale check resolved locally and, when a `port` is present, the TCP probe also succeeded.
- `blocked`: a required Tailscale check definitively failed due to host non-resolution, expected IP mismatch, expected prefix mismatch, or TCP connection failure.
- `inconclusive`: required checks were missing, inputs were invalid, or local socket resolution/probing failed for indeterminate reasons.

A `passed` result is evidence-only. It is **not** proof that Tailscale is correctly authenticated or configured, and it is **not** action authorisation.

Boundary:
- no tailscale CLI invocation
- no Tailscale API access
- no auth/key/socket/state-file access
- no daemon/service management
- no route/DNS/firewall mutation
- no subprocess execution path for runbook evaluation
- no shell=True
- no os.system
- no Stage-D executor call
- no action authorisation
