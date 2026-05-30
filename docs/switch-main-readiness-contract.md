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
`action-execution-readiness.v1` pull gate and the Phase 8E pull executor — but
for switch-main the executor half (Phase 9B) does **not** exist yet and is out
of scope here.

## Non-goals

The following are explicitly out of scope for this contract slice:

- no `steuerboard action run-switch-main` command
- no mutating runner
- no `git switch`, `git checkout`, `merge`, `rebase`, `reset`, or `clean`
- no Git subprocess of any kind (the readiness layer runs no commands)
- no reclassification of `plan switch-main` (it stays `derivation_only`)
- no expansion of the single `mutating_stage_d` CLI surface
  (`action run-git-pull-ff-only` stays the only mutating action)

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
would require a separate approval and a runner contract that **do not exist** in
this slice. Every artifact carries `boundary.does_not_execute = true`,
`boundary.does_not_mutate = true`, and
`boundary.does_not_authorise_actions = true`. The readiness module runs no
subprocess and therefore cannot `switch`, `checkout`, `merge`, `rebase`,
`reset`, `clean`, or `pull`.

## Phase 9A vs Phase 9B

- **Phase 9A (this contract):** readiness/proof only. Non-mutating.
- **Phase 9B (future, out of scope):** a gated switch-main executor, analogous
  to the Phase 8E pull executor, that would reproduce this readiness gate before
  performing exactly one bounded branch switch. No such runner exists yet, and
  none is introduced here.
