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
