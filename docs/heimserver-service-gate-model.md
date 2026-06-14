# Heimserver-Service-Gate Model

Status: Phase 11F-B contract implemented. Runtime and Runbook integration remain future-gated.

This document does not implement a runbook kind, schema, CLI command, action, service probe, or Stage-D executor.

## Purpose

A future Heimserver-Service-Gate is not intended to magically declare a server as "healthy".
It shall define under which conditions existing artifacts or clearly allowed future checks may support a service gate readiness claim.
It is an assessment/gate concept, not a repair mechanism.

## Relation to server-facts-snapshot

- `server-facts-snapshot` is implemented.
- It only collects host/runtime facts.
- It does not evaluate services.
- It is not a service gate.
- It might at most serve as one of several possible inputs for a future service gate logic.

## Open design question

Open question:
Should a future Heimserver-Service-Gate evaluate only existing artifacts, or may it perform bounded local live checks?

### Option A — artifact-derived gate

- `evidence` in v1 is a textual artifact-derived evidence summary.
- `passed` does not prove `live_service_running`.
- Option B remains future-gated.


- uses only existing artifacts
- no live execution
- no network probe
- no service manager interaction
- safer and closer to the existing read-only model
- Disadvantage: evidence may be stale

### Option B — bounded local live check

- could eventually permit local checks
- requires new schema, new tests, new boundary documentation
- would need to either continue prohibiting `systemctl`, subprocess, network probes, or explicitly contract them
- higher risk

Recommendation for next steps:
For the first implementation (Phase 11F-B), Option A (artifact-derived) is the selected path and its contract is now explicitly defined. There is no runbook kind, no runtime execution, and no Stage-D action involved yet. Option B (bounded local live check) remains future-gated and requires explicit design approval.

## Forbidden in current state

- no Runtime implementation
- no schema enum addition
- no CLI
- no Stage-D action
- no `systemctl`
- no SSH
- no Tailscale
- no subprocess
- no shell
- no network probe
- no port scan
- no service start/stop/restart/reload
- no mutation
- no action authorization

## Required before implementation

Any future implementation PR must provide:
- Contract/Semantic decision: artifact-derived vs live-check
- Schema changes
- Examples
- Tests
- Boundary tests
- Failure semantics
- Reason codes
- Evidence paths
- No-mutation proof
- Documentation synchronization
- Explicit decision whether it is a runbook kind or a separate assessment/derivation artifact

## Naming discipline

Preferred future name: `heimserver-service-gate`
Alternatives: `service-gate`, `heimserver-readiness-gate`
The decision is still open because the exact scope must be defined first.
