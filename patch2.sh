#!/bin/bash
(cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF_PATCH'
diff --git a/docs/reference/omnipull-legacy-behavior-map.md b/docs/reference/omnipull-legacy-behavior-map.md
index 4a53764..6c0e2c1 100644
--- a/docs/reference/omnipull-legacy-behavior-map.md
+++ b/docs/reference/omnipull-legacy-behavior-map.md
@@ -9,5 +9,5 @@ This map is descriptive, not normative. It records legacy behavior so steuerboard
 | non-default branch skip | `non_default_branch` |
 | origin mismatch | `wrong_remote` / `remote_mismatch` |
 | pull --ff-only failure | `ff_only_not_possible` |
-| repo cloned | future run-result + command-trace |
-| reset --hard | blocked/destructive action |
+| repo cloned | future gated clone action + action-plan + run-result + command-trace |
+| reset --hard | blocked/destructive action / legacy-only |
diff --git a/docs/reference/omnipull-legacy-command.md b/docs/reference/omnipull-legacy-command.md
index d4cab65..3bcb7b7 100644
--- a/docs/reference/omnipull-legacy-command.md
+++ b/docs/reference/omnipull-legacy-command.md
@@ -1,5 +1,9 @@
 # Legacy Omnipull Command
+
 Status: legacy reference only. Not executable in steuerboard Phase 0b.
+
 The preserved command is stored as:
+
 - `docs/reference/omnipull-legacy-command.sh.txt`
+
 It is intentionally stored as `.sh.txt` so it is not treated as a runnable project script.
EOF_PATCH
)
