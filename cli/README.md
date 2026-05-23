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
