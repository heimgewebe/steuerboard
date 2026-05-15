# Action Model

Actions are future gated capabilities. They are not implemented in Phase 0b.

A plan is not an action. A plan does not execute, does not mutate, and does
not authorise actions. The `boundary` block on every `action-plan.v1`
instance enforces this contract:

- `does_not_execute: true`
- `does_not_mutate: true`
- `does_not_authorise_actions: true`

The plan-preview surface for `switch-main` (Phase 5 minimal) emits only
`decision: "blocked"` or `decision: "not_applicable"`. It never emits
`decision: "allowed"`; authorising a mutating switch requires a real
preflight gate that is not implemented in this slice.

## Allowed later with gates

- read-only status commands
- fetch-only operations
- switch to default branch after lifecycle proof
- fast-forward pull on default branch after preflight checks

## Blocked in v1

- free shell
- sudo
- force push
- branch deletion
- destructive reset or clean
- automatic conflict resolution
