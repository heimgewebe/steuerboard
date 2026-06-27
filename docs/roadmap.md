# Roadmap

## Phase 0a — Masterplan verankert

Status: complete.

The repository contains the masterplan and README link that establish the planning anchor and core architecture rule.

## Phase 0b — prüfbare Mindeststruktur

Status: core structure plus complete masterplan Pflichtfall example coverage in this commit.

Create the falsification-first repository structure:

- documentation for source, freshness, local scope, redaction, security, and roadmap
- minimal JSON Schemas using Draft 2020-12
- example failure cases
- example validation script
- tests that run validation
- schema files checked against Draft 2020-12 when `jsonschema` is available

No productive scanner, CLI command surface, UI, backend, or action executor is part of this phase. This phase also includes static examples for non-failure-case schemas before Phase 1.

## Phase 1 — Read-only Observation CLI

Status: sealed.

Phase 1 includes a minimal single-repo read-only observation CLI:

```bash
python -m steuerboard observe repo <path> --json
```

The CLI observes only. It must not assess, decide, plan actions, fetch, switch branches, pull, or mutate repositories.

Stop cases now covered by explicit tests:

1. clean main — tracking origin/main, clean worktree, ahead/behind == 0
2. dirty main — tracked modified + untracked files present
3. feature branch — non-default branch, no upstream tracking
4. missing upstream — local branch with no remote tracking ref configured, ahead/behind/upstream all None
5. detached HEAD — `current_branch` is `None`, `head_sha` is present
6. remote missing — no origin configured, `remote_url` is `None`
7. wrong remote / remote identity observable — non-GitHub remote URL observable without assessment
8. empty/unborn repo — `git init` with no commits; `head_sha` is `None`

Open stop case (manual verification item):

- **dubious ownership** — git's `safe.directory` guard fires when the repo is owned by a different user. Triggering this portably requires either root access to change file ownership or manipulation of the global git config, which would affect the host environment. This case is left as a manual verification item until a safe portable approach is available.

## Phase 2 — Inventory & Scope (minimal slice)

Status: sealed.

Phase 2 now includes a minimal read-only inventory CLI:

```bash
python -m steuerboard inventory --json
```

This slice reads local config roots, observes local Git repository paths, and classifies local scope (`scope_canonical`, `scope_shadow`, `scope_backup`, `scope_gdrive`, `scope_unknown`, `scope_excluded`).

Phase 2 includes:

- `python -m steuerboard inventory --json`
- `python -m steuerboard inventory duplicates --json`
- `python -m steuerboard scope explain <path> --json`

Boundary for this slice:

- no assessment output
- no decision or planning fields
- no action execution
- no Omnipull integration

## Phase 3 — Assessment Engine (minimal slice)

Status: minimal slice started.

Phase 3 introduces a read-only assessment engine for a single local repository.
Assessment status is derived deterministically from Phase 1 observations and Phase 2
scope classifications. Runtime identifiers and observation timestamps are intentionally
time-dependent. No action planning, no execution, no network access.

PR #11 erzeugt Assessments. PR #11 erklärt diese noch nicht menschenlesbar.
PR #11 plant keine Aktionen. PR #11 führt keine Aktionen aus.

```bash
python -m steuerboard assess repo <path> --json
```

- `decision_state` is a **contractual enum** in the schema: `action_blocked`, `evidence_missing`, `assessment_clear`. Free strings are rejected.
- `clean_default_current` means current branch matches observed `default_branch_candidate`.
    Observation now exposes `default_branch_candidate_source`.
    If source is `remote_origin_head`, `default_branch_source` is not missing and confidence is `0.9`.
    Provenance refs in this branch are
    `assessment.rule.clean_default_current_remote_origin_head_local_source_observed`
    and `freshness.default_branch_source.remote_origin_head_local_observed`.
    Otherwise, the source gap remains marked via `missing_evidence: ["default_branch_source"]` with `confidence: 0.8`.
    Provenance refs remain
    `assessment.rule.clean_default_current_is_clear_but_default_source_unverified`
    and `freshness.default_branch_source.unverified`.
- `derived_status` is a proper list: non-canonical scope and `dirty_worktree` are both collected when observed together.

- `risk_level` — enum `low`, `medium`, `high`, `unknown`
- `skip_reasons` — normalised reason codes why action is blocked or deferred
- `confidence` — 0..1 confidence in derived_status
- `missing_evidence` — already present; expanded usage
- schema-optional, emitted by `assess_repo`: `rule_refs`, `freshness_refs`, `falsification_refs`
- assessment provenance refs are now attached for emitted status codes (rule/freshness/falsification when applicable)
- provenance is context-sensitive: when evidence sources are absent (e.g. `local_config.unavailable`),
  freshness is marked `unavailable` rather than `current_invocation` to avoid self-contradictory output
- ref lists are deduplicated in deterministic insertion order

Status cases implemented:

- `not_git_repo` — path is not a Git repository
- `scope_backup`, `scope_gdrive`, `scope_excluded`, `scope_unknown` — non-canonical scope
- `dirty_worktree` — uncommitted local changes
- `detached_head` — HEAD is not on any branch
- `default_branch_unknown` — default branch not determinable from observation
- `non_default_branch` — on a non-default branch, clean; missing_evidence set
- `clean_default_current` — canonical, clean, current branch matches observed `default_branch_candidate`; source gap remains only when `default_branch_candidate_source != remote_origin_head`

`decision_state` remains required and is an Assessment-Ergebnis, not an Action-Freigabe.
Values: `action_blocked`, `evidence_missing`, `assessment_clear`.

Boundary for this slice:

- read-only: no mutation, no fetch, no pull, no branch switch
- no action planning fields (`action`, `plan_id`, `would_run`, `would_mutate`, `safe_actions`, `safe_alternatives`, `command_trace`, `run_result`)
- no network operations
- no free shell execution
- no sudo

Open epistemic gaps:

- Residual boundary: `remote_origin_head` is a locally observed ref provenance signal, not a remote freshness proof. Assessment still does not claim network freshness without fetch.
- Richer human-readable assessment narratives remain deferred beyond the minimal `assess explain` contract; action advice remains out of scope.
- Assessment now cross-references rule_refs, freshness_refs, and falsification_refs (when applicable).
- `scope_shadow` remains an inventory/duplicates classification and is not emitted by single-path `assess repo` in this slice.

## Phase 5 — Plan Preview (minimal contract slice)

Status: minimal slice started.

Phase 5 adds assessment-artifact-only plan preview for `switch-main`:

```bash
python -m steuerboard plan switch-main <assessment-json> --json
```

This command derives `action-plan.v1` from existing `repo-assessment.v1` JSON.
It does not observe repositories, does not read local scope config, does not run
Git commands, and does not execute or authorise actions.
It is a pure transformation from `repo-assessment.v1` to `action-plan.v1` and
does not provide command advice.

Contract notes:

- `decision` is a plan result, not execution permission
- `not_applicable` means no switch is required (`clean_default_current`)
- `blocked` means blockers remain and no bypass advice is produced
- boundary fields are constant true: no execute, no mutate, no authorise

## Phase 4 — Assessment Explanations (minimal contract slice)

Status: minimal slice started.

Phase 4 minimal adds a read-only explanation contract for existing assessment output:

```bash
python -m steuerboard assess explain <assessment-json> --json
```

This slice adds `repo-assessment-explanation.v1` plus runtime/CLI support to explain
`derived_status` entries in bounded human-readable form.

Boundary for this slice:

- explanation is interpretation, not planning
- no action authorisation fields
- no action suggestions, no safe next steps
- no mutation, no network calls, no fetch/pull/switch/reset/clean
- missing evidence and epistemic gaps are preserved

Out of scope in this phase:

- planner outputs
- action suggestions
- command execution advice

## Phase 6a — Omnipull Report Read-only Adapter (minimal contract slice)

Status: minimal slice started.

Phase 6a adds a bounded artifact adapter for Omnipull reports:

```bash
python -m steuerboard omnipull-report show <report-json> --json
```

This command reads one explicitly provided JSON file and emits a validated
`omnipull-report.v1` artifact. It does not execute Git, mutate repositories,
or authorize actions.
The report `source_path` must match the explicit loaded artifact path.

Boundary for this slice:

- no `omnipull-report latest` command
- no path search or policy over `/home/alex/logs/omnipull`
- no fetch/pull/switch/reset/clean
- no network access
- no Git subprocess
- no action execution or action authorization
- no new plan generation from Omnipull report input
- no command advice

## Phase 6b — Omnipull Run-Index + strict `latest` lookup

Status: complete (merged).

Phase 6b adds an explicit run-index schema and a strictly bounded `latest`
lookup that operates only on one explicitly loaded run-index artifact:

```bash
python -m steuerboard omnipull-report latest <run-index-json> --json
```

The run-index contract is `omnipull-run-index.v1`. It lists report references
(each with `report_id`, `run_id`, `generated_at`, `source_path`) plus a boundary
block identical to `omnipull-report.v1`.

The `latest` selection rule is:

1. primary key: `generated_at` (descending — newest wins)
2. tie-break: `run_id` (descending lexicographic comparison)

The command emits an `omnipull-report-ref.v1` reference artifact carrying only
metadata copied from the selected index entry: `report_id`, `run_id`,
`source_path`, plus `selected_by: "latest.generated_at"`.

Boundary for this slice:

- `latest` works **only** against the explicit run-index artifact supplied on
  the command line
- no auto-loading of the referenced omnipull-report file
- no directory scanning, no glob, no `$PWD` walking, no environment lookups
- no path search under `/home/alex/logs/omnipull`
- no fetch/pull/switch/reset/clean
- no network access
- no Git subprocess
- no action execution or action authorization
- no new plan generation from Omnipull report or run-index input
- no command advice
- no canonicalization "smart" path matching — `source_path` must match the
  explicit path string passed to the command lexically
- `reports: []` is a valid run-index, but `latest` against an empty index
  raises a precise `ValueError`; there is no fallback discovery

Architecture rule reinforced by Phase 6b:

> The Omnipull adapter reads, validates, and references. It does not
> interpret, recommend, search, or execute.

## Phase 7a — Git Pull FF-only Action Contract

Status: started.

Scope:

- define a documentation-first contract blueprint for future single-repo
  `git pull --ff-only`
- no implementation in this phase
- no command execution in this phase

Subtasks:

- 7a.1 contract blueprint (complete): `docs/git-pull-ff-only-contract.md`
- 7a.2 pull-readiness assessment (complete): read-only derivation in `assess repo`
- 7a.3 plan preview (implemented): `plan git-pull-ff-only <assessment-json> --json`

7a.2 scope:

- derive pull readiness from existing local observation state only
- no fetch, no pull, no plan, no action execution
- add pull-readiness status vocabulary in assessment output
  - `git_pull_ff_only_local_preflight_clear`
  - `git_pull_ff_only_blocked_missing_upstream`
  - `git_pull_ff_only_blocked_branch_ahead`
  - `git_pull_ff_only_blocked_branch_diverged`
  - `git_pull_ff_only_evidence_missing_remote_freshness`

Not part of 7a.1 (later phases):

- schema updates
- CLI command additions
- execution runner
- UI integration

Implemented command shape:

```bash
python -m steuerboard plan git-pull-ff-only <assessment-json> --json
```

7a.3 scope is preview-only transformation from assessment artifact to
action-plan artifact. It does not execute Git and can remain blocked while
remote freshness evidence is missing.

Explicitly not yet:

- `steuerboard pull <repo>`
- `steuerboard do pull`
- automatic Omnipull execution
- fleet-wide mutating execution
- free shell execution
- destructive Git operations
- conflict resolution
- branch deletion
- reset/clean

Required future gates for `git-pull-ff-only`:

Preflight gates:

- repo is in canonical scope
- repository identity is known
- working tree is clean
- HEAD is not detached
- current branch is known
- current branch equals default branch
- upstream exists
- remote is known and acceptable
- remote freshness evidence exists
- branch is not ahead
- branch is not diverged
- fast-forward is possible
- ownership/dubious ownership state is acceptable
- action plan exists
- user approval exists

Execution evidence:

- command trace is recorded
- run-result is recorded
- stdout/stderr are bounded and redacted

Postcheck evidence:

- final HEAD is recorded
- final branch is still the expected default branch
- final worktree is clean
- ahead/behind state is recorded
- result explains whether the pull changed HEAD or was already current

Boundary statement:

A future `git-pull-ff-only` plan is not a generic pull abstraction.
It is a narrow mutating pilot with explicit preflight, approval,
execution trace, run-result, and postcheck.

## Phase 7b.1 — Remote Refresh Evidence Contract (fetch-only)

Status: minimal contract slice started.

Phase 7b.1 adds a bounded Stage B evidence artifact for remote freshness:

- model: `docs/remote-refresh-model.md`
- schema: `remote-refresh-result.v1`
- examples: fetch success and network-failed refresh outcomes

Scope in this slice:

- documentation for fetch-only remote freshness evidence
- JSON schema contract for refresh result artifacts
- static example artifacts for success/failure evidence
- validation and tests for schema/example integrity

Boundary for this slice:

- no productive fetch execution path in CLI yet
- no pull, merge, switch, reset, or clean
- no action authorization
- no execution runner
- no UI trigger

## Phase 7b.2 — Planner Consumes Remote-Refresh Evidence

Status: complete.

Phase 7b.2 extends the `plan git-pull-ff-only` command with optional
remote freshness evidence consumption.

New command shape:

```bash
python -m steuerboard plan git-pull-ff-only <assessment-json> \
  --remote-refresh-result <remote-refresh-json> --json
```

Scope in this slice:

- Strict validation of `remote-refresh-result.v1` artifacts
- Explicit repo_ref binding enforcement
- Planning gate satisfaction: successful remote refresh satisfies remote
  freshness evidence requirement in planner
- Provenance tracking: refresh evidence recorded in plan source_refs and
  freshness_refs
- Backward compatibility: existing behavior without `--remote-refresh-result`
  unchanged

Boundary for this slice:

- Planner remains preview-only; no execution authorization despite complete
  remote freshness evidence
- No fetch execution
- No pull execution
- No approval runner
- No command advice (no `would_run`, `would_mutate`, `safe_alternatives`,
  `required_evidence`)
- No Git subprocess
- No network access
- No repository mutation
- Pure artifact transformation: assessment + optional refresh evidence →
  action-plan

## Phase 7b.3 — Fetch-only Remote Refresh Producer

Status: complete.

Phase 7b.3 adds a bounded Stage B producer command that runs exactly one
fetch-only Git subprocess and emits evidence artifacts.

Command shape:

```bash
python -m steuerboard remote-refresh fetch-origin-prune <repo-path> \
  --config <local-config-json> \
  --assessment-id <assessment-id> \
  --command-trace-out <trace-json> --json
```

Scope in this slice:

- preflight gates before fetch (explicit repo/config/assessment/trace args,
  canonical scope gate, origin/HEAD/branch/worktree readability)
- blocked scope classes: `scope_backup`, `scope_gdrive`, `scope_shadow`,
  `scope_unknown`, `scope_excluded`
- exact execution surface:
  - `git -C <repo-toplevel> fetch origin --prune`
- redacted `command-trace.v1` artifact output
- emitted `remote-refresh-result.v1` artifact with explicit
  `repo_ref = repo-<assessment-id>` binding
- postcheck invariants for HEAD, current branch, and worktree status

Boundary for this slice:

- no pull, merge, rebase, switch, reset, clean
- no generic subprocess runner
- no generic git command execution surface
- no approval runner
- no action authorization
- no omnipull execution

## Phase 7b.4 — Pull Readiness End-to-End Proof

Status: complete.

Phase 7b.4 proves the non-mutating pull-antechamber chain end-to-end:

```text
assess repo
-> remote-refresh fetch-origin-prune
-> plan git-pull-ff-only --remote-refresh-result
```

Scope in this slice:

- reproducible local E2E tests with temporary Git repositories and a local bare
  origin only
- positive chain proof: successful fetch-only remote freshness evidence removes
  the remote-freshness planning blocker
- negative chain proof: failed/unavailable refresh evidence keeps the
  remote-freshness planning blocker
- explicit assertion that planner output remains preview-only and blocked for
  execution scope (`execution_authorization`, `runner_contract`,
  `user_approval` still missing; concrete future approval artifact form is
  `action-approval.v1`)

Boundary for this slice:

- no pull, merge, rebase, switch, reset, clean
- no approval runner
- no execution runner
- no UI
- no free shell execution
- no generic subprocess execution surface
- no generic Git command execution surface
- no Omnipull execution
- no action-plan semantics change that would authorize execution

## Phase 7c.1 — Action Approval Artifact Contract

Status: complete.

Phase 7c.1 introduces a narrow, expiring, plan-bound approval artifact:

- schema: `action-approval.v1`
- examples: approved and rejected approval artifacts
- validation/test wiring for approval schema and examples
- documentation model for approval semantics and boundary

Scope in this slice:

- schema, examples, validation, and docs only
- `action-approval.v1` as artifact, not command
- rejected approvals are first-class artifacts

Boundary for this slice:

- no runner
- no pull
- no execution
- no UI
- no generic subprocess surface
- no generic Git execution surface

## Phase 7c.2 — Action Approval Binding Validation

Status: started.

Phase 7c.2 adds a pure artifact validation slice that proves one approval binds
exactly to one plan:

- schema: `action-approval-validation.v1`
- module: `steuerboard/action_approval_validations.py` (pure function, no I/O)
- CLI: `python -m steuerboard approval validate <approval-json> --plan <plan-json> --checked-at <YYYY-MM-DDTHH:MM:SSZ> --json`
- examples: binding-valid, rejected, expired, plan-mismatch
- validation/test wiring for new schema and examples

Scope in this slice:

- pure artifact validation only
- `checked_at` is always explicit; no hidden system time
- `binding_state: binding_valid` means only: approval matches plan, is approved,
  and is time-valid at `checked_at`; it does NOT mean execution is allowed

Boundary for this slice:

- no runner
- no pull
- no execution
- no UI
- no repo observation
- no config read
- no Git subprocess
- no network
- no mutation
- no command advice
- no execution authorisation

## Phase 8A — Read-only Action Runner / Run Evidence Pilot

Status: started.

Phase 8A introduces the first bounded execution evidence slice. It proves that
a hard-coded read-only action can be executed, traced, and verified — without
authorising mutation.

Command:

```bash
python -m steuerboard action run-read-only <action-plan-json> \
  --repo-path <repo-path> \
  --command-trace-out <trace-json> \
  --run-result-out <run-result-json> \
  --json
```

Scope in this slice:

- single pilot action: `git-status-read-only`
  (hard-coded productive traced command:
  `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`)
- preflight Git commands (`rev-parse`) are hard-coded and read-only; they are
  not the productive traced command
- action plan must be schema-valid (`action-plan.v1`)
- action must be in Phase 8A allowlist (exactly `git-status-read-only`)
- all mutating actions (`git-pull-ff-only`, `switch-main`) are explicitly blocked
- output paths validated before any execution: parent must exist, target must not
- `command-trace.v1` artifact written with redaction flag set
- `run-result.v1` artifact written referencing the trace path
- stdout/stderr excerpts bounded to 2000 characters each
- exit code normalised (signal → 128+abs)
- on precondition failure: no partial output written

New module: `steuerboard/action_runs.py`

Boundary for this slice:

- no mutating Git actions
- no pull, fetch, switch, merge, rebase, reset, clean
- no free shell, no sudo, no network
- no generic subprocess surface
- no approval runner
- no execution authorisation
- no UI
- `does_not_execute`, `does_not_mutate`, `does_not_authorise_actions` remain
  true in plan artifacts produced by Phase 5/7a planners

## Phase 8B — Run Postcheck + Run Record Binding

Status: started.

Phase 8B introduces a bounded read-only postcheck that validates prior run
evidence and emits `run-postcheck.v1`.

Scope in this slice:

- new schema: `run-postcheck.v1`
- new module: `steuerboard/run_postchecks.py`
- CLI: `python -m steuerboard action postcheck-read-only ... --json`
- examples and tests for passed/failed/inconclusive postcheck outputs

Boundary for this slice:

- no mutating Git actions
- no pull, fetch, switch, merge, rebase, reset, clean
- no free shell, no sudo, no network
- no generic subprocess surface
- no approval runner
- no execution authorisation
- no UI
- output must be outside the inspected repository worktree

## Phase 8C — Run Evidence Chain Verifier

Status: started.

Phase 8C adds a pure artifact verifier for the read-only chain produced by the
existing run evidence. This phase does not execute anything new. It checks chain
integrity only.

Premise:

- Stage D remains future-only.
- `git pull --ff-only` is still not implemented here.

Command:

```bash
python -m steuerboard action validate-run-chain <action-plan-json> \
  --command-trace <trace-json> \
  --run-result <run-result-json> \
  --run-postcheck <postcheck-json> \
  --chain-out <chain-json> \
  --json
```

Scope in this slice:

- new schema: `run-evidence-chain.v1` (evidence/validation artifact only)
- new module: `steuerboard/run_evidence_chains.py`
- supports only `git-status-read-only`
- fully schema-validates `action-plan.v1`, `command-trace.v1`, `run-result.v1`,
  and `run-postcheck.v1`
- verifies exact hardened trace command shape
- verifies `command-trace.v1.exit_code == 0`
- verifies trace/result/postcheck redaction flags
- verifies `run-result.v1.status == success`
- verifies `run-result.v1.run_id == run-postcheck.v1.run_id`
- verifies `run-result.v1.evidence_paths` includes the supplied trace path
- verifies `run-postcheck.v1.trace_ref == command-trace.v1.trace_id`
- verifies `run-postcheck.v1.run_result_ref == run-result.v1.run_id`
- emits `plan_binding_unavailable` when plan-to-run binding is not provable from
  the available artifacts
- maps postcheck outcomes onto chain `status: valid | invalid | inconclusive`

Meaning of `valid` in this phase:

- the evidence chain is internally coherent
- it is not execution permission
- it does not authorise pull
- without proven plan binding the chain remains `inconclusive`, not `valid`

Boundary for this slice:

- no subprocess calls
- no Git commands
- no network
- no mutation
- no approval runner
- no execution authorisation
- no UI
- `--chain-out` parent must exist and target must not pre-exist
- `--chain-out` must stay outside the inspected repo when `repo_toplevel` is known

Stage D remains future-only after this phase.

## Phase 8D.1 — Action Preflight Binding (artifact bridge)

**Status:** started
**Schema:** `action-preflight-binding.v1`
**CLI:** `python -m steuerboard action bind-preflight-to-action`

Phase 8D.1 introduces the `action-preflight-binding.v1` artifact — a pure
artifact-level bridge that binds a `git-pull-ff-only` action plan to a
`git-status-read-only` run evidence chain. It exists so that the preflight
relationship between the two artifacts becomes explicit and auditable rather
than implicit.

Scope:

- new schema: `action-preflight-binding.v1`
- new module: `steuerboard/action_preflight_bindings.py` (pure function, no I/O
  beyond reading the two input dicts and atomically writing the output file)
- CLI: `python -m steuerboard action bind-preflight-to-action ... --json`
- examples for inconclusive and three blocked variants
- optional `--preflight-binding` argument added to
  `python -m steuerboard action validate-execution-readiness`

Binding state contract:

- `binding_valid` is reserved for the case where the chain provably belongs to
  the supplied pull plan from contract-defined fields. In the current slice
  this is not achievable, because `run-evidence-chain.v1.action` is fixed to
  `git-status-read-only` and the chain exposes no field that references the
  pull plan.
- `binding_invalid` means at least one hard gate fails (unsupported plan
  action, unsupported chain action, chain status invalid, chain redaction
  unverified, or binding material mismatches).
- `binding_inconclusive` is the honest result for the standard
  pull-plan-plus-status-chain combination: the artifacts do not contain
  contract-defined fields that prove binding.

Phase 8D.1 is not execution.
Phase 8D.1 is not authorisation.
Phase 8D.1 is not a pull gate.

Boundary:

- no subprocess calls
- no Git commands
- no network
- no mutation
- no approval runner
- no execution authorisation
- output artifact always carries `does_not_execute=true`,
  `does_not_mutate=true`, `does_not_authorise_actions=true`
- `--binding-out` parent must exist and target must not already exist

Phase 8D.0 readiness without `--preflight-binding` is unchanged: best
achievable status remains `inconclusive` with
`preflight_chain_plan_binding_unproven`.

## Phase 8D.2 — Contract-defined Preflight Proof Material

**Status:** started
**Schemas:** `run-result.v1`, `run-evidence-chain.v1`, `action-preflight-binding.v1`
**CLI:** `python -m steuerboard action run-read-only ... --preflight-for-action-plan <pull-plan-json>`

Phase 8D.2 introduces a single, contract-defined object —
`preflight_for_action_plan` — that proves a `git-status-read-only` run evidence
chain was produced as preflight for a specific `git-pull-ff-only` action plan.
It closes the epistemic gap Phase 8D.1 had to record honestly: in Phase 8D.1
the binding could never emit `binding_valid` because no contract-defined field
tied a read-only chain to a pull plan.

Scope:

- add an optional `preflight_for_action_plan` object to:
  - `run-result.v1`
  - `run-evidence-chain.v1`
  - `action-preflight-binding.v1`
- extend `action run-read-only` with `--preflight-for-action-plan <pull-plan-json>`
- propagate proof from `run-result.v1` into `run-evidence-chain.v1`
- accept proof in `bind-preflight-to-action`:
  - `binding_valid` when proof matches plan_ref / plan_action / plan_content_sha256
  - `binding_invalid` (with `binding_mismatch`) when proof is present but any field mismatches
  - `binding_inconclusive` when proof is absent (preserves pre-8D.2 behaviour)
- `validate-execution-readiness` consumes `binding_valid` only when the
  binding artifact carries the proof object
- new examples cover the binding-valid case and three binding-invalid
  mismatch cases plus the inconclusive (no-proof) case

Proof object shape:

```json
{
  "preflight_for_action_plan": {
    "plan_ref": "<pull-plan.plan_id>",
    "plan_action": "git-pull-ff-only",
    "plan_content_sha256": "<canonical_json_sha256 of pull plan>"
  }
}
```

Why `plan_content_sha256` is required:

- without a content hash, binding tracks only `plan_id`, which leaves a plan
  free to change content without invalidating prior preflight evidence
- the canonical hash is `canonical_json_sha256` — the same canonical hash
  used by `run-result.v1.plan_content_sha256` and
  `action-approval.v1.plan_content_sha256`; Phase 8D.2 does not introduce a
  second canonical hash implementation

Phase 8D.2 is not execution.
Phase 8D.2 is not authorisation.
Phase 8D.2 is not a runner.

Boundary:

- no subprocess additions to pure binding modules
- no Git mutation; the executed command in Phase 8A is unchanged
- no fetch, no pull, no merge, no rebase, no reset, no clean
- no network access added
- output artifacts always carry `does_not_execute=true`,
  `does_not_mutate=true`, `does_not_authorise_actions=true`
- artifacts produced before Phase 8D.2 remain schema-valid and continue to
  produce `binding_inconclusive`; only artifacts that explicitly carry the
  proof object can yield `binding_valid`

## Phase 8D.0 — Stage-D Execution Readiness

**Status:** started
**Schema:** `action-execution-readiness.v1`
**CLI:** `python -m steuerboard action validate-execution-readiness`

Phase 8D.0 introduces the `action-execution-readiness.v1` artifact — a pure
readiness gate that validates whether an action plan, an approval validation,
and a preflight run evidence chain together satisfy the Stage-D conditions for
executing the supported action (`git-pull-ff-only` only in this slice).

Scope:

- validate all three prerequisite artifact types against their schemas
- evaluate seven named readiness gates (plan action supported, approval binding
  valid, approval plan ref match, approval action match, chain status valid,
  chain redaction verified, preflight chain plan binding proven)
- emit `action-execution-readiness.v1` artifact with status `ready | blocked |
  inconclusive`
- in this slice, `run-evidence-chain.v1` always records `git-status-read-only`;
  plan binding to `git-pull-ff-only` is structurally unproven → status is at
  best `inconclusive` with `preflight_chain_plan_binding_unproven`

Boundary:

- no subprocess calls
- no Git commands
- no network
- no mutation
- no approval runner
- no execution authorisation
- output artifact always carries `does_not_execute=true`,
  `does_not_mutate=true`, `does_not_authorise_actions=true`

## Phase 8E — Stage-D git-pull-ff-only Executor

Phase 8E activates Stage D for exactly one mutating action: `git-pull-ff-only`.
It introduces `steuerboard/action_git_pull.py` and the CLI subcommand
`action run-git-pull-ff-only`.

### What the runner does

Given four input artifacts — `action-plan.v1`, `action-approval-validation.v1`,
`run-evidence-chain.v1`, and `action-preflight-binding.v1` — the runner:

1. Schema-validates all four input artifacts.
2. Asserts `action_plan.action == "git-pull-ff-only"`.
3. Asserts `preflight_binding.binding_state == "binding_valid"` and that a
   `preflight_for_action_plan` proof object is present, then verifies the proof
   binds (plan_ref, plan_action, plan_content_sha256) to the supplied plan.
4. Checks all three output paths: must not exist, parents must exist, all distinct.
5. Resolves the git worktree toplevel via `git rev-parse --show-toplevel` and
   asserts no output path is inside the worktree.
6. **Internally reproduces** the Stage-D readiness gate by calling
   `validate_execution_readiness()` inside a `TemporaryDirectory`.  The runner
   never trusts a pre-computed `action-execution-readiness.v1` artifact — only
   if the four underlying artifacts together prove `status == "ready"` will
   the pull proceed.
7. Requires the run evidence chain and preflight binding proof to carry the
   same `repo_toplevel`, then verifies that `--repo-path` resolves to that git
   toplevel. This binds the approved evidence to the repository being mutated.
8. Checks that the worktree is clean (`git status --porcelain=v1` empty) before
   any mutation.
9. Records `HEAD` before the pull.
10. Executes exactly one mutating Git subprocess call:
   `["git", "--no-optional-locks", "-C", <toplevel>, "pull", "--ff-only"]`.
   Read-only pre/post checks are separate non-mutating subprocess calls.
   No `shell=True`.  No merge, rebase, reset, or clean.

### Output artifacts

On any precondition failure no output artifacts are written and no Git
mutation occurs.  The CLI may still emit a redacted blocked `run-result.v1`
sentinel to stdout.
On execution the runner writes three artifacts atomically (with a rollback
chain on partial failure):

- **`command-trace.v1`** — records the exact command, exit code, and stdout/
  stderr excerpts.
- **`run-result.v1`** — records `action: git-pull-ff-only`, `status`, plan
  hash, and timestamps.
- **`run-postcheck.v1`** — records `action: git-pull-ff-only`, postcheck
  status, and (on success) `head_before`/`head_after` observations.

### Postcheck status semantics

| Condition | `run_result.status` | `postcheck.status` | Reason code |
|---|---|---|---|
| `git pull` exit code ≠ 0 | `failure` | `failed` | `pull_exit_code_nonzero` |
| "Already up to date" (explicit git output) | `success` | `inconclusive` | `already_up_to_date` |
| HEAD unchanged without explicit up-to-date output | `success` | `inconclusive` | `head_unchanged_after_pull` |
| HEAD unreadable after pull | `success` | `inconclusive` | `head_unreadable_after_pull` |
| Post-pull status check error | `success` | `inconclusive` | `post_pull_status_check_failed` |
| Worktree dirty after pull | `failure` | `failed` | `worktree_not_clean_after_pull` |
| All checks pass | `success` | `passed` | — |

### Boundary

Phase 8E makes exactly one **mutating** Git subprocess call under a single,
statically-known argv vector (`--ff-only`).  Read-only pre/post checks
(worktree status, HEAD rev-parse) are separate non-mutating subprocess calls.
Phase 8E does not expand the action allowlist further,
does not introduce `switch-main` execution, and does not remove the Phase 8A
read-only runner.

## Phase 9A — Switch-main Execution Readiness (non-mutating)

Phase 9A introduces the **non-mutating** readiness/proof layer for a future
`switch-main` action. It is the switch-main analogue of the Phase 8D.0
`action-execution-readiness.v1` pull gate, and the deliberate proof belt that
must exist before any future switch-main executor (Phase 9B).

It introduces `steuerboard/action_switch_main_readiness.py`, the CLI subcommand
`action validate-switch-main-readiness` (classified `derivation_only`), and two
schema-validated artifacts:

- `switch-main-preflight-proof.v1` — input proof material carrying the plan
  binding (`plan_ref`, `plan_action`, `plan_content_sha256`) plus observed
  repository-state claims (`repo_toplevel`, `current_branch`, `default_branch`,
  `branch_contains_origin_main_or_pr_merged`, `worktree_clean`, `remote_main_fresh`,
  `ownership_ok`).
- `switch-main-readiness.v1` — output verdict: `ready` / `blocked` /
  `inconclusive`.

### What the validator does

Given a `switch-main` `action-plan.v1` and a `switch-main-preflight-proof.v1`,
the validator:

1. Schema-validates both inputs.
2. Asserts `action_plan.action == "switch-main"` (else `unsupported_action`).
3. Verifies the proof binds to the plan: `plan_ref`, `plan_action`, and
   `plan_content_sha256 == canonical_json_sha256(action_plan)`.
4. Evaluates the observed state gates: `repo_toplevel`/`current_branch`/
   `default_branch` known, `default_branch == main`, branch lifecycle proof when
   `current_branch != main`, `worktree_clean`, `remote_main_fresh`, `ownership_ok`.
5. Emits `switch-main-readiness.v1` with `ready` only when every hard gate
   passes and all proof material is present and consistent; `blocked` on any
   hard contradiction (hard failures dominate unknowns); `inconclusive` when
   material is merely unknown.

### Decision contract

As in Phase 8D.0, the plan's own `decision` is not an independent readiness
blocker. Readiness is a pure evidence gate over proof material and plan binding,
orthogonal to whether a switch is needed. A `ready` verdict proves that a later
switch could be evaluated; it is never permission to switch.

### Boundary

Phase 9A makes **no** Git subprocess calls of any kind — the module imports no
subprocess surface, so it cannot switch, checkout, merge, rebase, reset, clean,
or pull. It does not execute, does not switch a branch, does not mutate, and
does not authorise actions. Every produced artifact carries const-true boundary
flags.

Phase 9A does **not** introduce a `switch-main` runner; it is the readiness/proof
layer only. `plan switch-main` stays `derivation_only`. The bounded `switch-main`
executor is a separate slice (Phase 9B, below). The full contract is in
`docs/switch-main-readiness-contract.md`.

## Phase 9B — Switch-main Executor

Status: implemented.

Phase 9B activates Stage D for the second bounded mutating action, `switch-main`.
It introduces `steuerboard/action_switch_main.py` and the CLI subcommand
`action run-switch-main` (classified `mutating_stage_d`), the switch-main
analogue of the Phase 8E pull executor narrowed to exactly one safe branch
switch to `main`.

The layered boundary is explicit:

> `ready` readiness is not approval. Approval is not execution. Execution is
> exactly one bounded branch switch to `main`. Postcheck is required after
> execution.

Command:

```bash
python -m steuerboard action run-switch-main <action-plan-json> \
  --config <local-config-json> \
  --approval-validation <action-approval-validation-json> \
  --switch-main-readiness <switch-main-readiness-json> \
  --repo-path <repo-path> \
  --command-trace-out <trace-json> \
  --run-result-out <run-result-json> \
  --postcheck-out <postcheck-json> \
  --json
```

Scope in this slice:

- consume a `ready` `switch-main-readiness.v1` (Phase 9A) and a `binding_valid`
  `action-approval-validation.v1`, both pinned to the same `switch-main` plan
  (plan ref, action, and the readiness-recorded plan content hash)
- re-derive the mutation-critical live state immediately before mutation
  (resolved toplevel matches readiness `repo_toplevel`; current branch known and
  not detached; worktree clean; readiness `branch_lifecycle_proof` required when
  the live branch is not `main`); **no fetch** — freshness/ownership trusted from
  the readiness artifact
- exact execution surface: `git --no-optional-locks -C <repo-toplevel> switch main`
- write `command-trace.v1`, `run-result.v1` (`action: switch-main`), and
  `run-postcheck.v1` (`action: switch-main`) atomically; precondition failures
  write nothing and perform no mutation
- additive schema extensions only: `switch-main` added to the `action` enum of
  `run-result.v1`, `run-postcheck.v1`, and `action-approval-validation.v1`

Boundary for this slice:

- no generic Git executor, no free shell, no `shell=True`
- no `git checkout` fallback, merge, rebase, reset, clean, pull, fetch, push,
  branch deletion, or conflict resolution
- no UI trigger, no fleet/multi-repo switching
- does not loosen the Phase 9A readiness gate; `plan switch-main` stays
  `derivation_only`
- Stage D now contains exactly two bounded executors: `run-git-pull-ff-only` and
  `run-switch-main`

The full contract is in `docs/switch-main-readiness-contract.md`
(Phase 9B Execution Implementation).

## Phase 10A — Read-only UI Display Contract + View-Model Layer

Status: implemented.

Phase 10A is the first, contract-first slice of the Phase 10 read-only UI. It
proves *displayability without action*: steuerboard artifacts can be shown
faithfully through a thin presentation film that carries no authority of its own.
It adds a display contract, a schema-validated UI view model, derived examples,
and a minimal dependency-free read-only scaffold — and nothing that can act.

Artifacts:

- contract: `docs/ui-readonly-contract.md`
- schema: `ui-view-model.v1` (`schemas/ui-view-model.v1.schema.json`)
- examples: `examples/ui-view-models/` (`cli-surface-summary`,
  `switch-main-readiness-ready-view`, `run-switch-main-success-view`,
  `blocked-readiness-view`)
- scaffold: `frontend/index.html` (static, dependency-free read-only renderer)
  plus an updated `frontend/README.md`
- tests: `tests/test_ui_view_models.py`

Scope in this slice:

- a UI view model is bounded display material derived from an existing artifact;
  it is not canonical repository state and not an action approval
- every view model carries a const-true boundary (`does_not_execute`,
  `does_not_mutate`, `does_not_authorise_actions`, `display_only`)
- the schema is strict (`additionalProperties: false` everywhere) and defines no
  command, `argv`, endpoint, method, approval-decision, or execution field
- the static scaffold renders one pasted `ui-view-model.v1` document read-only,
  refusing anything whose boundary is not display-only
- parity: the CLI-surface summary view's counts are tested against the real
  capability classification; `ready` displays as proof, never permission;
  blocked/inconclusive/unknown are never softened

Boundary for this slice:

- no action buttons, no approval UI, no execute UI
- no backend, no server, no localhost/LAN bind
- no Git, no subprocess, no shell, no network mutation, no action endpoint
- no `POST`/`PUT`/`PATCH`/`DELETE` for actions
- no new mutating command; Stage D stays at exactly two executors
  (`action run-git-pull-ff-only`, `action run-switch-main`)

Out of scope (future, separately-contracted phases):

- a productive backend or local server (any server must bind `127.0.0.1` only)
- UI-triggered actions (Stage E in `docs/action-model.md`)
- approval UI, fleet/multi-repo views, richer interactive UI

The full contract is in `docs/ui-readonly-contract.md`.

## Phase 11A — Read-only Runbook Starter: repo-sync-gate

Status: implemented.

Scope:
- runbook-plan.v1
- runbook-result.v1
- runbook-step-trace.v1
- CLI: python -m steuerboard runbook run <runbook-plan-json> --result-out <result-json> --command-trace-out <trace-jsonl> --json
- exactly one runbook kind: repo-sync-gate
- read-only/derivation-only only

Boundary:
- no mutating action
- no Stage-D executor call
- no Git mutation
- no fetch/pull/switch
- no backend/server/UI trigger

## Phase 11B — Read-only Runbook Starter: dns-gate

Status: implemented.

Scope:
- add dns-gate as second runbook kind in runbook-plan.v1 and runbook-result.v1
- add dns_checks contract for dns-gate inputs (required for dns-gate plans)
- implement read-only local resolver checks via Python stdlib (`socket.getaddrinfo`)
- emit runbook-result.v1 and runbook-step-trace.v1 JSONL artifacts
- add passed / blocked / inconclusive examples and deterministic tests with mocked resolver
- keep `python -m steuerboard runbook run ...` as the only runbook CLI entrypoint (no new CLI command)

Boundary:
- no DNS configuration mutation (`/etc/resolv.conf`, resolver services, Pi-hole/Unbound/systemd-resolved/NetworkManager)
- no Stage-D executor call
- no Git mutation
- no fetch/pull/switch/reset/clean/merge/rebase/push
- no backend/server/UI trigger
- no shell=True or generic command runner

## Phase 11C — Read-only Runbook Starter: ssh-gate

Status: implemented.

Scope:
- add ssh-gate as third runbook kind in runbook-plan.v1 and runbook-result.v1
- add ssh_checks contract for ssh-gate inputs (required for ssh-gate plans)
- implement read-only local TCP reachability checks via Python stdlib (`socket.create_connection`)
- emit runbook-result.v1 and runbook-step-trace.v1 JSONL artifacts
- add passed / blocked / inconclusive examples and deterministic tests with mocked sockets
- keep `python -m steuerboard runbook run ...` as the only runbook CLI entrypoint (no new CLI command)

Boundary:
- no ssh subprocess invocation
- no SSH authentication or key handling
- no remote command execution
- no Stage-D executor call
- no Git mutation
- no fetch/pull/switch/reset/clean/merge/rebase/push
- no backend/server/UI trigger
- no shell=True or generic command runner

Stage D remains exactly two mutating executors:
- action run-git-pull-ff-only
- action run-switch-main

## Phase 11D — Read-only Runbook Starter: tailscale-preflight

Status: implemented.

Scope:
- add tailscale-preflight as fourth runbook kind in runbook-plan.v1 and runbook-result.v1
- add tailscale_checks contract for tailscale-preflight inputs (required for tailscale-preflight plans)
- implement read-only local resolver checks via `socket.getaddrinfo`
- implement optional read-only TCP reachability checks via `socket.create_connection` when `port` is present
- emit runbook-result.v1 and runbook-step-trace.v1 JSONL artifacts
- add passed / blocked / inconclusive examples and deterministic tests with mocked sockets
- keep `python -m steuerboard runbook run ...` as the only runbook CLI entrypoint (no new CLI command)

Boundary:
- no tailscale CLI invocation
- no Tailscale API access
- no auth/key/socket/state-file access
- no route/DNS/firewall mutation
- no subprocess execution for runbook evaluation
- no Stage-D executor call
- no Git mutation
- no fetch/pull/switch/reset/clean/merge/rebase/push
- no backend/server/UI trigger
- no shell=True or generic command runner

Stage D remains exactly two mutating executors:
- action run-git-pull-ff-only
- action run-switch-main

## Phase 11E — Read-only Runbook Starter: server-facts-snapshot

Status: implemented.

Scope:
- add server-facts-snapshot as fifth runbook kind in runbook-plan.v1 and runbook-result.v1
- add server_facts_options contract for server-facts-snapshot inputs
- implement read-only host/runtime facts snapshot via Python stdlib metadata access (`platform`, `sys`, bounded `os` process-context calls)
- emit runbook-result.v1, runbook-step-trace.v1 JSONL, and `server-facts.v1` artifact via `server-facts.json`
- add passed examples and deterministic tests for success, failure reason-codes, output collision, rollback behavior, and no-network boundaries
- keep `python -m steuerboard runbook run ...` as the only runbook CLI entrypoint (no new CLI command)

Boundary:
- no subprocess execution
- no shell=True or generic command runner
- no network probe
- no `socket.getfqdn()` — FQDN is explicitly not collected
- no SSH
- no Tailscale
- no `systemctl`
- no daemon/service management
- no service evaluation
- no service gate
- no Stage-D executor call
- no Git mutation
- no fetch/pull/switch/reset/clean/merge/rebase/push
- no backend/server/UI trigger

Output collision protection:
- `server-facts.json` must not collide with `result_out` or `command_trace_out`
- `server-facts.json` must not already exist

Rollback:
- `server-facts.json` is removed on subsequent failure to prevent orphaned incomplete output sets

Stage D remains exactly two mutating executors:
- action run-git-pull-ff-only
- action run-switch-main

## Phase 11F-A — Heimserver-Service-Gate design contract

Status: design-only / future-gated.

Scope:
- document the future Heimserver-Service-Gate boundary
- distinguish it from implemented `server-facts-snapshot`
- define open decision: artifact-derived gate vs bounded local live check
- list prerequisites before any implementation

Non-goals:
- no runtime implementation
- no schema enum addition
- no CLI
- no service checks
- no Stage-D action

## Phase 11F-B — Heimserver-Service-Gate artifact-derived contract

Status: done.

- added `heimserver-service-gate-assessment.v1.schema.json`
- added passed, blocked, and inconclusive examples
- added boundary tests to ensure no runtime/runbook leaks
- option A (artifact-derived) is fixed for this phase
- option B (live check) and runbook/runtime integration remain future-gated

## Phase 11F-C — Producer Preimage Boundary

Status: design/decision-prep / future-gated.

Scope:
- define the producer preimage / field-lineage contract for `heimserver-service-gate-assessment.v1`
- document which assessment fields must be derivable from which input artifacts (`server_facts_ref`, `expectation_ref`) or fixed contract rules
- document which fields must not claim to prove live truth (`does_not_prove`)
- add a documentation/schema guard test for the boundary
- record the missing `heimserver-service-expectation.v1` schema as an explicit open gap

Non-goals:
- no runtime producer
- no runbook kind
- no CLI
- no service checks
- no Stage-D action
- no live network / SSH / Tailscale / systemctl / subprocess

## Phase 11F-D — Heimserver-Service-Expectation Contract

Status: done (contract only).

Closes the asymmetry surfaced by 11F-C: the assessment output was contracted, the expectation input was not.

Scope:
- add `schemas/heimserver-service-expectation.v1.schema.json` (the `expectation_ref` input contract)
- wire it into the validator (`SCHEMA_MAP`) so the example validates
- migrate `examples/heimserver-service-expectations/minimal-tailscale.json` (add `schema_version`) and re-hash `inputs.expectation_ref.sha256` in all five assessment fixtures
- add expectation contract tests (validation, required fields, `scope` const, no additional properties, hash consistency)

Design decision: Variant A′ — `schema_version` (universal repo convention) but no top-level `kind` (which only the assessment carries; the co-input `server-facts.v1` omits it).

Non-goals:
- no runtime producer
- no runbook kind
- no CLI
- no service checks
- no Stage-D action
- no live network / SSH / Tailscale / systemctl / subprocess / socket
- no change to `SUPPORTED_RUNBOOK_KINDS`, `runbook-plan.v1`, or `runbook-result.v1`

## Phase 11F-E — Heimserver-Service-Evidence Contract

Status: done (contract only).

Closes the last preimage gap after 11F-D: the admissible artifact from which `evaluated_services` may later be derived, without any live check. Avoids the false-coherence trap of building a producer before a legitimate evidence artifact exists.

Scope:
- add `schemas/heimserver-service-evidence.v1.schema.json` (the `service_evidence_ref` input contract)
- add `examples/heimserver-service-evidence/minimal-artifact-only.json`
- wire it into the validator (`SCHEMA_MAP`) and register the example in `tests/test_schema_examples.py`
- add evidence contract tests (validation, required fields, `scope` const, strict UTC-Z `observed_at`, no additional properties, pure-input guard, no runbook leak)

Design: reuses the 11F-D envelope decision (`schema_version`, no `kind`). Descriptive `evidence_status` (`present` / `missing` / `mismatch` / `unknown`) and a dedicated `service_evidence_*` reason-code namespace, decoupled from the assessment's verdict vocabulary. Assessment integration (`inputs.service_evidence_ref`) deferred to a later phase.

Non-goals:
- no runtime producer / no producer-preimage deriver
- no runbook kind
- no CLI
- no service checks
- no Stage-D action
- no live network / SSH / Tailscale / systemctl / subprocess / socket / shell
- no change to `SUPPORTED_RUNBOOK_KINDS`, `runbook-plan.v1`, or `runbook-result.v1`
- no assessment-schema rebuild in this phase

## Phase 11F-F — Assessment Evidence Input Integration

Status: done (contract integration only).

Connects the 11F-E evidence input to the assessment so the assessment's direct input-reference set is complete (evidence-internal provenance remains future work).

Scope:
- `schemas/heimserver-service-gate-assessment.v1.schema.json`: add `inputs.service_evidence_ref` (`path` + `sha256` `^[0-9a-f]{64}$`, `additionalProperties: false`) and add it to `inputs.required`
- migrate all five assessment fixtures with a real `service_evidence_ref` sha256
- extend the input-hash guard to all three refs; add negatives (missing `service_evidence_ref`, malformed sha256) and boundary tests (closed `inputs` / top level)
- docs: record 11F-F and the completed assessment preimage references

Non-goals:
- no producer / derivation script
- no runbook kind
- no CLI
- no Stage-D action / executor
- no service probe / live check
- no live network / SSH / Tailscale / systemctl / subprocess / socket / shell
- no change to `SUPPORTED_RUNBOOK_KINDS`, `runbook-plan.v1`, or `runbook-result.v1`
- no status-semantics change, no `$ref`/`$defs`, no `format: date-time`, no rename of `passed`

## Phase 11F-G — Heimserver Service Gate Derivation Readiness Contract

Status: implemented (contract and reference validation only).

Schafft die kausalen Voraussetzungen, damit ein Producer eindeutig aus den Artefakten ableiten kann.
Scope:
- Einführung des `heimserver-service-gate-derivation-case.v1` Vertrages und eines dedizierten Cross-Artifact-Validators.
- `freshness_status` als Required Field in Evidence eingeführt.
- Strenge Enum-Partitionen für Reason-Codes (Status-Kapselung) und `uniqueItems` Arrays.
- Exakte `does_not_prove` 4-Element-Liste.
- Maschinengeprüftes, exaktes Golden Case Inventar (14 Fälle).
- Loader/Derivation-Grenzziehung vertraglich fixiert (Host-Identity, Service-Join).

Non-goals:
- Kein Producer, keine CLI, kein Runbook, keine Live-Prüfung.
- Keine I/O Integration, kein Netzwerk, keine Systemzeit.

## Phase 11F-H — Heimserver Service Gate Producer In-Memory

Status: implemented (pure in-memory producer only)

Scope:
- Implementierung der reinen In-Memory-Ableitung aus den validierten 11F-G Inputartefakten.
- Erfüllung des exakten 11F-G Case Inventars.
- Output ist ein korrektes Assessment-Artefakt.
- Keine CLI-, Runbook- oder Liveintegration als erledigt markieren.

## Phase 11F-I — Safe Artifact Input Adapter

Status: implemented (safe artifact adapter only)

Macht den reinen 11F-H-Producer erstmals kontrolliert über explizite, artifact-root-relative Artefaktverweise erreichbar.

Scope:
- neues Modul `steuerboard/heimserver_service_gate_artifacts.py` mit genau einer öffentlichen Adapterfunktion (`derive_heimserver_service_gate_assessment_from_refs`) und einer Fehlerklasse (`HeimserverServiceGateArtifactError`).
- prüft exakt drei `input_refs`; löst Pfade sicher innerhalb eines erlaubten `artifact_root` auf (statische Root-Escape- und Symlink-Abwehr).
- liest jede Datei genau einmal als Rohbytes, bindet SHA-256 über exakt diese Bytes, dekodiert dieselben Bytes streng als UTF-8 und JSON (Ablehnung doppelter Schlüssel und nicht endlicher Zahlen).
- validiert die drei Payloads vollständig mit `Draft202012Validator` gegen die kanonischen Schemas; die Schemas stammen aus dem steuerboard-Checkout, nicht aus `artifact_root` (Contract Authority).
- ruft den unveränderten Producer genau einmal auf und validiert dessen Assessment gegen das Assessment-Schema; Rückgabe ausschließlich im Speicher.
- alle 14 Golden Cases werden über den Adapter reproduziert; technische Ladefehler sind keine Assessment-Reason-Codes.

Non-goals:
- keine CLI, kein Writer, kein Runbook-Kind, keine Runtime-Integration, keine Live-Prüfung, keine Stage-D-Action.
- keine neue externe Abhängigkeit, keine Packaging-Reform, kein Dateigrößenlimit, keine evidence-interne Provenienz.
- kein vollständiger Schutz gegen einen gleichzeitig agierenden Akteur mit Schreibrechten im Artifact-Root (TOCTOU; Schreibrechte genügen, Systemprivilegien nicht zwingend erforderlich).

## Phase 11F-J — Safe Assessment Artifact Writer

Status: implemented (safe single-assessment writer only)

Persistiert ein bereits im Speicher erzeugtes `heimserver-service-gate-assessment.v1` deterministisch als JSON-Artefakt, ohne Inputartefakte zu laden oder Producer/Adapter aufzurufen.

Scope:
- neues Modul `steuerboard/heimserver_service_gate_writer.py` mit genau einer öffentlichen Writerfunktion (`write_heimserver_service_gate_assessment`) und einer Fehlerklasse (`HeimserverServiceGateWriteError`).
- erzeugt eine unabhängige Assessment-Momentaufnahme, validiert sie vollständig gegen das kanonische Assessment-Schema aus dem Checkout und serialisiert exakt mit `json.dumps(..., indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"`.
- verwendet einen expliziten Zielpfad ohne Standarddateiname; Parent muss existieren; vorhandene Dateien, Verzeichnisse, Symlinks und dangling Symlinks werden abgelehnt.
- schreibt Bytes in eine Tempdatei im Zielverzeichnis und veröffentlicht mit `os.replace()`; Tempdateien werden bei Fehlern bestmöglich entfernt.
- Fehlerdiagnosen bleiben wertfrei: Schemafehler nennen nur Keyword und schema-seitigen JSON Pointer; technische Writerfehler sind keine Assessment-Reason-Codes.

Non-goals:
- keine CLI, kein Runbook-Kind, keine Runtime-Integration, keine Live-Prüfung, keine Stage-D-Action.
- kein neues Schema, keine `SCHEMA_MAP`-Änderung, keine neue Abhängigkeit, keine strukturierte Output-Ref-Metadaten.
- kein race-free No-Clobber gegen parallele Writer zwischen Vorprüfung und `os.replace()` und keine `fsync`-/Stromausfall-Durability-Garantie.


## Phase 11F-K — Artifact-derived Read-only Runbook Integration

Status: implemented (sixth read-only runbook kind)

Connects the existing 11F-I adapter and 11F-J writer through the generic `runbook run` entrypoint.

Scope:
- `heimserver-service-gate` added to `runbook-plan.v1`, `runbook-result.v1`, and `SUPPORTED_RUNBOOK_KINDS`.
- kind-specific `service_gate_inputs` carries `artifact_root` and opaque `input_refs`; the adapter remains the authority for the exact three-ref contract.
- derives through `derive_heimserver_service_gate_assessment_from_refs()` and persists through `write_heimserver_service_gate_assessment()`.
- writes `heimserver-service-gate-assessment.json` beside the trace and maps assessment status exactly to runbook status.
- technical adapter/writer failures remain technical and produce `inconclusive`, without inventing assessment reason codes.
- assessment, result, and trace form one rollback-protected output set; later publication failures trigger cleanup, and cleanup failures are surfaced explicitly.
- `repo_path` must resolve inside a path with a concrete `.git` worktree marker so the outside-worktree boundary cannot be spoofed.
- examples and tests cover passed, blocked, inconclusive, adapter failure, dangling-symlink collision preflight, false `repo_path`, unexpected internal failures, rollback, and rollback-cleanup failure.

Non-goals:
- no specialized top-level CLI command, live service check, service manager, network probe, subprocess, shell, repair, automatic artifact discovery, Runtime/Stage-D integration, or evidence-internal provenance.


## Phase 12A — Read-only Repository Favorites

Status: implemented.

Adds a preference-derived comfort view without changing repository observation
semantics.

Scope:
- optional `preferences.favorite_repo_paths` in `local-config.v1`;
- new `repo-favorites.v1` report contract and validated example;
- new `inventory favorites` read-only CLI command;
- exact-path join against the existing configured inventory;
- configuration order is preserved;
- normalized duplicate preferences are rejected;
- configured paths outside the inventory are reported as `not_in_inventory`;
- no discovery or Git probing is added for missing favorites;
- an empty favorites configuration stops before inventory construction and
  records only the preference source.

Architecture boundary:
- favorites are explicit user preferences, not observed repository facts;
- `repo-inventory.v1` remains unchanged;
- the command does not mutate repositories, configuration, or preferences;
- the report does not plan, authorize, or execute actions.

Non-goals:
- no history, problem-repository ranking, warning engine, PR lookup, desktop
  notification, backend, TUI, or favorite-management command.

## Phase 12B — Read-only Recent Problem Repositories

Status: implemented.

Adds a bounded history view over explicitly supplied `omnipull-report.v1`
artifacts.

Command:

```bash
python -m steuerboard omnipull-report recent-problems \
  <report-json> [<report-json> ...] --limit 20 --json
```

Scope:
- new `recent-problem-repos.v1` derived report contract and validated example;
- one or more explicit Omnipull report paths are required;
- newest occurrence per `repo_id` is selected from only those reports;
- deterministic report tie-breakers and source-report order for same-report ties;
- bounded `--limit` from 1 through 100;
- total distinct and returned counts remain explicit;
- repeated occurrences are exposed as `occurrence_count`.

Architecture boundary:
- no file discovery, globbing, directory walk, or automatic latest lookup;
- no run-index expansion or implicit loading of referenced reports;
- no claim that supplied reports are complete or globally latest;
- no severity or remediation ranking;
- no Git, network, mutation, planning, authorisation, or action execution.

Non-goals:
- no persistent history store, warning engine, manual PR links, desktop
  notification, backend, TUI, or action command.

## Phase 13A — Operational Profile v1

Status: implemented.

Turns the existing `local-config.v1.policy` booleans into fail-closed CLI preconditions.

Scope:
- `profile show [--config] --json` emits `operational-profile.v1`;
- policy fields are all required booleans;
- remote refresh requires `allow_network_fetch`;
- fast-forward pull requires mutation plus network permission;
- branch switching requires mutation plus branch-switch permission;
- denials occur before Git probes, artifact loading, or output creation;
- one loaded configuration snapshot is reused for remote-refresh policy and scope checks.

Boundary:
- an effective gate is a prerequisite, never action authorisation;
- all existing plan, approval, evidence, readiness, live-state, and postcheck gates remain mandatory;
- no daemon, scheduler, updater, policy editor, or automatic action execution.
