# Assessment Model

Assessment derives status from observations, source refs, freshness, and rules.

An assessment must reference:

- the observation it used (`observation_ref`)
- the source refs it used (`source_refs`)
- the freshness state of those sources (optional: `freshness_refs`)
- the rule that produced the status (optional: `rule_refs`)
- the falsification case that motivated the rule, when applicable (optional: `falsification_refs`)

## Boundary

Assessment is strictly read-only. An assessment:

- derives status from existing observations and scope classifications
- does not plan, authorise, or execute actions
- does not fetch, pull, push, switch branches, or mutate repositories
- does not make network requests

`decision_state` is an Assessment-Ergebnis, not an Action-Freigabe. It answers
"what does the assessment conclude?", not "what is the system allowed to do?".

`decision_state` is a **contractual enum** in the schema — free strings are rejected:
- `action_blocked` — assessment concludes an action would be unsafe or inapplicable
- `evidence_missing` — assessment cannot conclude without additional evidence
- `assessment_clear` — current branch matches observed default_branch_candidate, canonical, clean

### Epistemic boundary: `clean_default_current`

`clean_default_current` means the current branch matches the observed
`default_branch_candidate`. It does **not** mean the default branch is confirmed.
Observation now exposes `default_branch_candidate_source` with values:

- `remote_origin_head`
- `local_branch_heuristic`
- `unavailable`

When `default_branch_candidate_source == "remote_origin_head"`, assessment treats
the local source evidence as observed and does not add
`missing_evidence: ["default_branch_source"]`; confidence is `0.9`.
In this case, provenance emits:

- `assessment.rule.clean_default_current_remote_origin_head_local_source_observed`
- `freshness.default_branch_source.remote_origin_head_local_observed`

When source is not `remote_origin_head`, the source-quality gap remains marked:

- `missing_evidence: ["default_branch_source"]`
- `confidence: 0.8` (not 1.0 or 0.9)
- `assessment.rule.clean_default_current_is_clear_but_default_source_unverified`
- `freshness.default_branch_source.unverified`

`remote_origin_head` provenance is still local observation only. It does not claim
remote freshness or network truth without fetch.

## Pull Readiness (Phase 7a.2)

Assessment derives pull-readiness state from existing local observation fields
(`upstream`, `ahead`, `behind`, default-branch match) without fetch/pull/plan/action.

Status vocabulary for this slice:

- `git_pull_ff_only_local_preflight_clear`
- `git_pull_ff_only_blocked_missing_upstream`
- `git_pull_ff_only_blocked_branch_ahead`
- `git_pull_ff_only_blocked_branch_diverged`
- `git_pull_ff_only_evidence_missing_remote_freshness`

Interpretation boundary:

- `git_pull_ff_only_local_preflight_clear` means local preflight checks are clear
- it does not claim remote freshness
- therefore assessment emits `git_pull_ff_only_evidence_missing_remote_freshness`
  until remote freshness evidence exists
- no fetch is executed by assessment to fill this gap

Existing status `non_default_branch` satisfies the pull-readiness gate
`current_branch_is_default == false`; no separate
`git_pull_ff_only_blocked_non_default_branch` status is introduced in this slice.

This keeps pull readiness as assessment truth, not planner logic.

## Fields (repo-assessment.v1)

Required:
- `schema_version` — const `repo-assessment.v1`
- `assessment_id` — unique ID, format `assess-<timestamp>-<hash>`
- `observation_ref` — `observation_id` of the observation used
- `derived_status` — list of status codes (e.g. `not_git_repo`, `dirty_worktree`, `non_default_branch`, `clean_default_current`)
- `source_refs` — list of data sources used
- `decision_state` — Assessment-Ergebnis (see above)

Optional in schema, emitted by assess_repo in this slice:
- `risk_level` — enum `low`, `medium`, `high`, `unknown`
- `skip_reasons` — normalised reason codes mirroring blocking/defer-style `derived_status` entries only; may be empty for non-blocking outcomes such as `clean_default_current`
- `confidence` — number 0..1, confidence in derived_status
- `missing_evidence` — list of evidence items that would change the assessment
- `rule_refs` — references to assessment rules supporting each derived status
- `freshness_refs` — marks the observed evidence state for each data source used.
  When a config file is absent (`local_config.unavailable` in `source_refs`),
  `scope_unknown` emits `freshness.local_scope_config.unavailable` instead of
  `freshness.local_scope_config.current_invocation`. The two are mutually exclusive:
  a config that was not found cannot be 'freshly read'.
  `freshness_refs` never claim remote freshness without a prior fetch.
- `falsification_refs` — references to matching falsification cases when applicable;
  emitted values are validated by runtime/tests against known failure-case IDs and must not be silently dropped

Explicitly excluded (never in this schema):
- `action`, `plan_id`, `would_run`, `would_mutate`
- `safe_actions`, `safe_alternatives`
- `command_trace`, `run_result`

## Assessment explanations

Assessment explanations are an interpretation layer over an existing
`repo-assessment.v1` object. They do not create plans and do not provide action advice.

`repo-assessment-explanation.v1` is a separate contract with these core fields:

- `assessment_ref` points to the assessed object
- `summary` is bounded narrative about assessment outcomes
- `status_explanations[]` provides one explanation entry per `derived_status`
- `boundary` hard-codes read-only guarantees

`status_explanations[]` uses status-specific provenance refs:

- `rule_refs`, `freshness_refs`, `falsification_refs` are scoped to each status
- `missing_evidence` remains assessment-level context and is repeated per status item

Boundary fields are contractual and always true:

- `does_not_authorise_actions`
- `does_not_mutate`
- `does_not_plan_actions`

This keeps the architecture boundary explicit:

> Observation ≠ Derivation ≠ Decision ≠ Action

An assessment explanation explains decisions already present in assessment output.
It must not recommend commands, must not authorise actions, and must not claim
remote freshness beyond observed evidence.

## Phase history

- Phase 0b: schema shape defined, static examples only
- Phase 3 (PR #11): `assess_repo()` implemented, new optional fields, 5 new examples
