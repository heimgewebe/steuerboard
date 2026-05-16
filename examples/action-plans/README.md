# Action Plan Examples

Contains simulated `action-plan.v1` examples only. No actions are executed
by this repository.

Each example carries a `boundary` block whose three fields are all `true`:

- `does_not_execute`
- `does_not_mutate`
- `does_not_authorise_actions`

`switch-main` is a mutating action. The plan preview for `switch-main` only
emits `decision: "blocked"` or `decision: "not_applicable"`. It never emits
`decision: "allowed"`.
