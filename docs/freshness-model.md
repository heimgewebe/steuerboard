# Freshness Model

A source can be correct and still too old for action.

## Freshness states

| State | Meaning |
| --- | --- |
| `fresh` | Measured or loaded within the policy window. |
| `stale` | Available but outside the policy window. |
| `unknown` | Age or collection time is missing. |
| `unavailable` | Source could not be read. |

## Decision use

Freshness is separate from authority. A canonical source with stale freshness can support explanation, but not necessarily action.

Examples:

- A 14-day-old metarepo file may explain intended fleet membership but should not authorize mutation.
- A recent local Git status can support observation but cannot prove remote state if no fetch was performed.
