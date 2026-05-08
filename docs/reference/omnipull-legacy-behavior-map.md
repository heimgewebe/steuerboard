# Omnipull Legacy Behavior Map

This document maps the behavior of the legacy omnipull command to the new steuerboard model.

| Legacy-Verhalten | steuerboard-Modell |
| :--- | :--- |
| dirty skip | `dirty_worktree` |
| detached HEAD skip | `detached_head` |
| non-default branch skip | `non_default_branch` |
| origin mismatch | `wrong_remote` / `remote_mismatch` |
| pull --ff-only failure | `ff_only_not_possible` |
| repo cloned | future run-result + command-trace |
| reset --hard | blocked/destructive action |
