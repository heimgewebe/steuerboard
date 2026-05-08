# Security Model

steuerboard must not turn local diagnostics into an ambient remote-control surface.

## Phase 0b security posture

- no productive scanner
- no action executor
- no free shell
- no backend
- no UI
- no real evidence capture
- no secrets in examples

## Future UI constraints

- bind to `127.0.0.1`
- no LAN bind by default
- no GET for mutating actions
- CSRF protection
- origin checks
- ephemeral local token
- actions disabled by default
