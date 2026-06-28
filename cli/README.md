# CLI

Phase 1 introduces a read-only observation CLI.

Command:

    python -m steuerboard observe repo <path> --json

The command emits `repo-observation.v1` JSON. It does not assess risk, plan actions, switch branches, pull, fetch, or mutate repositories.

Phase 2 starts with a minimal read-only inventory CLI.

Command:

    python -m steuerboard inventory --json

Additional Phase 2 commands:

    python -m steuerboard inventory duplicates --json
    python -m steuerboard scope explain <path> --json

The command emits `repo-inventory.v1` JSON with local scope classification (`scope_canonical`, `scope_shadow`, `scope_backup`, `scope_gdrive`, `scope_unknown`, `scope_excluded`).
The duplicates command emits `repo-duplicates.v1` JSON grouped by observed `git_toplevel`.
The scope command emits `scope-explanation.v1` JSON for one path.

The Phase 2 inventory and scope commands remain read-only and do not emit assessment, decision, planning, or action fields.

Phase 3 introduces a minimal read-only assessment engine.

Command:

    python -m steuerboard assess repo <path> --json [--config <path>]

The command emits `repo-assessment.v1` JSON derived from observation and scope classification.
It does not plan or execute actions. `decision_state` is an assessment outcome, not an action
authorisation.

Status codes emitted in `derived_status`:

- `not_git_repo` — path is not a Git repository
- `scope_backup`, `scope_gdrive`, `scope_excluded`, `scope_unknown` — non-canonical scope
- `dirty_worktree` — uncommitted local changes (also collected alongside scope codes if both observed)
- `detached_head` — HEAD is detached
- `default_branch_unknown` — default branch not determinable
- `non_default_branch` — clean, on a non-default branch; `missing_evidence` is set
- `clean_default_current` — current branch matches observed `default_branch_candidate`; if observation has `default_branch_candidate_source == "remote_origin_head"`, no `default_branch_source` gap is reported (confidence `0.9`), otherwise the gap remains marked via `missing_evidence: ["default_branch_source"]` (confidence `0.8`)

For `clean_default_current`, provenance refs are source-aware:

- `remote_origin_head` source emits rule ref `assessment.rule.clean_default_current_remote_origin_head_local_source_observed` and freshness ref `freshness.default_branch_source.remote_origin_head_local_observed`
- non-remote source keeps rule ref `assessment.rule.clean_default_current_is_clear_but_default_source_unverified` and freshness ref `freshness.default_branch_source.unverified`

`remote_origin_head_local_observed` means locally observed ref provenance only; it does not prove remote freshness.

`decision_state` is a contractual enum: `action_blocked`, `evidence_missing`, `assessment_clear`.

Assessment boundary: read-only, no mutation, no fetch, no network, no action planning.

Phase 5 introduces a minimal plan preview command that derives from an existing
assessment artifact only.

Command:

    python -m steuerboard plan switch-main <assessment-json> --json

The command reads `repo-assessment.v1` JSON and emits `action-plan.v1` JSON.
It does not observe repositories, read config, run Git commands, execute actions,
mutate repositories, or authorise actions.
It is a pure transformation from `repo-assessment.v1` to `action-plan.v1` and
does not provide command advice.

For this slice, `decision` in the plan is a plan result only:

- `blocked` means switch-main cannot be proposed because blocking status is present
- `not_applicable` means no switch is needed (`clean_default_current`)

Phase 7a.3 adds a second preview-only planner command for the future
single-repo `git pull --ff-only` action shape.

Command:

    python -m steuerboard plan git-pull-ff-only <assessment-json> --json

The command is still a pure artifact transformation from `repo-assessment.v1`
to `action-plan.v1`. It remains preview-only, does not execute Git, and may
return `decision: blocked` when pull preflight evidence is incomplete (notably
missing remote freshness evidence).

Phase 7b.1 introduces the `remote-refresh-result.v1` evidence artifact schema
for remote freshness observation.

Phase 7b.2 extends the `git-pull-ff-only` planner with optional remote freshness
evidence consumption.

Command:

    python -m steuerboard plan git-pull-ff-only <assessment-json> \
      [--remote-refresh-result <remote-refresh-json>] --json

When `--remote-refresh-result` is provided, the planner:

- Strictly validates the remote-refresh-result.v1 artifact
- Enforces explicit repo_ref matching: `remote_refresh.repo_ref == f"repo-{assessment_id}"`
- On successful remote refresh (exit_code == 0, remote_freshness == "fresh"):
  - Removes the `git_pull_ff_only_evidence_missing_remote_freshness` blocker
  - Removes `remote_freshness` from `missing_evidence`
  - Adds refresh provenance to `source_refs` and `freshness_refs`
- On failed or unfresh remote refresh:
  - Keeps the `git_pull_ff_only_evidence_missing_remote_freshness` blocker
  - Preserves `remote_freshness` in `missing_evidence`
  - Adds refresh provenance for audit trail

**Important:** The planner remains preview-only and intentionally does not authorise pull execution.
`decision: blocked` with `git_pull_ff_only_preview_only_execution_out_of_scope` is still emitted
even with successful remote freshness evidence. Remote freshness evidence satisfies only the
planning gate for freshness, not execution authorisation.

Boundary for Phase 7b.2:

- No fetch execution
- No pull execution
- No approval runner
- No command advice (no `would_run`, `would_mutate`, `safe_alternatives`, `required_evidence`)
- Planner remains pure transformation artifact-only
- No Git subprocess, no network, no repository mutation

Phase 7b.3 adds a bounded Stage B producer command for remote-refresh evidence.

Command:

    python -m steuerboard remote-refresh fetch-origin-prune <repo-path> \
      --config <local-config-json> \
      --assessment-id <assessment-id> \
      --command-trace-out <trace-json> --json

Preflight gates:

- explicit `repo-path`, `--config`, `--assessment-id`, and `--command-trace-out`
- `--command-trace-out` parent directory must exist
- `--command-trace-out` target must not already exist
- input path must resolve to a Git worktree and an explicit Git toplevel
- repo scope must be canonical under the provided local config
- blocked scope classes (`scope_backup`, `scope_gdrive`, `scope_shadow`, `scope_unknown`, `scope_excluded`) fail fast
- `origin` remote URL must be readable
- pre-fetch HEAD, current branch, and worktree porcelain must be readable

Execution boundary:

- exactly one productive Git command is run:
  - `git -C <repo-toplevel> fetch origin --prune`
- command trace output is redacted (`command-trace.v1`)
- command output excerpts are bounded
- emitted result is `remote-refresh-result.v1`

Postcheck boundary:

- HEAD, current branch, and worktree porcelain are re-read after fetch
- if any postcheck invariant changes unexpectedly, the command emits a failed
  remote-refresh result (`remote_freshness = unavailable`) and keeps bounded
  postcheck evidence in command trace stderr excerpt

Non-goals remain unchanged:

- no pull, merge, rebase, switch, reset, clean
- no generic subprocess runner
- no generic Git command execution surface
- no action execution authorization

Phase 6a introduces a minimal read-only Omnipull report adapter.

Command:

    python -m steuerboard omnipull-report show <report-json> --json

The command loads one explicit `omnipull-report.v1` JSON file, validates required
fields, and emits a bounded report artifact.
The report `source_path` must match the explicit artifact path string passed to the command.
For this slice, the match is lexical (no path canonicalization).
`repos: []` is allowed to represent an empty run artifact.

Phase 6b extends the adapter with an explicit run-index and a strictly bounded
`latest` lookup.

Command:

    python -m steuerboard omnipull-report latest <run-index-json> --json

The command loads one explicit `omnipull-run-index.v1` JSON file, selects the
newest report entry (by `generated_at`, with `run_id` as lexicographic tie-break),
and emits an `omnipull-report-ref.v1` reference artifact. The reference contains
only `schema_version`, `report_id`, `run_id`, `source_path`, and `selected_by`.

`selected_by` is currently the contractual enum value `latest.generated_at`.

The run-index `source_path` must lexically match the explicit artifact path
passed on the command line. `reports: []` is rejected with a precise error
message: there is no implicit "nothing to do" fallback.

Boundary for the Omnipull adapter (both `show` and `latest`):

- `latest` operates **only** on the explicit run-index artifact supplied on the
  command line; no auto-discovery, no glob, no path search under
  `/home/alex/logs/omnipull`, no `$PWD` scanning
- `latest` does **not** auto-load the referenced omnipull-report file; the
  reference artifact only contains metadata copied from the index entry
- no fetch/pull/switch/reset/clean
- no network access
- no Git subprocess
- no action execution and no action authorization
- no new plan generation from Omnipull report or run-index input
- no command advice

Phase 7c.1 defines `action-approval.v1` as a plan-bound approval artifact contract.
No CLI command is introduced in Phase 7c.1.

Phase 7c.2 adds a pure artifact approval binding validation command.

Command:

    python -m steuerboard approval validate <approval-json> \
      --plan <action-plan-json> \
      --checked-at <YYYY-MM-DDTHH:MM:SSZ> \
      --json

The command reads one `action-approval.v1` JSON file and one `action-plan.v1` JSON
file, validates that the approval binds exactly to the plan at the explicit
`checked_at` timestamp, and emits an `action-approval-validation.v1` artifact.

`checked_at` is required and explicit. No hidden system time is used.

`binding_state: binding_valid` means only:

- the approval matches the exact plan id/action and plan content hash (`plan_content_sha256`)
- the approval decision is `approved`
- the approval is time-valid at `checked_at`
- both input artifacts are fully schema-valid

It does **not** mean execution is allowed.

Boundary for Phase 7c.2:

- reads only the two explicit JSON files passed on the command line
- no repo observation
- no config read
- no Git subprocess
- no network
- no mutation
- no command advice
- no execution authorisation

Phase 8A introduces the first bounded execution evidence slice.

Command:

    python -m steuerboard action run-read-only <action-plan-json> \
      --repo-path <repo-path> \
      --command-trace-out <trace-json> \
      --run-result-out <run-result-json> \
      [--preflight-for-action-plan <pull-action-plan-json>] \
      --json

The command:

- reads one `action-plan.v1` JSON file and validates it fully against the
  `action-plan.v1` JSON Schema
- checks the action against the Phase 8A allowlist (only `git-status-read-only` allowed)
- explicitly blocks all mutating actions (`git-pull-ff-only`, `switch-main`)
- runs hard-coded read-only preflight Git commands to resolve and verify
  worktree/toplevel (`rev-parse` checks)
- executes exactly one productive traced command:
  `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
- writes a redacted `command-trace.v1` artifact to `--command-trace-out`
- writes a `run-result.v1` artifact to `--run-result-out` referencing the trace
- emits `run-result.v1` JSON on stdout

Output path invariants:

- `--command-trace-out` and `--run-result-out` must be different final files
- both output paths must be outside the inspected repository worktree
- reason: evidence writing must not mutate the inspected worktree or stale the
  status signal it is proving

On precondition failure (missing parent directory, output file already exists,
action not allowed), the command emits a blocked `run-result.v1` JSON on stdout
and exits with code 1 using `blocked_reasons` for diagnostics. Writes use temp
files and best-effort rollback so precondition failures and handled write
failures do not leave final partial outputs.

The runner does **not** authorise actions. Approval binding is not a
precondition in Phase 8A. This slice proves only bounded read-only execution evidence.

Boundary for Phase 8A:

- no mutating Git actions
- no pull, fetch, switch, merge, rebase, reset, clean
- no free shell, no sudo, no network
- no generic subprocess surface
- no approval runner
- no execution authorisation
- output files must not pre-exist; parent directories must exist
- stdout/stderr excerpts bounded to 2000 characters each

Phase 8B introduces a bounded read-only postcheck for an existing read-only run.
It validates `command-trace.v1` and `run-result.v1`, re-runs the hardened
read-only git status command, and emits `run-postcheck.v1`.

Command:

    python -m steuerboard action postcheck-read-only <run-result-json> \
      --command-trace <trace-json> \
      --repo-path <repo-path> \
      --postcheck-out <postcheck-json> \
      --json

Boundary for Phase 8B:

- no mutating Git actions
- no pull, fetch, switch, merge, rebase, reset, clean
- no free shell, no sudo, no network
- no generic subprocess surface
- no approval runner
- no execution authorisation
- output must be outside the inspected repository worktree
- output file must not pre-exist; parent directory must exist

Phase 8C introduces a read-only evidence-chain verifier for the artifacts already
produced by earlier run-evidence slices. Phase 8C is **not** an execution step,
**not** an approval runner, and **not** a pull gate. It validates internal chain
coherence only.

Command:

    python -m steuerboard action validate-run-chain <action-plan-json> \
      --command-trace <trace-json> \
      --run-result <run-result-json> \
      --run-postcheck <postcheck-json> \
      --chain-out <chain-json> \
      --json

The command:

- reads and fully schema-validates one `action-plan.v1`, `command-trace.v1`,
  `run-result.v1`, and `run-postcheck.v1` JSON file
- supports only `action == git-status-read-only` in this slice
- validates that the trace command is exactly
  `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
- requires `command-trace.v1.exit_code == 0`
- requires `command-trace.v1.redacted == true`
- requires `run-result.v1.status == success`
- requires `run-result.v1.redaction_verified == true`
- requires `run-result.v1.evidence_paths` to include the provided trace path
- requires `run-postcheck.v1.run_id`, `trace_ref`, and `run_result_ref` to bind
  to the same run/trace/result chain
- requires `run-postcheck.v1.redaction_verified == true`
- records `plan_binding_unavailable` when the supplied artifacts do not prove a
  causal plan-to-run binding
- writes one `run-evidence-chain.v1` artifact to `--chain-out`
- emits `run-evidence-chain.v1` JSON on stdout

Status contract:

- `valid` is reserved for a coherent chain with proven plan binding
- `invalid` means the chain is contradictory or the postcheck failed
- `inconclusive` means the chain could not be established from the supplied artifacts,
  including when plan binding is unavailable

Important boundary note:

- a `valid` chain artifact does **not** authorise pull, fetch, switch, reset,
  clean, merge, or any other action
- Stage D remains future-only

Boundary for Phase 8C:

- no subprocess execution
- no Git commands
- no network
- no mutation
- no approval runner
- no execution authorisation
- `--chain-out` parent must exist and target must not already exist
- `--chain-out` must not be written into the inspected repository when
  `repo_toplevel` is known from the evidence chain

---

## Phase 8D.0: action validate-execution-readiness

```
python -m steuerboard action validate-execution-readiness <action-plan-json> \
  --approval-validation <approval-validation-json> \
  --run-evidence-chain <chain-json> \
  --readiness-out <readiness-json> \
  [--preflight-binding <action-preflight-binding-json>] \
  --json
```

Validates Stage-D execution readiness for a single supported action
(`git-pull-ff-only`).  Reads three prerequisite artifacts and emits an
`action-execution-readiness.v1` artifact.

Arguments:

| Argument | Description |
|----------|-------------|
| `<action-plan-json>` | Path to an `action-plan.v1` JSON artifact |
| `--approval-validation` | Path to an `action-approval-validation.v1` JSON artifact |
| `--run-evidence-chain` | Path to a `run-evidence-chain.v1` JSON artifact |
| `--readiness-out` | Output path for the `action-execution-readiness.v1` artifact (must not exist; parent must exist) |
| `--preflight-binding` | Optional Phase 8D.1 `action-preflight-binding.v1` JSON. When supplied, readiness verifies ref/action consistency and records `preflight_binding_ref` in the output artifact. |
| `--json` | Required flag; emits JSON to stdout |

Status values:

- `ready` — all hard gates pass and plan binding is contractually proven
- `blocked` — at least one hard gate fails
- `inconclusive` — no hard failure but plan binding cannot be proven

Without `--preflight-binding`, the best achievable status is `inconclusive`
with `preflight_chain_plan_binding_unproven`, because the preflight chain
records `git-status-read-only` which cannot prove binding to a
`git-pull-ff-only` plan.

With `--preflight-binding`, readiness consumes the binding's `binding_state`
conservatively:

- `binding_valid` still yields `inconclusive` in the current slice (no
  contract-defined binding proof field exists yet)
- `binding_invalid` blocks readiness with `preflight_binding_invalid`
- `binding_inconclusive` keeps readiness inconclusive with
  `preflight_chain_plan_binding_unproven`

Readiness raises a precondition error if the supplied binding's `plan_ref`,
`chain_ref`, `plan_action`, or `chain_action` do not match the supplied plan
and chain.

Boundary for Phase 8D.0:

- no subprocess execution
- no Git commands
- no network
- no mutation
- no approval runner
- no execution authorisation
- output artifact always carries `does_not_execute=true`,
  `does_not_mutate=true`, `does_not_authorise_actions=true`
- `--readiness-out` parent must exist and target must not already exist

## Phase 8D.2: Contract-defined Preflight Proof Material

Phase 8D.2 closes the Phase 8D.1 epistemic gap by adding an explicit,
schema-validated proof object — `preflight_for_action_plan` — that proves a
`git-status-read-only` run evidence chain was produced as preflight for a
specific `git-pull-ff-only` action plan.

The proof object shape is:

```json
{
  "preflight_for_action_plan": {
    "plan_ref": "<pull-plan.plan_id>",
    "plan_action": "git-pull-ff-only",
    "plan_content_sha256": "<canonical sha256 of the pull plan>"
  }
}
```

It can appear on three artifacts: `run-result.v1`, `run-evidence-chain.v1`,
and `action-preflight-binding.v1`. The field is optional everywhere; pre-8D.2
artifacts remain schema-valid.

The hash uses the same `canonical_json_sha256` function already used elsewhere
in the repository for plan-content binding (`run-result.v1.plan_content_sha256`,
`action-approval.v1.plan_content_sha256`). Editing the pull plan changes the
hash and invalidates the binding — by design.

### `action run-read-only --preflight-for-action-plan`

The Phase 8A read-only runner accepts an optional
`--preflight-for-action-plan <pull-action-plan-json>` argument.

When supplied:

- the referenced JSON must validate as `action-plan.v1`
- the referenced plan's `action` must be exactly `git-pull-ff-only`
- the executing plan's action stays `git-status-read-only` (existing allowlist)
- the executed command is unchanged: exactly one read-only `git status` call
- the emitted `run-result.v1` carries `preflight_for_action_plan` with
  `plan_ref`, `plan_action: "git-pull-ff-only"`, and
  `plan_content_sha256 = canonical_json_sha256(<pull-plan>)`
- the proof material is then propagated into `run-evidence-chain.v1` when the
  chain is validated by `validate-run-chain`

Without `--preflight-for-action-plan`, behaviour is unchanged: the emitted
`run-result.v1` has no `preflight_for_action_plan` field, and downstream
binding remains `binding_inconclusive`.

### Binding states in Phase 8D.2

`bind-preflight-to-action` now distinguishes the following cases:

- `binding_valid` — chain carries `preflight_for_action_plan`, and
  `plan_ref == action_plan.plan_id`,
  `plan_action == "git-pull-ff-only"`, and
  `plan_content_sha256 == canonical_json_sha256(action_plan)` for the supplied
  pull plan.
- `binding_invalid` (with `binding_mismatch`) — proof is present but any of
  `plan_ref`, `plan_action`, or `plan_content_sha256` does not match.
- `binding_inconclusive` — chain has no `preflight_for_action_plan` object.
  This preserves the honest pre-8D.2 result for artifacts that do not carry
  proof.

### Readiness integration

`validate-execution-readiness` trusts `binding_state == binding_valid` only
when the binding artifact carries the `preflight_for_action_plan` proof
object. With proof, the `preflight_chain_plan_binding_proven` gate passes;
without proof, readiness stays `inconclusive` (conservative consumption).
`binding_invalid` continues to block readiness with `preflight_binding_invalid`.

Stage-D execution remains future-only. A `ready` readiness artifact still does
not execute, mutate, or authorise. There is still no Stage-D runner contract.

Boundary for Phase 8D.2:

- pure artifact contract extension
- no subprocess additions to pure binding/readiness modules
- no Git mutation, no fetch, no pull, no network
- existing artifacts without the proof field remain schema-valid
- `binding_valid` is now achievable only with explicit, content-bound proof;
  it is never inferred from naming conventions, timestamps, or source_refs

## Phase 8D.1: action bind-preflight-to-action

```
python -m steuerboard action bind-preflight-to-action <action-plan-json> \
  --run-evidence-chain <chain-json> \
  --binding-out <binding-json> \
  --json
```

Pure artifact bridge that binds one `git-pull-ff-only` `action-plan.v1` to one
`git-status-read-only` `run-evidence-chain.v1`. Emits one
`action-preflight-binding.v1` artifact to stdout and to `--binding-out`.

Arguments:

| Argument | Description |
|----------|-------------|
| `<action-plan-json>` | Path to an `action-plan.v1` JSON artifact (action `git-pull-ff-only`) |
| `--run-evidence-chain` | Path to a `run-evidence-chain.v1` JSON artifact (action `git-status-read-only`) |
| `--binding-out` | Output path for the `action-preflight-binding.v1` artifact (must not exist; parent must exist) |
| `--json` | Required flag; emits JSON to stdout |

Binding states:

- `binding_valid` — chain provably belongs to the supplied pull plan from
  contract-defined fields. Not achievable from current artifacts.
- `binding_invalid` — at least one hard gate fails (unsupported plan or chain
  action, chain status invalid, chain redaction unverified, binding mismatch)
- `binding_inconclusive` — no hard failure but the chain artifact does not
  contain a contract-defined field that ties it to the pull plan. This is the
  honest natural result for the current `run-evidence-chain.v1` contract.

Exit codes:

- `0` for all successfully emitted `action-preflight-binding.v1` artifacts:
  `binding_valid`, `binding_invalid`, and `binding_inconclusive`
- nonzero only for malformed JSON, schema-invalid input, or output-path
  precondition failure (the sentinel JSON written to stdout in those cases
  also satisfies `action-preflight-binding.v1`)

Boundary for Phase 8D.1:

- pure artifact validation: no subprocess, no Git, no network, no mutation
- reads only the two explicitly passed input artifacts
- validates both inputs against their JSON Schemas before processing
- does not execute git pull, does not authorise actions, does not create a runner
- output artifact always carries `does_not_execute=true`,
  `does_not_mutate=true`, `does_not_authorise_actions=true`
- `--binding-out` parent must exist and target must not already exist

## Phase 8E: action run-git-pull-ff-only

Executes a Stage-D approved `git pull --ff-only` for a single repository.
The runner internally reproduces the readiness gate; it never trusts a
pre-computed `action-execution-readiness.v1` artifact.

```
python -m steuerboard action run-git-pull-ff-only <action-plan-json> \
  --approval-validation <approval-validation-json> \
  --run-evidence-chain <run-evidence-chain-json> \
  --preflight-binding <preflight-binding-json> \
  --repo-path <path-to-git-repo> \
  --command-trace-out <output-path> \
  --run-result-out <output-path> \
  --postcheck-out <output-path> \
  --json
```

| Argument | Description |
|---|---|
| `action_plan_json` | Path to `action-plan.v1` JSON (action must be `git-pull-ff-only`) |
| `--approval-validation` | Path to `action-approval-validation.v1` JSON |
| `--run-evidence-chain` | Path to `run-evidence-chain.v1` JSON |
| `--preflight-binding` | Path to `action-preflight-binding.v1` JSON |
| `--repo-path` | Explicit path to the local git repository |
| `--command-trace-out` | Output path for `command-trace.v1` (must not exist) |
| `--run-result-out` | Output path for `run-result.v1` (must not exist) |
| `--postcheck-out` | Output path for `run-postcheck.v1` (must not exist) |
| `--json` | Required flag; emits `run-result.v1` JSON to stdout |

Preconditions enforced before any mutation:

- `action_plan.action == "git-pull-ff-only"`
- `preflight_binding.binding_state == "binding_valid"` with a
  `preflight_for_action_plan` proof block whose `plan_content_sha256` matches
  the supplied plan
- Readiness gate reproduced internally: all four artifacts must yield
  `status == "ready"` from `validate_execution_readiness()`
- `repo_toplevel` must be present and identical in the run evidence chain and
  the preflight binding proof, and `--repo-path` must resolve to that same git
  toplevel
- All three output paths must not exist; their parent directories must exist
- No output path may be inside the git worktree
- Worktree must be clean before pull

Exit codes:

- `0` when the runner completes an execution attempt and emits `run-result.v1`
  with `status` `success` or `failure`
- nonzero for precondition blockers. The CLI still emits a redacted
  `run-result.v1` sentinel with `status: blocked` to stdout, but writes no
  output artifacts and performs no Git mutation

Boundary for Phase 8E:

- exactly one **mutating** Git subprocess call: `git --no-optional-locks pull --ff-only`
- read-only pre/post checks (worktree status, HEAD rev-parse) are separate non-mutating calls
- no `shell=True`
- no merge, rebase, reset, or clean
- three output artifacts written atomically with rollback on partial failure


## Phase 11F-K: runbook run — Heimserver-Service-Gate

The existing generic runner accepts `runbook_kind: "heimserver-service-gate"`:

```bash
python -m steuerboard runbook run examples/runbooks/heimserver-service-gate.json \
  --result-out /tmp/steuerboard/service-gate-result.json \
  --command-trace-out /tmp/steuerboard/service-gate-trace.jsonl \
  --json
```

The plan supplies `service_gate_inputs.artifact_root` and `service_gate_inputs.input_refs`. The runner passes those references to the safe artifact adapter, writes the resulting assessment through the dedicated writer, and emits:

- the standard `runbook-result.v1` at `--result-out`;
- the standard `runbook-step-trace.v1` JSONL at `--command-trace-out`;
- `heimserver-service-gate-assessment.json` in the trace output directory.

`repo_path` must resolve inside a path with a concrete `.git` worktree marker. All three targets must be outside that resolved `.git`-marked worktree, distinct, and absent before execution; regular files, directories, symlinks, and dangling symlinks are rejected without following the final entry. A later publication failure triggers cleanup of all temporary and committed outputs, and any cleanup failure is surfaced explicitly.

Status binding is exact: assessment `passed`, `blocked`, or `inconclusive` becomes the runbook status of the same name. Adapter or writer technical failures produce an inconclusive runbook result and no assessment artifact.

This is artifact-derived diagnostic execution only. It performs no live service check, service-manager operation, network probe, subprocess, shell, SSH, Tailscale CLI/API, repair, or Stage-D action, and it grants no action authorisation.

## Phase 12C: Branch Drift

`inventory branch-drift --warning-threshold N --json` summarizes canonical repositories against each locally available default-branch candidate. This means `main`, `master`, and `trunk` may each be correct for their own repository. Detached, unknown, and failed observations remain separate. The threshold is explicit; local remote references do not prove freshness.
