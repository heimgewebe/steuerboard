# Source-of-Truth Model

steuerboard must never say “steuerboard says” as if that were enough. Every claim needs a source reference.

## Source classes

| Class | Meaning | Examples |
| --- | --- | --- |
| Canonical source | External or configured reference used as authority for intended state. | metarepo inventory, Git remote default branch, wgx config, omnipull JSON report |
| Local observation | Read-only fact measured on the workstation. | current branch, HEAD SHA, worktree status |
| Derived assessment | steuerboard rule output from observations and source refs. | `clean_feature_branch`, `scope_shadow` |
| Decision | Allow, warn, block, or require evidence. | `action_blocked`, `source_stale_for_action` |

## Rule

No source reference means no judgment. A derived assessment must keep links to the observations and sources that produced it.
