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

This slice narrows refresh to one explicit operation and remote:

- operation: `git.fetch_origin_prune`
- remote_name: `origin`

The artifact records bounded evidence only. It does not authorise pull execution.

## Phase 7b.3 Producer Command

Phase 7b.3 adds one bounded productive command that writes Stage B evidence:

```bash
python -m steuerboard remote-refresh fetch-origin-prune <repo-path> \
  --config <local-config-json> \
  --assessment-id <assessment-id> \
  --command-trace-out <trace-json> \
  --json
```

Producer constraints in this slice:

- exactly one productive Git command:
  - `git -C <repo-toplevel> fetch origin --prune`
- no pull, merge, switch, reset, clean, or action authorisation
- preflight gate requires canonical scope and blocks
  `scope_backup`, `scope_gdrive`, `scope_shadow`, `scope_unknown`, `scope_excluded`
- output `repo_ref` is explicitly bound to `repo-<assessment-id>`
- command trace ref must lexically equal the CLI `--command-trace-out` argument
- failed fetches or postcheck mismatches remain explicit evidence
  (`remote_freshness = unavailable`)

## Required Evidence Fields

- operation metadata (`operation`, `remote_name`, timestamps, exit code)
- mutation boundary markers (`mutates_worktree`, `mutates_refs`, `mutates_remote`)
- freshness outcome (`remote_freshness`)
- command trace reference (`command_trace_ref`)
- redaction declaration (`redacted`)
- boundary booleans proving prohibited actions were not taken

## Interpretation Guidance

- For Phase 7b.1, success is defined as `exit_code == 0` and
  `remote_freshness = fresh`.
- Failed refresh results (`exit_code != 0`) must not claim `remote_freshness = fresh`.
- `redacted` is mandatory and must be `true` for this contract slice.
- Non-zero exit codes should keep pull planning blocked and preserve the failure as
  evidence, not silence it.
- This artifact is evidence for planning and approval chains, not an execution grant.
