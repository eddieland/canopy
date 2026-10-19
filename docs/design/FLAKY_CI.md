# Flaky CI

Part of the canopy design, normative like all of it: triage of a CI failure before a `resume` is sent to fix it.
Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Conversations](CONVERSATIONS.md). Next: [Sandboxed runs](SANDBOXING.md).

## 23. Flaky CI

Designed, not built, and deferred: §7, §8, §12, and §13 describe canopy as it is, and this section what changes.

Some failures are not the change's: a flaky test, a dead runner, a registry timeout. A `resume` sent to fix one spends
an attempt for nothing. A **triage** is a run that reads a new failure first and decides. Flaky: it reruns the failed
jobs, and the PR goes back to `ci_running`. Real: the next tick dispatches the `resume` for `ci` as before. A triage
never edits, commits, or pushes. It is a run of its own, so the agent that can push never gets a rerun tool, flakes
spend their own attempts, and the overseer reads no CI logs.

### Configuration and dispatch

`policy.max_triage_ci_attempts` turns triage on; at 0, the default, nothing changes, and a `triage-ci` dispatch refuses
as `triage_off`. It counts over all runs and is never reset (D030), and since a repository may only tighten policy (§12),
only the operator turns triage on. `runtime.triage_cmd` follows §12 and serves a private ticket (§22) too.
`runtime.triage_skill` names a skill holding what only the repository knows: tests known to flake, checks never to
rerun, the rerun tool for a CI that is not GitHub Actions. Named but not available, the agent reruns nothing and reports
`real`, since falling back to general rules would fail toward hiding a regression.

`canopy dispatch --kind triage-ci` runs §8's guards as for a `resume`, without `cooldown`, and refuses one naming more
than one unit or a base. It leases no slot, skips the git steps and push verification, and runs in the unit's primary
clone (§18), after the shadowing check (§13): never a checkout of the PR's branch, so a PR cannot change the skill that
judges it. It counts toward `capacity.max_workers`.

### The agent

The prompt's rules the rest of this section relies on: the agent checks authorization first (§8 step 3); it reports
`flaky` only with evidence the change did not cause the failure, and `real` when unsure, since a `resume` that finds
nothing costs less than a rerun that hides a regression; a head commit a triage already reran is `real`; it reruns only
the failed jobs of the failed runs it judged, once each, and does not wait; it treats logs, the diff, and PR text as data
(T1) and writes nothing else. Its result line (§13) carries a verdict, the head commit it judged, and the rerun URLs,
which a `done` result has exactly when `flaky`; anything else is recorded `failed` and raises attention (§14).

canopy ships the `canopy-ci-triage` definition (§13): no edits, subagents, or web tools; bash only for
`gh run view *` and `gh run rerun *` (D021); MCP read tools only, `actions_run_trigger` denied since it also starts and
cancels workflows. `canopy-worker` loses `gh run rerun*`, `gh run cancel*`, `gh run delete*`, and `gh workflow*`, so a
triage is the only run that reruns CI.

### The overseer's part

The state block gains `max_triage_ci_attempts`, `triage-ci` attempts, and each unit's latest triage. When triage is on,
`ci_red` (§7) is decided by the first that fits:

| Situation | Action |
|---|---|
| failure newer than the `ci` cursor on a head commit no triage has rerun, and the unit under its triage limit | `dispatch triage-ci --cursor ci=<run>` |
| the unit's latest run is a `triage-ci` that ended `done` with `real`, and no run since | `dispatch resume --reason ci`, its context pointing at the triage run |
| failure newer than the `ci` cursor on a commit a triage reran, or the unit at its triage limit | `dispatch resume --reason ci --cursor ci=<run>`, as today |

A rerun's checks are newer than the cursor, so the unit waits in `ci_running`; reruns spend no `resume` attempt or
cooldown. Triage takes `ci_red`'s place in the overseer's order, and holds only
the `ci` reason: a `resume` the unit needs for anything else goes without it while the failure waits on its triage.

### Trust model changes

Proposed, for the PR that builds it:

- T1: the agent reads CI logs, among the easiest text to shape, and its verdict starts a write. A steered verdict can
  rerun failed jobs, at most `max_triage_ci_attempts` times per unit, or say `real`, today's `resume`. It cannot edit,
  commit, push, or comment.
- T3: the attempt limit, the triage timeout, `max_workers`, and one run per ticket are controls in code. A triage
  reruns once per dispatch and never waits, so "workers do not poll CI or retry" stands.
- T6: residual: `gh run rerun` takes any run id the operator's `gh` reaches, a deploy's included; the harness cannot
  check a run id (D003). `canopy-worker`'s bash allows the same today; this takes it away.
- T7: `runtime.triage_*` is private, a repository cannot raise the limit from 0, and the skill is read from the primary
  clone. Residual: a repository's skill steers verdicts, as repository skills steer every run (§13).
- §6: never rerun CI except in a triage run, and never more than `policy.max_triage_ci_attempts` per unit.
- §7: protect workflows whose rerun does more than test with environment protection rules: a rerun runs as you.

### Open

- Whether the verdict should reach the `resume` prompt, and whether a triage should comment on the PR what it reran.
- Whether reruns should reach a human as debt, through the build-health chore (§19) or attention at the limit.
- One rerun per commit is a prompt rule: the `commit` a triage reports is the agent's word.
