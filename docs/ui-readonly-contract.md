# Read-only UI Contract (Phase 10A)

## Purpose

Phase 10A defines the steuerboard UI as a **display layer** over existing,
already-validated steuerboard artifacts. It introduces a contractual,
schema-validated UI view model (`ui-view-model.v1`), example view models derived
from existing CLI/example artifacts, and a minimal dependency-free read-only
scaffold that renders such view models.

The point of this phase is not to "build a frontend". It is to **prove
displayability without action**: that steuerboard artifacts can be shown faithfully
through a thin presentation film that carries no authority of its own.

> Observation ≠ Derivation ≠ Decision ≠ Action

The UI sits at the very bottom of the architecture (masterplan §3, Ebene 8). It
is the last, thinnest layer over already-checked artifacts — never a new source
of truth and never a controller.

## Non-goals

Phase 10A explicitly does **not** add, and must not be read as adding:

- no mutation of any kind
- no execution of any action
- no approval creation
- no action authorisation
- no Git subprocess, no shell, no generic command runner
- no backend in this slice (the existing `backend/` placeholder stays a
  placeholder; only its documentation describes the read-only boundary)
- no UI-triggered actions
- no action buttons, no approval UI, no execute UI
- no fleet / multi-repo operations
- no production deployment surface
- no network server (no localhost bind, no LAN bind) in this slice
- no "temporary" escape hatch of any kind

This slice is boring by design. Boring is the feature.

## Authority model

The UI has **no independent authority**.

It may display:

- CLI JSON artifacts
- schema-validated example artifacts
- derived UI view models (`ui-view-model.v1`)

It must **not**:

- inspect repositories directly
- run Git or any subprocess
- infer hidden state
- decide whether an action is allowed
- authorise actions
- execute actions

Recommended wording, reused across the codebase:

> A UI view model is navigation/display material, not canonical repository state
> and not an action approval.

## Artifact chain

The intended, one-directional chain is:

```text
Existing CLI/example artifacts
  → ui-view-model.v1            (derived display material)
    → read-only display         (scaffold renders the view model)
```

There is **no reverse path** from the UI back to an action. The display end of
the chain cannot reach back to produce a plan, an approval, a readiness verdict,
or an execution. A view model is a leaf, not a lever.

## Boundary flags

Every view model carries a mandatory `boundary` object whose flags are const
true in the schema:

- `does_not_execute: true`
- `does_not_mutate: true`
- `does_not_authorise_actions: true`
- `display_only: true`

Because `boundary` is required and each flag is `const true`, a view model that
weakens any flag is schema-invalid and is rejected by validation.

## Phase 10A security boundary

- No subprocess.
- No Git.
- No shell.
- No network mutation.
- No action endpoint.
- No `POST` / `PUT` / `PATCH` / `DELETE` for actions.
- The `ui-view-model.v1` schema has `additionalProperties: false` everywhere and
  defines **no** command, `argv`, endpoint, method, approval-decision, or
  execution-instruction field. A view model therefore cannot carry an
  executable affordance even by accident.
- This slice ships **no server**. Any future server must bind to `127.0.0.1`
  only, unless a later explicit contract expands that.
- Any future mutating UI path requires a **separate contract**, its own approval
  chain, CSRF / origin controls, a local token model, and explicit tests. None
  of that is in scope here, and Phase 10A does not pre-authorise any of it.

## Parity rule

The UI must show the **same facts** as the underlying CLI JSON / artifacts. It
may simplify presentation (labels, grouping, severity hints), but it must not
add authority and must not silently reinterpret status.

A `ready` readiness rendered in the UI means exactly what `ready` means in the
artifact: proof that a later action could be evaluated — never permission to
act. The display restates; it does not upgrade.

## Failure / unknown semantics

- Unknown remains unknown.
- Inconclusive remains inconclusive.
- Blocked remains blocked.
- Ready remains display-only, not permission.

The UI must never soften, hide, or "round up" a blocking or unknown state into
something more permissive. Severity hints (`info`, `success`, `warning`,
`danger`, `unknown`) are presentation only and do not change the underlying
status.

## Phase 10A vs future phases

- **Phase 10A** = display contract + `ui-view-model.v1` schema + derived example
  view models + minimal static read-only scaffold + boundary tests.
- **Future phases** may add local serving, richer UI, or interactive surfaces —
  but only through separate, explicit contracts. In particular, any
  UI-triggered action remains Stage E in `docs/action-model.md` ("UI may trigger
  only the same approved runner path; UI must not contain independent action
  logic"), which is future-only and out of scope here.

The fence goes up in Phase 10A. The gate — if one is ever built — is a later,
separately-approved slice.
