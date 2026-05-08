# Vision

steuerboard is a local coherence checker and operating adapter for workstation repository state. It does not create canonical truth. It creates source-bound, freshness-bound, inspectable operational derivations.

The central rule is:

> Observation ≠ Derivation ≠ Decision ≠ Action

## What steuerboard should answer later

- Which repositories exist locally?
- Which repositories are canonical, shadows, backups, or unknown clones?
- Which source facts are fresh enough for a decision?
- Why would omnipull skip a repository?
- Which action would be safe, which is blocked, and which evidence is missing?

## What Phase 0b does

Phase 0b makes the plan testable. It introduces failure cases, minimal schemas, examples, and validation. It does not implement a scanner or a command surface for real repositories.
