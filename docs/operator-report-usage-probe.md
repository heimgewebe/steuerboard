# Operator Report Usage Probe

Status: active trial.

This probe is the deliberate stop before turning `operator report` into another
mandatory automation layer. It answers one question only:

> Does `steuerboard operator report` prevent real operator mistakes often enough
to justify integrating it into Grabowski or Bureau workflows?

## Scope

Use the report as human/operator context for the next 5 to 10 real repository
operations that are already being performed. Do not add a scheduler, daemon,
background monitor, blocking preflight, Bureau integration, Grabowski integration,
notification surface, repair command, or action runner for this probe.

Eligible operations:

- preparing a PR after local work;
- deciding whether to pull, switch branches, or merge;
- reviewing a failed or surprising repo state;
- choosing which repo/branch needs attention next.

Out of scope:

- automatic branch cleanup;
- mandatory global stop on high branch-drift counts;
- automatic repair recommendations;
- scoring repositories by severity;
- treating the report as action approval.

## Trial command

For a normal local trial run:

```sh
steuerboard operator report \
  --branch-warning-threshold 5 \
  --json
```

When explicit Omnipull reports are already known and relevant, include them by
name. The command must not search for them:

```sh
steuerboard operator report \
  --branch-warning-threshold 5 \
  --omnipull-report <path-to-omnipull-report.v1.json> \
  --recent-problem-limit 10 \
  --json
```

## What to record

For each trial, record only a short note in the operator log, PR body, issue, or
conversation summary. No new storage format is required.

Record:

1. operation being considered;
2. target repository;
3. report fields that mattered;
4. decision made;
5. whether the report changed the decision;
6. whether the report produced noise.

Suggested note:

```text
steuerboard operator-report probe:
- operation: <pull|switch-main|merge-prep|review|triage>
- target_repo: <path or repo id>
- useful_signal: <policy|favorite-present|branch-drift|recent-problems|none>
- changed_decision: <yes|no>
- noise: <low|medium|high>
- follow_up: <none|manual check|repo-specific gate|tool change>
```

## Promotion criteria

After 5 to 10 trials, promote to a real Grabowski/Bureau integration only if at
least two trials show a concrete useful signal, such as:

- target repo was not in inventory when it should have been;
- target repo was on an unexpected non-default branch;
- mutation policy was disabled and would have prevented accidental execution;
- recent explicit Omnipull evidence changed the next action;
- the report made a hidden repo-state problem visible before a mutating command.

A useful signal must be a concrete operator decision input. General reassurance
does not count.

## Stop criteria

Do not integrate the report into Grabowski/Bureau if any of these happen:

- most trials say `useful_signal: none`;
- the report mostly repeats facts already checked by the concrete action gate;
- branch-drift count creates anxiety but does not change a target-specific action;
- the report slows normal work without preventing a mistake;
- operators start reading the report as action approval.

If stop criteria trigger, keep `operator report` as a manual diagnostic command
and do not build additional workflow around it.

## Interpretation rule

High global branch drift is not automatically bad. Worktrees, feature branches,
agent branches, and abandoned experiments can all be legitimate. During this
probe, only the target repository and the decision at hand matter.

## Boundary

The usage probe itself does not execute commands, mutate repositories, fetch
remote state, switch branches, approve actions, or create a new gate. It is a
trial protocol for deciding whether a later gate is worth building.
