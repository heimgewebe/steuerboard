# Local Scope Model

Local scope determines whether a repository path is eligible for assessment or future actions.

## Scope classes

| Scope | Meaning |
| --- | --- |
| `scope_canonical` | Intended local working clone under an approved root. |
| `scope_shadow` | Duplicate or secondary clone that should not be mutated. |
| `scope_backup` | Backup copy, archive, or restore snapshot. |
| `scope_gdrive` | Cloud-synced clone where Git mutation is unsafe. |
| `scope_unknown` | Path is not covered by configured policy. |
| `scope_excluded` | Explicitly excluded by local config. |

## Phase 0b boundary

This document defines the vocabulary only. No code scans the local filesystem in this phase.
