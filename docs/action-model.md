# Action Model

Mutating actions remain future-gated capabilities in the current implemented slices.

Plan preview output is not an action executor and not an action authorisation.
It is a contract artifact derived from prior assessment.

## Action Stages

Stage A: read-only observation commands

- local facts only
- no network
- no mutation
- examples: status, branch, scope, inventory, assessment from existing facts

Stage B: fetch-only / network-refresh commands

- network allowed
- local refs may change
- worktree must not change
- no merge, switch, reset, clean, or pull
- future only unless explicitly implemented

Stage C: planned mutating Git actions

- plan artifact only
- no execution
- no authorization
- includes future planning for `git-pull-ff-only`

Stage D: approved execution runner

- executes only approved bounded commands
- requires plan, approval, trace, run-result, and postcheck
- future only

Stage E: UI-triggered approved actions

- UI may trigger only the same approved runner path
- UI must not contain independent action logic
- future only

## Blocked in v1

- free shell
- sudo
- force push
- branch deletion
- destructive reset or clean
- automatic conflict resolution

## Plan Preview Boundary

`action-plan.v1` in the current slice is preview-only:

- no command execution
- no repository mutation
- no action authorisation
- no command advice
- no Git subprocess

## Phase 8A — Read-only Action Runner

Phase 8A introduces a strictly bounded read-only runner for a single pilot action.

Allowed actions in Phase 8A: `git-status-read-only` only.

The runner:

- takes an `action-plan.v1` artifact as input
- validates the action plan fully against the `action-plan.v1` JSON Schema before execution
- verifies the action is in the Phase 8A allowlist
- explicitly blocks all mutating actions (`git-pull-ff-only`, `switch-main`)
- executes exactly one productive traced Git command:
  `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
  with `GIT_OPTIONAL_LOCKS=0` in the environment
- writes a `command-trace.v1` artifact (redacted)
- writes a `run-result.v1` artifact referencing the trace
- writes both artifacts atomically via temp files and `os.replace()`

The runner uses hard-coded Git subprocesses only; the traced productive command is:

- `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`

Preflight worktree/toplevel checks remain hard-coded and read-only. The runner
does not expose a free shell, a generic subprocess surface, or mutating Git commands.

The runner does **not** authorise actions. Approval binding is not a precondition
in this slice. Phase 8A proves only bounded read-only execution evidence.

Command:

```bash
python -m steuerboard action run-read-only <action-plan-json> \
  --repo-path <repo-path> \
  --command-trace-out <trace-json> \
  --run-result-out <run-result-json> \
  --json
```

Boundary:

- no mutating Git actions
- no pull, fetch, switch, merge, rebase, reset, clean
- no free shell, no sudo, no network
- no generic subprocess surface
- no approval runner
- output files must not pre-exist; parent directories must exist
- on any precondition failure: no partial output written

The planned `git-pull-ff-only` action is specified in
`docs/git-pull-ff-only-contract.md`.

`git pull --ff-only` belongs to Stage C/D, not Stage A/B.
`git pull --ff-only` is acceptable only with preflight gates, approval,
trace, run-result, and postcheck.
No destructive Git actions are in scope.
No free shell is in scope.
Existing commands remain read-only or preview-only as already documented.

## Contract Note: Redefinition of action-plan.v1

This phase redefines the previously reserved `action-plan.v1` schema shape.
Previous examples in Phase 0b used executor-oriented placeholders (`would_run`, `would_mutate`).
The current slice redefines `action-plan.v1` as a preview-only contract artifact derived from assessment, not as an executor interface.
No executor compatibility is promised in this or earlier phases.
The schema enforces this boundary:
- Boundary fields (`does_not_execute`, `does_not_mutate`, `does_not_authorise_actions`) are mandatory and const true.
- Execution/advice fields (`would_run`, `would_mutate`, `safe_alternatives`, `required_evidence`) are not present in the schema; any mention remains historical only.
