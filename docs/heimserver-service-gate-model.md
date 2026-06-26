# Heimserver-Service-Gate Model

Status: Phase 11F-B implements the assessment contract. Phases 11F-C through 11F-F define and complete the producer preimage and input contract boundaries. Phase 11F-G implements the derivation contract, golden cases, cross-artifact validation, and the independent reference oracle. Phase 11F-H implements the pure in-memory producer. Phase 11F-I implements the safe artifact input adapter that makes the producer reachable through explicit, hash-bound, artifact-root-relative artifact references. CLI, runbook, writer, runtime, live-check, and Stage-D integration remain future-gated. Evidence-internal provenance remains future work.

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

Phase 11F-B fixed the *shape* of `heimserver-service-gate-assessment.v1`. Phase 11F-C fixes its preimage
boundary and field lineage: which declared inputs and fixed contract
constraints a future artifact-derived producer may use, and which fields
must never claim live truth. Complete derivation and mapping rules remain
future-gated.

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
| `inputs.service_evidence_ref` | declared input | `path` + `sha256` of an existing `heimserver-service-evidence.v1` artifact |
| `expected_services` | **exclusively** from `expectation_ref` | never invented by the producer |
| `evaluated_services` | **exclusively** from admissible artifact evidence | while no such evidence exists, no live state may be claimed |
| `reason_codes` | contract rules (the schema reason-code enum + per-status partition) | no free-form codes |
| `evidence` | textual artifact-derived summary | not a `SourceRef`, not a live proof |
| `freshness` | artifact time / declared observation time | never derived from a live query |
| `does_not_prove` | fixed contract protection list | must always contain `live_service_running` |

The crucial preimage rule is for `evaluated_services`. At the time of
Phase 11F-C, the input set — a `server-facts.v1` snapshot plus a
service-expectation artifact — contained no admissible per-service evidence.
Therefore, no conformant future producer could derive `passed` from those
inputs alone. The assessment schema already fixes the allowed reason-code
partitions for `blocked` and `inconclusive`; the evidence-condition
selection, aggregation, precedence, and concrete reason-code choice within
those partitions remain future-gated. The `passed` example fixture
remains a contract fixture, not a proof that any service is running.

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

11F-D contracted the expectation input; 11F-E contracts the missing third input: **service evidence**. Without it, a producer would have to invent `evaluated_services` out of `server-facts` + `expectation` — more than those inputs carry. That would be false coherence. 11F-E supplies the admissible act from which `evaluated_services` may later be derived. Note: The `heimserver-service-evidence.v1` artifact is purely descriptive and currently lacks cryptographically bound references (e.g. `SourceRef` with hashes) to its underlying source artifacts (like system logs or status dumps). This means the traceability chain currently terminates at the evidence artifact itself. This is a known limitation that may be addressed in future phases.

### Why a separate evidence contract (and not a producer next)

The relevant question is not "how do we produce the verdict?" but "which admissible act does a verdict require?". Evidence is a *descriptive* artifact (what the existing artifacts show); the assessment is the *verdict* (`passed` / `blocked` / `inconclusive`). Keeping them in separate vocabularies prevents the evidence layer from smuggling a verdict or a live claim:

- `evidence_status` is `present | missing | mismatch | unknown` — descriptive, never `running` / `reachable` / `live`.
- Reason codes use a dedicated `service_evidence_*` namespace, distinct from the assessment's verdict-oriented `service_gate_*` codes. A future producer maps the former to the latter explicitly.

### The preimage chain

```text
server_facts_ref
+ expectation_ref
+ service_evidence_ref
= declared input-reference set for a future derivation

Complete derivation and mapping rules
+ producer implementation
= future-gated
```

All three input artifact types are now contracted
(`server-facts.v1`, `heimserver-service-expectation.v1`,
`heimserver-service-evidence.v1`). This completes the declared input-reference
set, not the derivation algorithm. The derivation and mapping rules remain
future-gated.

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

11F-E contracted service evidence but kept it disconnected from the assessment. 11F-F closes the direct assessment-input loop: the assessment now references all three declared producer input artifacts, so its complete direct input-reference set is available from a single assessment artifact. Evidence-internal provenance remains future work.

### What changed

- `heimserver-service-gate-assessment.v1`: `inputs` now requires `service_evidence_ref` (alongside `server_facts_ref` and `expectation_ref`), with the same shape — `path` + `sha256` (`^[0-9a-f]{64}$`), `additionalProperties: false`. No status semantics changed; no `$ref` / `$defs`; the strict UTC-`Z` pattern is untouched.
- All five assessment fixtures gained a real `service_evidence_ref` pointing at `examples/heimserver-service-evidence/minimal-artifact-only.json`.
- The input-hash guard now checks all three references; new negatives cover a missing `service_evidence_ref` and a malformed `service_evidence_ref.sha256`; boundary tests confirm the closed `inputs` and top-level objects reject any smuggled runtime / probe / executor field.

### Direct assessment input references are complete

```
server_facts_ref
+ expectation_ref
+ service_evidence_ref
= declared input-reference set for a future derivation

Derivation rules + producer implementation
= future-gated
```

Every assessment fixture declares all three input references by content hash.
This proves reference-path and content-hash integrity only; it does not prove
that the fixture verdict was derived from those artifacts.
The derivation rules and producer implementation remain future-gated.

### Fixture Semantics

For Phase 11F-F, the current assessment examples are contract-shape fixtures.
They validate schema shape, status partitions, and input-reference integrity.
Their input references do not prove that the fixture verdict is derivable
from the referenced artifacts. Producer-golden semantics and derivation rules
remain future-gated.

This classification is fixed by Phase 11F-F to avoid treating schema examples
as producer-golden proofs before derivation rules exist.

Future producer-golden fixtures must not be subjected accidentally to the
shared-reference assumptions of the current shape-fixture tests.

### Still forbidden (unchanged)

No producer, derivation script, runbook kind, CLI, Stage-D / executor, service probe, subprocess, shell, SSH, Tailscale CLI/API, `systemctl`, or socket; no change to `SUPPORTED_RUNBOOK_KINDS`, `runbook-plan.v1`, or `runbook-result.v1`; no rename of `passed`; no live-truth claim (`does_not_prove` still guards `live_service_running`, `service_reachable`, `runtime_correctness`).

## Known Contract Asymmetries

- `schema_version`: Expectation and Evidence use `<name>.v1` whereas Assessment uses `"1"`. As noted in Phase 11F-D, Assessment is the repository's lone outlier and harmonising it is a deferred follow-up.
- `host` and `scope`: Expectation and Evidence define these at the top-level, whereas Assessment nests them under a `subject` object. This is a known architectural asymmetry.

## Phase 11F-G — Derivation Readiness Contract

Status: implemented (contract and validation only)

11F-G establishes the strict derivation boundary between the three declared inputs (`server-facts.v1`, `heimserver-service-expectation.v1`, `heimserver-service-evidence.v1`) and the resulting assessment. It provides a formal, machine-verifiable derivation contract (via `heimserver-service-gate-derivation-case.v1`) against which a future producer must be tested.

### Input Preconditions
Derivation semantics apply exclusively to inputs that are:
- loaded
- JSON-decoded
- schema-valid
- hash-verified
- resolved from safe repository paths
Loader errors (missing file, invalid JSON, invalid schema, wrong hash, unsafe path, read error) are technical failures outside the derivation semantics. Loader validity ≠ semantic derivation.

### Host Identity Rule
Host identity is evaluated by strictly comparing three sources:
- `server_facts.host.hostname`
- `expectation.host`
- `service_evidence.host`

This comparison is an exact byte-for-byte string match without any normalization (no lowercasing, no trimming, no FQDN alias mapping).
If any of the three differs, the assessment is blocked:
- `status` = `blocked`
- `subject.host` = `expectation.host`
- `evaluated_services` = `[]`
- `reason_codes` = `["service_gate_subject_mismatch"]`
- `freshness` is strictly mapped from evidence.
- A fixed evidence text is emitted: `Host identity mismatch: server_facts='<facts_host>', expectation='<expectation_host>', service_evidence='<evidence_host>'.`

### Expected Services Rule
For every assessment, including host-identity mismatch assessments, the `expected_services` list is copied exactly from the expectation artifact to the assessment. This means exact element equality, identical ordering, and exact `expected_role` values without addition, omission, or normalization. `expected_role` is a declarative label; this phase performs no role verification.

### Service Join Rule
The join key between expected services and service evidence is strictly `service_name`.
These lists must be unique by `service_name` (no duplicates allowed).
`evaluated_services` exactly follows the order of `expectation.expected_services`.
Any extra service evidence not present in the expectation is completely ignored and does not alter the status, reasons, or order.

### Missing Evidence Match
If an expected service has no matching evidence entry:
- `service.status` = `inconclusive`
- `service.reason_codes` = `["service_gate_no_service_evidence"]`
- Fixed evidence text: `No matching artifact-derived evidence found for expected service '<service_name>'.`

### Evidence-Status to Service Mapping
For a matching evidence entry, the service status is derived strictly as follows:
| Evidence Status | Freshness | Service Status | Service Reason |
| --- | --- | --- | --- |
| `present` | `fresh` | `passed` | `service_gate_artifact_only_scope` |
| `present` | `stale` | `inconclusive` | `service_gate_artifacts_stale` |
| `present` | `unknown` | `inconclusive` | `service_gate_freshness_unknown` |
| `missing` | any | `inconclusive` | `service_gate_no_service_evidence` |
| `unknown` | any | `inconclusive` | `service_gate_no_service_evidence` |
| `mismatch` | any | `blocked` | `service_gate_service_evidence_mismatch` |

`mismatch` has strict precedence over freshness rules.

### Freshness
The assessment freshness is mapped exactly and exclusively from the evidence artifact (`freshness_status` and `observed_at`). No system clock or server-facts timestamps are used.

### Aggregation Rule
The overall assessment status follows a strict precedence:
`blocked` > `inconclusive` > `passed`

Sonderfälle:
- Host-Mismatch -> `blocked`
- Empty Expectation -> `inconclusive` (Reason: `service_gate_expectation_missing`, Fixed Evidence Text: `No expected services were declared.`)

For standard aggregation:
- **Blocked**: If at least one service is blocked, the overall status is blocked. The top-level reasons contain the deduplicated blocked service reasons. Inconclusive reasons remain at the service level.
- **Inconclusive**: If no service is blocked but at least one is inconclusive, the overall status is inconclusive. The top-level reasons contain the deduplicated inconclusive service reasons.
- **Passed**: Only if all expected services are passed. Reason: `service_gate_artifact_only_scope`.

### Reason Code Order
Top-level reason codes must be deduplicated and emitted strictly in the exact order defined by the canonical master-enum in the assessment schema (not sorted alphabetically).

### Evidence Texts
Fixed templates for evidence:
- Host Mismatch: `Host identity mismatch: server_facts='<facts_host>', expectation='<expectation_host>', service_evidence='<evidence_host>'.`
- Empty Expectation: `No expected services were declared.`
- Unmatched Service: `No matching artifact-derived evidence found for expected service '<service_name>'.`

For any matching evidence entry — including missing and unknown — the service-level evidence array is copied unchanged from that entry.

Only the complete absence of a matching service entry creates the fixed "No matching artifact-derived evidence..." template.

### Does Not Prove
The assessment explicitly declares that it `does_not_prove` the following properties, as a strictly enforced exact 4-element array:
- `live_service_running`
- `service_reachable`
- `runtime_correctness`
- `service_role_fulfilled`

### Shape vs Golden Cases
- **Shape Fixtures**: Test the structural validity, constraints, and reference validity of artifacts against the JSON schemas.
- **Golden Cases**: Test the causal Input → Output mapping semantics enforcing the normative rules above.

### Validator Boundary & Non-Goals
The derivation rules are protected by a dedicated schema and cross-artifact validator that enforces these constraints across the golden cases.
**Non-Goals**: This phase establishes the rules and validating tests but implements **no producer**, no CLI, no runbooks, no live-checks, no network/subprocesses usage, no system time calls, no writer logic, and no evidence-internal provenance.

### In-Place v1 Hardening Justification
The addition of the required `freshness_status` to `heimserver-service-evidence.v1` is an in-place pre-runtime contract hardening. No production producer or consumer existed; all repository fixtures were migrated atomically.

## Phase 11F-H — Producer In-Memory

Status: implemented (pure in-memory producer only)

11F-H implementiert den eigentlichen Producer (`steuerboard.heimserver_service_gate.derive_heimserver_service_gate_assessment`), der die in 11F-G definierten Derivations-Regeln programmatisch abbildet.

- **Modulpfad:** `steuerboard/heimserver_service_gate.py`
- **Öffentliche Funktion:** `derive_heimserver_service_gate_assessment`
- **Vier Parameter:** `server_facts`, `expectation`, `service_evidence`, `input_refs`
- **Rückgabewert:** Vollständiges `heimserver-service-gate-assessment.v1` Dictionary.
- **Inputvoraussetzung:** Setzt JSON-decodierte, schema-valide Payloads und exakte Input-Referenzen voraus.
- **Guards:** Keine Hash-, Schema- oder Pfadprüfung im Producer. Lokale semantische Guards lehnen fehlende Referenzen, Duplikate oder unbekannte Statuswerte ab.
- **Referenzorakel:** Das in 11F-G geschaffene Referenzorakel bleibt vollständig unabhängig vom Producer und wird exklusiv für Cross-Validierungen in den Tests verwendet.
- **Erreichbarkeit von Reasons:** Der Producer erzeugt keine artifiziellen Loader- oder Schemafehler, die aus den validierten In-Memory Inputs gar nicht erreichbar sein dürfen.
- **Reinheitsgarantien:** Keine Datei-I/O, keine Subprozesse, keine Systemzeit, keine Netzwerkzugriffe. Reine deterministische In-Memory Funktion ohne Alias-Beziehungen zum Input.
- **Non-Goals:** Keine CLI-Integration, kein Runbook, kein Writer, kein Loader, keine Liveprüfung, keine Stage-D-Action.

## Phase 11F-I — Safe Artifact Input Adapter

Status: implemented (safe artifact adapter only)

11F-I macht den reinen, in 11F-H implementierten Producer erstmals kontrolliert über explizite, artifact-root-relative Artefaktverweise erreichbar. Der Adapter verantwortet ausschließlich die technische Ladegrenze; die fachliche Derivation bleibt unverändert beim Producer.

- **Modulpfad:** `steuerboard/heimserver_service_gate_artifacts.py`
- **Öffentliche API:** genau die Fehlerklasse `HeimserverServiceGateArtifactError` und die Funktion `derive_heimserver_service_gate_assessment_from_refs(*, artifact_root, input_refs)`. Alle Lade-, Pfad-, JSON- und Schemahelfer bleiben privat. Es gibt keine öffentliche Loaderfunktion und keine öffentliche Dataclass.

### Explizite, artifact-root-relative Inputrefs

Der Adapter prüft exakt die drei `input_refs` (`server_facts_ref`, `expectation_ref`, `service_evidence_ref`) gegen das kanonisch kopierte `inputs`-Subschema des Assessment-Vertrages. Es gibt keine automatische Discovery, kein Glob, kein `expanduser()`, keine Umgebungsvariablenauflösung und keine Standardpfade.

### Artifact-Root vs. kanonische Schemaautorität

`artifact_root` bestimmt ausschließlich, wo die drei Eingabeartefakte liegen dürfen. Die vier kanonischen Schemas (`server-facts.v1`, `heimserver-service-expectation.v1`, `heimserver-service-evidence.v1`, `heimserver-service-gate-assessment.v1`) werden immer code-relativ aus dem steuerboard-Checkout geladen (`_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"`), niemals aus `artifact_root`. Ein Aufrufer kann damit kein abgeschwächtes Ersatzschema neben den Artefakten einschleusen. Es gibt keinen öffentlichen `schema_root`-Parameter. Diese Grenze setzt das aktuelle steuerboard-Checkout- bzw. lokale Installationsmodell voraus; eine Packaging-Reform findet nicht statt.

### Statische Root-Escape- und Symlink-Prüfung

Pfade werden ohne lexikalisches `..`-Segment und ohne absolute Form akzeptiert, mit `resolve(strict=True)` aufgelöst und per `relative_to(resolved_root)` als innerhalb des Roots bewiesen. Symlink-Policy: ein Symlink auf eine reguläre Datei innerhalb des Roots ist zulässig; ein Symlink (oder eine Symlinkkette) auf ein Ziel außerhalb des Roots ergibt `unsafe_path`; ein fehlendes Ziel ergibt `file_missing`; ein Verzeichnis oder anderes nicht reguläres Ziel ergibt `not_regular_file`.

### Einmaliges Rohbyte-Lesen und SHA-256-Bindung

Jede Inputdatei wird genau einmal als Rohbytes gelesen. Der SHA-256 wird über exakt diese gelesenen Rohbytes gebildet und vor jeder semantischen Verarbeitung gegen den deklarierten `sha256` geprüft. Es wird nicht über neu serialisiertes JSON gehasht; `canonical_json_sha256()` wird bewusst nicht verwendet. Eine semantisch gleiche, aber anders formatierte JSON-Datei benötigt daher einen anderen Referenzhash.

### Striktes UTF-8 und striktes JSON

Dieselben gelesenen Rohbytes werden streng als UTF-8 und anschließend als JSON dekodiert. Der strikte JSON-Decoder lehnt doppelte Objektschlüssel sowie `NaN`, `Infinity` und `-Infinity` ab (Code `invalid_json`, Stage `json_decode`). Diese Striktheit gilt sowohl für die Inputartefakte als auch für die kanonischen Schema-Dateien.

### Vollständige Draft-2020-12-Schemavalidierung

Die drei Payloads werden vollständig mit `jsonschema.Draft202012Validator` gegen die kanonischen Schemas validiert; jedes Schema wird zuvor mit `check_schema` geprüft. Der interne Minimalvalidator reicht für diesen Slice nicht (u. a. wegen `contains` in Evidence und Assessment) und wird hier nicht als stiller Fallback verwendet. Bei mehreren Schemafehlern wird deterministisch der nach (`absolute_path`, `absolute_schema_path`, `message`) erste Fehler ausgewählt. Die ausgegebene Diagnose besteht jedoch ausschließlich aus dem fehlgeschlagenen Schema-Keyword und dem vertrauenswürdigen schema-seitigen Pfad (JSON-Pointer-kodiert); **Artefaktinstanzwerte und untrusted JSON-Schlüssel erscheinen nicht in der Fehlermeldung** (weder über `error.message` noch über `absolute_path`). Kanonische Schemas müssen über die Meta-Schema-Validität (`check_schema`) hinaus strukturell mit dem Adapter kompatibel sein: Mapping-Schemas mit nutzbarem `properties.inputs`; boolesche „akzeptiere alles“-Schemas (z. B. `true`) werden als `contract_schema_invalid` abgelehnt.

### Contract-Kompatibilität und Producer-Preimage-Form

Über die reine Schemavalidierung hinaus prüft der Adapter, dass der kanonische Vertrag tatsächlich mit Adapter und Producer zusammenpasst — ohne die JSON-Schemas in Python nachzubauen:

- Das `inputs`-Subschema wird nicht nur meta-schema-validiert, sondern verhaltensbasiert anhand consumer-relevanter Probeinstanzen auf Adapterkompatibilität geprüft: eine kanonische gültige Referenzmenge muss akzeptiert werden, und die definierte, vom Adapter technisch nicht konsumierbare Inkompatibilitätsmatrix wird symmetrisch für alle drei kanonischen Referenzen (`server_facts_ref`, `expectation_ref`, `service_evidence_ref`) abgelehnt. Es ist keine theoretisch unbegrenzte „alle denkbaren Formen“-Aussage, sondern eine feste consumer-relevante Gegenmatrix.
- Nach der Schemavalidierung der `input_refs` greift ein defensiver Form-Guard vor jedem Indexzugriff (exakte Schlüsselmenge, je Ref genau `path` + `sha256`, nichtleerer `path`, `^[0-9a-f]{64}$`).
- Tatsächlich geladene Payloads durchlaufen nach der Schemavalidierung einen schmalen Producer-Preimage-Shape-Guard, der nur die vom Producer unmittelbar per Indexzugriff oder Iteration benötigte Struktur prüft (`server_facts.host.hostname`, `expectation.host`, `service_evidence.host`/`observed_at` sowie `service_name`/`expected_role`/`evidence_status` je Listenelement). `service_name` muss zusätzlich ein String sein, weil der Producer ihn als Set- und Dictionary-Schlüssel verwendet; das verhindert rohe Hashbarkeits-`TypeError`. Ein vorhandenes `service_evidence.services[*].evidence` muss eine Liste sein, weil der Producer dieses Feld später direkt iteriert. Ein fehlendes `evidence` bleibt im technischen Guard zulässig, da der Producer dafür den sicheren Default `[]` verwendet. Die Typen der Evidence-Listenelemente sowie `expected_role`, `evidence_status` und `freshness_status` werden bewusst nicht zusätzlich technisch typisiert; Schema, Outputschema beziehungsweise fachliche Producer-`ValueError`-Regeln bleiben zuständig.
- Besteht ein Payload sein kanonisches Schema, verletzt aber die technisch benötigte Form, gilt das kanonische Schema als adapterinkompatibel: `contract_schema_invalid` (nicht `invalid_input_refs`/`input_schema_invalid`). Der Producer wird in diesem Fall nicht aufgerufen; seine fachlichen `ValueError`-Regeln (z. B. `freshness_status`) werden nicht dupliziert und nicht umklassifiziert.
- Die vier kanonischen Schemas sind in 11F-I selbstenthalten und referenzfrei; `$ref`, `$dynamicRef` und `$recursiveRef` werden abgelehnt (`contract_schema_invalid`), sodass keinerlei — auch keine netzwerkbasierte — Referenzauflösung stattfindet. Lokale Schema-Referenzen erfordern später eine explizite Offline-Registry und einen eigenen Contract-Slice.
- Es findet keine vollständige Fachschema-Duplikation in Python statt; die Zusatzprüfungen sind schmale, consumer-getriebene Kompatibilitäts- und Form-Guards. Referenzen sind artifact-root-relativ; `artifact_root` muss kein Git-Repository sein.

### Producer bleibt rein und unverändert; Outputschema-Validierung

Der bestehende Producer wird genau einmal aufgerufen und nicht verändert; seine fachliche Logik wird nicht dupliziert. Das erzeugte Assessment wird anschließend vollständig gegen `heimserver-service-gate-assessment.v1` validiert (`output_schema_invalid` bei Verstoß). Zurückgegeben wird eine tiefe, unabhängige Dictionary-Kopie; Original-`input_refs`, Producer-Eingaben und Rückgabe stehen in keiner Alias-Beziehung.

### Technische Artefaktfehler sind keine Assessment-Reason-Codes

Ladefehler sind technische Fehler des Adapters, keine fachlichen Reason-Codes des Assessments. Sie werden als `HeimserverServiceGateArtifactError` mit den maschinenprüfbaren Attributen `code`, `stage`, `input_name`, `path` erhoben. `input_name` ist auf die drei kanonischen Ref-Namen begrenzt (sonst `None`); ein untrusted Aufruferschlüssel erscheint dort nie. Der deklarierte Referenzpfad bleibt bewusst als `path`-Attribut erhalten und ist damit ein vorgesehener Bestandteil der strukturierten Fehlerschnittstelle (es wird also nicht pauschal behauptet, Exceptions enthielten unter allen Umständen „keine Pfade“). Rohe Pfadausnahmen — `ValueError` bei eingebettetem NUL-Byte, reproduzierter `RuntimeError` bei Symlink-Schleife — werden strukturiert in `invalid_artifact_root` bzw. `unsafe_path` übersetzt und treten nicht als rohe Python-Ausnahmen durch die Adaptergrenze. Die fachlichen `ValueError`-Ausnahmen des Producers werden bewusst nicht abgefangen oder in Adapterfehler übersetzt. Stabile Fehlercodes: `invalid_artifact_root`, `contract_load_failed`, `contract_schema_invalid`, `invalid_input_refs`, `unsafe_path`, `file_missing`, `not_regular_file`, `read_failed`, `hash_mismatch`, `invalid_utf8`, `invalid_json`, `input_schema_invalid`, `output_schema_invalid`.

### Bedrohungsmodell und Speicherverhalten

Der Adapter schützt gegen statische Pfadflucht und normale Fehlkonfiguration. Er behauptet keinen vollständigen Schutz gegen einen gleichzeitig agierenden Akteur mit Schreibrechten im Artifact-Root (kein `openat2`, kein `O_NOFOLLOW`, keine fd-relative Architektur in diesem Slice). Für eine konkurrierende TOCTOU-Mutation zwischen Pfadprüfung und `read_bytes()` genügen Schreibrechte im betroffenen Root; Systemprivilegien sind dafür nicht zwingend erforderlich. Kleine lokale steuerboard-Artefakte werden vollständig in den Speicher gelesen; ein Schutz vor absichtlich riesigen Dateien ist nicht Bestandteil dieses Slices, und es wird kein künstliches Dateigrößenlimit eingeführt.

### Weiter offen (future-gated)

CLI, Writer, Runbook, Runtime, Live-Checks, Stage D und evidence-interne Provenienz bleiben unverändert offen.
