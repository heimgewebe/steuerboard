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

Phase 8B introduces a bounded read-only postcheck for an existing Phase 8A run.
Phase 8B is **not** a pull. Phase 8B is **not** an approval runner. Phase 8B is
a read-only Postcheck/Record slice whose purpose is to make execution evidence
auditable before any Stage-D mutation is discussed.

Command:

    python -m steuerboard action postcheck-read-only <run-result-json> \
      --command-trace <trace-json> \
      --repo-path <repo-path> \
      --postcheck-out <postcheck-json> \
      --json

The command:

- reads one `run-result.v1` JSON file and validates it fully against its schema
- reads one `command-trace.v1` JSON file and validates it fully against its schema
- requires `run-result.v1.status == success`
- requires `run-result.v1.evidence_paths` to include the supplied
  `command-trace.v1` path
- validates that the trace command is exactly the hardened git status command:
  `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
- requires `command-trace.v1.exit_code == 0`
- requires `command-trace.v1.stdout_excerpt` for output comparison
- requires `run-result.v1.redaction_verified == true`
- requires `command-trace.v1.redacted == true`
- verifies `--repo-path` resolves to the same git toplevel as in the trace command
- re-runs `git --no-optional-locks -C <repo-toplevel> status --porcelain=v1`
- compares new status output against original trace `stdout_excerpt`
- writes a `run-postcheck.v1` artifact to `--postcheck-out` (outside the inspected repo)
- emits `run-postcheck.v1` JSON on stdout

Status values:

- `passed` — new status output matches the original trace excerpt and
  neither side is truncated
- `failed` — new status output differs (reason: `worktree_changed_after_run`)
- `inconclusive` — precondition failure or recheck command failure
  (reasons include `postcheck_command_failed` and
  `stdout_excerpt_truncated`)

If either original or rechecked status output is truncated at excerpt
boundary, postcheck result is `inconclusive` (reason:
`stdout_excerpt_truncated`) and never `passed`.

On precondition failure the command emits a sentinel `run-postcheck.v1` JSON on
stdout with `status: inconclusive` and exits with code 1.

`run-postcheck.v1` is an evidence artifact, not an authorisation mechanism.
A passed postcheck does not authorise any subsequent action.

Evidence chain produced by Phases 8A + 8B:

1. `command-trace.v1` — what command ran, what it produced, redacted
2. `run-result.v1` — run succeeded, redaction verified, trace referenced
3. `run-postcheck.v1` — worktree state verified against original trace

Boundary for Phase 8B:

- no mutating Git actions
- no pull, fetch, switch, merge, rebase, reset, clean
- no free shell, no sudo, no network
- no generic subprocess surface
- no approval runner
- no execution authorisation
- output must be outside the inspected repository worktree
- output file must not pre-exist; parent directory must exist

