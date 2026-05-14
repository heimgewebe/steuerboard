# Local CLI deploy readiness

This document describes the **local read-only CLI deploy** of steuerboard.
It is not a product deploy. There is no backend, no UI, no server, no cloud target.

## What this proves

After installing with `python -m pip install -e '.[test]'`, running `make deploy-check` proves:

- All five read-only CLI entrypoints start, parse arguments, and emit valid JSON:
  - `steuerboard observe repo <path> --json`
  - `steuerboard scope explain <path> --json`
  - `steuerboard inventory --json`
  - `steuerboard inventory duplicates --json`
  - `steuerboard assess repo <path> --json`
- All JSON Schemas validate against all checked-in examples (14 schemas, 45 examples).
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
python -m pip install -e '.[test]'
```

This installs the package in editable mode and includes test dependencies (pytest).

## Run the deploy gate

```sh
make deploy-check
```

This runs three targets in sequence:

| Target     | What it does                                                  |
|------------|---------------------------------------------------------------|
| `validate` | `python scripts/validate_examples.py` — all schemas/examples |
| `test`     | `python -m pytest` — full test suite                          |
| `smoke`    | All CLI entrypoints: exit 0 and emit valid JSON               |

You can run any target independently:

```sh
make validate
make test
make smoke
```

## Config in smoke

The `smoke` target passes `examples/local-configs/heim-pc.json` explicitly via `--config`
to `scope explain`, `inventory`, and `inventory duplicates`. This config is checked in and
declares `/home/alex/repos` as canonical root. On other machines this path may not exist;
inventory will return an empty result, which is still valid JSON and a passing smoke.

`observe repo . --json` does not require a config. `assess repo . --json --config ...` exercises the explicit scope-config path.

## Boundary

All commands in `make deploy-check` are **read-only**:

- No mutation of any repository.
- No `git fetch`, `git pull`, `git switch`, `git reset`, or `git clean`.
- No network requests.
- No action planning, no action authorization.
- No branch switches.

This boundary follows the architecture rule:

> Observation ≠ Derivation ≠ Decision ≠ Action

## What comes next

The local CLI deploy gate is Phase 3.5 in the roadmap. It does not advance to Phase 4.
Phase 4 would add human-readable assessment explanations and cross-referencing rule refs.
That phase is deferred until after this gate is proven reproducible.
