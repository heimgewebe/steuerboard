# steuerboard

steuerboard is a local diagnostics and planning surface for workstation repository state, source freshness, omnipull reports, evidence snapshots, and gated local actions. It is not a canonical source of truth.

## Planning anchors

- [Masterplan](docs/masterplan.md)
- [Vision](docs/vision.md)
- [Roadmap](docs/roadmap.md)
- [Falsification cases](docs/falsification-cases.md)

## Current scope

This repository contains documentation, JSON Schemas, examples, example validation, and a minimal Phase 1 read-only observation CLI.

It intentionally does **not** contain a productive fleet scanner, backend, UI, assessment engine, planner, evidence archival system, or mutating action executor.

Architecture rule:

> Observation ≠ Derivation ≠ Decision ≠ Action

Executable code currently covers schema/example validation and read-only single-repo observation. It must not assess, decide, plan actions, switch branches, pull, fetch, or mutate repositories.
