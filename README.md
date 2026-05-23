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
- `python -m steuerboard plan git-pull-ff-only <assessment-json> --json`
- `python -m steuerboard omnipull-report show <report-json> --json`
- `python -m steuerboard omnipull-report latest <run-index-json> --json`

Observation, scope, inventory, and assessment commands are read-only: they must not plan actions, switch branches, pull, fetch, push, or mutate repositories.

The `plan switch-main` command emits a preview-only plan artifact from an existing assessment. It does not execute Git, does not mutate repositories, and does not authorise actions.
It is a pure transformation from `repo-assessment.v1` to `action-plan.v1` and does not provide command advice.

The `plan git-pull-ff-only` command emits a preview-only plan artifact for fast-forward-only Git pulls from an existing assessment. It does not execute Git, does not mutate repositories, does not fetch or pull, and does not authorise actions.
It is a pure transformation from `repo-assessment.v1` to `action-plan.v1` and blocks on missing remote freshness evidence or other pull-blocking conditions.
This slice remains preview-only and does not provide execution permission.

The `omnipull-report show` command is a read-only artifact adapter: it loads exactly one provided
`omnipull-report.v1` JSON file and emits a validated report artifact. It does not implement
filesystem search, does not search `/home/alex/logs/omnipull`, does not execute Git, does not mutate
repositories, does not execute actions, does not authorise actions, and does not generate new plans
from Omnipull report input in this slice.
The artifact `source_path` must match the explicit path provided to the loader.
This match is lexical for this slice (`./examples/x.json` and `examples/x.json` are different strings).
`repos: []` is valid and represents an empty run artifact.

The `omnipull-report latest` command operates on **exactly one** explicit `omnipull-run-index.v1`
JSON file. It selects the newest report entry (by `generated_at`, with `run_id` as lexicographic
tie-break) and emits a bounded `omnipull-report-ref.v1` artifact. It never scans the filesystem,
never auto-loads the referenced report file, never calls Git, never accesses the network, and never
authorises actions. There is no automatic discovery, no glob, no path search under
`/home/alex/logs/omnipull`. The run-index's `source_path` must lexically match the explicit path
passed on the command line.
