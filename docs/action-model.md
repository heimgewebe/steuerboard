# Action Model

Actions are future gated capabilities. They are not implemented in Phase 0b.

Plan preview output is not an action executor and not an action authorisation.
It is a contract artifact derived from prior assessment.

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

## Plan Preview Boundary

`action-plan.v1` in the current slice is preview-only:

- no command execution
- no repository mutation
- no action authorisation
