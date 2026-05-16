# Planning Model

Planning simulates an action before it can be allowed.

A plan must state:

- the action target and linked assessment reference
- the plan result (`decision`) as a plan-only outcome
- blockers and missing evidence carried from assessment provenance
- boundary guarantees that preview neither executes nor mutates

## Boundary

Plan preview does not execute commands, does not mutate repositories, and does not
authorise actions.
It also does not provide command advice.

Current minimal slice:

- `python -m steuerboard plan switch-main <assessment-json> --json`
- input is an existing `repo-assessment.v1` artifact
- output is `action-plan.v1`
- pure transformation from `repo-assessment.v1` to `action-plan.v1`
- no repository observation, no config read, no network, no Git subprocess
- this slice is limited to `action == "switch-main"`
- additional actions require a separate contract extension or a new schema slice

`decision` in this contract is not an execution permission:

- `blocked` means blockers are present and no bypass recommendation is generated
- `not_applicable` means no branch switch is needed (`clean_default_current`)
- `decision` never authorises execution or mutation
