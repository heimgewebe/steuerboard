# Operational Profile v1

Status: implemented.

The operational profile turns the three policy booleans already declared in `local-config.v1` into fail-closed CLI preconditions. Before this phase those fields were descriptive only. They now have executable meaning at the bounded network and Stage-D mutation boundaries.

## Inspect the effective profile

```bash
steuerboard profile show --config ~/.config/steuerboard/local-config.json --json
```

The resulting `operational-profile.v1` report contains the exact loaded configuration path, the three raw policy booleans, the effective decision for each policy-gated operation, and explicit read-only boundary markers.

An effective value of `true` is only a local prerequisite. It is never an authorisation and does not replace action plans, approval validation, evidence chains, readiness verdicts, live-state checks, or postchecks.

## Effective gates

| Operation | Required policy fields |
| --- | --- |
| `remote-refresh.fetch-origin-prune` | `allow_network_fetch=true` |
| `action.run-git-pull-ff-only` | `allow_mutating_actions=true` and `allow_network_fetch=true` |
| `action.run-switch-main` | `allow_mutating_actions=true` and `allow_branch_switch=true` |

A denied operation stops before Git probing, artifact loading, output creation, or mutation. All missing required switches are named in the diagnostic.

## Complete policy is mandatory

`local-config.v1.policy` now requires all three booleans. Missing values do not inherit permissive defaults. Invalid or incomplete policy input fails closed.

## Snapshot semantics

Each command loads one configuration snapshot. The same snapshot is used for both policy and local scope checks in `remote-refresh fetch-origin-prune`; the configuration is not re-read between those checks and the fetch operation.

The profile does not provide dynamic revocation of a process that is already running. It is a command-start precondition, not a background policy daemon.

## Non-goals

- no automatic action execution;
- no daemon or service;
- no scheduled inventory;
- no policy editor command;
- no remote policy source;
- no replacement for the existing Stage-D evidence and approval gates.
