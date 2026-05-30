<!-- GENERATED FILE — do not edit by hand.
     Source: steuerboard.cli.build_parser() + scripts/docmeta/cli_surface.json
     Regenerate: make docs  (python scripts/docmeta/generate_cli_surface.py --write) -->

# CLI capability surface (generated)

This file enumerates every invocable `steuerboard` CLI command joined with an
explicit capability classification. It is generated and verified by
`scripts/docmeta/generate_cli_surface.py`; the same table is mirrored into the
marked block in `README.md`. Classification lives in
`scripts/docmeta/cli_surface.json` and is declared explicitly, never inferred
from help text.

Capability counts: read_only=10, derivation_only=6, fetch_only=1, mutating_stage_d=1.

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

## Capability classes

- `read_only` — Reads, observes, or runs a bounded read-only command; no repository mutation and no network access.
- `derivation_only` — Pure transformation or artifact validation producing preview/derived artifacts; no repository mutation, no network access, no execution.
- `fetch_only` — Performs exactly one bounded network fetch and writes evidence; no working-tree mutation.
- `mutating_stage_d` — Bounded Stage-D executor that mutates the working tree (exactly one fast-forward pull) behind a reproduced readiness gate.
