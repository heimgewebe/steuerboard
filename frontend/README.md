# Frontend

Phase 10A read-only display scaffold.

The frontend is **read-only** in Phase 10A. It consumes `ui-view-model.v1`
artifacts and renders them as display material. It is the thin presentation film
over already-validated steuerboard artifacts — never a controller.

> A UI view model is navigation/display material, not canonical repository state
> and not an action approval.

## What this scaffold is

- `index.html` — a single, dependency-free static page. It renders one pasted
  `ui-view-model.v1` document read-only (title, status, summary rows, sections,
  warnings, sources). It builds the DOM with `textContent` only.
- It verifies the document's `schema_version` is `ui-view-model.v1` and that the
  `boundary` is display-only (all flags true) before rendering anything.

Open `index.html` in a browser and paste any artifact from
`../examples/ui-view-models/` to see it rendered.

## Boundary (Phase 10A)

This frontend:

- is read-only and consumes `ui-view-model.v1` artifacts only
- does not inspect Git repositories
- does not run Git, a shell, or any subprocess
- does not execute actions
- does not authorise actions
- has no action buttons, no approval UI, and no execute UI
- has no network access and ships no server in this slice

Future interactive or action-triggering UI is **out of scope** for Phase 10A and
would require a separate contract (see
[../docs/ui-readonly-contract.md](../docs/ui-readonly-contract.md) and Stage E in
[../docs/action-model.md](../docs/action-model.md)).
