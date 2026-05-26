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
- writes both artifacts via temp files and `os.replace()` with best-effort
  rollback so handled failures do not leave final partial outputs

The runner uses hard-coded Git subprocesses only; the traced productive command is:

- `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`

Preflight worktree/toplevel checks remain hard-coded and read-only. The runner
does not expose a free shell, a generic subprocess surface, or mutating Git commands.

Output invariants in this slice:

- trace and run-result outputs must be different files
- both outputs must be outside the inspected repository worktree
- rationale: evidence generation must not mutate or stale the measured worktree status

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

## Phase 8B — Read-only Postcheck + Run Record Binding

Phase 8B introduces a bounded read-only postcheck that verifies the evidence
produced by a Phase 8A run. It is not a pull, not an approval runner, and not
a mutating action. Its sole purpose is to make execution evidence auditable.

The postcheck:

- reads an existing `run-result.v1` artifact and `command-trace.v1` artifact
- validates both fully against their JSON Schemas
- requires `run-result.v1.status == success`
- requires `run-result.v1.evidence_paths` to include the provided
  `command-trace.v1` path (run-record binding)
- validates that the trace command is exactly the hardened git status command
- requires `command-trace.v1.exit_code == 0`
- requires `command-trace.v1.stdout_excerpt` for comparison
- requires `run-result.v1.redaction_verified == true`
- requires `command-trace.v1.redacted == true`
- re-runs `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
  (the same bounded read-only command as Phase 8A)
- compares the new output against the original trace `stdout_excerpt`
- emits a `run-postcheck.v1` artifact with
  `status: passed | failed | inconclusive`
- writes no files into the inspected repository
- performs no network access, no pull, no fetch, no branch switch, no mutation

`run-postcheck.v1` is an evidence artifact, not an authorisation mechanism.
A passed postcheck does not authorise any subsequent action.

Command:

```bash
python -m steuerboard action postcheck-read-only <run-result-json> \
  --command-trace <trace-json> \
  --repo-path <repo-path> \
  --postcheck-out <postcheck-json> \
  --json
```

Boundary:

- no mutating Git actions
- no pull, fetch, switch, merge, rebase, reset, clean
- no free shell, no sudo, no network
- no generic subprocess surface
- no approval runner
- output file must not pre-exist; parent directory must exist
- output must be outside the inspected repository worktree
- on any precondition failure: no output file is written; schema-valid
  `run-postcheck.v1` with `status: inconclusive` is emitted to stdout

Status contract:

- `passed`: recheck command succeeded, excerpts match, and neither side is
  truncated at excerpt boundary
- `failed`: recheck command succeeded, excerpts differ
  (`worktree_changed_after_run`)
- `inconclusive`: precondition failure or recheck command failure
  (`postcheck_command_failed`), or truncated comparison basis
  (`stdout_excerpt_truncated`)

If either original trace excerpt or rechecked status output is truncated at
excerpt boundary, postcheck status is `inconclusive`, not `passed`.

Trace + run-result + postcheck form a verifiable, auditable chain:

- `command-trace.v1` proves what command ran and what it produced
- `run-result.v1` proves the run succeeded and was redacted
- `run-postcheck.v1` proves the worktree state matches (or has drifted from)
  the original run evidence

Stage D (approved mutating execution) is not implemented in this phase.

## Contract Note: Redefinition of action-plan.v1
Previous examples in Phase 0b used executor-oriented placeholders (`would_run`, `would_mutate`).
The current slice redefines `action-plan.v1` as a preview-only contract artifact derived from assessment, not as an executor interface.
No executor compatibility is promised in this or earlier phases.
The schema enforces this boundary:
- Boundary fields (`does_not_execute`, `does_not_mutate`, `does_not_authorise_actions`) are mandatory and const true.
- Execution/advice fields (`would_run`, `would_mutate`, `safe_alternatives`, `required_evidence`) are not present in the schema; any mention remains historical only.
