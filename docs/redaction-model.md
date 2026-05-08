# Redaction Model

Redaction must exist before evidence archival.

## Minimum rules

- redact token-like values
- redact secret-like key/value pairs
- bound stdout and stderr excerpts
- avoid full diffs unless an explicit policy allows them
- avoid uncontrolled absolute private paths

The example `evidence_contains_secret_like_pattern` demonstrates a case where archival is blocked until redaction is verified.
