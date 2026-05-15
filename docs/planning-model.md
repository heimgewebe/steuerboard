# Planning Model

Planning simulates an action before it can be allowed.

A plan must state:

- what would run
- what would change
- why the action is allowed, warned, blocked, or not applicable
- what evidence is required
- what safe alternatives exist

## Boundary

A plan is not an executor and not an authorisation. The contract is enforced
by the `boundary` block on every `action-plan.v1` instance:

- `does_not_execute: true`
- `does_not_mutate: true`
- `does_not_authorise_actions: true`

`decision` in the plan is a plan outcome, not an action permission.

- `blocked` means the plan must not propose a way to bypass the blocker.
- `not_applicable` means no action is required — for example, the working
  tree already matches the target state.

## Phase 5 — Plan Preview (minimal contract slice)

Status: minimal slice started.

The first plan-preview surface derives an `action-plan.v1` from an existing
`repo-assessment.v1` JSON object. It does not start a new observation, does
not read configuration, does not run Git, and does not touch any repository.

```bash
python -m steuerboard plan switch-main <assessment-json> --json
```

Status mapping for `switch-main`:

- blocking statuses → `decision: "blocked"`: `not_git_repo`, `scope_backup`,
  `scope_gdrive`, `scope_excluded`, `scope_unknown`, `scope_shadow`,
  `dirty_worktree`, `detached_head`, `default_branch_unknown`,
  `non_default_branch`.
- `clean_default_current` → `decision: "not_applicable"`: the current branch
  already matches the observed default branch candidate, so no switch is
  required.

`switch-main` is a mutating action. This preview slice never emits
`decision: "allowed"`; authorising the switch is out of scope until later
phases attach lifecycle evidence and a real preflight gate.
