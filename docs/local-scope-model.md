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

## Minimal inventory slice

Phase 2 starts with read-only local inventory classification.

- `scope_excluded`: path under `excluded_repo_roots`
- `scope_gdrive`: path contains a `GDrive` segment
- `scope_backup`: path contains a segment including `backup`
- `scope_canonical`: path under `canonical_repo_roots`
- `scope_unknown`: outside configured roots
- `scope_shadow`: duplicate `git_toplevel` observed via multiple local paths

This is local path classification only. It does not assess risk, decide actions, or mutate repositories.
