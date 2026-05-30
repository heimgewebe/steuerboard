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

It intentionally does **not** contain a productive fleet scanner, backend, UI, production fleet planner, evidence archival system, or general mutating action executor. The only mutating capability is one bounded Stage-D `action run-git-pull-ff-only` executor, which performs exactly one fast-forward pull behind a reproduced readiness gate.

Architecture rule:

> Observation ≠ Derivation ≠ Decision ≠ Action

The executable CLI surface is enumerated below, generated from `steuerboard.cli.build_parser()` and an explicit capability classification (`scripts/docmeta/cli_surface.json`). Do not edit the table by hand — run `make docs` to regenerate it; the full generated reference lives in [docs/_generated/cli-surface.md](docs/_generated/cli-surface.md). Capability classes are `read_only`, `derivation_only` (preview/validation), `fetch_only` (one bounded fetch), and `mutating_stage_d` (the single bounded Stage-D executor).

<!-- BEGIN GENERATED: cli-surface -->
| Command | Capability class | Invocation |
| --- | --- | --- |
| `action postcheck-read-only` | `read_only` | `python -m steuerboard action postcheck-read-only <run-result-json> --command-trace <command-trace> --repo-path <repo-path> --postcheck-out <postcheck-out> --json` |
| `action run-read-only` | `read_only` | `python -m steuerboard action run-read-only <action-plan-json> --repo-path <repo-path> --command-trace-out <command-trace-out> --run-result-out <run-result-out> [--preflight-for-action-plan <preflight-for-action-plan>] --json` |
| `assess explain` | `read_only` | `python -m steuerboard assess explain <assessment-json> --json` |
| `assess repo` | `read_only` | `python -m steuerboard assess repo <path> [--config <config>] --json` |
| `inventory` | `read_only` | `python -m steuerboard inventory [--config <config>] --json` |
| `inventory duplicates` | `read_only` | `python -m steuerboard inventory duplicates [--config <config>] --json` |
| `observe repo` | `read_only` | `python -m steuerboard observe repo <path> --json` |
| `omnipull-report latest` | `read_only` | `python -m steuerboard omnipull-report latest <run-index-json> --json` |
| `omnipull-report show` | `read_only` | `python -m steuerboard omnipull-report show <report-json> --json` |
| `scope explain` | `read_only` | `python -m steuerboard scope explain <path> [--config <config>] --json` |
| `action bind-preflight-to-action` | `derivation_only` | `python -m steuerboard action bind-preflight-to-action <action-plan-json> --run-evidence-chain <run-evidence-chain> --binding-out <binding-out> --json` |
| `action validate-execution-readiness` | `derivation_only` | `python -m steuerboard action validate-execution-readiness <action-plan-json> --approval-validation <approval-validation> --run-evidence-chain <run-evidence-chain> --readiness-out <readiness-out> [--preflight-binding <preflight-binding>] --json` |
| `action validate-run-chain` | `derivation_only` | `python -m steuerboard action validate-run-chain <action-plan-json> --command-trace <command-trace> --run-result <run-result> --run-postcheck <run-postcheck> --chain-out <chain-out> --json` |
| `approval validate` | `derivation_only` | `python -m steuerboard approval validate <approval-json> --plan <plan> --checked-at <checked-at> --json` |
| `plan git-pull-ff-only` | `derivation_only` | `python -m steuerboard plan git-pull-ff-only <assessment-json> [--remote-refresh-result <remote-refresh-result>] --json` |
| `plan switch-main` | `derivation_only` | `python -m steuerboard plan switch-main <assessment-json> --json` |
| `remote-refresh fetch-origin-prune` | `fetch_only` | `python -m steuerboard remote-refresh fetch-origin-prune <repo-path> --config <config> --assessment-id <assessment-id> --command-trace-out <command-trace-out> --json` |
| `action run-git-pull-ff-only` | `mutating_stage_d` | `python -m steuerboard action run-git-pull-ff-only <action-plan-json> --approval-validation <approval-validation> --run-evidence-chain <run-evidence-chain> --preflight-binding <preflight-binding> --repo-path <repo-path> --command-trace-out <command-trace-out> --run-result-out <run-result-out> --postcheck-out <postcheck-out> --json` |
<!-- END GENERATED: cli-surface -->

Observation, scope, inventory, and assessment commands are read-only: they must not plan actions, switch branches, pull, fetch, push, or mutate repositories.

The `plan switch-main` command emits a preview-only plan artifact from an existing assessment. It does not execute Git, does not mutate repositories, and does not authorise actions.
It is a pure transformation from `repo-assessment.v1` to `action-plan.v1` and does not provide command advice.

The `plan git-pull-ff-only` command emits a preview-only plan artifact for fast-forward-only Git pulls from an existing assessment. It does not execute Git, does not mutate repositories, does not fetch or pull, and does not authorise actions.
It is a pure transformation from `repo-assessment.v1` to `action-plan.v1` and blocks on missing remote freshness evidence or other pull-blocking conditions.
This slice remains preview-only and does not provide execution permission.

The `remote-refresh fetch-origin-prune` command is Stage B fetch-only evidence production. It runs exactly one bounded command (`git fetch origin --prune`), writes a redacted `command-trace.v1` artifact, and emits `remote-refresh-result.v1`.
It does not perform pull, merge, switch, reset, clean, generic command execution, or action authorization.

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
