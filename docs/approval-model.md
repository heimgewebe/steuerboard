# Approval Model

## Purpose

`action-approval.v1` defines approval as a bounded artifact.
Approval is an artifact, not a command.

## Contract

- Approval does not execute anything.
- Approval is valid only for one exact `plan_ref`.
- Approval must not permit plan substitution.
- Approval must not permit command substitution.
- Approval must expire.
- Approval is necessary but not sufficient for execution.
- A rejected approval is also a first-class artifact.

## Execution Boundary

Even when approval exists, future execution remains gated.
Execution still requires a runner contract, command trace, run-result, and postcheck evidence.

## Out of Scope in This Slice

Phase 7c.1 does not introduce an approval runner, execution runner, or UI approval flow.
No UI approval flow exists in this slice.
