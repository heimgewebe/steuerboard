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

Phase 8B introduces a bounded read-only postcheck that verifies prior run
evidence. It is not a pull, not an approval runner, and not a mutating action.

The postcheck:

- reads an existing `run-result.v1` artifact and `command-trace.v1` artifact
- validates both fully against their JSON Schemas
- requires `run-result.v1.status == success`
- requires `run-result.v1.evidence_paths` to include the provided trace path
- validates that the trace command is exactly the hardened git status command
- requires `command-trace.v1.exit_code == 0`
- requires `run-result.v1.redaction_verified == true`
- requires `command-trace.v1.redacted == true`
- re-runs `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
- emits `run-postcheck.v1` with `status: passed | failed | inconclusive`

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

## Phase 8C — Run Evidence Chain Verifier

Phase 8C introduces a pure evidence-chain validation artifact. It reads
existing action-plan, trace, run-result, and postcheck artifacts, validates them
as one coherent chain, and emits `run-evidence-chain.v1`.

Phase 8C is not execution.
Phase 8C is not authorisation.
Phase 8C is not a pull gate.

Command:

```bash
python -m steuerboard action validate-run-chain <action-plan-json> \
  --command-trace <trace-json> \
  --run-result <run-result-json> \
  --run-postcheck <postcheck-json> \
  --chain-out <chain-json> \
  --json
```

The verifier:

- validates all four input artifacts fully against their JSON Schemas
- supports only `action == "git-status-read-only"` in this slice
- checks that the trace command is exactly the hardened read-only git status command
- checks redaction and success invariants across trace, run-result, and postcheck
- checks binding invariants across `run_id`, `trace_ref`, `run_result_ref`, and
  `run-result.v1.evidence_paths`
- records `plan_binding_unavailable` when the supplied artifacts do not prove
  plan-to-run binding
- emits `run-evidence-chain.v1` with `status: valid | invalid | inconclusive`

Status meaning:

- `valid` means internal evidence-chain coherence plus proven plan binding
- `invalid` means the evidence contradicts itself or the postcheck failed
- `inconclusive` means the verifier could not establish chain coherence from the
  supplied artifacts, including when plan binding remains unavailable

`run-evidence-chain.v1` is an evidence artifact, not an authorisation mechanism.
A `valid` chain does not authorise pull, fetch, switch, merge, rebase, reset,
clean, or any other action.

Boundary:

- no subprocess calls
- no Git commands
- no network
- no mutation
- no approval runner
- output file parent must exist and target must not pre-exist
- output file must stay outside the inspected repository when the chain exposes
  `repo_toplevel`

Stage D remains future-only.

## Phase 8D.1 — Action Preflight Binding (artifact bridge)

Phase 8D.1 introduces the `action-preflight-binding.v1` artifact — a pure
artifact-level binding between a `git-pull-ff-only` action plan and a
`git-status-read-only` run evidence chain.

Phase 8D.1 is not execution.
Phase 8D.1 is not authorisation.
Phase 8D.1 is not a pull gate.

The bridge exists to make the preflight relationship between the two artifacts
explicit and auditable rather than implicit. It does not relax the readiness
gate; it provides a separate, schema-validated artifact whose `binding_state`
can be consumed by Phase 8D.0 readiness when supplied.

### CLI

```bash
python -m steuerboard action bind-preflight-to-action <action-plan-json> \
  --run-evidence-chain <chain-json> \
  --binding-out <binding-json> \
  --json
```

The command:

- reads only the two explicitly passed input artifacts
- schema-validates `action-plan.v1` and `run-evidence-chain.v1`
- emits `action-preflight-binding.v1` JSON to stdout
- writes the artifact to `--binding-out` (parent must exist; target must not pre-exist)

### Binding states

- `binding_valid` — the chain provably belongs to the supplied pull plan from
  contract-defined fields. Not achievable from current artifacts in this slice.
- `binding_invalid` — at least one hard gate fails (unsupported plan action,
  unsupported chain action, chain status invalid, chain redaction unverified,
  or binding material is present but mismatches).
- `binding_inconclusive` — no hard failure, but the chain artifact's
  contract-defined fields do not contain a binding key that ties it to the
  supplied pull plan. This is the honest result for the current
  `run-evidence-chain.v1` contract.

### Epistemic gap and the missing binding key

In this slice, `run-evidence-chain.v1.action` is fixed to
`git-status-read-only` and `chain.plan_ref` points to the status plan only.
The chain artifact does not expose any contract-defined field (such as an
`assessment_ref`, a `bound_action_plans` list, or an explicit
`pull_plan_ref`) that ties it to a `git-pull-ff-only` plan. Therefore the
production binding function cannot honestly emit `binding_valid` for any
combination of current pull plan and current status chain.

Closing this gap requires either:

- extending `run-evidence-chain.v1` with an explicit binding field that
  references the pull plan it was produced for, or
- a separate binding manifest that records the causal relationship at
  production time, or
- a future evidence-chain variant whose `action` field can record
  `git-pull-ff-only` once Stage-D execution exists.

Until one of these is added to the contract, `bind-preflight-to-action`
remains honestly `binding_inconclusive` for the standard combination.

### Boundary

- pure artifact validation: no subprocesses, no Git, no network, no mutation
- reads only the two explicitly passed artifacts
- validates both inputs against their JSON Schemas before processing
- does NOT execute git pull, does NOT authorise actions, does NOT create a runner
- output artifact always includes `boundary.does_not_execute=true`,
  `boundary.does_not_mutate=true`, `boundary.does_not_authorise_actions=true`

### Integration with Phase 8D.0 readiness

`python -m steuerboard action validate-execution-readiness` accepts an
optional `--preflight-binding <action-preflight-binding-json>` argument.

Without `--preflight-binding`, Phase 8D.0 behavior is unchanged: the best
achievable status remains `inconclusive` with
`preflight_chain_plan_binding_unproven`.

With `--preflight-binding`, readiness verifies the binding artifact references
the same plan and chain (`plan_ref`, `chain_ref`, `plan_action`, `chain_action`
consistency; mismatches raise a precondition error) and records
`preflight_binding_ref` in the emitted readiness artifact. The binding's
`binding_state` is then consumed conservatively:

- `binding_valid` — remains `inconclusive` in the current slice, because
  `action-preflight-binding.v1` does not yet carry contract-defined proof
  material that can elevate plan-binding to proven
- `binding_invalid` — readiness is `blocked` with `preflight_binding_invalid`
- `binding_inconclusive` — readiness stays `inconclusive` with
  `preflight_chain_plan_binding_unproven`

Readiness still does not execute, does not authorise, and does not create a
runner. Boundary flags remain const true.

## Phase 8D.0: Stage-D Execution Readiness

Phase 8D.0 introduces the `action-execution-readiness.v1` artifact — a pure
readiness assessment that gates Stage-D execution by validating that all three
prerequisite artifacts (action plan, approval validation, and preflight run
evidence chain) satisfy the required conditions.

### CLI

```
python -m steuerboard action validate-execution-readiness <action-plan-json> \
  --approval-validation <approval-validation-json> \
  --run-evidence-chain <chain-json> \
  --readiness-out <readiness-json> \
  --json
```

### Status Semantics

- `ready` — all hard gates pass AND plan binding is contractually proven
- `blocked` — at least one hard gate fails (rejected/expired approval, invalid
  chain, unsupported action, plan ref or action mismatch, redaction unverified)
- `inconclusive` — no hard failure but plan binding cannot be contractually
  proven (e.g., `preflight_chain_plan_binding_unproven`)

In the current slice, `run-evidence-chain.v1` always records a
`git-status-read-only` chain, which structurally cannot prove binding to a
`git-pull-ff-only` plan.  Therefore the best achievable status in this slice
is `inconclusive` with `preflight_chain_plan_binding_unproven`.

### Hard Gates (blocked)

| Reason | Condition |
|--------|-----------|
| `unsupported_action` | plan.action is not in the supported set |
| `approval_not_binding_valid` | approval_validation.binding_state ≠ binding_valid |
| `approval_plan_ref_mismatch` | approval_validation.plan_ref ≠ plan.plan_id |
| `approval_action_mismatch` | approval_validation.action ≠ plan.action |
| `chain_invalid` | run_evidence_chain.status == invalid |
| `chain_redaction_unverified` | run_evidence_chain.redaction_verified ≠ true |

### Decision Contract in 8D.0

In this slice, `action_plan.decision` is not evaluated as an independent hard
readiness blocker. Readiness is derived from explicit approval-validation and
run-evidence-chain gates plus plan/approval/chain consistency checks.

This keeps Phase 8D.0 as a pure evidence-based gate that can incorporate newer
approval/chain artifacts without being forced to mirror the original plan
decision field.

### Inconclusive Reasons

| Reason | Condition |
|--------|-----------|
| `chain_inconclusive` | run_evidence_chain.status == inconclusive |
| `preflight_chain_plan_binding_unproven` | chain.action ≠ plan.action or chain.plan_ref ≠ plan.plan_id |

### Boundary

- pure artifact validation: no subprocesses, no Git, no network, no mutation
- reads only the three explicitly passed artifact dicts
- validates all three inputs against their JSON Schemas before processing
- does NOT execute git pull, does NOT authorise actions, does NOT create a runner
- output artifact always includes `boundary.does_not_execute=true`,
  `boundary.does_not_mutate=true`, `boundary.does_not_authorise_actions=true`

## Contract Note: Redefinition of action-plan.v1

This phase redefines the previously reserved `action-plan.v1` schema shape.
Previous examples in Phase 0b used executor-oriented placeholders (`would_run`, `would_mutate`).
The current slice redefines `action-plan.v1` as a preview-only contract artifact derived from assessment, not as an executor interface.
No executor compatibility is promised in this or earlier phases.
The schema enforces this boundary:
- Boundary fields (`does_not_execute`, `does_not_mutate`, `does_not_authorise_actions`) are mandatory and const true.
- Execution/advice fields (`would_run`, `would_mutate`, `safe_alternatives`, `required_evidence`) are not present in the schema; any mention remains historical only.
