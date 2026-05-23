# Remote Refresh Model

Remote freshness for pull planning cannot be inferred from local Git state alone.
This model defines a bounded Stage B artifact that records fetch-only evidence
without entering pull execution.

## Purpose

- produce explicit remote freshness evidence for later planning and approval gates
- keep worktree mutation out of scope
- keep pull, merge, switch, reset, and clean out of scope

## Stage Boundary

`remote-refresh-result.v1` is a Stage B network-refresh artifact:

- network access is allowed
- local refs may change
- worktree must not change
- remote must not be mutated
- no pull, merge, switch, reset, clean, or execution approval

## Operation Scope

This slice narrows refresh to one explicit operation:

- `git.fetch_origin_prune`

The artifact records bounded evidence only. It does not authorise pull execution.

## Required Evidence Fields

- operation metadata (`operation`, `remote_name`, timestamps, exit code)
- mutation boundary markers (`mutates_worktree`, `mutates_refs`, `mutates_remote`)
- freshness outcome (`remote_freshness`)
- command trace reference (`command_trace_ref`)
- redaction declaration (`redacted`)
- boundary booleans proving prohibited actions were not taken

## Interpretation Guidance

- `exit_code == 0` with `remote_freshness = fresh` supports the pull contract gate
  `remote_freshness_evidence_exists`.
- Non-zero exit codes should keep pull planning blocked and preserve the failure as
  evidence, not silence it.
- This artifact is evidence for planning and approval chains, not an execution grant.
