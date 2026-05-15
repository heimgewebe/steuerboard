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

Boundary: read-only, no mutation, no fetch, no network, no action planning.

Phase 5 minimal introduces a read-only plan preview surface.

Command:

    python -m steuerboard plan switch-main <assessment-json> --json

The command reads an existing `repo-assessment.v1` JSON file and emits
`action-plan.v1` JSON. It does not start a new observation, does not read
config, does not run Git, and does not touch any repository.

`decision` for the `switch-main` action is one of:

- `blocked` — any blocking status in `derived_status` (e.g. `dirty_worktree`,
  `non_default_branch`, non-canonical `scope_*`, `detached_head`,
  `default_branch_unknown`, `not_git_repo`). The plan must not propose a way
  to bypass the blocker.
- `not_applicable` — `clean_default_current`: current branch already matches
  the observed default branch candidate, no switch is required.

This slice never emits `decision: "allowed"`. Authorising a mutating switch
is out of scope.

Boundary: every plan carries a `boundary` block with
`does_not_execute`, `does_not_mutate`, and `does_not_authorise_actions`
all set to `true`. The plan is a plan outcome, not an action permission.
