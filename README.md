# steuerboard

steuerboard is a local diagnostics and planning surface for workstation repository state, source freshness, omnipull reports, evidence snapshots, and gated local actions. It is not a canonical source of truth.

## Local deploy

```sh
python3 -m pip install -e '.[test]'
make PYTHON=python3 deploy-check
```

See [docs/local-cli-deploy.md](docs/local-cli-deploy.md) for what this proves and what it does not.

The CI gate (`.github/workflows/validate.yml`) reproduces these checks for pushes to `main` and pull requests targeting `main`.

## Planning anchors

- [Masterplan](docs/masterplan.md)
- [Vision](docs/vision.md)
- [Roadmap](docs/roadmap.md)
- [Falsification cases](docs/falsification-cases.md)

## Current scope

This repository contains documentation, JSON Schemas, examples, example validation, and read-only observation, scope, and assessment CLI surfaces.

It intentionally does **not** contain a productive fleet scanner, backend, UI, planner, evidence archival system, or mutating action executor.

Architecture rule:

> Observation ≠ Derivation ≠ Decision ≠ Action

Executable code currently covers schema/example validation, read-only observation/scope surfaces, and a minimal read-only assessment engine:

- `python -m steuerboard observe repo <path> --json`
- `python -m steuerboard inventory --json`
- `python -m steuerboard inventory duplicates --json`
- `python -m steuerboard scope explain <path> --json`
- `python -m steuerboard assess repo <path> --json`
- `python -m steuerboard assess explain <assessment-json> --json`
- `python -m steuerboard plan switch-main <assessment-json> --json`

These commands are read-only. They must not plan actions, switch branches, pull, fetch, push, or mutate repositories. The `assess` command derives a structured assessment from observation and scope — it does not produce action plans or authorise actions.

The `plan switch-main` command is a plan preview only: it derives `action-plan.v1` from an existing `repo-assessment.v1` artifact, does not execute Git, does not mutate repositories, and does not authorise actions.
