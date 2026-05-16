# Local CLI deploy readiness

This document describes the **local read-only CLI deploy** of steuerboard.
It is not a product deploy. There is no backend, no UI, no server, no cloud target.

## What this proves

After installing with `python3 -m pip install -e '.[test]'`, running `make PYTHON=python3 deploy-check` proves:

- The installed `steuerboard` console script starts and parses arguments.
- All eight read-only CLI entrypoints emit valid JSON and exit with status 0:
  - `steuerboard observe repo <path> --json`
  - `steuerboard scope explain <path> --json`
  - `steuerboard inventory --json`
  - `steuerboard inventory duplicates --json`
  - `steuerboard assess repo <path> --json`
  - `steuerboard assess explain <assessment-json> --json`
  - `steuerboard plan switch-main <assessment-json> --json`
  - `steuerboard omnipull-report show <report-json> --json`
- All JSON Schemas validate against all checked-in examples.
- The full test suite passes.

The smoke path invokes only read-only CLI commands and contains no fetch, pull, switch,
reset, clean, or network command. It does not instrument system calls.

## What this does not prove

- Any backend readiness. There is no backend.
- Any frontend readiness. There is no frontend.
- Any product deploy readiness. No CI pipeline, no packaging, no distribution.
- Action execution or action authorization. Plan preview is derivation only.
- Plan execution. Plan preview is derivation only.
- Correctness on all machines. `inventory` results depend on the local config and what exists at
  `canonical_repo_roots`. Results are machine-specific; JSON validity is not.

## Install

```sh
python3 -m pip install -e '.[test]'
```

This installs the package in editable mode and includes test dependencies (pytest).

If another interpreter is used, pass the same interpreter to make:

```sh
python -m pip install -e '.[test]'
make PYTHON=python deploy-check
```

## Run the deploy gate

```sh
make PYTHON=python3 deploy-check
```

This runs three targets in sequence, even if make is invoked with parallelism:

| Target     | What it does                                                  |
|------------|---------------------------------------------------------------|
| `validate` | `python3 scripts/validate_examples.py` — all schemas/examples |
| `test`     | `python3 -m pytest` — full test suite                         |
| `smoke`    | Installed CLI entrypoints: exit 0 and emit valid JSON         |

You can run any target independently:

```sh
make PYTHON=python3 validate
make PYTHON=python3 test
make PYTHON=python3 smoke
```

## Config in smoke

The `smoke` target passes `examples/local-configs/heim-pc.json` explicitly via `--config`
to `scope explain`, `inventory`, `inventory duplicates`, and `assess repo`. This config is
checked in and declares `/home/alex/repos` as canonical root.

On other machines this path may not exist. Inventory output is therefore machine-specific
and may still be non-empty because configured excluded roots are also reported, but it remains
valid JSON and a passing smoke.

`observe repo . --json` does not require a config. `assess repo . --json --config ...`
exercises the explicit scope-config path.

## Boundary

The CLI smoke commands exercised by `make deploy-check` are **read-only**:

- No mutation of any target repository.
- No `git fetch`, `git pull`, `git switch`, `git reset`, or `git clean`.
- No network requests.
- No action execution, no action authorization.
- Plan preview only from existing assessment artifacts.
- No branch switches.
- Omnipull adapter reads one explicit artifact path only; no latest lookup and no `/home/alex/logs/omnipull` path search.

The `test` target may create and mutate temporary test fixtures; that is test infrastructure,
not a productive repository action.

This boundary follows the architecture rule:

> Observation ≠ Derivation ≠ Decision ≠ Action


## What comes next

The local CLI deploy gate remains a read-only reproducibility gate.

Phase 4 minimal now adds a contract-first assessment explanation surface.
Phase 5 minimal adds a read-only plan preview surface for `switch-main`. The
preview does not execute, mutate, or authorise actions; its `decision` is a
plan outcome, not an action permission. Action execution and command advice
remain out of scope.

## Local gate vs CI gate

The **local gate** (`make PYTHON=python3 deploy-check` on your machine) proves local correctness
and JSON schema compliance.

The **CI gate** (`.github/workflows/validate.yml`) reproduces the same checks on a clean
checkout across the configured Python matrix. This makes the gate reproducible and ensures
drift between machines does not hide issues.

Both gates prove the same boundary for productive CLI smoke commands: read-only observation, valid schemas, and no target-repository mutations. Test fixtures may still create and mutate temporary repositories.
Neither proves product deploy readiness, backend availability, or frontend functionality.
