# Heimserver-Service-Gate Model

Status: Phase 11F-B contract implemented. Phase 11F-C (Producer Preimage Boundary) is design/decision-prep (documentation and guard tests). Phase 11F-D adds the `heimserver-service-expectation.v1` input contract; Phase 11F-E adds the `heimserver-service-evidence.v1` input contract; Phase 11F-F integrates `inputs.service_evidence_ref` into the assessment so the producer preimage is fully referenceable (all schema-only, no producer/runtime). Runtime and Runbook integration remain future-gated.

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

The crucial preimage rule is for `evaluated_services`. At the time of Phase 11F-C, the input set — a `server-facts.v1` snapshot plus a service-expectation artifact — contained **no admissible per-service runtime evidence**. Therefore, until such an evidence artifact was contracted, a conformant producer could not populate `evaluated_services` with a `passed` live claim purely from these inputs; the honest derivations were `inconclusive` (`service_gate_no_service_evidence`) or `blocked` (`service_gate_service_evidence_mismatch`). The `passed` example fixture remains a *contract* fixture, not a proof that any service is running.

Phase 11F-E/F closes that reference gap by adding a contracted `service_evidence_ref`; it does not implement the producer or authorize live checks. The derivation step remains future-gated, and a future producer must still not generate live claims.

### Open gap — expectation input schema (resolved in Phase 11F-D)

> **Update (Phase 11F-D):** Closed. The expectation input now has its own contract, `schemas/heimserver-service-expectation.v1.schema.json`, wired into the validator. See [Phase 11F-D](#phase-11f-d--heimserver-service-expectation-contract) for the design decision.

The gap that 11F-C surfaced: the expectation input artifact `examples/heimserver-service-expectations/minimal-tailscale.json` existed without a schema while the assessment was already contracted — an asymmetric producer chain. The example carried no `SCHEMA_MAP` entry and was therefore unvalidated.

The deferral reason recorded by 11F-C: closing it needs a contract decision, not just a transcription. The example carried no `schema_version`, so adding one changes its bytes and forces a coordinated re-hash of every assessment fixture's `inputs.expectation_ref.sha256` (and the hash guard). Phase 11F-D made that decision (a `schema_version`-only envelope; no `kind`) and performed the migration.

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

## Phase 11F-D — Heimserver-Service-Expectation Contract

Status: implemented (contract only). No runtime, producer, runbook kind, CLI, executor, Stage-D action, service probe, or live check is added.

11F-C surfaced an asymmetry: the assessment **output** was contracted, but the expectation **input** was not. 11F-D closes it by giving the expectation input its own schema, so the producer preimage is reproducibly typed on both inputs (`server-facts.v1` + `heimserver-service-expectation.v1`).

### Design decision — Variant A′ (`schema_version`, no `kind`)

Decided against both the maximal Variant A (`schema_version` + `kind` + …) and the bare Variant B (no envelope), in favour of a hybrid, on repo evidence:

- `schema_version` is **required** — it is universal across all 33 schemas (e.g. `server-facts.v1`, `source-ref.v1`). The const follows the dominant `"<name>.v1"` form: `heimserver-service-expectation.v1`. (The sibling assessment's `schema_version: "1"` is the repo's lone outlier and is intentionally not propagated; harmonising it is a separate follow-up.)
- `kind` is **omitted** — 31/33 schemas have no top-level `kind`; `scope-explanation.v1` uses `kind` only as a nested domain enum; only `heimserver-service-gate-assessment.v1` carries a top-level `kind`. Decisively, the co-input `server-facts.v1` has `schema_version` and no `kind`. Adding `kind` would over-specify and break symmetry with the other producer input. Artifact type is already discriminated by directory + `SCHEMA_MAP` + the `schema_version` const.

Contracts-first here means consistency with the organism, not maximal field count.

### Contract shape

| Field | Rule |
| --- | --- |
| `schema_version` | const `heimserver-service-expectation.v1` |
| `host` | string, `minLength` 1 |
| `scope` | const `artifact-derived` |
| `expected_services[]` | objects of `service_name` + `expected_role` (both `minLength` 1), `additionalProperties: false` |

`additionalProperties: false` at every level. No runtime fields, no live evidence, no freshness, no result fields — the expectation is a static input, not a verdict.

### Migration

- New schema `schemas/heimserver-service-expectation.v1.schema.json`; new `SCHEMA_MAP` entry `heimserver-service-expectations`.
- `examples/heimserver-service-expectations/minimal-tailscale.json` gained `schema_version`; its `sha256` changed, so `inputs.expectation_ref.sha256` was updated in all five assessment fixtures. The existing hash guard plus a new explicit cross-check (`tests/test_heimserver_service_expectations.py`) keep the references consistent.

### Still forbidden (unchanged)

Same fence as 11F-B / 11F-C: no producer, runbook kind, CLI, Stage-D / executor, service probe, subprocess, shell, SSH, Tailscale CLI/API, `systemctl`, or socket; no change to `SUPPORTED_RUNBOOK_KINDS`, `runbook-plan.v1`, or `runbook-result.v1`.

## Phase 11F-E — Heimserver-Service-Evidence Contract

Status: implemented (contract only). No producer, runbook kind, CLI, executor, Stage-D action, service probe, or live check is added.

11F-D contracted the expectation input; 11F-E contracts the missing third input: **service evidence**. Without it, a producer would have to invent `evaluated_services` out of `server-facts` + `expectation` — more than those inputs carry. That would be false coherence. 11F-E supplies the admissible act from which `evaluated_services` may later be derived.

### Why a separate evidence contract (and not a producer next)

The relevant question is not "how do we produce the verdict?" but "which admissible act does a verdict require?". Evidence is a *descriptive* artifact (what the existing artifacts show); the assessment is the *verdict* (`passed` / `blocked` / `inconclusive`). Keeping them in separate vocabularies prevents the evidence layer from smuggling a verdict or a live claim:

- `evidence_status` is `present | missing | mismatch | unknown` — descriptive, never `running` / `reachable` / `live`.
- Reason codes use a dedicated `service_evidence_*` namespace, distinct from the assessment's verdict-oriented `service_gate_*` codes. A future producer maps the former to the latter explicitly.

### The preimage chain

```
server_facts_ref
+ expectation_ref
+ service_evidence_ref
+ contract rules
= future assessment derivation (heimserver-service-gate-assessment.v1)
```

All three inputs are now contracted (`server-facts.v1`, `heimserver-service-expectation.v1`, `heimserver-service-evidence.v1`). The derivation step itself stays future-gated.

### Contract shape

| Field | Rule |
| --- | --- |
| `schema_version` | const `heimserver-service-evidence.v1` |
| `host` | string, `minLength` 1 |
| `scope` | const `artifact-derived` |
| `observed_at` | strict UTC-`Z` pattern (not `format: date-time`) |
| `services[]` | objects of `service_name`, `evidence_status`, `reason_codes` (≥1), `evidence` (≥1) |

`additionalProperties: false` at every level. The artifact carries **no** `status`, `evaluated_services`, `freshness`, `does_not_prove`, or any live-truth field. It records artifact evidence only and must never assert `live_service_running`, `service_reachable`, or `runtime_correctness`.

### Assessment integration (done in Phase 11F-F)

11F-E kept the assessment schema unchanged. Phase 11F-F adds `inputs.service_evidence_ref` to `heimserver-service-gate-assessment.v1` and migrates its fixtures — see [Phase 11F-F](#phase-11f-f--assessment-evidence-input-integration).

### Still forbidden (unchanged)

Same fence as 11F-B / 11F-C / 11F-D: no producer, runbook kind, CLI, Stage-D / executor, service probe, subprocess, shell, SSH, Tailscale CLI/API, `systemctl`, or socket; no change to `SUPPORTED_RUNBOOK_KINDS`, `runbook-plan.v1`, or `runbook-result.v1`; no rename of `passed`.

## Phase 11F-F — Assessment Evidence Input Integration

Status: implemented (contract integration only). No producer, runbook kind, CLI, executor, Stage-D action, service probe, or live check is added.

11F-E contracted service evidence but kept it disconnected from the assessment. 11F-F closes the loop: the assessment now references all three producer inputs, so the entire preimage is referenceable from a single artifact.

### What changed

- `heimserver-service-gate-assessment.v1`: `inputs` now requires `service_evidence_ref` (alongside `server_facts_ref` and `expectation_ref`), with the same shape — `path` + `sha256` (`^[0-9a-f]{64}$`), `additionalProperties: false`. No status semantics changed; no `$ref` / `$defs`; the strict UTC-`Z` pattern is untouched.
- All five assessment fixtures gained a real `service_evidence_ref` pointing at `examples/heimserver-service-evidence/minimal-artifact-only.json`.
- The input-hash guard now checks all three references; new negatives cover a missing `service_evidence_ref` and a malformed `service_evidence_ref.sha256`; boundary tests confirm the closed `inputs` and top-level objects reject any smuggled runtime / probe / executor field.

### The preimage is now fully referenceable

```
server_facts_ref + expectation_ref + service_evidence_ref + contract rules
= future assessment derivation
```

Every assessment now declares, by content hash, exactly which server-facts, expectation, and service-evidence artifacts it was derived from. The derivation step (the producer) remains future-gated.

### Still forbidden (unchanged)

No producer, derivation script, runbook kind, CLI, Stage-D / executor, service probe, subprocess, shell, SSH, Tailscale CLI/API, `systemctl`, or socket; no change to `SUPPORTED_RUNBOOK_KINDS`, `runbook-plan.v1`, or `runbook-result.v1`; no rename of `passed`; no live-truth claim (`does_not_prove` still guards `live_service_running`, `service_reachable`, `runtime_correctness`).
