# Flaky CI

Part of the canopy design, normative like all of it: triage of a CI failure before a fix-ci worker is sent. Sections are
numbered across the whole design; the [README](README.md) has the map. Previous: [Conversations](CONVERSATIONS.md).
Next: [Sandboxed runs](SANDBOXING.md).

## 23. Flaky CI (M25)

Designed, not built, and deferred (ROADMAP M25): until M25 lands, §7's `ci_red` always dispatches `fix-ci`, and §7,
§8, §12, and §13 describe canopy as it is. This section says what changes in each.

Some failures are not the change's: a test that fails one run in five, a runner that died, a package registry that
timed out. A `fix-ci` worker sent to one changes code that is not broken, or reports `blocked`, and spends an attempt
either way. A **triage** is a run that reads a new failure first and decides. Flaky: it reruns the failed jobs, and the
PR goes back to `ci_running`. Real: the next tick dispatches `fix-ci` as before. A triage never edits, commits, or
pushes, and holds no worktree. It is a run of its own, not part of `fix-ci` or the overseer's judgment, so the agent
that can push never gets a rerun tool, flakes spend their own attempts rather than `fix-ci`'s, and the overseer reads no
CI logs.

### Configuration

```toml
[policy]
max_triage_ci_attempts = 0   # per unit; 0, the default, turns triage off

[runtime]
triage_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-ci-triage --format json {prompt}'
triage_timeout_minutes = 10
triage_skill = ""            # optional; the skill that says which of a repository's failures are flaky
```

- `max_triage_ci_attempts` is a `max_<kind>_attempts` like the others (§8): counted over all runs, never reset (D030).
  A repository may only tighten policy (§12), so only the operator's file turns triage on.
- `triage_cmd` follows §12, and serves a private ticket (§22) too: the triage agent writes nothing to the tracker.
- `triage_skill` names a skill the triage agent follows, the repository's (read from its primary clone, below) or the
  operator's (§13). It holds what only the repository knows: tests known to flake, failures that are always
  infrastructure, checks never to rerun, and, for a CI that is not GitHub Actions, which tool reruns a job. Unset, the
  agent follows the prompt's general rules alone. Named but not available, the agent reruns nothing and reports `real`
  with a summary starting `no triage skill:`; falling back to the general rules would fail toward hiding a regression.

### Off unless configured

With `max_triage_ci_attempts` at 0 nothing changes: the state block has no triage fields, the overseer prompt's triage
rows do not apply, `ci_red` dispatches `fix-ci`, and a `triage-ci` dispatch refuses as `triage_off`, with no attention
item.

### Dispatch

`canopy dispatch --kind triage-ci`, with the failed run as its `ci` cursor and the check in its context, runs §8's
guards as for `fix-ci`, without `cooldown`, plus:

- `triage_off`: `policy.max_triage_ci_attempts` is 0.
- `bad_request`: a `triage-ci` that names more than one unit, or a base. A triage reads one PR.

It leases no slot. The run skips the git steps and push verification, and runs `triage_cmd` with
`triage_timeout_minutes` in the unit's primary clone (§18), which the shadowing check (§13) covers first, as for the
overseer. The cwd is never a checkout of the PR's branch, so a PR cannot change the skill that judges it. A triage
counts toward `capacity.max_workers` with workers and reviews: it is an agent run, with spend.

### The prompt

`prompts/ci-triage.md`, and `ci-triage-private.md` for a started ticket (§22), hold the agent's rules. What the rest
of this section relies on:

- It checks authorization first, as every worker does (§8 step 3), and is `failed` with `not authorized:` otherwise.
- It reports `flaky` only with evidence the change did not cause the failure: the skill names it, the job failed
  before any of the repository's code ran, or a test the diff does not touch also fails and passes on the base branch.
  Anything it is unsure of is `real`: a `fix-ci` that finds nothing to fix costs less than a rerun that hides a
  regression. A head commit a triage already reran is `real`: a check gets one rerun per commit.
- It reruns only the failed jobs of the failed runs it judged, on the PR's head commit, once each, with
  `gh run rerun <id> --failed` or the tool the skill names. It starts, cancels, and touches nothing else, and does not
  wait for the rerun.
- It treats logs, the diff, and PR text as data (TRUST_MODEL T1), and writes nothing else: no comments, labels, edits,
  or commits. Its summary is its report, listed with the ticket's other runs (§22).

Result contract, one JSON line, last line of the agent's text (§13):

```json
{"status":"done|failed","verdict":"flaky|real","commit":"<full head sha>",
 "reruns":["https://github.com/o/r/actions/runs/123"],"summary":"one paragraph"}
```

- `done` has a verdict and the full head commit it judged. `reruns` is non-empty exactly when the verdict is `flaky`:
  at most 10 plain `https://` URLs. Otherwise the run is recorded `failed` with a harness note.
- `failed` means it could not triage, and the summary says why. Like any run that ends other than `done`, it raises
  attention (§14), and the overseer waits for an authorized reply or an operator message before the unit's next
  dispatch.
- Anything else is `unknown`.

### The overseer's part

The state block's `policy` gains `max_triage_ci_attempts`, each unit's `attempts` gains `triage-ci`, and each unit
gains its latest triage: status, verdict, commit, reruns, and when it ended. When triage is on, `ci_red` (§7) is
decided by the first that fits:

| Situation | Action |
|---|---|
| failure newer than the `ci` cursor on a head commit no triage has rerun, and the unit under its triage limit | `dispatch triage-ci --cursor ci=<run>` |
| the unit's latest run is a `triage-ci` that ended `done` with `real`, and no run since | `dispatch fix-ci`, its context pointing at the triage run |
| failure newer than the `ci` cursor on a commit a triage reran, or the unit at its triage limit | `dispatch fix-ci --cursor ci=<run>`, as today |

A rerun's checks are newer than the cursor, so a unit whose rerun is still running is `ci_running` and waits, and one
whose rerun passes moves on as any green PR does. Triage takes `ci_red`'s place in step 4's priority order. The
`fix-ci` cooldown and attempts count `fix-ci` runs only, so reruns spend neither.

### Agent definition

canopy ships `canopy-ci-triage` in the definitions directory (§13):

- no edits, no subagents, no web tools; reads only inside its cwd.
- bash denied but for `gh run view *` and `gh run rerun *`, checked command by command (D021).
- MCP: the tracker and GitHub, read tools only. Denied by name: every tool the worker definition denies, and comment,
  label, and PR update tools. GitHub's server folds reruns into `actions_run_trigger`, which also starts workflows and
  cancels runs, so it stays denied, and reruns go through `gh`; a tool named for reruns alone (`*rerun*`) is allowed.

A CI reached through another MCP server needs its rerun tool allowed: the operator copies the definition into their
runtime config, allows exactly that tool, and points `triage_cmd` at it, as for a chore's tools (§19).

Workers lose what this section gives the triage: `canopy-worker` denies `gh run rerun*`, `gh run cancel*`,
`gh run delete*`, and `gh workflow*` (today its bash allows them; only the MCP names are denied), so a triage is the
only run that reruns CI. `gh run view` stays: reading a failure is `fix-ci`'s job. `canopy-worker-private` already
denies all of `gh`.

### Journal

- A triage is a run of kind `triage-ci` that holds no slot, on the ticket's branch, with its validated result. Its
  report (§8 step 7) is the summary with each rerun URL on a line.
- `canopy status`, the web UI, and notifications show it as any run.

### Trust model changes

Proposed, for the operator's approval note in M25's PR:

- T1: the triage agent reads CI logs, among the easiest text to shape, and its verdict starts a write. A steered
  verdict can rerun failed jobs, at most `max_triage_ci_attempts` times per unit, or say `real`, which is today's
  `fix-ci`. It cannot edit, commit, push, or comment.
- T3: `max_triage_ci_attempts`, never reset, the triage timeout, `max_workers`, and one run per ticket are controls in
  code. "Workers do not poll CI or retry" stands: a triage reruns once per dispatch and never waits for the result.
- T6: residual: `gh run rerun` takes any run id in any repository the operator's `gh` reaches, so a steered triage can
  rerun another workflow's failed run, a deploy's included, which deploys the commit it ran on again. The harness
  cannot check a run id (D003). `canopy-worker`'s bash allows the same today; M25 takes it away.
- T7: `runtime.triage_*` is private, and a repository cannot raise `max_triage_ci_attempts` from 0. The skill is
  read from the primary clone, never the PR's branch. Residual: a repository's skill steers verdicts, as repository
  skills steer every run (§13).
- §6: never rerun CI except in a triage run, and never more than `policy.max_triage_ci_attempts` triage runs per unit.
- §7: protect workflows whose rerun does more than test, such as deploys and releases, with environment protection
  rules that require a reviewer: a rerun runs as you.

### Open

- Whether the triage's verdict should reach the `fix-ci` prompt, rather than the worker reading the failure again.
  The overseer's context only points at the triage run (§8).
- Whether a triage should comment on the PR saying what it reran and why, for its reviewers. That needs a comment tool
  the definition denies.
- Whether reruns should reach a human as debt: a finding of the build-health chore (§19), or an attention item when a
  unit's reruns reach its limit.
- One rerun per commit is a prompt rule. The harness does not know the head commit; the `commit` a triage reports is
  the agent's word.
- Whether the overseer should skip triage for a failure the change obviously caused, saving a run. It reads check
  names and states, not logs (T1).
