# canopy roadmap

Milestones are sequential. Each has acceptance criteria that must be met before the next begins. Acceptance criteria
that involve running against real systems are the operator's job; the agent building the repo stops and asks.

Each milestone ends with a `Status:` line, the only place its progress is tracked. Keep it current in the same PR that
changes it: `Status: not started.` or `Status: in progress.` while work is open, and once the acceptance criteria are
met:

```text
Status: done YYYY-MM-DD.
Learned: what surprised us or turned out different from the plan.
Next: how that changes later milestones, docs, or open questions.
```

A milestone a later one absorbs ends `Status: superseded by MN (YYYY-MM-DD).`, `MN` a milestone or a range, followed
by one sentence saying how.

A done milestone is collapsed: one line on what it delivered replaces its bullets and Accept, and `Learned` and `Next`
keep only what a later milestone needs, a sentence or two each. Leave `Next` out when nothing changes. The detail lives
where it lasts: a behavior and its rationale in the design (`design/`), a choice every future developer must know in
`DECISIONS.md`, live numbers in `MEASUREMENTS.md`, and the story in the PR. Edit a later milestone's bullets directly
when `Next` calls for it.

The operator may close a milestone on real use before every live check in its Accept has run. Its `Learned` says so,
and each check still unrun goes to `SCENARIOS.md`, the live checks worth running again.

## M0. Skeleton

Repository layout, `make check` in CI, the treehouse and agent fakes, and `procs.py` as the one subprocess boundary.

Status: done 2026-09-23.
Learned: the treehouse fake follows treehouse's real JSON shapes and exit codes, read from its source. The subprocess
boundary is a lint rule (D015), and a timeout kills the child's whole process group.

## M1. Read-only tick

Config, journal, lock, and treehouse; `canopy init`, `tick --dry-run`, `decide`, `attention`, and `status`; the
OpenCode deny canary.

Status: done 2026-09-24.
Learned: dry runs found plans a live tick would not carry out, so a dry-run dispatch checks the guards (D036). The first
real failures were setup, not the loop: treehouse versions and the overseer's missing GitHub MCP server. Accept was
narrowed from days of dry runs to sensible plans on an empty queue and on a labeled candidate.

## M2. Dispatch implement

Guarded dispatch with a lease and a detached `_run`, the `implement` worker, attention for crashed and unpushed runs,
the worker's own agent definition, and definitions from a directory canopy owns (D040, D044).

Status: done 2026-10-07.
Learned: live, GH-64 went from label to PR #69 unattended, and a run killed with SIGKILL was `crashed` on the next tick
with its slot returned. An empty journal's comment cursors make old authorized comments read as new. The worker's MCP
tools cannot label a PR, so the `agent` label lands only when the model uses `gh`.
Next: give the worker a reliable way to label, or have the harness do it.

## M3. Fix-CI and resume

Phases for red CI, requested changes, and human replies; the `fix-ci` and `resume` workers; attempt limits, cooldowns,
per-ticket cursors, and notification of the attention list.

Status: done 2026-10-13.
Learned: closed on the operator's real use; a check taken to the limit and a conflicted PR are SCENARIOS S9 to S11.
Authorship is checked when a comment is read, so adding an account to `authorized_repliers` authorizes its earlier
comments too. A bot's review comments drive `resume`, though they never count as approval.

## M4. Dependencies and stacking

Blocker ordering from the tracker's relations, and `dispatch --base` to stack a PR on its blocker's branch.

Status: done 2026-10-07.
Learned: live, GH-67 waited on GH-66 and was stacked on its open, green PR (#73).
Next: nothing checks what happens to a stacked PR when its base merges.

## M5. Shareable

The CLI skill, an install verified from a clean machine, and a license.

Status: done 2026-10-13.
Learned: closed on the operator's real use; a second person installing from README unaided is SCENARIOS S5. The PyPI
name is another project's, so README installs from git (D046), CI repeats that install, and a version tag releases one
executable per platform (D067). The license is proprietary for now.

## M6. Workspace

Several repositories as one queue (DESIGN §18, D033): the workspace file and `MAP.md`, `init --workspace`,
`workspace sync`, pools under the workspace root, and `dispatch --repo`.

Status: done 2026-10-13.
Learned: closed on the operator's real use; canopy runs only from a workspace (#146). The two-repository run is
SCENARIOS S13. A workspace's `.canopy/` must be private to the operator (D053).

## M7. Joint multi-repo runs

A ticket with a unit per repository: all-or-nothing leases, desks, `prs` in the result contract, per-unit phases and
cursors, and the desk canary.

Status: done 2026-10-13.
Learned: closed on the operator's real use, without a live joint run (SCENARIOS S14). The desk canary fails when the
workspace root is a git checkout, since OpenCode takes the enclosing repository as its project (TRUST_MODEL T4).
Next: run the canary (S1) before a real joint run in a workspace that is a git checkout.

## M8. Split tickets

`dispatch --kind split`, only when an authorized replier asks for it, making linked children that wait for the
operator's label.

Status: done 2026-10-13.
Learned: closed on the operator's real use, with no live split (SCENARIOS S15, after S2).
Next: S2 belongs in the OpenCode canary once someone writes it.

## M9. Chores

Recurring runs the operator defines and the overseer schedules (DESIGN §19): `[chores.<name>]`, `chore_runs`,
`canopy chore run`, `wait`, and `try`, and findings on the attention list.

Status: done 2026-10-13.
Learned: closed on the operator's real use; several days of a build-health chore are SCENARIOS S22. A chore's `days`
and `hours` became a guard in code. Use added `canopy chore try` and `canopy reply chore:NAME`.

## M10. Notification sinks

Per-sink delivery with cursors and digests (DESIGN §20, D035), a desktop sink, a Slack sink as a uv workspace member,
`loop.failing`, and `canopy notify test`.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the live desktop and Slack checks are SCENARIOS S24 and S25. DESIGN §15's
three-failure item is `loop.failing` alone, since the attention list is the latest `ok` tick's.

## M11. Reviews

A fresh reviewer per PR commit (DESIGN §21): guarded review runs in a slot, findings kept in the journal and posted
nowhere (D114), `resume --review-run`, and `canopy review show`.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the reviewer canary passed and PR #69 was reviewed live (2026-10-07), and
the other live checks are SCENARIOS S19 to S21. Review runs ending `unknown` within seconds were a plugin printing after
the result; since #218 an agent's result is the last line of its output that starts with `{`. Use added
`canopy dismiss` and `canopy grant URL review`.
Next: the next spend measurement confirms review runs no longer end `unknown` (MEASUREMENTS 2026-10-13 F18).

## M12. The loop

`canopy loop` (D042, D043): one tick after another, a lock, stops on SIGINT and SIGTERM, and rich output.

Status: done 2026-10-13.
Learned: checked live on 2026-10-07, and the loop has been the operator's daily surface since. Pausing (`p`,
`canopy pause` and `resume`) and reloading config (SIGHUP) joined it on request. A session's legibility and a live
reload are SCENARIOS S26 and S31.
Next: the closing line does not say a signal stopped it; a small follow-up, not a milestone.

## M13. Spend-paced loop

D042's pacing rule, fed by what ticks cost. Needs M12. Sketch only; the design comes first.

- Record what each overseer run and each worker run cost, in tokens and dollars, in the journal next to its tick or
  run. Worker, split, chore, and review runs and each tick's overseer do.
- A spend budget in the user config, and a pacing rule that lengthens the wait when recent ticks cost more and returns
  to `loop.interval_minutes` when they cost less. Idle ticks are M21's: the loop waits the longer of the two rules,
  within M21's gate deadlines.
- Spend in the loop's per-tick block and in `canopy status`.
- Open: what the budget's unit is (per day, per tick, or both); whether a worker's cost counts against the tick that
  dispatched it. How the runtime reports cost is settled: OpenCode's JSON events on stdout.

Accept: written with the design, before work starts.

Status: in progress. Taken in part on request (2026-10-07, 2026-10-08, and 2026-10-13), with M15's session ids:
worker, split, chore, and review runs and each tick's overseer record their cost in dollars and tokens, so every agent
run canopy starts is in the spend, and the loop's per-tick block, `canopy tick`, `canopy status`, `canopy decisions`,
and the web UI's attention page (the last 24 hours and 30 days) show it, and its chores pages each chore's. A tick's
cost is its overseer's alone, so a worker's is not counted against the tick that dispatched it. An `overseer_cmd`,
`review_cmd`, or chore `cmd` in a user file from before needs `--format json` added. What keeps it open: the budget
and the pacing rule are not designed.

## M14. PR-scoped work

REQUIREMENTS R9 and D056. Needs M3's `fix-ci` and `resume`. Sketch only; the design comes first.

- A unit of work keyed by a PR rather than a ticket, for the operator's own hand-written PRs: `fix-ci` when its checks
  fail, `resume` when review comments arrive, with the same cursors, attempt limits, and cooldown as a ticket's.
- Authorization by a queue label on the PR, as on a ticket, so neither the operator nor a coworker learns a command.
  Only PRs the operator authored, in the repository or workspace the loop runs for.
- The worker pushes to the PR's head branch, never with force, never on a PR from a fork; the harness refuses the
  repository's base branch. The worker prompt re-reads the PR's author and labels first and changes nothing without
  both (D051's pattern).
- `canopy status` and the attention list name PR units by the PR, not a ticket key.
- PR references (`repo#N` or the PR's URL) in `canopy start`, `stop`, `reply`, and `show` (DESIGN §22, D075), so
  the operator can also start one of their own PRs privately instead of labeling it. That is a T1 change beside D056's,
  needing the operator's approval as M18's does.
- `canopy mirror` for a PR reference: the PR's review comments join the journal as its conversation (DESIGN §22, M19).
- TRUST_MODEL T1 and §6 already allow it (D056).

Accept: written with the design, before work starts, and like every milestone's, a real run of what it delivers.

Status: not started.

## M15. Sessions and recent runs

REQUIREMENTS R4 and R6, D055. Needs M2. Sketch only; the design comes first.

- Record each run's OpenCode session id in `runs`, read from what `opencode run` reports, without the harness parsing
  runtime-specific output beyond one validated field (D009, D026). Done with `--format json`, which also gives
  M13 each run's cost.
- `canopy status` lists recent runs as well as running ones: ticket, kind, outcome, PR, one-line summary, run log, and
  session id, so the operator can open a transcript with OpenCode's own tools.
- Decide, against the decisions corpus, whether `fix-ci` and `resume` should continue the session of the run that
  wrote the PR instead of starting fresh (PRIOR_ART warns about long-lived sessions fed events).
- Workers run against OpenCode's server (`opencode serve`, with `opencode run --attach`), so the operator can
  `opencode attach` to a running worker and prompt it. The listener follows TRUST_MODEL T8: a user-only bind address,
  loopback by default, refused if wildcard or public; the operator's listener secret from an operator-only file, passed
  only to the server. Verify OpenCode's server authentication on the pinned version first.
- Whether one server serves every run or each run gets its own, and what happens to a session whose run has ended: its
  slot is returned and may be leased again, so prompting it must not run tools in that directory. Either the session
  is read-only once its run ends, or prompting it starts a `resume` dispatch through the guards.
- Prompting is the operator's own input (T8): it is not checked against `trust.authorized_repliers`, and it lifts no
  guard. Capacity, attempt limits, the run's timeout, and push verification still apply.

Accept: written with the design, before work starts, and like every milestone's, a real run of what it delivers.

Status: in progress. Taken in part on request (2026-10-07): each worker and split run records its session id, and
`canopy status` lists the ten most recent runs with their outcome, PRs, summary, cost, run log, and session id; M27
shows a session's transcript in the web UI. A `worker_cmd` in a user file from before needs `--format json` added.
Checking a run's session against `opencode export` is SCENARIOS S30. What keeps it open: whether `fix-ci` and `resume`
continue a session, and workers against OpenCode's server. Taken in part on request (2026-10-13): the overseer names
each ticket (`canopy ticket set --title`), the name shows beside the key in `canopy status`, `canopy show`, and the web
UI, and every default template passes it, or a tick's, chore's, or review's own, as the session title
(`opencode run --title={title}`, DESIGN §13). Learned: `run --format json` prints no event with OpenCode's own title,
so canopy names sessions rather than reading them back. Next: workers renaming their ticket through their result line,
once real runs show whether the overseer's names hold up. On request (2026-10-13), a `json` notification carries the
title beside each ticket key and the Slack sink shows it (DESIGN §20); `attention.md` and the `text` format do not.

## M16. Worktree setup for large monorepos

`paths.worktree_include`, `runtime.setup_cmd`, and for Bazel a shared-cache recipe (`docs/BAZEL.md`) and a canary.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the Bazel run and the canary's first real run are SCENARIOS S7 and S1.
Pools get no root of their own: a fast disk takes the whole workspace (DESIGN §18, D033).
Next: run S1 before relying on a worker's reads through Bazel's links.

## M17. Declared repositories and pools

Declared pool sizes (`capacity.slots_per_repo`), a `workspace sync` that converges on them, and `workspace add` (D066).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the live run is SCENARIOS S6. treehouse's `max_trees` must be at least the
largest declared size, and canopy cannot set it.

## M18. Private tickets

Tickets the operator starts privately (DESIGN §22, D072, D075): `canopy start`, `stop`, `reply`, and `show`, the
`messages` table, a private worker that only reads the tracker, and `awaiting_reply`.

Status: done 2026-10-13.
Learned: closed on the operator's real use: the first live session's tickets were all started privately. The full run is
SCENARIOS S16, and OpenCode's wildcard deny, confirmed only in its source, is S3. Atlassian's MCP server needs
`?tools=all` in its URL for a private worker to read comments.
Next: a start does not end the loop's wait (MEASUREMENTS F3); M28 takes it.

## M19. Tracker comments in the journal

`canopy mirror`: the overseer copies each new tracker comment into the journal once, and `canopy show` shows it.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the working session is SCENARIOS S17, and the heredoc rule read in
OpenCode's source is S4. PR review comments join the journal with PR subjects, in M14.

## M20. Web UI

`canopy loop` serves a web UI (D074, D079) under TRUST_MODEL T8: the attention list, runs, tickets and their
conversations, reply, start, stop, forget, and grant, and a worktrees page.

Status: done 2026-10-13.
Learned: closed on the operator's real use: the first live session was driven from it on loopback. A private address
and the worktrees page against real pools are SCENARIOS S28. The browser signs in once with the listener secret. A
reply no tick has read yet says so, since the list lagging read as a bug.
Next: M15's session attach joins the UI once M15 runs workers against OpenCode's server.

## M21. Idle-paced loop

The wait doubles per idle tick up to `loop.idle_max_minutes`, ends by a cooldown or a chore's due time, and ends early
when a run ends (DESIGN §6, Idle pacing).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the overnight run is SCENARIOS S27. Ticks that fail after doing their work,
and overseer churn, keep a quiet night from backing off (MEASUREMENTS 2026-10-12), which M28 takes. A shorter `--every`
keeps idle pacing from that base.
Next: M39 waits on S27's overnight run and its re-measurement.

## M22. Trusted reviewers

`trust.trusted_reviewers` and `untrusted_review`, and the operator's replies as instructions to every public worker
(D089, D093).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the live run is SCENARIOS S18.

## M23. Chores in the web UI

Chores pages, and answering a chore's finding from the browser.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the live run is SCENARIOS S23, after S22. The chores' journal view moved to
`core` so the server reads it as the CLI does.

## M24. Ticks in the web UI

Ticks pages with the overseer's decisions, and each ticket's decisions across ticks.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the day-long check is SCENARIOS S29.

## M25. Flaky CI triage

REQUIREMENTS R14, DESIGN §23. Needs M3. Asked for by the operator (2026-10-09): a check that fails for a
reason the change did not cause sends a `fix-ci` worker to change code that is not broken, and spends its attempts.

- TRUST_MODEL T1, T3, T6, T7, §6, and §7 as DESIGN §23 lists them, with the operator's approval note in the PR.
- Config: `policy.max_triage_ci_attempts` (default 0), `runtime.triage_cmd`, `runtime.triage_timeout_minutes`,
  `runtime.triage_skill`.
- `canopy dispatch --kind triage-ci`: `triage_off`, one unit, no slot. `_run` runs it in the unit's primary clone after
  the shadowing check, validates the triage result, and records its report.
- `agents/canopy-ci-triage.md`. `canopy-worker` denies `gh run rerun`, `gh run cancel`, `gh run delete`, and
  `gh workflow`; `test_definitions.py` checks both.
- `prompts/ci-triage.md` and its private variant; the overseer prompt's triage rows and the state block's fields.
- §7, §8, §12, and §13 say what §23 changes in them, and §23 loses its "designed, not built" line.
- Tests with the fakes: `triage_off` under the default config; a dry-run tick that triages a new failure; a triage
  run's cwd is the primary clone and it leases nothing; a `flaky` result without reruns recorded `failed`; a `real`
  verdict followed by `fix-ci`; the limit refusing the next triage; `fix-ci` attempts not counting triages.

Accept: the tests above pass. Live: on a PR whose check fails for a reason the change did not cause, the loop reruns it
once and the PR goes green with no `fix-ci` run; on a PR with a real failure, the triage reports `real` and the next
tick's `fix-ci` fixes it; a repository skill that names a flaky test is followed.

Status: not started.

## M26. Sandboxed workers, opt-in

HOST_ISOLATION, TRUST_MODEL T4 and T6, D107, D109. Needs M2. Asked for by the operator (2026-10-12), ahead
of the deferred list's trigger: the sandbox should be proven on the operator's machines before a second team adopts
canopy, not built after an incident.

- The per-run object directory (HOST_ISOLATION §4.2). `_run` makes `<state_dir>/runs/<id>.objects/` before step 2 and
  passes it to `setup_cmd` and the worker as `CANOPY_GIT_OBJECTS`, never as git's own variables. When the worker left
  anything in it, step 5 runs with `GIT_OBJECT_DIRECTORY` and `GIT_ALTERNATE_OBJECT_DIRECTORIES` set, and then, on
  every exit path, each slot is checked out detached at step 2's commit, its HEAD reflog expired, and the directory
  deleted, before the slot is returned. An unsandboxed run leaves it empty, and nothing changes for it.
- `run_slots` records each slot's `.git` link (a new migration), so reconcile's `end_run` does the same cleanup for a
  run whose `_run` is gone, after the same link check `_run` makes; this closes the gap a `_run` killed with SIGKILL
  leaves (HOST_ISOLATION §5 item 2).
- `examples/sandbox/`: `canopy-sandbox`, the wrapper HOST_ISOLATION §4.1 describes (resolve the cwd's worktrees and
  their git directories, write a per-run `srt` policy, drop `BASH_ENV`, map `CANOPY_GIT_OBJECTS` to git's variables,
  `exec srt --settings <policy> -- "$@"`), taking a role (`worker`, `setup`, `chore`) that picks the policy; and the
  policy template, §4.2's filesystem table and §4.3's network allowlist with the operator's hosts left to fill in. No
  Unix sockets, so sandboxed runs push over HTTPS. Examples, not harness code: the harness sees only the
  command template, as today.
- `docs/SANDBOX.md`, an operator's guide like `docs/BAZEL.md`: the pinned `srt` install, the prefixes for `worker_cmd`,
  `private_worker_cmd`, `split_cmd`, `setup_cmd`, and chore `cmd`, the allowlist, HTTPS remotes, and Ubuntu 24.04's
  restriction on unprivileged user namespaces. `canopy init` prints the suggested `worker_cmd` and writes nothing.
- The canary (HOST_ISOLATION §6), `tests/canopy/test_sandbox_canary.py`, opt-in with `CANOPY_SANDBOX_CANARY=1`: a
  plain script run through the real `worker_cmd` prefix and the example wrapper, every denial and every positive
  control §6 lists, the prompt property test included. A Linux CI job runs it with bubblewrap and `srt`.
- Settled before Accept, each in HOST_ISOLATION §7 or a decision: what treehouse's `return` runs in a slot; caches that
  tools keep as git repositories under the per-run object directory; OpenCode's local MCP servers inside the sandbox.
- TRUST_MODEL T4 and T6: the sandbox as a control, what it does not cover (the shared kernel, exfiltration through an
  allowed host), and that it is opt-in, with the operator's approval note in the PR. DESIGN §8 and §15 for the object
  directory and reconcile's cleanup; HOST_ISOLATION's settled parts move to DESIGN.
- Tests with the fakes: an empty object directory sets no git variable for step 5 and is deleted; a worker that commits
  through it is pushed and leaves the slot on step 2's commit with `git gc` clean in the primary clone; a `_run`
  killed after the worker leaves cleanup to reconcile, which puts back a slot's changed link before any git there.

Accept: the tests above pass, and the canary passes in CI on Linux. Live: the canary passes on the operator's Linux and
macOS machines, then a day of `canopy loop` with sandboxed workers pushes and opens PRs as before, and a worker run that
tries to read `~/.ssh` or write `~/.config/canopy` is refused.

Status: in progress. The per-run object directory and the `run_slots` link are in: `_run` and reconcile tidy each slot
before it is returned, and `tests/canopy/test_run_objects.py` holds the fakes-based tests above. Checking them found
that the tidy step must also drop the slot's own refs, and that `_run`'s own push must put origin's remote-tracking ref
back (HOST_ISOLATION §4.2). The wrapper and a policy template for each role are in `examples/sandbox/`, tested
against a fake `srt` in `tests/canopy/test_sandbox_wrapper.py`, `_run` with the wrapper as `worker_cmd`'s prefix
included. Trying them under `srt` 0.0.79 and bubblewrap found that `srt` binds an `allowRead` path over an
`allowWrite` path beneath it, so the wrapper names the common git directory entry by entry, and that a write under a
denied directory lands in a `tmpfs` and is dropped, so the canary must check writes on the host (HOST_ISOLATION §4.2,
§6). Next: `docs/SANDBOX.md`, the canary, the questions Accept needs settled, and TRUST_MODEL T4 and T6.

## M27. Session transcripts in the web UI

A run's and a tick's OpenCode session, its text, tool calls, and model calls, read back from its log
(`core/transcript.py`).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the check against `opencode export` is SCENARIOS S30. A running run's events
reach its log only when it ends, because `procs.run` captures stdout whole.
Next: watching a run live needs the worker's stdout streamed to its log.

## M28. Overseer reliability from the first live session

MEASUREMENTS 2026-10-12, F1 to F3 and F5; 2026-10-13, F15, F17, and F20. Needs M12 and M21's code. Asked for by
the operator (2026-10-12): a quarter of the first session's overseer spend bought nothing, mostly for reasons a check
in code can catch, and the same reasons keep idle pacing from counting a quiet tick as idle.

- The overseer's `canopy` works before the overseer is paid for. The tick either puts this canopy's own launcher
  first on the overseer's PATH, or checks, through `procs`, that `canopy --version` runs from the overseer's
  environment. When it cannot, the tick closes without running the overseer, with a status of its own, and raises an
  attention item saying why. Settle which in DESIGN §6; every way of installing canopy has to work.
- The done line: the overseer ends its final message with a line `CANOPY_TICK_DONE`, and may summarize before or after
  it; the harness accepts it as a line anywhere in that message, never in an earlier one. DESIGN §6, with the
  operator's approval note in the PR for the prompt.
- A ticket started or stopped from the web UI or the CLI (`starts`) and attempts granted (`canopy grant`) each end the
  loop's wait as an operator message does, with the same one-minute floor, count against idleness the same way, and
  are recorded as what woke the tick (`ticks.woken_by`). DESIGN §6 (The loop, Idle pacing) and §22 (Waking the loop).
  A config reload does not: the operator declined it (2026-10-13).
- Churn, measured before it is fixed: the loop's `loop waits` log line says when a tick changed a phase or the
  attention list with no run, message, start, or gate since the tick before. Prompt changes follow only when the
  `decisions` table shows a pattern. The first day shows one (2026-10-13 F17): the overseer leaves out an attention
  item and restores it a tick later, and a tick without the tracker's MCP wipes the list. Settled by the operator
  (2026-10-13): a prompt fix, with the overseer's open items in its state block (DESIGN §6 step 4).
- Tests with the fakes: a missing or failing `canopy` closes the tick without starting the fake overseer; a start ends
  the wait; a fake overseer that prints a summary after `CANOPY_TICK_DONE` closes the tick `ok`.

Accept: the tests above pass. Live: a working session re-measured (MEASUREMENTS) has no tick that ran the overseer
without a working `canopy`, no `overseer_failed` tick that recorded its decisions, and every web-UI start picked up
within about a minute.

Status: in progress.

## M29. Probe-gated overseer

MEASUREMENTS 2026-10-12, F7 to F10; D003's revisit. Needs M28 and M21's overnight run (SCENARIOS S27). Sketch only;
the design comes first. Taken only if a re-measurement after both shows that the steady state's spend or its latency
(up to `loop.idle_max_minutes` on a teammate's comment or a CI result) is still worth the trust change. The first
session says a gate saves little while the operator is active (F8), and the first day agrees: 6 to 9% (2026-10-13
F13). The day's case for a probe is as M30's source of facts, not as a gate; take M34 first, which changes both
milestones' arithmetic. M36 to M39 absorb this milestone: the probe's facts go into the journal as observations, and
the overseer runs only when they leave it something to judge, the gate this one wanted. M39 marks it superseded once
built; until then it stays open, so the series can stop after M36's shadow measurement.

- A `probe_cmd` command template, run through `procs`, prints one JSON line of fingerprints. Per ticket: updated
  time, latest comment id, labels, open or closed, and the keys the tracker query returns. Per PR: head SHA, the
  result and latest build or check-run id of each named CI context (a re-run at the same head, 2026-10-13 F16), latest
  review or review-comment id, mergeable, draft, and open, merged, or closed.
  canopy validates the line, keeps the last one per subject in the journal, and runs the overseer only when a
  fingerprint changed, a harness wake event happened, a gate came due, or `loop.idle_max_minutes` passed since the
  last overseer run. In between, the loop polls the probe, not the overseer.
- The probe fails open: an error, a timeout, or output that does not validate runs the overseer as today. With no
  `probe_cmd`, nothing changes.
- The probe's output never reaches the overseer's prompt, so a wrong or steered probe can cost a missed or an extra
  overseer run and nothing else. canopy still imports no tracker or GitHub client and reads no token: the probe holds
  its own credentials (`gh`'s login, or an operator-only file as the Slack sink does).
- CI is fingerprinted by contexts the repository's config names, never by GitHub's combined status, which some
  repositories hold at `pending` forever (F9). PR issue comments are not fingerprinted.
- An example GitHub probe: one GraphQL query through `gh` for every PR the journal records on an unfinished unit,
  merged and closed included, never a list of open PRs, which drops a merged one (2026-10-13 F16). A Jira one if the
  operator's setup allows it without a new token. A reload that changes the tracker query changes what it lists.
- TRUST_MODEL T2 with the operator's approval note, D003, and DESIGN §6 and §12.
- Open: how the probe learns which subjects to watch (argv, stdin, or reading nothing and listing by query); how often
  it polls (2 minutes matched the first session's median latency, F10); whether a cold-cache overseer run after a
  long gap changes the arithmetic (MEASUREMENTS: Spend).

Accept: written with the design, before work starts.

Status: not started.

## M30. Fewer re-reads per tick

MEASUREMENTS 2026-10-12, F6; 2026-10-13, F14. Needs M29's probe and M34. Sketch only; the design comes first.
Re-reading the tracker and GitHub was 29% of every tick's cost in the first session, productive ticks included, and
most of it was things that had not changed: over the first day, one approved PR was read 170 times and a stopped
ticket was in the search on 92 ticks. The day's analysis models this milestone at up to 40% of overseer spend, an
upper bound until measured. M36 to M39 absorb this milestone: M37 takes the cut from the journal's observations
instead of a probe's output, and M38 moves the derivation that needs no judgment into code. M39 marks it superseded
once built; until then it stays open, as M29 does.

- The probe's facts in the state block: per unit, head SHA, named CI results, latest review id, mergeable, and draft;
  per ticket, labels, state, and latest comment id with its author's account id. Ids, states, and account ids only; no
  comment, review, or PR text enters the state block.
- The overseer prompt reads a PR or a ticket in full only when a fact changed since its cursor, with the operator's
  approval note in the PR.
- A ticket the operator stopped is not read: the state block says it is stopped, and the overseer records its wait
  from that.
- TRUST_MODEL T1 and T2: what canopy now asserts about the world, and that the tracker and GitHub stay the source of
  authority (DESIGN §22), with the operator's approval note.
- Open: whether canopy should then check `trust.authorized_repliers` against comment authors in code, which would close
  D003's "cannot verify who wrote a comment".

Accept: written with the design, before work starts. Live, once built: a re-measurement shows tool-result tokens per
tick at half the first session's (about 19k) or less, with no action missed.

Status: not started.

## M31. Search in the web UI

One box over tickets, messages, chore runs, decisions, and ticks (`core/search.py`).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the timed check is SCENARIOS S32. A plain `LIKE` scan was measured fast
enough, so there is no FTS5 index.
Next: FTS5 when a real journal's empty search takes more than a quarter of a second (DESIGN §22, Search).

## M32. Shadow PR reviews in the web UI

REQUIREMENTS N1, DESIGN §21 and §22. Needs M11 and M20. Asked for by the operator (2026-10-13): canopy's reviews stay
off the PR (D114), so canopy shows them itself, as a PR review of its own that only the operator sees.

- A PR's page: each review run at its commit, the verdict, and each finding with its detail, anchored on the diff at
  its `path:line` where the line is in the diff.
- What the operator does from there, such as dismissing a finding or sending some findings to a worker, through the
  journal's existing channels (`canopy reply`, the overseer), never a write to the PR.
- Settled: the diff is kept from the review run. `_review` writes `git diff` of the commit against where it leaves its
  pool's base branch beside the run's log, since the harness cannot ask GitHub and the slot is gone afterwards
  (DESIGN §21, The diff). Open: how a finding is followed from one commit's review to the next.

Status: in progress. Migration 0016 records a review run's base branch, and `_review` keeps the diff, which
`core/review_diff.py` reads back and anchors each finding on (2026-10-13). `GET /reviews` and `GET /reviews/{id}` serve
them, over a mock of four review runs; TRUST_MODEL T8 gains the diff, waiting on the operator's approval note. The
Reviews pages show them, findings on the diff. The pull requests pages make the PR the subject: each PR the journal
knows, the loop's own included before any review, with its page of the runs that pushed to it, its reviews, and the
decisions naming it. The operator dismisses a finding from its card or with `canopy dismiss review:ID N` (2026-10-13),
which holds it back from a resume's worker and from the overseer, for that run only. Next: sending some findings to a
worker from the page; then the live check, a real review's page against its PR's diff on GitHub.

## M33. Spend by what it bought

MEASUREMENTS 2026-10-12 (Ticks by what they did). Needs M13's recorded cost and M21. Asked for by the operator
(2026-10-13): better cost analysis in canopy and the web UI, starting with how much goes to ticks that do nothing.
Every agent run records its cost, but whether a tick was idle was only in the log, so that split took a one-off
analysis session.

- Each tick `canopy loop` runs records whether it was idle by `pacing.idle` and what ended the wait before it
  (`ticks.idle`, `ticks.woken_by`), with idle pacing off too. DESIGN §6 (Idle pacing) and §11.
- `canopy spend [--days N]` reads the journal: per day, what the overseer, workers and splits, chores, and reviews
  cost, live and dry runs apart; ticks by idle, not idle, and not `ok`, with the count and spend of each and idle
  ticks' share of overseer spend; ticks by what woke them; and how many runs reported no cost.
- The web UI: the same breakdown from a route over a window, and a spend page with daily spend by kind, idle overseer
  spend as its own series, and links to the ticks behind it.
- Not here: churn, which M28 measures first, and a budget or pacing by cost, which stay M13's.
- Tests with the fakes: the loop records `idle` and `woken_by` for each cause and a hand-run tick records neither;
  `canopy spend` over a journal written by hand; the route over the mock journal; Playwright for the page.
- Open: whether the spend page replaces the attention page's two counters or links from them; whether `canopy spend`
  takes `--json` so a re-measurement (MEASUREMENTS) can start from it.

Accept: the tests above pass. Live: after a day of `canopy loop` against the real queue, the operator reads idle
ticks' share of overseer spend from `canopy spend` and from the web UI, and both agree with a query on the journal.

Status: in progress. Each tick the loop runs records `idle` and `woken_by` (2026-10-13). What keeps it open:
`canopy spend` and the web UI's spend page.

## M34. A cacheable overseer prompt

MEASUREMENTS 2026-10-13, F11 and F12. Needs M13's recorded cost. Taken before M29 and M30, whose arithmetic it
changes. The first step was 41% of the first day's overseer spend, because the fixed prompt travels in the same
message as the state block, which changes every tick, and so is written to the cache fresh on every tick.

- Measured first: two dry ticks a minute apart, before and after, comparing the first step's cache write and cache
  read. The change is kept only if the fixed prompt moves from one to the other. Each tick is its own session; the
  provider's cache is by content and lasts minutes, so only a tick that starts soon after another gains, which the
  first day's ticks mostly did (2026-10-13: 103 of 158 gaps under 2 minutes).
- The fixed prompt reaches the runtime where it caches across ticks, such as the overseer's agent definition body
  in canopy's definitions snapshot (D040), and the message carries only the state block. A prompt override (§12)
  still works and still wins. The provider skill goes the same way, instead of a tool call on most ticks.
- The order of what changes inside the state block: what changes rarely (config, the workspace, repositories) before
  what changes every tick (time, tick id, running runs), if the runtime caches part of a message.
- DESIGN §6 step 4 and §13, with the operator's approval note in the PR for the agent definition and the prompt.
- Tests with the fakes: the overseer's message is the state block alone, the snapshot carries the prompt, and an
  override reaches the snapshot.

Accept: the tests above pass. Live: a re-measurement (MEASUREMENTS) shows the first step's fresh cache write at the
state block's size, not the prompt's plus the state block's, on ticks that start within the cache's lifetime of the
one before, and a median such tick at least 15% cheaper at the same price, with no change in what the ticks decided.

Status: in progress. Built and tested with the fakes (DESIGN §6 step 4, §13); the before and after measurement, and
the re-measurement Accept asks for, are the operator's (SCENARIOS S33).

## M35. Temporary notices to workers

REQUIREMENTS R15. Needs M12 and M20. Asked for by the operator (2026-10-14): a way to tell workers about a passing
condition, such as "Artifactory is having issues and CI builds will likely fail". `paths.worker_instructions` (§12)
carries it today, but it never lapses, the overseer never sees it, and nothing shows it is in force, so it outlives the
outage or is forgotten.

- A notice is a journal fact, like the pause (§6, The loop): its text, when and through which channel it was set, and
  when it lapses. One at a time; setting another replaces it. A lapsed notice reads as none, so nothing has to delete
  it. It has its own bound, apart from the standing instructions' 4 KiB, checked when it is set, so no dispatch fails
  on a notice's size.
- `canopy notice 'TEXT' [--for DURATION]` sets it, `canopy notice --clear` lifts it, and `canopy notice` alone prints
  the one in force. Without `--for` it lapses after a default. Like `pause`, `reply`, and `grant`, it refuses as
  `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set: a notice reaches every later run's prompt, so an agent
  steered by one ticket's text could otherwise write instructions into every other ticket's runs.
- Who hears it: every run that builds, tests, or reads CI. That is `implement`, `fix-ci`, and `resume` workers,
  reviews (§21), chores (§19), and M25's `triage-ci` once built. A split hears none: it reads and writes the ticket
  and builds nothing. A run already running keeps the prompt it started with.
- How: a `{{NOTICE}}` section of its own in each of those shipped prompts, `None.` without one, and a key in a chore's
  generated `## Run` object, which the operator's file cannot drop. While a notice is in force, a prompt without
  `{{NOTICE}}` is `bad_prompt`, as an override without `{{STANDING_INSTRUCTIONS}}` is once that file is set, so an
  override written before notices existed cannot drop one silently. `canopy notice` names each such override when it
  sets one, and the kinds that will refuse until the override gains the placeholder or the notice lapses.
- The overseer: the state block carries the notice in force, and the overseer prompt says how to weigh it. A failed
  check whose run started while the notice was in force, and that the notice explains, is held: neither fixed nor
  triaged. It stays held after the notice lapses until a newer run of that check exists, so a lapse alone never sends
  `fix-ci` at the outage's failure and spends an attempt that never resets (D030). Once the notice has lapsed, M25's
  `triage-ci` reruns it where triage is on; elsewhere the PR goes on the attention list, under a reason this milestone
  adds, for the operator to rerun. No guard in code: whether a failure is the one the notice names is judgment.
- Idle pacing (§6): setting or clearing a notice is an operator act, like a message. It wakes the loop, keeps the next
  tick from counting as idle, and is recorded as `woken_by` `notice`. A notice's lapse is a gate the wait ends at, like
  a `fix-ci` cooldown's end, so held work resumes when the notice lapses, not up to `loop.idle_max_minutes` later.
- `canopy status` and the web UI show the notice while it is in force, and the web UI sets and clears it.
- TRUST_MODEL: T1 adds `notice` to the commands that refuse inside a run, and T8 adds setting and clearing a notice to
  the web channel's list of writes. With the operator's approval note in the PR, for those and the overseer prompt.
- DESIGN §6, §8, §11, §12, §19, §21, and §22 say what changes in them, and §23 too if M25 is built first.
- Tests with the fakes: a notice reaches an `implement`, `fix-ci`, `resume`, and review prompt and a chore's `## Run`
  object, and not a split's; a lapsed or cleared notice reaches no prompt; an override without `{{NOTICE}}` renders
  with no notice in force and is `bad_prompt` with one, and `canopy notice` names it; text over the bound is refused
  when set; `canopy notice` refuses inside a run; a dry-run tick's state block carries it; setting one wakes the loop,
  and a lapse ends the wait; the web route sets and clears it; Playwright for its banner.
- Open: the bound and the default lifetime; whether a notice can name repositories, so an outage in one repository's
  CI does not reach runs in another.

Accept: the tests above pass. Live: during a CI outage, real or staged, the operator sets a notice from the CLI or the
web UI; the next worker's summary takes it into account; the overseer holds `fix-ci` on a check the outage failed, and
after the notice lapses that check is rerun, by `triage-ci` or by the operator from the attention list, before any
`fix-ci`; and the next worker's prompt after the lapse does not carry the notice.

Status: not started.

## M36. Connectors: the world observed into the journal, in shadow

MEASUREMENTS 2026-10-12 F6, F9, F10; 2026-10-13 F13, F14, F16, F17; D003's revisit and D008's. Needs M28 and M34.
Asked for by the operator (2026-10-14): each tick of the overseer should run from journal state, read into it by
deterministic programs, instead of an agent re-reading the tracker and GitHub every tick. M36 to M39 take that one
step at a time, and supersede M29 and M30: the probe's facts go into the journal rather than gating on them, and the
overseer runs only when they leave it something to judge. Sketch only; the design comes first, as a new design file
(§24).

The shape the four share:

- A **connector** is a deterministic program, configured like a sink (§20) and run by the harness through `procs`,
  that reads one source and prints what it saw as JSON lines. canopy validates each line (pydantic, D026), bounds its
  text, and writes it to the journal as an **observation**: a dated copy of a fact about the world. Authority stays
  with the source (principle 1, §22): an observation says what the connector saw and when, never what is true now.
- The harness still imports no tracker or VCS client and holds no token (D003). A connector is a separate program
  with credentials of its own, as the Slack sink is (`packages/`, stdlib only, nothing from canopy). canopy ships
  `canopy-connect-github` (GitHub Issues and PRs, with the token `gh` holds) and `canopy-connect-jira` (Jira Cloud's
  REST API, an email and API token from an operator-only file); another tracker is the operator's program speaking
  the same contract, the only thing the harness knows of any of them. In the same PR, AGENTS.md's "no tracker code"
  line (Toolchain) is scoped to the harness package, its "a tracker adapter interface" line (Do not build) is
  amended to allow this contract, and D003 is reshaped.
- The overseer's message becomes the journal: observations, the phase the harness derives from them in code, and
  what is new since each cursor. Judgment stays the overseer's: which repository, a slug and title, a worker's
  context, whether a review comment is a change or a question, what an operator's reply asks for, a chore's `when`.
  Reading does not, and neither does anything §7's table derives from facts alone (D008's revisit: one rule at a
  time, each checked against the `decisions` corpus before it moves).

This milestone adds the connectors and the derivation without changing what the overseer sees or does:

- The contract. On stdin, one JSON object naming what to observe: the tracker query, every ticket not marked done,
  every PR URL on an unfinished unit (merged and closed included, 2026-10-13 F16), the repositories, and
  `review.query` when set. On stdout, one JSON line per observation: `ticket` (key, title, body cut, open or
  closed, labels, updated at, blocker keys, label events when the tracker has them), `comment` (ticket, id, author
  account id, time, body cut), `pr` (url, repository, number, head sha, base ref, open, merged, or closed, draft,
  mergeable, mergeable state, author login), `check` (pr, head sha, context name, status, conclusion, run id, url),
  `review` (pr, id, review or review comment, author login, whether a bot, state, time, body cut, url), and last an
  `end` line naming what it covered, so a connector cut off mid-way does not read as everything else having
  vanished. Unknown kinds are skipped. Ids, states, times, and bounded text; never logs or diffs. The tracker query
  is paged by the connector (REQUIREMENTS R1's gap), and CI is observed by named context, never the combined status
  (2026-10-12 F9).
- The journal: one table per kind (`observed_tickets`, `observed_prs`, `observed_checks`, `observed_reviews`), each
  row keyed by the source's id and replaced on each observation with its `observed_at`; a subject the `end` line did
  not cover keeps its old rows and their age. Comments go into `messages` as mirrored comments do now, with the
  workers' marks read in code (D069). `connector_runs` records each run: when, status, counts, the tail of stderr.
- Config, user-only (TRUST_MODEL T7): `[connect.sources.<name>]` with `cmd` (argv, no shell, as a sink's), `kind`
  (`tracker` or `vcs`), and `timeout_minutes`, one per kind at most, nested as sinks are (§20). Beside the table, the
  scalars later milestones read, defined here so the model needs no special case: `connect.max_age_minutes` (M37)
  and `connect.every_minutes` (M39).
- Each tick runs the connectors after reconcile and before the state block (§6 step 3). A failure, a timeout, or
  output that does not validate keeps the previous observations, is logged, and raises `connector_failed`, a
  harness item like `repo_missing`; the tick goes on, and in this milestone loses nothing, since the overseer still
  reads live.
- `loop/phases.py` derives every candidate, phase, and attention reason of §7 and §14 from the observations and the
  journal's cursors, in code, and records them per tick in a `derivations` table beside `decisions`, which it does
  not touch. The loop's per-tick block and its `loop waits` line count the disagreements with what the overseer
  recorded.
- `canopy status` names each connector's last run and the age of its observations.
- Tests with the fakes: `tests/fakes/connector` prints configured lines; a line out of bounds is refused and the
  rest kept; a cut-off output keeps the previous observations; the derivation over journals written by hand, one
  case per row of the phase table.

Accept: written with the design, before work starts. Live, once built: a day of `canopy loop` with both connectors
against the real queue, and a MEASUREMENTS section giving the agreement between the derivation and the overseer per
phase row, each disagreement read and attributed (the rationale says which side was right), and what the connectors
cost (calls and seconds per tick, no tokens).

Status: not started.

## M37. The overseer reads the journal

Needs M36's measurement, with the disagreements that were the derivation's fixed. Sketch only; the design comes first.
This is M30's cut, taken from the journal rather than a probe, and it is where the trust model gains its first code
checks on what the overseer claims.

- The state block carries the observations: per ticket, its title, state, labels, blockers, and the comments newer
  than its comment cursor (id, author, time, body, and whether the author is an authorized replier, decided in code);
  per unit, its PR (state, head, base, draft, mergeable), each named check at the head, and the reviews and review
  comments newer than its review cursor (author, trusted or not, decided in code, body); and the derived phase of
  each, as the harness's reading. Bounded text, labeled by source and author in code, after the fixed sections
  (M34's order).
- The prompt's procedure drops its reads: no tracker search, no ticket or PR reads, no mirror, no provider skill.
  An MCP call is allowed only for a subject the block marks `stale`, one no connector has covered within
  `connect.max_age_minutes`, with the operator's approval note; M39 removes that too.
- Claims become references to observations, checked in code: `canopy dispatch --label` is refused `unauthorized`
  unless the connector saw that label on the ticket (D051 gains a code check before the worker's own); a
  `human_replied` resume must name a comment by an authorized replier or an operator message; a `resume` for review
  feedback must name items by trusted reviewers, or an operator message about them (D089's revisit); `--cursor` must
  name an observed item. `canopy dispatch` is refused `stale` when a subject it depends on has an observation older
  than `connect.max_age_minutes`: a public ticket's, and the PR's of a unit a `fix-ci` or `resume` names. It covers
  only subjects a connector observes: a private ticket, authorized by its start record, a chore, and a subject no
  connector covers are not refused. Principle 1's "re-read before any action that matters" becomes "observed this
  tick, or no dispatch".
- Cursors become journal ids: observations order reviews, review comments, and canopy's review runs together, so the
  `review` cursor's time form (§7) is no longer needed. CI is keyed on head sha, context, and run id, so a re-run at
  the same head is observed, as resolving a held check needs (M35, 2026-10-13 F16); `fix-ci` alone starts only when
  a context's conclusion changed at that head, never on a re-run that went red to red (PRIOR_ART).
- `canopy mirror` and the heredoc (D081) are retired: the tracker connector writes comments. Open: whether a tracker
  with no connector keeps the live-read procedure, or a connector is required (recommended: required; the two shipped
  cover the operator's trackers, and the contract is a page of Python for another).
- TRUST_MODEL T1 (labels, repliers, and reviewers checked in code; the overseer's MCP narrowed to stale subjects),
  T2 (a connector's credentials), T7 (`connect.*`), with the approval note; DESIGN §6, §7, §17, §22; D003 and D081
  edited in place.

Accept: written with the design, before work starts. Live, once built: a re-measurement (MEASUREMENTS) with
tool-result tokens per tick at a tenth of the first day's median (about 14k), no MCP call on a tick whose
observations are fresh, and no action missed over a day, checked against the derivation as in M36.

Status: not started.

## M38. The harness decides what needs no judgment

Needs M37. Sketch only; the design comes first. D008's revisit, taken for the rows of §7 that measurement (M36)
showed the derivation getting right: a rule moves into code only with that evidence.

- Before the overseer runs, the harness records the decisions that need no judgment, as it records `awaiting_reply`
  today: `wait` for `running`, `ci_running`, `needs_human`, a cooldown, a failed latest run, and `blocked` with no
  stackable blocker; `done` for a closed ticket and for `merged`; `dispatch resume` for `pushed_no_pr` and
  `conflicted`, with their fixed contexts; `dispatch fix-ci` for `ci_red`, naming the failed checks (after `triage-ci`,
  with M25), only while no notice (M35) is in force: with one, the row stays the overseer's, since whether the notice
  explains the failure is judgment, which M35 keeps out of code; `review run` for `review_pending` and for
  `review.query`'s PRs. Each is a `decisions` row with `by = harness`, so the corpus, `canopy decisions`, and the
  tick's page show every decision and who made it.
- The priority order across both deciders is the overseer prompt's step 4 today (a human waiting, then conflicts and
  red CI, then a pushed branch with no PR, then `ready`) and nowhere in the design: it goes into §7, and the
  harness keeps it. The harness records its decisions before the overseer and makes its dispatches after it; the
  state block names them and the capacity they take, so the overseer dispatches its human-waiting tickets first and
  its `ready` tickets only into what remains, and a `ready` dispatch past that is refused `reserved`.
- The attention list from observations: `green_unreviewed`, `approved`, `untrusted_review`, `attempt_limit`,
  `split_unlabeled`, `split_self_labeled`, `review_failed`, and `review_limit` are the harness's, open while their
  cause holds in the journal, like the run reasons (§14). No re-recording rule, which M28's prompt fix (the
  overseer's open items in its state block) works around and this removes, so an item cannot flap (2026-10-13 F17)
  or go because the overseer left it out on partial data. Issue #219's harness half, a ticket-keyed
  `mcp_unavailable` skip closing the tick `ok`, is a `loop/tick.py` fix of its own, not this milestone's. The
  overseer keeps the two that are judgment, `needs_author` and
  `multi_repo`: it records each once, naming the item it is about, and the harness holds it until the cursor passes
  that item or the cause is gone.
- The overseer's state block lists only the tickets left to it, each with why: `ready` (choose the repository, slug,
  title, and context), `blocked` with a stackable blocker, `changes_requested` and `review_findings` (classify),
  `human_replied` (what the reply asks), a due chore with a `when`, and a ticket whose observations fit no row. A
  decision about any other ticket is refused `decided`. A dispatch for new items advances the cursors to the items
  the block showed, so the overseer passes `--cursor` only to leave feedback alone.
- The prompt shrinks to the judgment sections: candidates, the phase table, cursors, mirroring, and the attention
  list section go, with the operator's approval note.
- Tests with the fakes: the harness's decisions over journals written by hand, one per row; a decision on a ticket
  not left to the overseer refused; a fake overseer that handles only the listed tickets closes the tick `ok`.

Accept: written with the design, before work starts. Live, once built, over a day: the overseer's decisions are only
on the tickets listed to it; the attention list changes only when an observation or the operator did; `loop waits`
reports no churn; a median tick at half of M37's.

Status: not started.

## M39. A tick without the overseer

Needs M38 and M21's overnight run (SCENARIOS S27). Sketch only; the design comes first. This is M29's gate without the
trust change: the overseer runs when the journal leaves it something to judge, not when a fingerprint moved.

- When the harness's decisions leave nothing for the overseer, no ticket and no due chore, the tick records them,
  closes `ok`, and does not run the overseer: the common tick overnight, and after a run ends with nothing to
  classify. `ticks` says whether the overseer ran, and M33's spend page splits ticks by it.
- Connectors poll between ticks: the loop runs them every `connect.every_minutes` (default 2, 2026-10-12 F10) during
  its wait, writes their observations, and ticks early when the derivation over them yields a decision the latest
  tick did not record, a gate comes due, or the operator acts, as today. An external event is then seen within one
  poll, not up to `loop.idle_max_minutes` later (M21's trade, lifted). Idle pacing paces only the overseer's runs. A
  connector that fails during a poll raises `connector_failed` and the loop falls back to today's pacing.
- The overseer's definition loses the tracker and GitHub MCP servers: it has `bash` for `canopy` and nothing else,
  since a `stale` subject now gets `wait` instead of a live read. TRUST_MODEL T1: the overseer can be steered only by
  text the journal holds, bounded and labeled by source, and can call no tracker or VCS tool at all. Approval note.
- M29 and M30 are marked superseded, in the form the top of this file gives, once this is built; their open questions
  are answered here or in M36's design.

Accept: written with the design, before work starts. Live, once built: S27 re-measured (MEASUREMENTS) with most ticks
running no overseer, overseer spend per day at a quarter of the first day's for the same queue, median latency from
an external event to the tick that acted on it under three minutes, and no action missed.

Status: not started.

## M40. The overseer per decision

Needs M39. Sketch only, and taken only if M39's re-measurement shows the state block's size still dominating what the
overseer spends: M34's cache hit needs ticks minutes apart, which M39 makes rarer, so each remaining run may be cold.

- One overseer run per ticket left to judgment, whose message is that ticket's observations alone: a cold run writes
  a few thousand tokens, not fifty, and text on one ticket cannot steer a decision about another.
- The harness orders dispatches across tickets by phase priority (§7's order, written there by M38), which today
  the one overseer does, and bounds the runs per tick by capacity.
- Open: whether runs go in parallel; chores' `when`, which needs no ticket; whether one run may still see the queue.

Accept: written with the design, before work starts.

Status: not started.

## Deferred, with the trigger that would unblock each

- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it, or when a repository wants to trust review verdicts.
- Second runtime (Copilot CLI, Claude Code): when a coworker asks. More than a config change: canopy's definitions,
  their permissions, and the D044 guard are written for OpenCode, so a runtime needs its own (REQUIREMENTS N4).
- Slack replies: when the operator wants to answer from Slack. A channel into the journal's conversation (DESIGN
  §22): a Socket Mode bridge running `canopy reply`, or the overseer reading Slack through MCP. Needs a T1
  change.
