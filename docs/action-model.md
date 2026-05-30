# Action Model

Stage D is now active for **exactly one** bounded mutating action,
`git-pull-ff-only` (Phase 8E). Every other mutating capability — including
`switch-main` execution — remains future-gated. `switch-main` has a
non-mutating readiness/proof layer (Phase 9A) but **no executor**.

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
- active for exactly one action: `git-pull-ff-only` (Phase 8E)
- all other mutating actions, including `switch-main` execution, remain future only
- `switch-main` has a non-mutating readiness/proof layer only (Phase 9A); see below

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

## Phase 8D.2 — Contract-defined Preflight Proof Material

Phase 8D.2 closes the epistemic gap that Phase 8D.1 honestly recorded: it adds
a contract-defined object that proves a `git-status-read-only` run evidence
chain was produced as preflight for a specific `git-pull-ff-only` action plan.

Phase 8D.2 is not execution.
Phase 8D.2 is not authorisation.
Phase 8D.2 is not a runner.
Phase 8D.2 is artifact-level proof material only.

### Proof Object

The new field is `preflight_for_action_plan` and carries three required
properties:

```json
{
  "preflight_for_action_plan": {
    "plan_ref": "plan-git-pull-ff-only-2026-05-23-001",
    "plan_action": "git-pull-ff-only",
    "plan_content_sha256": "<canonical sha256 of the pull plan>"
  }
}
```

- `plan_ref` — the `plan_id` of the future `git-pull-ff-only` action plan that
  this read-only run was produced as preflight for.
- `plan_action` — must be `git-pull-ff-only` for binding to be valid.
- `plan_content_sha256` — the canonical SHA-256 of the pull plan as computed by
  `canonical_json_sha256`, the same canonical hash used elsewhere in the
  repository for `run-result.v1.plan_content_sha256` and
  `action-approval.v1.plan_content_sha256`.

The hash binds the proof to a specific bit-exact plan content. If the pull
plan is edited, the hash no longer matches and the binding becomes
`binding_invalid`. This is intentional: a plan-binding artifact must not
silently track plan content drift.

### Carried By

- `run-result.v1` — optionally carries the proof when produced via
  `action run-read-only --preflight-for-action-plan <pull-plan-json>`.
- `run-evidence-chain.v1` — preserves the proof from `run-result.v1`
  unchanged when the chain is validated.
- `action-preflight-binding.v1` — records the proof object it found in the
  chain whenever it was present.

### Binding States in Phase 8D.2

`bind-preflight-to-action` now distinguishes the following cases:

- `binding_valid` — chain carries `preflight_for_action_plan`, all three
  fields match the supplied pull plan exactly (`plan_ref ==
  action_plan.plan_id`, `plan_action == "git-pull-ff-only"`,
  `plan_content_sha256 == canonical_json_sha256(action_plan)`), and the
  remaining gates (plan/chain action, chain status, redaction) pass.
- `binding_inconclusive` — the chain has no `preflight_for_action_plan` object
  and no hard gate fails. This is the honest result for pre-8D.2 chains.
- `binding_invalid` — the proof object is present but at least one field does
  not match the supplied pull plan, or one of the existing hard gates fails.
  The mismatch is recorded as `blocked_because: ["binding_mismatch"]`.

### Readiness Integration

`validate-execution-readiness` now trusts a supplied
`action-preflight-binding.v1` only when its `binding_state == binding_valid`
**and** the binding artifact carries the `preflight_for_action_plan` proof
object. The binding logic has already verified the proof against the supplied
pull plan, so readiness can consume it directly without re-implementing the
check.

- `binding_valid` + proof present → readiness gate `preflight_chain_plan_binding_proven` passes.
- `binding_valid` without proof → readiness stays `inconclusive` (conservative).
- `binding_invalid` → readiness blocks with `preflight_binding_invalid`.
- `binding_inconclusive` → readiness stays `inconclusive`.

Stage-D execution remains future-only. A `ready` readiness artifact still does
not execute, mutate, or authorise. There is still no Stage-D runner contract
in the current slice.

### CLI

```bash
python -m steuerboard action run-read-only <status-action-plan-json> \
  --repo-path <repo-path> \
  --command-trace-out <trace-json> \
  --run-result-out <run-result-json> \
  --preflight-for-action-plan <pull-action-plan-json> \
  --json
```

Validation of `--preflight-for-action-plan`:

- the referenced JSON must validate as `action-plan.v1`
- the referenced plan's `action` must be exactly `git-pull-ff-only`
- the executing plan's action remains `git-status-read-only` (already enforced
  by the Phase 8A allowlist)
- the executed command is unchanged — exactly one read-only `git status` call
- the emitted `run-result.v1` carries `preflight_for_action_plan` with
  `plan_ref`, `plan_action`, and the canonical `plan_content_sha256`

### Boundary

- pure artifact contract extension; no subprocess change, no Git mutation,
  no network, no fetch, no pull
- the executed command and read-only boundary in Phase 8A are unchanged
- all produced artifacts continue to carry
  `boundary.does_not_execute=true`, `boundary.does_not_mutate=true`,
  `boundary.does_not_authorise_actions=true`
- existing artifacts without `preflight_for_action_plan` remain
  schema-valid; the field is strictly optional everywhere it appears
- `binding_valid` is now achievable only with explicit, content-bound proof
  material; it is never inferred from naming conventions, timestamps, or
  source_refs

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

## Phase 9A — Switch-main Execution Readiness (non-mutating proof)

Phase 9A introduces the non-mutating readiness/proof layer for a future
`switch-main` action. It is the switch-main analogue of the Phase 8D.0
`action-execution-readiness.v1` pull gate.

Phase 9A is not execution.
Phase 9A is not authorisation.
Phase 9A is not a switch.
There is no `switch-main` runner in this slice, and none is introduced.

Stage D already exists for `git-pull-ff-only` (Phase 8E). `switch-main` stays
**readiness/proof only** in Phase 9A; its execution remains future-gated
(Phase 9B, out of scope here).

### Artifacts

- `switch-main-preflight-proof.v1` — input proof material: the plan binding
  (`plan_ref`, `plan_action`, `plan_content_sha256`) plus the observed
  repository-state claims (`repo_toplevel`, `current_branch`, `default_branch`,
  `branch_contains_origin_main_or_pr_merged`, `worktree_clean`, `remote_main_fresh`,
  `ownership_ok`). Absence of an optional state claim means *unknown*.
- `switch-main-readiness.v1` — output verdict: `ready` / `blocked` /
  `inconclusive` with `checks`, `blocked_because`, and `failure_reasons`.

### Status semantics

- `ready` — all hard gates pass and all proof material is present and
  consistent. Proof that a later switch could be evaluated, never permission to
  switch.
- `blocked` — a hard contradiction (plan-binding mismatch, unsupported action,
  dirty worktree, default branch not `main`, stale `origin/main`, ownership/path
  split-brain).
- `inconclusive` — no contradiction, but proof material is unknown.

### CLI

```bash
python -m steuerboard action validate-switch-main-readiness <action-plan-json> \
  --preflight-proof <switch-main-preflight-proof-json> \
  --readiness-out <switch-main-readiness-json> \
  --json
```

Classified `derivation_only`.

### Boundary

- pure artifact validation: no subprocesses, no Git, no network, no mutation
- the module runs no subprocess and therefore cannot switch, checkout, merge,
  rebase, reset, clean, or pull
- reads only the two explicitly passed artifacts; validates both against their
  JSON Schemas before processing
- output path must not pre-exist; parent must exist; on any precondition failure
  no output file is written
- every produced artifact carries `boundary.does_not_execute = true`,
  `boundary.does_not_mutate = true`, `boundary.does_not_authorise_actions = true`
- `plan switch-main` is unchanged and stays `derivation_only`;
  `action run-git-pull-ff-only` stays the only `mutating_stage_d` action

The full contract lives in
[docs/switch-main-readiness-contract.md](switch-main-readiness-contract.md).

## Contract Note: Redefinition of action-plan.v1

This phase redefines the previously reserved `action-plan.v1` schema shape.
Previous examples in Phase 0b used executor-oriented placeholders (`would_run`, `would_mutate`).
The current slice redefines `action-plan.v1` as a preview-only contract artifact derived from assessment, not as an executor interface.
No executor compatibility is promised in this or earlier phases.
The schema enforces this boundary:
- Boundary fields (`does_not_execute`, `does_not_mutate`, `does_not_authorise_actions`) are mandatory and const true.
- Execution/advice fields (`would_run`, `would_mutate`, `safe_alternatives`, `required_evidence`) are not present in the schema; any mention remains historical only.
