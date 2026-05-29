# Git Pull FF-only Contract Blueprint

## Purpose

This document defines the future planning contract for a single-repository
`git pull --ff-only` action in steuerboard.

Scope of this contract:

- single-repo `git pull --ff-only`
- no Omnipull execution
- no fleet pull
- no free shell runner

This is a documentation contract only. It does not authorize or implement
execution.

Phase 7a.3 implementation note:

- the `plan git-pull-ff-only` command now exists as a preview-only planner
  slice that transforms `repo-assessment.v1` into `action-plan.v1`
- it does not execute Git and intentionally blocks when pull-readiness evidence
  is incomplete (for example missing remote freshness)
- no approval or execution runner is introduced in this slice

## Non-goals

The following are explicitly out of scope for this contract slice:

- no `steuerboard pull <repo>` command
- no direct pull execution
- no merge
- no rebase
- no reset or clean
- no conflict resolution
- no automatic execution

## Canonical Chain

Observe
-> Assess
-> Plan
-> Approve
-> Execute
-> Record
-> Explain

The chain is strict: each stage needs bounded evidence from prior stages.

## Plan Eligibility Gates

Minimum gates before emitting a future `git-pull-ff-only` plan candidate:

- `repo_in_scope`
- `repo_identity_known`
- `worktree_clean`
- `head_not_detached`
- `current_branch_known`
- `current_branch_is_default`
- `upstream_exists`
- `remote_known_acceptable`
- `remote_freshness_evidence_exists`
- `not_ahead`
- `not_diverged`
- `ff_only_possible`
- `ownership_ok`

## Execution Gates

A future runner may execute only if all of the following exist:

- `action_plan_exists`
- `action_approval_exists` (`action-approval.v1`)
- `action_approval_binding_validated` (`action-approval-validation.v1`, Phase 7c.2)
- `runner_contract_exists`

`action-approval.v1` is a plan-bound approval artifact only.
It does not execute `git pull --ff-only` and does not authorize execution by itself.
In existing planner `missing_evidence` vocabulary, `user_approval` can remain the
runtime gap marker; Phase 7c.1 defines `action-approval.v1` as the concrete future
artifact form for satisfying that gap.

Phase 7c.2 adds `action-approval-validation.v1` as a pure pre-run gate.
Binding validation proves that the approval matches exactly the plan at an explicit
`checked_at` timestamp. `binding_state == "binding_valid"` still does not execute pull.

## Decision Table

| Befund                     | Entscheidung   | Blocker                  | Fehlende Evidenz               |
| -------------------------- | -------------- | ------------------------ | ------------------------------ |
| dirty worktree             | blocked        | dirty_worktree           | clean_worktree                 |
| feature branch             | blocked        | non_default_branch       | default_branch_checkout_intent |
| remote stale               | blocked        | remote_freshness_unknown | fresh_remote_refs              |
| clean default, ff possible | plan_candidate | none                     | none                           |
| plan exists, no approval   | execution_blocked | approval_missing        | action_approval_exists         |

## Postcheck Evidence

After a future execution step, the evidence set must include:

- `command_trace`
- `run_result`
- `postcheck_head`
- `postcheck_branch`
- `postcheck_worktree`
- `postcheck_ahead_behind`

## Security Boundary

A git-pull-ff-only plan is not permission to execute; execution requires a
separate approval and runner contract.

## Phase 8E Execution Implementation

Phase 8E implements the execution contract for `git-pull-ff-only`.

### CLI command

```
steuerboard action run-git-pull-ff-only \
  <action_plan_json> \
  --approval-validation <path> \
  --run-evidence-chain <path> \
  --preflight-binding <path> \
  --repo-path <path> \
  --command-trace-out <path> \
  --run-result-out <path> \
  --postcheck-out <path> \
  --json
```

### Security contract

- The runner verifies `preflight_binding.preflight_for_action_plan.plan_ref`,
  `plan_action`, and `plan_content_sha256` against the supplied `action_plan`
  directly — not delegated to `validate_execution_readiness()`.
- Only `preflight_binding.binding_state == "binding_valid"` AND a proof block
  with matching `plan_ref`, `plan_action`, and `plan_content_sha256` allows execution.
- No `shell=True`. No merge, rebase, reset, or clean.
- Output paths must not exist before the command runs.
- No output path may reside inside the git worktree.
- All three output paths must be distinct.
- Precondition failures emit a stdout sentinel (`run-result.v1` with `status: blocked`)
  but write no output files.
- Exactly one **mutating** Git subprocess call: `["git", "--no-optional-locks", "-C",
  <toplevel>, "pull", "--ff-only"]`. Read-only pre/post checks (status, rev-parse) are
  separate non-mutating subprocess calls.

### Output artifacts

All three output artifacts are written atomically with a rollback chain:

1. `command-trace.v1` — exact command argv, exit code, stdout/stderr excerpts
2. `run-result.v1` — action, status, plan hash, timestamps
3. `run-postcheck.v1` — action, postcheck status, observations
