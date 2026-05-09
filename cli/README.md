# CLI

Phase 1 introduces a read-only observation CLI.

Command:

    python -m steuerboard observe repo <path> --json

The command emits `repo-observation.v1` JSON. It does not assess risk, plan actions, switch branches, pull, fetch, or mutate repositories.
