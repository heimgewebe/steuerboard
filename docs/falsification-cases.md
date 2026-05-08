# Falsification Cases

Falsification cases are the first-class input for steuerboard. Status names must be derived from failure cases, not invented before the local risks are understood.

Each case must include:

- `id`
- `title`
- `trigger`
- `expected_observation`
- `risk`
- `expected_assessment`
- `blocked_actions`
- `safe_actions`
- `required_evidence`

## Initial Phase 0b cases

| Case | Purpose |
| --- | --- |
| `duplicate_repo` | Detect multiple local clones that could be confused. |
| `gdrive_shadow_repo` | Treat synced-drive clones as non-canonical shadows. |
| `backup_repo_accidentally_used` | Avoid mutating backup copies. |
| `dubious_ownership` | Block trust in Git output when ownership is unsafe. |
| `foreign_owner_present` | Surface owner mismatches before actions. |
| `wrong_remote` | Detect remotes that do not match canonical source expectations. |
| `remote_missing` | Explain missing origin/remotes. |
| `remote_unreachable` | Separate network reachability from local repo state. |
| `stale_metarepo` | Mark canonical inventory sources as stale. |
| `stale_omnipull_log` | Avoid treating old omnipull results as fresh. |
| `missing_upstream` | Explain branch state without upstream tracking. |
| `unknown_default_branch` | Prevent default-branch assumptions when source evidence is missing. |
| `branch_local_only` | Require care for local-only work without upstream. |
| `branch_remote_deleted` | Explain branches whose upstream disappeared after fresh remote refs. |
| `ff_only_not_possible` | Block automated merge/rebase decisions when fast-forward is impossible. |
| `origin_main_stale` | Prevent actions based on stale `origin/main` knowledge. |
| `omnipull_skip_unknown_reason` | Surface unrecognized omnipull skip reasons as missing evidence. |
| `detached_head` | Block branch-switch/pull assumptions. |
| `dirty_worktree` | Block mutating actions until local changes are understood. |
| `dirty_submodule` | Surface nested dirty state. |
| `feature_branch_unmerged` | Require lifecycle evidence before switching branches. |
| `feature_branch_merged` | Demonstrate a case where switching may be plannable after evidence. |
| `evidence_contains_secret_like_pattern` | Ensure evidence redaction gates archival. |

The concrete machine-readable examples live in `examples/failure-cases/` and validate against `schemas/falsification-case.v1.schema.json`. Phase 0b now covers the masterplan Pflichtfälle as examples, while deeper observation, assessment, and action-plan examples remain future work.
