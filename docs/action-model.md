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

## Contract Note: Redefinition of action-plan.v1

This phase redefines the previously reserved `action-plan.v1` schema shape.
Previous examples in Phase 0b used executor-oriented placeholders (`would_run`, `would_mutate`).
The current slice redefines `action-plan.v1` as a preview-only contract artifact derived from assessment, not as an executor interface.
No executor compatibility is promised in this or earlier phases.
The schema enforces this boundary:
- Boundary fields (`does_not_execute`, `does_not_mutate`, `does_not_authorise_actions`) are mandatory and const true.
- Execution/advice fields (`would_run`, `would_mutate`, `safe_alternatives`, `required_evidence`) are not present in the schema.
