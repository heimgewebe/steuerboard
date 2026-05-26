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

Phase 8B introduces a bounded read-only postcheck that makes Phase 8A execution
evidence auditable. It is **not** a pull, **not** an approval runner, and **not**
a mutating action. The next missing building block after Phase 8A is
Postcheck/Record, not mutation.

Premise:
- Phase 8A is merged and proves bounded read-only execution evidence.
- Stage D (mutating execution) remains future-only.
- `git pull --ff-only` is not implemented in this phase.

Command:

```bash
python -m steuerboard action postcheck-read-only <run-result-json> \
  --command-trace <trace-json> \
  --repo-path <repo-path> \
  --postcheck-out <postcheck-json> \
  --json
```

Scope in this slice:

- new schema: `run-postcheck.v1` (evidence artifact, not authorisation)
- new module: `steuerboard/run_postchecks.py`
- only the `git-status-read-only` action is supported
- reads and fully schema-validates `run-result.v1` and `command-trace.v1`
- validates the trace command is exactly the hardened git status command
- validates `redaction_verified == true` on both input artifacts
- re-runs `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
- compares new status output against original trace `stdout_excerpt`
- `status: passed` when outputs match; `status: failed` with reason
  `worktree_changed_after_run` when they differ
- writes `run-postcheck.v1` via temp file + `os.replace()` (atomic)
- on any precondition failure: no output written; schema-valid
  `run-postcheck.v1` with `status: inconclusive` emitted to stdout

Evidence chain produced by Phases 8A + 8B:

1. `command-trace.v1` — what command ran, what it produced, redacted
2. `run-result.v1` — run succeeded, redaction verified, trace referenced
3. `run-postcheck.v1` — worktree state verified against original trace

Boundary for this slice:

- no mutating Git actions
- no pull, fetch, switch, merge, rebase, reset, clean
- no free shell, no sudo, no network
- no generic subprocess surface
- no approval runner
- no execution authorisation
- no UI
- output must be outside the inspected repository worktree

