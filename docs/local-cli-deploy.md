# Local CLI deploy readiness

This document describes the **local read-only CLI deploy** of steuerboard.
It is not a product deploy. There is no backend, no UI, no server, no cloud target.

## What this proves

After installing with `python3 -m pip install -e '.[test]'`, running `make PYTHON=python3 deploy-check` proves:

- The installed `steuerboard` console script starts and parses arguments.
- All six read-only CLI entrypoints emit valid JSON and exit with status 0:
  - `steuerboard observe repo <path> --json`
  - `steuerboard scope explain <path> --json`
  - `steuerboard inventory --json`
  - `steuerboard inventory duplicates --json`
  - `steuerboard assess repo <path> --json`
  - `steuerboard assess explain <assessment-json> --json`
- All JSON Schemas validate against all checked-in examples.
- The full test suite passes.

The smoke path invokes only read-only CLI commands and contains no fetch, pull, switch,
reset, clean, or network command. It does not instrument system calls.

## What this does not prove

- Any backend readiness. There is no backend.
- Any frontend readiness. There is no frontend.
- Any product deploy readiness. No CI pipeline, no packaging, no distribution.
- Action planning or authorization. All commands are strictly read-only.
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
- No action planning, no action authorization.
- No branch switches.

The `test` target may create and mutate temporary test fixtures; that is test infrastructure,
not a productive repository action.

This boundary follows the architecture rule:

> Observation ≠ Derivation ≠ Decision ≠ Action

## What comes next

The local CLI deploy gate remains a read-only reproducibility gate.

Phase 4 minimal now adds a contract-first assessment explanation surface. Action
planning, action authorization, and command advice remain out of scope.
