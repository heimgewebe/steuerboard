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

## Phase 7c.2 — Binding Validation

`action-approval-validation.v1` proves only that one approval binds exactly to one plan.

Binding validation checks:

- approval decision is `approved`
- `approval.plan_ref` matches `plan.plan_id`
- `approval.plan_content_sha256` matches the canonical SHA-256 of the full `action-plan.v1` artifact
- `approval.action` matches `plan.action`
- `approval.decided_at` is not in the future relative to `checked_at`
- `checked_at` is before `approval.expires_at`
- `approval.decided_at` is before `approval.expires_at`
- input plan/approval artifacts are fully schema-valid before semantic binding checks run

`binding_state == "binding_valid"` means only that the binding is intact.
It does **not** mean execution is allowed.

`checked_at` is always explicit. No hidden system time is used.

## Out of Scope in This Slice

Phase 7c.1 does not introduce an approval runner, execution runner, or UI approval flow.
Phase 7c.2 does not introduce an execution runner or UI approval flow.
No UI approval flow exists in this slice.
