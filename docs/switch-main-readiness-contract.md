# Switch-main Readiness Contract (Phase 9A)

## Purpose

This document defines the **non-mutating** readiness/proof contract for a future
single-repository `switch-main` action in steuerboard.

Phase 9A is deliberately a safety intermediate phase. It does **not** switch a
branch. It builds the *proof belt* that must exist before any future switch-main
execution slice (Phase 9B): an artifact layer that can answer "is a later
switch-main provably permissible for this exact plan and this repository state?"
without performing — or authorising — the switch.

Scope of this contract:

- single-repo `switch-main` readiness assessment
- pure artifact validation, derived from a plan plus observed proof material
- no Git execution, no branch switch, no mutation, no authorisation

This mirrors the relationship between the Phase 8D.0
`action-execution-readiness.v1` pull gate and the Phase 8E pull executor. The
switch-main executor half (Phase 9B) is now implemented and **consumes** this
readiness verdict; see [Phase 9B Execution Implementation](#phase-9b-execution-implementation)
below. This document remains the readiness contract — Phase 9B does not change
the readiness layer.

## Non-goals (Phase 9A readiness layer)

The readiness layer itself stays pure and non-mutating. Within Phase 9A the
following remain explicitly out of scope (the bounded executor is a separate
slice, Phase 9B, below):

- the readiness module emits no command and runs no Git subprocess of any kind
- no `git switch`, `git checkout`, `merge`, `rebase`, `reset`, or `clean` in the
  readiness layer
- no reclassification of `plan switch-main` (it stays `derivation_only`)
- a `ready` verdict never authorises or executes a switch by itself

## Canonical Chain

Observe -> Assess -> Plan -> **Prove readiness** -> (future) Approve -> Execute
-> Record -> Explain

Phase 9A occupies the **Prove readiness** stage for switch-main. Plan preview
(`plan switch-main`) already exists and stays preview-only.

## Artifacts

Phase 9A introduces two schema-validated artifacts.

### `switch-main-preflight-proof.v1` (input — proof material)

A pure evidence artifact carrying the plan binding plus the observed
repository-state claims a future switch-main gate requires. It does not execute,
switch, mutate, or authorise. Required envelope fields:

- `schema_version` — const `switch-main-preflight-proof.v1`
- `proof_id`
- `checked_at`
- `plan_ref` — the `plan_id` of the switch-main `action-plan.v1`
- `plan_action` — must equal the plan's action (`switch-main`)
- `plan_content_sha256` — canonical SHA-256 of the bound plan
  (`canonical_json_sha256`, the same hash used for pull plan binding)
- `source_refs`
- `boundary` — `does_not_execute` / `does_not_mutate` /
  `does_not_authorise_actions`, all const true

Optional repository-state claims (absence is meaningful — it means *unknown*):

- `repo_toplevel` — the git toplevel the future switch would target
- `current_branch` — the currently checked-out branch
- `default_branch` — the repository default branch (contractually expected
  `main`; see masterplan Phase 9 switch-main gate)
- `branch_contains_origin_main_or_pr_merged` — boolean; used only when
  `current_branch` is not `main`. `true` = the current branch is contained in
  `origin/main` or is merged via a pull request; `false` = explicitly not
  contained/merged (blocking); absent = unknown
  
  **Semantic note:** Despite its name, this field answers the Phase 9A readiness
  question: "Is it safe to leave the current non-main branch?" A `true` value
  means the current branch's work is proven contained in `origin/main` or merged
  via PR, so switching to main will not lose or hide work. A `false` value means
  the branch is unmerged and uncontained — switching could hide or bypass unmerged
  branch work; uncommitted work is covered separately by `worktree_clean`.
- `worktree_clean` — boolean; `true` = clean
- `remote_main_fresh` — boolean; `true` = `origin/main` is fresh enough
- `ownership_ok` — boolean; `true` = single coherent owner/path (no
  ownership/path split-brain)

### `switch-main-readiness.v1` (output — verdict)

The readiness verdict over one proof and one plan: `status` in
`ready` / `blocked` / `inconclusive`, with `checks`, `blocked_because`,
`failure_reasons`, `source_refs`, and a const-true `boundary`.

## Proof Content Required for `switch-main`

Derived from the masterplan Phase 9 switch-main **gate preflight** and bound to
the plan by content hash:

| Proof material | Gate | Outcome when violated |
| --- | --- | --- |
| `plan_action == "switch-main"` (plan) | `plan_action_supported` | `blocked` (`unsupported_action`) |
| `plan_ref == plan.plan_id` | `proof_plan_ref_matches_plan` | `blocked` (`plan_ref_mismatch`) |
| `plan_action == plan.action` | `proof_plan_action_matches_plan` | `blocked` (`plan_action_mismatch`) |
| `plan_content_sha256 == canonical_json_sha256(plan)` | `proof_plan_content_sha256_matches_plan` | `blocked` (`plan_content_sha256_mismatch`) |
| `repo_toplevel` known | `repo_toplevel_known` | `inconclusive` (`repo_toplevel_unknown`) |
| current branch known | `current_branch_known` | `inconclusive` (`current_branch_unknown`) |
| default branch known | `default_branch_known` | `inconclusive` (`default_branch_unknown`) |
| default branch `== main` | `default_branch_is_main` | `blocked` (`default_branch_not_main`) |
| branch lifecycle (when `current_branch != main`) | `branch_lifecycle_proof` | `blocked` (`branch_lifecycle_unproven`) / `inconclusive` (`branch_lifecycle_unknown`) |
| worktree clean | `worktree_clean` | `blocked` (`worktree_not_clean`) / `inconclusive` (`worktree_state_unknown`) |
| `origin/main` fresh | `remote_main_fresh` | `blocked` (`remote_main_stale`) / `inconclusive` (`remote_freshness_unknown`) |
| ownership/path coherent | `ownership_ok` | `blocked` (`ownership_conflict`) / `inconclusive` (`ownership_unknown`) |

## Status Semantics

- `ready` — every hard gate passes **and** all proof material is present and
  consistent (plan binding proven; worktree clean; default branch known and
  `main`; current branch known; branch lifecycle proven or on main; `origin/main`
  fresh; ownership coherent; `repo_toplevel` known). A `ready` verdict is **proof
  that a later switch could be evaluated** — it is never permission to switch.
- `blocked` — at least one hard contradiction. Hard failures dominate any
  unknown material.
- `inconclusive` — no hard contradiction, but at least one piece of proof
  material is unknown.

### Decision contract

The plan's own `decision` (`blocked` / `not_applicable`) is **not** an
independent readiness blocker. As with the Phase 8D.0 pull gate, readiness is a
pure evidence gate over proof material and plan binding, orthogonal to whether a
switch is *needed*. A switch-main plan whose `decision` is `blocked` (for
example, a clean feature branch awaiting lifecycle proof) can still produce a
`ready` readiness verdict, meaning only that the *mechanical preflight proof
material* is complete, consistent, and bound — not that a switch is authorised
or even required.

## CLI

```bash
python -m steuerboard action validate-switch-main-readiness <action-plan-json> \
  --preflight-proof <switch-main-preflight-proof-json> \
  --readiness-out <switch-main-readiness-json> \
  --json
```

- reads only the two explicitly passed artifacts
- schema-validates both inputs before processing
- writes `switch-main-readiness.v1` to `--readiness-out` (parent must exist;
  target must not pre-exist)
- on a precondition failure (bad JSON, schema-invalid input, output path
  occupied) it emits a redacted `inconclusive` sentinel to stdout, exits
  non-zero, and writes **no** output file
- classified `derivation_only`

## Security Boundary

A `switch-main-readiness.v1` artifact is not permission to switch. Execution
requires a separate approval (`action-approval-validation.v1`) **and** the
bounded Phase 9B runner (see
[Phase 9B Execution Implementation](#phase-9b-execution-implementation)); a
`ready` verdict alone never switches. Every readiness artifact carries
`boundary.does_not_execute = true`, `boundary.does_not_mutate = true`, and
`boundary.does_not_authorise_actions = true`. The readiness module runs no
subprocess and therefore cannot `switch`, `checkout`, `merge`, `rebase`,
`reset`, `clean`, or `pull`.

## Phase 9A vs Phase 9B

- **Phase 9A (readiness, this contract's core):** readiness/proof only.
  Non-mutating. Emits `switch-main-readiness.v1`.
- **Phase 9B (executor, implemented):** the gated `switch-main` executor,
  analogous to the Phase 8E pull executor. It consumes a `ready`
  `switch-main-readiness.v1`, re-derives the mutation-critical live state, and
  performs exactly one bounded branch switch to `main`. See
  [Phase 9B Execution Implementation](#phase-9b-execution-implementation).

## Phase 9B Execution Implementation

Phase 9B implements the bounded `switch-main` executor — the second
`mutating_stage_d` action alongside `action run-git-pull-ff-only`. It is
deliberately narrow: it performs exactly one safe branch switch to `main` and
nothing else.

The boundary is layered and explicit:

> `ready` readiness is not approval. Approval is not execution. Execution is
> exactly one bounded branch switch to `main`. Postcheck is required after
> execution.

### CLI command

```bash
python -m steuerboard action run-switch-main <action-plan-json> \
  --approval-validation <action-approval-validation-json> \
  --switch-main-readiness <switch-main-readiness-json> \
  --repo-path <repo-path> \
  --command-trace-out <trace-json> \
  --run-result-out <run-result-json> \
  --postcheck-out <postcheck-json> \
  --json
```

Classified `mutating_stage_d`.

### Inputs and gates

The runner consumes three artifacts, all pinned to the same plan:

- `action-plan.v1` — `action` must be `switch-main`.
- `action-approval-validation.v1` — `binding_state == "binding_valid"`,
  `plan_ref == plan.plan_id`, `action == "switch-main"`. This is the separate
  approval gate: a `ready` readiness verdict is **not** approval.
- `switch-main-readiness.v1` — `status == "ready"`, `plan_ref` and `action`
  bound to the plan, and the recorded `proof_plan_content_sha256_matches_plan`
  check equal to `canonical_json_sha256(action_plan)`. The content-hash binding
  prevents substituting a readiness computed for different plan content.

### Live safety gates reproduced before mutation

The runner does not merely trust the readiness artifact. Immediately before the
switch it re-derives, read-only:

- the git toplevel (`git rev-parse --show-toplevel`), which must equal the
  readiness `repo_toplevel` (and `--repo-path` must resolve to it);
- the current branch (`git rev-parse --abbrev-ref HEAD`), which must be known
  and not a detached `HEAD`;
- worktree cleanliness (`git status --porcelain=v1` must be empty);
- when the live branch is **not** `main`, the readiness must carry a passed
  `branch_lifecycle_proof` check (a readiness computed while on `main` cannot
  authorise leaving a live non-main branch).

It deliberately **does not fetch**: `origin/main` freshness and ownership/path
coherence are proven by the Phase 9A readiness artifact, never re-fetched here.

Residual boundary: `switch-main-readiness.v1` does not expose the attested
`current_branch` at top level, so the executor proves the lifecycle gate was
attested for *a* non-main branch but does not bind the attested branch *name* to
the live one. The live worktree-clean re-check protects uncommitted work, and
`git switch` never deletes a branch, so committed work on the departed branch is
preserved regardless. A future hardening could bind `current_branch` into the
readiness artifact.

### Security contract

- The only mutating Git subprocess call is the exact bounded switch:
  `["git", "--no-optional-locks", "-C", <toplevel>, "switch", "main"]`.
- No `shell=True`. No free shell. No `git checkout` fallback, merge, rebase,
  reset, clean, pull, fetch, push, branch deletion, or conflict resolution.
- Output paths must not exist before the run; parents must exist; all three are
  distinct and none may reside inside the git worktree.
- Precondition failures emit a stdout sentinel (`run-result.v1` with
  `status: blocked`, `action: switch-main`) and exit nonzero, but write no
  output files and perform no Git mutation.

### Output artifacts

All three output artifacts are written atomically with a rollback chain:

1. `command-trace.v1` — exact command argv, exit code, redacted stdout/stderr.
2. `run-result.v1` — `action: switch-main`, status, plan hash, timestamps.
3. `run-postcheck.v1` — `action: switch-main`, postcheck status, and
   `branch_before`/`branch_after` observations.

| Condition | `run_result.status` | `postcheck.status` | Reason code |
|---|---|---|---|
| `git switch` exit code ≠ 0 | `failure` | `failed` | `switch_exit_code_nonzero` |
| Branch ≠ `main` after switch | `failure` | `failed` | `not_on_main_after_switch` |
| Worktree dirty after switch | `failure` | `failed` | `worktree_not_clean_after_switch` |
| Branch unreadable after switch | `success` | `inconclusive` | `branch_unreadable_after_switch` |
| Post-switch status check error | `success` | `inconclusive` | `post_switch_status_check_failed` |
| Branch `main` and worktree clean | `success` | `passed` | — |
