# Omnipull Integration

omnipull integration status: minimal read-only adapter started in Phase 6a.

Current implemented surface:

- `python -m steuerboard omnipull-report show <report-json> --json`

Current boundary:

- reads one explicit JSON artifact path only
- no latest lookup
- no path search under `/home/alex/logs/omnipull`
- no fetch/pull/switch/reset/clean
- no network access
- no action execution and no action authorization
- no new plan generation from Omnipull report input in this slice

Future reports should be structured JSON instead of log-grep-only text. steuerboard should explain omnipull reports using the same shared vocabulary, for example:

- `non_default_branch`
- `dirty_worktree`
- `no_upstream`
- `remote_unreachable`
- `ff_only_not_possible`
- `default_branch_unknown`
- `repo_not_in_scope`
- `permission_denied`
