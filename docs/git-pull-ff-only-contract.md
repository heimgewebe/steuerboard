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
- `user_approval_exists`
- `runner_contract_exists`

## Decision Table

| Befund                     | Entscheidung   | Blocker                  | Fehlende Evidenz               |
| -------------------------- | -------------- | ------------------------ | ------------------------------ |
| dirty worktree             | blocked        | dirty_worktree           | clean_worktree                 |
| feature branch             | blocked        | non_default_branch       | default_branch_checkout_intent |
| remote stale               | blocked        | remote_freshness_unknown | fresh_remote_refs              |
| clean default, ff possible | plan_candidate | none                     | none                           |
| plan exists, no approval   | execution_blocked | approval_missing      | user_approval                  |

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
