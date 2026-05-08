# Retention Model

Retention controls how long evidence and run metadata remain available.

Initial principles:

- failed runs may be retained longer than successful runs
- redacted summaries may outlive raw traces
- garbage collection must have a dry-run mode
- retention policy must be documented before evidence archival begins

Phase 0b defines the boundary only.
