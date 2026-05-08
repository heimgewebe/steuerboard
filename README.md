# steuerboard

steuerboard is a local diagnostics and planning surface for workstation repository state, source freshness, omnipull reports, evidence snapshots, and gated local actions. It is not a canonical source of truth.

## Planning anchors

- [Masterplan](docs/masterplan.md)
- [Vision](docs/vision.md)
- [Roadmap](docs/roadmap.md)
- [Falsification cases](docs/falsification-cases.md)

## Phase 0b scope

This repository currently contains only documentation, JSON Schemas, examples, and example validation. It intentionally does **not** contain a productive scanner, CLI command surface, backend, UI, or mutating action executor.

Architecture rule:

> Observation ≠ Derivation ≠ Decision ≠ Action

The first executable code in this repository validates examples against schemas so the plan can be checked before implementation starts.
