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

Phase 0b includes only a minimal schema placeholder. The read-only observation CLI belongs to Phase 1 and is not implemented here.
