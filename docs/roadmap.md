# Roadmap

## Phase 0a — Masterplan verankert

Status: complete.

The repository contains the masterplan and README link that establish the planning anchor and core architecture rule.

## Phase 0b — prüfbare Mindeststruktur

Status: core structure plus complete masterplan Pflichtfall example coverage in this commit.

Create the falsification-first repository structure:

- documentation for source, freshness, local scope, redaction, security, and roadmap
- minimal JSON Schemas using Draft 2020-12
- example failure cases
- example validation script
- tests that run validation
- schema files checked against Draft 2020-12 when `jsonschema` is available

No productive scanner, CLI command surface, UI, backend, or action executor is part of this phase. This phase also includes static examples for non-failure-case schemas before Phase 1.

## Phase 1 — Read-only Observation CLI

Status: started.

Phase 1 now includes a minimal single-repo read-only observation CLI:

```bash
python -m steuerboard observe repo <path> --json
```

The CLI observes only. It must not assess, decide, plan actions, fetch, switch branches, pull, or mutate repositories.

Remaining Phase 1 stop cases still need explicit test coverage before Phase 2 begins.
