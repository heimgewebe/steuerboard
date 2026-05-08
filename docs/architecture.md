# Architecture

steuerboard is layered so display and action cannot masquerade as truth.

```text
steuerboard
├─ 1. Falsification Layer
├─ 2. Observation Layer
├─ 3. Source Layer
├─ 4. Assessment Layer
├─ 5. Planning Layer
├─ 6. Evidence Layer
├─ 7. Action Layer
└─ 8. UI Layer
```

## Layer boundaries

1. **Falsification Layer**: describes what can break before naming statuses.
2. **Observation Layer**: records read-only local facts and command results.
3. **Source Layer**: records origin, freshness, and authority of each fact.
4. **Assessment Layer**: derives statuses from observations and rules.
5. **Planning Layer**: simulates actions and identifies missing evidence.
6. **Evidence Layer**: stores redacted traces with retention rules.
7. **Action Layer**: remains gated and future-only.
8. **UI Layer**: renders CLI-equivalent results without independent logic.

## Phase 0b boundary

Only layers 1 and the schema/documentation foundations for layers 2 through 6 are represented here. There is no productive repo scanner, no backend, no UI, and no action executor.
