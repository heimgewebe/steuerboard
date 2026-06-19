# Heimserver-Service-Gate Model

Status: Phase 11F-B contract implemented. Phase 11F-C (Producer Preimage Boundary) is design/decision-prep only: documentation and guard tests, no producer. Runtime and Runbook integration remain future-gated.

Phase 11F-B implements only the artifact-derived assessment schema contract. It does not implement a runbook kind, CLI command, action, service probe, runtime executor, or Stage-D executor.

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

## Phase 11F-C — Producer Preimage Boundary

Status: design/decision-prep. Not implemented. This phase ships documentation and guard tests only. It does not add a producer, runbook kind, CLI, Stage-D action, executor, or service probe.

### Intent

Phase 11F-B fixed the *shape* of `heimserver-service-gate-assessment.v1`. Phase 11F-C fixes its *preimage*: the rules by which a future, artifact-derived producer may reconstruct (derive) such an assessment from its declared inputs and from fixed contract rules, and the fields that must never claim to prove live truth.

This is a fence, not a remote control. It constrains a future producer's inputs and derivation semantics without granting it any executable capability.

### Invariants

- The assessment is and stays **artifact-derived** (`subject.scope` is the const `artifact-derived`).
- `passed` means only: *the referenced artifacts satisfy the expectation defined in the assessment contract.*
- `passed` still does **not** prove any of:
  - `live_service_running`
  - `service_reachable`
  - `runtime_correctness`
- A future producer **may only read already-existing artifacts** (its declared inputs).
- A future producer **must not perform any live check** — no service probe, no network probe, no port scan, no service-manager query.
- No runbook kind, no CLI command, no Stage-D action, no executor, no service probe, no subprocess, no shell, no SSH, no Tailscale CLI/API, no `systemctl`, no socket probe.

### Field lineage (preimage)

How each assessment field must be derivable. "Input" means a declared, hashed input reference; "contract rule" means a fixed rule defined by the schema/contract, not observed at runtime.

| Field | Derived from | Constraint |
| --- | --- | --- |
| `subject.host` | `expectation_ref` artifact, or a fixed/controlled host context | no live hostname lookup |
| `subject.scope` | contract rule (const `artifact-derived`) | never any other value |
| `inputs.server_facts_ref` | declared input | `path` + `sha256` of an existing artifact |
| `inputs.expectation_ref` | declared input | `path` + `sha256` of an existing artifact |
| `expected_services` | **exclusively** from `expectation_ref` | never invented by the producer |
| `evaluated_services` | **exclusively** from admissible artifact evidence | while no such evidence exists, no live state may be claimed |
| `reason_codes` | contract rules (the schema reason-code enum + per-status partition) | no free-form codes |
| `evidence` | textual artifact-derived summary | not a `SourceRef`, not a live proof |
| `freshness` | artifact time / declared observation time | never derived from a live query |
| `does_not_prove` | fixed contract protection list | must always contain `live_service_running` |

The crucial preimage rule is for `evaluated_services`. The current input set — a `server-facts.v1` snapshot plus a service-expectation artifact — contains **no admissible per-service runtime evidence**. Therefore, until such an evidence artifact is contracted, a conformant producer must not populate `evaluated_services` with a `passed` live claim purely from these inputs; the honest derivations are `inconclusive` (`service_gate_no_service_evidence`) or `blocked` (`service_gate_service_evidence_mismatch`). The `passed` example fixture remains a *contract* fixture, not a proof that any service is running.

### Open gap — expectation input schema

- The expectation input artifact exists as an example: `examples/heimserver-service-expectations/minimal-tailscale.json`.
- A schema for it does **not** exist: there is no `schemas/heimserver-service-expectation.v1.schema.json`, and `scripts/validate_examples.py` has no `SCHEMA_MAP` entry for `heimserver-service-expectations`. The example is therefore currently unvalidated.
- Open gap: **`heimserver-service-expectation.v1.schema.json` is missing and is required for a reproducible producer preimage.** Without it, `inputs.expectation_ref` points at an artifact whose own shape is uncontracted, so `expected_services` cannot be derived reproducibly.
- It is intentionally **not** added in 11F-C, because it needs a decision first, not just a transcription:
  - Repo convention gives every artifact a `schema_version` and `kind`. The current expectation example has neither. Adding them changes the file's bytes, which would break the `sha256` values referenced by every assessment example (`inputs.expectation_ref.sha256`) and the `test_example_input_hashes_match_referenced_artifacts` guard — a coordinated re-hash across all fixtures.
  - The alternative — a schema that omits `schema_version`/`kind` to match the example as-is — silently diverges from the repo's artifact convention.
  - Either path is a contract decision, so it belongs to its own change, not to this boundary-only phase.

### Forbidden in 11F-C

The 11F-B fence, restated for the producer preimage:

- no producer script
- no runbook kind (`heimserver-service-gate` must stay out of `SUPPORTED_RUNBOOK_KINDS`, `runbook-plan.v1`, and `runbook-result.v1`)
- no CLI command
- no Stage-D action / executor
- no live network, socket, SSH, Tailscale CLI/API, `systemctl`, subprocess, or shell
- no service start/stop/restart/reload, no mutation, no action authorization
- no rename of `passed`
- no loosening of the strict UTC `Z` timestamp pattern to `format: date-time`
