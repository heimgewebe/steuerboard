# Observation Model

Observation is read-only measurement. It does not classify risk, decide actions, or mutate repositories.

Future observations may include:

- path
- `is_git_repo`
- current branch
- HEAD SHA
- dirty state
- upstream
- ahead/behind counts
- remote URL
- default branch candidate
- submodule status
- ownership status
- command exit codes

## Boundary

Phase 1 starts with a minimal read-only observation CLI for a single repository path.

The observation layer must not emit assessment, decision, safe-action, or risk fields. Those belong to later layers.
