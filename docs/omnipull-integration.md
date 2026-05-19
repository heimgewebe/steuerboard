# Omnipull Integration

omnipull integration status: minimal read-only adapter started in Phase 6a;
explicit run-index and strict `latest` lookup added in Phase 6b.

Current implemented surface:

- `python -m steuerboard omnipull-report show <report-json> --json`
- `python -m steuerboard omnipull-report latest <run-index-json> --json`

`latest` consumes one explicit `omnipull-run-index.v1` artifact and emits an
`omnipull-report-ref.v1` reference for the newest report entry. Ordering rule:
primary `generated_at` (descending), tie-break `run_id` (descending lexical).

Current boundary:

- reads one explicit JSON artifact path only (whether report or run-index)
- report and run-index `source_path` must match the explicit artifact path
  string passed to the command
- source path matching is lexical in this slice (no canonicalization, no
  symlink resolution)
- `repos: []` is valid for an empty omnipull-report artifact
- `reports: []` is valid for an empty run-index but `latest` against an empty
  index raises a precise `ValueError`; there is no fallback discovery
- `latest` operates **only** on the explicit run-index artifact: no automatic
  discovery, no directory scanning, no glob, no path search under
  `/home/alex/logs/omnipull`, no `$PWD` walking, no environment lookups
- `latest` does **not** auto-load the referenced omnipull-report file; the
  reference artifact only carries metadata copied from the selected index entry
- no fetch/pull/switch/reset/clean
- no network access
- no Git subprocess
- no action execution and no action authorization
- no new plan generation from Omnipull report or run-index input
- no command advice
- no canonicalization "smart" path matching

Future reports should be structured JSON instead of log-grep-only text. steuerboard should explain omnipull reports using the same shared vocabulary, for example:

- `non_default_branch`
- `dirty_worktree`
- `no_upstream`
- `remote_unreachable`
- `ff_only_not_possible`
- `default_branch_unknown`
- `repo_not_in_scope`
- `permission_denied`
