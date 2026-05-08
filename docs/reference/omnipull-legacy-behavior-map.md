# Omnipull Legacy Behavior Map

This map is descriptive, not normative. It records legacy behavior so steuerboard can model, explain, or reject it. It does not authorize these behaviors as steuerboard actions.

| Legacy-Verhalten | steuerboard-Modell |
| :--- | :--- |
| dirty skip | `dirty_worktree` |
| detached HEAD skip | `detached_head` |
| non-default branch skip | `non_default_branch` |
| origin mismatch | `wrong_remote` / `remote_mismatch` |
| pull --ff-only failure | `ff_only_not_possible` |
| repo cloned | future gated clone action + action-plan + run-result + command-trace |
| reset --hard | blocked/destructive action / legacy-only |
