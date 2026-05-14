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

Values:
- `action_blocked` — assessment concludes an action would be unsafe or inapplicable
- `evidence_missing` — assessment cannot conclude without additional evidence
- `assessment_clear` — assessment concludes the canonical, clean, on-default-branch state

## Fields (repo-assessment.v1)

Required:
- `schema_version` — const `repo-assessment.v1`
- `assessment_id` — unique ID, format `assess-<timestamp>-<hash>`
- `observation_ref` — `observation_id` of the observation used
- `derived_status` — list of status codes (e.g. `not_git_repo`, `dirty_worktree`, `non_default_branch`, `clean_default_current`)
- `source_refs` — list of data sources used
- `decision_state` — Assessment-Ergebnis (see above)

Optional (added in Phase 3):
- `risk_level` — enum `low`, `medium`, `high`, `unknown`
- `skip_reasons` — normalised reason codes matching `derived_status` entries
- `confidence` — number 0..1, confidence in derived_status
- `missing_evidence` — list of evidence items that would change the assessment
- `rule_refs` — optional references to rules that produced this assessment
- `freshness_refs` — optional references to freshness model entries
- `falsification_refs` — optional references to falsification cases

Explicitly excluded (never in this schema):
- `action`, `plan_id`, `would_run`, `would_mutate`
- `safe_actions`, `safe_alternatives`
- `command_trace`, `run_result`

## Phase history

- Phase 0b: schema shape defined, static examples only
- Phase 3 (PR #11): `assess_repo()` implemented, new optional fields, 5 new examples
