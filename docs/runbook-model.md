# Runbook Model

## Purpose

Phase 11A introduces read-only runbooks: repeatable local check sequences over existing steuerboard artifacts and read-only/derivation-only functions.

A runbook is an operational checklist, not an action executor.

## Architecture rule

Observation != Derivation != Decision != Action

A runbook may sequence observations and derivations. It must not collapse them into action.

## Authority model

A runbook result is derived diagnostic material.
It is not canonical repository state.
It is not an approval.
It is not permission to execute.
It is not a substitute for Stage-D readiness/approval gates.

## Phase 11A scope

Implemented runbook kind:
- repo-sync-gate

Allowed:
- observe repository state read-only
- derive repo assessment using existing assessment logic
- emit runbook-result.v1
- emit runbook-step-trace.v1 JSONL
- include evidence paths and short assessment

Forbidden:
- git switch
- git pull
- git fetch
- git reset
- git clean
- git merge
- git rebase
- git push
- branch delete
- shell=True
- free shell
- generic command runner
- Stage-D executor calls
- backend/server/UI trigger

## repo-sync-gate semantics

The runbook answers:
"Is this repository locally in a state where the existing steuerboard sync-related assessment can be understood and evidenced?"

It does not synchronize.
It does not fetch freshness.
It does not switch.
It does not pull.

## Output contract

The runbook must write:
- runbook-result.v1
- runbook-step-trace.v1 JSONL

Precondition failures write no output files unless the failure happens after execution has begun and the schema explicitly permits a blocked result.

## Status semantics

Use:
- passed
- blocked
- inconclusive

Do not invent permissive statuses.

## Phase 11A vs future phases

Future runbooks may cover DNS-Gate, SSH-Gate, Tailscale-Preflight, server-facts Snapshot, Heimserver-Service-Gate.
Those are out of scope here.
