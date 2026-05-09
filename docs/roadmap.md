# Roadmap

## Phase 0a — Masterplan verankert

Status: complete.

The repository contains the masterplan and README link that establish the planning anchor and core architecture rule.

## Phase 0b — prüfbare Mindeststruktur

Status: core structure plus complete masterplan Pflichtfall example coverage in this commit.

Create the falsification-first repository structure:

- documentation for source, freshness, local scope, redaction, security, and roadmap
- minimal JSON Schemas using Draft 2020-12
- example failure cases
- example validation script
- tests that run validation
- schema files checked against Draft 2020-12 when `jsonschema` is available

No productive scanner, CLI command surface, UI, backend, or action executor is part of this phase. This phase also includes static examples for non-failure-case schemas before Phase 1.

## Phase 1 — Read-only Observation CLI

Status: stop-case coverage expanded.

Phase 1 includes a minimal single-repo read-only observation CLI:

```bash
python -m steuerboard observe repo <path> --json
```

The CLI observes only. It must not assess, decide, plan actions, fetch, switch branches, pull, or mutate repositories.

Stop cases now covered by explicit tests:

1. clean main — local branch, no upstream, clean worktree
2. dirty main — untracked/modified files present
3. feature branch — non-default branch, no upstream
4. missing upstream — branch with no remote tracking ref configured
5. detached HEAD — `current_branch` is `None`, `head_sha` is present
6. remote missing — no origin configured, `remote_url` is `None`
7. wrong remote / remote identity observable — non-GitHub remote URL observable without assessment
8. empty/unborn repo — `git init` with no commits; `head_sha` is `None`

Open stop case (not yet covered by automated tests):

- **dubious ownership** — git's `safe.directory` guard fires when the repo is owned by a different user. Triggering this portably requires either root access to change file ownership or manipulation of the global git config, which would affect the host environment. This case is left as a manual verification item until a safe portable approach is available.
