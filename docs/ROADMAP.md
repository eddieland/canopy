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
by one sentence saying how. A milestone set aside before it is done ends `Status: deferred YYYY-MM-DD.` and keeps its
bullets and Accept, and the deferred list at the end names the trigger that would bring it back.

A milestone the operator puts off ends `Status: deferred YYYY-MM-DD.`, followed by one sentence saying why, and gets a
line on the deferred list naming the trigger that would bring it back. Later milestones do not wait for it.

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

Status: deferred 2026-10-15. The operator judged it YAGNI once canopy was in real use; the sketch stays for when the
deferred list's trigger fires.

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

Status: deferred 2026-10-15. Until it is built, `ci_red` dispatches `fix-ci` as DESIGN §7 says.

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
- `canopy-sandbox`, the wrapper HOST_ISOLATION §4.1 describes (resolve the cwd's worktrees and their git directories,
  write a per-run `srt` policy, drop `BASH_ENV`, map `CANOPY_GIT_OBJECTS` to git's variables,
  `exec srt --settings <policy> -- "$@"`), taking a role (`worker`, `setup`, `chore`) that picks the policy; and the
  policy template, §4.2's filesystem table and §4.3's network allowlist with the operator's hosts left to fill in. No
  Unix sockets, so sandboxed runs push over HTTPS. Not harness code: the harness sees only the command template, as
  today. First an example under `examples/sandbox/`; on the operator's request (2026-10-14) it ships with canopy, as
  the workspace member `packages/canopy-sandbox` (D041), and `canopy sandbox setup` copies the templates, installs the
  `srt` its lockfile pins with npm, and checks and prints what needs root (D117).
- `docs/SANDBOX.md`, an operator's guide like `docs/BAZEL.md`: `canopy sandbox setup` and what it cannot install, the
  prefixes for `worker_cmd`, `private_worker_cmd`, `split_cmd`, `setup_cmd`, and chore `cmd`, the allowlist, HTTPS
  remotes, and Ubuntu 24.04's restriction on unprivileged user namespaces. `canopy init` prints the suggested
  `worker_cmd` and writes nothing.
- The canary (HOST_ISOLATION §6), `tests/canopy/test_sandbox_canary.py`, opt-in with `CANOPY_SANDBOX_CANARY=1`: a
  plain script run through the real `worker_cmd` prefix and the shipped wrapper, every denial and every positive
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
back (HOST_ISOLATION §4.2). The wrapper and a policy template for each role are in `packages/canopy-sandbox`, tested
against a fake `srt` in `tests/canopy/test_sandbox_wrapper.py`, `_run` with the wrapper as `worker_cmd`'s prefix
included. Trying them under `srt` 0.0.79 and bubblewrap found that `srt` binds an `allowRead` path over an
`allowWrite` path beneath it, so the wrapper names the common git directory entry by entry, and that a write under a
denied directory lands in a `tmpfs` and is dropped, so the canary must check writes on the host (HOST_ISOLATION §4.2,
§6). `docs/SANDBOX.md` is the operator's guide, and `canopy init` prints the suggested `worker_cmd`. Running the
guide's check under `srt` 0.0.79 and bubblewrap 0.9 found that a check run through the wrapper outside canopy must use
a worktree of its own, since nothing tidies a slot it commits in, and that a process started with `setsid` inside the
sandbox ends with it. `canopy sandbox setup` installs the wrapper's pinned `srt` in `~/.local/share/canopy/`; trying it
found that `srt`'s seccomp helper runs inside the sandbox, so under the `$HOME` a template denies it is not found
unless the wrapper re-allows reading `srt`'s `vendor/` directory, which it now does wherever `srt` is installed. The
canary is `tests/canopy/test_sandbox_canary.py` (`make sandbox-canary`), and CI's `sandbox-canary` job runs it on Linux
and macOS after `canopy sandbox setup`. Running it under `srt` 0.0.79 and bubblewrap 0.9 found that `srt` makes its
network sockets in the run's temp directory, so a long system temp directory fails every run; the wrapper now refuses
one on Linux with a message that says so. macOS's deep per-user temp directory, which `srt`'s source suggested was too
long, is not: the macOS job runs a case under it (HOST_ISOLATION §7). Run against a fake `srt` that sandboxes nothing,
the canary fails every case but its positive controls. It passes in CI on Ubuntu 24.04, with the AppArmor restriction
lifted as docs/SANDBOX.md says, and on macOS, both with `srt` 0.0.79. What treehouse's `return` runs in a slot is
settled from its source (HOST_ISOLATION §7): plain git, which reads only what a sandboxed worker cannot write. Tracing
it found that the slot's own `commondir` and `gitdir` were writable, and a worker that rewrote `commondir` had every
git on the host in its slot, canopy's included, read a config it wrote; the wrapper now denies writing both, the
canary checks it, and `_run` and reconcile check `commondir` as they do the `.git` link.
Next: the other two questions Accept needs settled, TRUST_MODEL T4 and T6, and the canary on the operator's Linux and
macOS machines.

## M27. Session transcripts in the web UI

A run's and a tick's OpenCode session, its text, tool calls, and model calls, read back from its log
(`core/transcript.py`).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the check against `opencode export` is SCENARIOS S30. A running run's events
reach its log only when it ends, because `procs.run` captures stdout whole.
Next: watching a run live needs the worker's stdout streamed to its log.

## M28. Overseer reliability from the first live session

A check that the overseer's `canopy` works before the overseer runs, the `CANOPY_TICK_DONE` line anywhere in the final
message, starts and grants ending the loop's wait, churn in the `loop waits` line, and the overseer's open attention
items in its state block.

Status: done 2026-10-14.
Learned: closed on the operator's request before the live re-measurement, which is SCENARIOS S34. A check beat putting
canopy's launcher first on PATH, which misses a launcher whose environment is gone (DESIGN §6 step 5). The first day's
churn was the overseer dropping items it could not see, fixed in the prompt (DESIGN §6 step 4).
Next: M39 waits on S27's overnight run.

## M29. Probe-gated overseer

A `probe_cmd` that fingerprinted tickets and PRs, so the overseer ran only when one changed, the loop was woken, a gate
came due, or `loop.idle_max_minutes` passed (MEASUREMENTS 2026-10-12 F7 to F10).

Status: superseded by M36 to M39 (2026-10-15). M36's connectors observe into the journal every fact the probe would
have fingerprinted, and M39 runs the overseer only when those observations leave it something to judge.

## M30. Fewer re-reads per tick

The probe's facts in the state block, so the overseer read a PR or a ticket in full only when one changed
(MEASUREMENTS 2026-10-12 F6; 2026-10-13 F14).

Status: superseded by M37 (2026-10-15). M37 puts the connectors' observations in the state block instead of a probe's
facts and drops the overseer's reads, so an unchanged PR or a stopped ticket is read only while its observations are
stale, and it checks authorized repliers against comment authors in code, the question this milestone left open.

## M31. Search in the web UI

One box over tickets, messages, chore runs, decisions, and ticks (`core/search.py`).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the timed check is SCENARIOS S32. A plain `LIKE` scan was measured fast
enough, so there is no FTS5 index.
Next: FTS5 when a real journal's empty search takes more than a quarter of a second (DESIGN §22, Search).

## M32. Shadow PR reviews in the web UI

A review's page shows canopy's own review of a PR, never posted on it (D114): its findings on the diff `_review` keeps,
each dismissed from its card (`canopy dismiss review:ID N`) or, on the loop's own PRs, ticked and sent to a worker
(`canopy send review:ID N...`), and the pull requests pages make the PR the subject (DESIGN §21, §22).

Status: done 2026-10-15.
Learned: closed on the operator's request before the live check against a real PR, which is SCENARIOS S36. Sending
findings needed no new channel: it is a reply on the review's ticket naming them by number, which the overseer already
reads as the go-ahead on review feedback (D089), so the reviewer's text never reaches a prompt as the operator's words.
Next: a finding still has no id that lasts across commits, so a dismissal or a send is one run's (DESIGN §21, Open).
A review of a PR the loop does not own offers no send; publishing it on the PR after iterating on it is M43.

## M33. Spend by what it bought

Each tick the loop runs records `ticks.idle` and `ticks.woken_by`; `canopy spend [--days N] [--json]` and the web UI's
spend page read them with every run's cost: per UTC day by kind, idle overseer spend as its own series, the ticks by
what they bought and by what woke them, and the runs that reported no cost (DESIGN §11, §22; `core/spend.py`).

Status: done 2026-10-14.
Learned: closed on the operator's request before the day-long live check, which is SCENARIOS S35. One module behind the
command and the route makes them agree by construction, so the check is against the journal. The open questions
settled small: the rail's two counters stay and open the page, and `--json` is in, for a re-measurement to start from.
Next: a re-measurement (MEASUREMENTS) can take idle share and `woken_by` from `canopy spend --json` rather than an
analysis session; M13's budget can read the same breakdown.

## M34. A cacheable overseer prompt

MEASUREMENTS 2026-10-13, F11 and F12. Needs M13's recorded cost. Taken before M36, which needs it. The first step was
41% of the first day's overseer spend, because the fixed prompt travels in the same message as the state block, which
changes every tick, and so is written to the cache fresh on every tick.

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
- M29's open questions are answered by M36's contract (which subjects to watch), `connect.every_minutes` (how often),
  and M40 (a cold overseer run after a long gap). If M36's measurement leaves the derivation untrusted, the series
  need not stop there for want of M29: a gate on the observations alone, running the overseer only when one changed
  since its last run, a gate came due, or the operator acted, can be taken from M36 without M37 or M38.

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

## M41. Limits and trust settings from the web UI

REQUIREMENTS R16, DESIGN §12 and §22. Needs M20. Asked for by the operator (2026-10-14): change a pool's slots or a
trust setting from the web UI without opening the user config file. Today the web channel asks for a reload and writes
no config (TRUST_MODEL T8).

- Which keys: an allowlist in code, by name, never a section's wildcard. Limits, raised or lowered: the counts in
  `capacity` (`slots_per_repo` and `repo_slots` among them), the attempt limits and the cooldown in `policy`, and
  `loop.interval_minutes` and `loop.idle_max_minutes`. Only toward stricter: `policy.stacking` to `"never"`, removing
  an entry from `trust.authorized_repliers` or `trust.trusted_reviewers`, `trust.rebase` to false, and
  `trust.commit_trailer` to true. Nothing else: `runtime.*`, `notify.*`, `chores`, `paths.*`, `review.*`, `serve.*`,
  `tracker.*`, the comment marks, and the trailer's name and email each run a command, choose a prompt or whose words
  are read, or move the listener. A key added to a section later is not editable until it is named.
- Why the stricter-only keys: a config write outlives the secret. A new secret ends every session, but a replier added
  through a stolen one would go on steering workers.
- Ceilings: no count can be raised from the page past a ceiling in code, such as `capacity.max_workers` at 8; the file
  can set any value. A raise within the ceilings outlives a new secret too; that residual is spend, and the page and
  the log show it.
- Where it writes: the user file only, never the workspace file (shared, perhaps committed, T7). Edited in place,
  keeping the operator's comments and layout, so a TOML writer joins the runtime dependencies with its DECISIONS
  entry; `tomllib` only reads. Rejected: a file of canopy's own layered after the user file (a hand edit to the user
  file would be silently overridden), and writing the file anew with the stdlib (its comments lost).
- How: the request carries a hash of the user file as the page read it. The server holds a lock from reading the file
  to replacing it, so two requests cannot both pass the check on the same hash; a file whose hash differs is refused
  as `stale`, checked again just before the replace, so a hand edit is lost only if it lands in that last moment. The
  change is applied to a copy and validated by `config.load`, as any `canopy` command would read it; a refusal writes
  nothing and gives the loader's message. The file is replaced atomically, keeping its mode, and refused when it is a
  symlink or not the operator's (D053's check). Then the loop is asked to reload through the existing path
  (`loop.reread`).
- The answer says what was saved apart from what the reload did: the keys changed, whether they wait for a running
  tick to end, and that a run already running keeps the prompt and permissions it started with, so a stricter trust
  setting reaches only runs started after it. A save whose reload was not asked for, the server stopping between the
  two, takes effect at the next reload; the settings page's Reload asks again. Under `canopy loop --every`, a changed
  `loop.interval_minutes` is saved, and the answer says `--every` still sets the pace until the loop restarts.
- No CLI verb: the operator's editor is the CLI's way. A `canopy config set` would be in reach of the overseer's
  `canopy *` bash rule; the write refuses as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set regardless.
- Each change is logged with channel `web`, the key, and its old and new values.
- Slots: a changed `capacity.slots_per_repo` or `capacity.repo_slots` bounds leases from the next tick. Making or
  removing slots is still `canopy workspace sync`, which the page names; the web UI runs no sync.
- API: `GET /config`, each editable key's value, the file it came from, its ceiling, and the user file's hash;
  `PATCH /config`, the changed keys and that hash. The settings page edits them, beside Reload.
- TRUST_MODEL T8: "It cannot write config" becomes the allowlist, ceilings, and stricter-only keys above, and its
  residual gains a stolen session raising limits up to their ceilings, which outlives a new secret until the operator
  sees it. With the operator's approval note in the PR. DESIGN §12 marks the keys the page edits and their ceilings,
  and §22 the routes and the settings page. DECISIONS: an entry for what the web channel may write to config (a rule
  the trust boundary relies on), and one for the TOML writer.
- Tests with the fakes: an allowed key written and reloaded, the file's comments kept; a key outside the allowlist, a
  stricter-only key loosened, a count over its ceiling, a stale hash, two requests on one hash, an invalid value, and
  a symlinked user file each refused with the file unchanged; the workspace file never written; Playwright for the
  form.
- Open: the ceilings' values; whether the page also shows the keys it cannot edit, read-only, with the file each came
  from.

Accept: the tests above pass. Live: while `canopy loop` runs, the operator changes `capacity.slots_per_repo` and
removes a trusted reviewer from the settings page; the next tick leases under the new size and reads the shorter list;
and the user file keeps its comments, with only those two values changed.

Status: not started.

## M42. Other people's PRs, reviewed on request

REQUIREMENTS R17, DESIGN §21 and §22. Needs M11 and M20. Asked for by the operator (2026-10-14): hand canopy a
coworker's PR to review, once or for as long as it is open, without writing a search into `review.query`. Today a PR
is reviewed only as the loop's own (`review.agent_prs`) or as a match of that standing query, which lives in the user
file and reads one repository's PRs.

- A review request is a journal fact, like a start record (§22): the PR's URL, its repository, `once` or `watch`, when
  and through which channel it was made, and when and why it ended. At most one open request per PR; a new one
  replaces its mode. A `once` request ends when a review of the PR ends `done`. A `watch` ends when the PR merges or
  closes, or the operator stops it.
- `canopy start URL --review --repo NAME [--watch]` makes one, D075's verb on a PR reference; `canopy stop URL` ends it,
  a running review finishing; `canopy show URL` shows it with its reviews, and `canopy status` lists the open ones.
  `--repo` names the repository whose clone fetches the commit and whose pool leases the slot, as for
  `canopy review run`. `start` on a PR without `--review` stays M14's, so a missing flag never turns a review into work
  on someone else's branch.
- Like `start`, `reply`, and `grant`, it refuses as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set. A
  request authorizes reviews as `review.query` does, so an agent steered by a PR's text could otherwise point the
  reviewer, and the operator's spend, at any PR. It also refuses, recording nothing: `reviews_off` when
  `capacity.max_reviews` is 0, `bad_pr` for a URL `canopy review run` would refuse, `unknown_repo`, and `loop_pr` for a
  PR a ticket's run pushed to, which `review.agent_prs` covers. An open request turns reviews on without `agent_prs`
  or `query` (§21, Off unless configured).
- The overseer: the state block's `reviews` gains each open request: URL, repository, mode, review runs so far, and
  its latest review run. Each tick it reads each requested PR through MCP, as it reads `review.query`'s matches. For an
  open PR whose head commit has no `done` review, it runs `canopy review run --pr URL --sha SHA --repo NAME` or
  records `canopy review wait` (checks still running, a draft). For a merged or closed PR, it records
  `canopy review end --pr URL --reason merged|closed`, which needs `CANOPY_TICK_ID` and ends only a `watch`. A steered
  overseer could end a watch early; that costs reviews, never adds one, and the PR's page shows who ended it and why.
- The harness ends a `once` request when its review ends `done`. A review that ends otherwise leaves it open, so a
  later tick retries within the per-PR limit, as `review_failed` says today. Every guard of `canopy review run` holds
  unchanged: one `done` review per commit, `policy.max_reviews_per_pr` (a watched PR pushed to often reaches it, and
  `review_limit` names `canopy grant URL review`), the daily limit, and capacity.
- What follows a review is what follows a `review.query` review: findings in the journal, posted nowhere (D114), no
  worker, no ticket, and `review.ended` (§20) to the operator's sinks. A PR from a fork is reviewed like any other;
  `_review` fetches its commit from the repository's `origin` and pushes nothing.
- Web UI: the pull requests page takes a PR's URL and a repository, with `Review once` and `Watch`; a PR's page shows
  its request, with `Stop`. `POST /pull-request/start?url=` and `POST /pull-request/stop?url=`, through the same code
  as the CLI, so with the same refusals.
- Journal: a migration adds `review_requests`: id, URL, repository, mode, created at and channel, ended at, and end
  reason (`reviewed`, `merged`, `closed`, `stopped`, or `replaced`), with at most one open row per URL. Its hash joins
  `SHIPPED`, and a row `SEED`, in `tests/canopy/test_db.py`.
- TRUST_MODEL: T1 says a review request authorizes a review as `review.query` does, made only through the operator's
  channels and refused inside a run; T8 adds making and ending one to the web channel's writes; §7's note that
  `review.query` may review other people's PRs covers requests too. With the operator's approval note in the PR, for
  those and the overseer prompt.
- DESIGN §21 (requests beside `agent_prs` and `query`, the overseer's part, Off unless configured, the journal) and
  §22 (the references table's PR row, the verbs, the routes and pages) say what changes.
- Tests with the fakes: a `once` request is reviewed at its head and ends `reviewed`; a `watch` is reviewed again at a
  new head and ends on `review end`; a failed review leaves a `once` request open; `start --review` refuses inside a
  run, with reviews off, for a loop PR, and for an unknown repository; `review end` refuses without `CANOPY_TICK_ID`
  and on a `once` request; a dry-run tick's state block carries the requests; with no request, no query, and
  `agent_prs` off, it has no `reviews` key; the web routes start and stop one; Playwright for the form.
- Open: whether `REPO#N` works, which needs a PR's URL from the repository's map (M14's references); a bound on open
  watches, since the overseer reads each one every tick, and whether a watch lapses after some days with no new
  commit; whether a watched PR's review waits for its checks to pass.

Accept: the tests above pass. Live: the operator asks for one coworker's open PR to be reviewed once from the CLI, and
another watched from the web UI. The first is reviewed at its head and its request ends. The second is reviewed,
reviewed again after its author pushes, and its watch ends when it merges. Nothing is posted on either PR.

Status: not started.

## M43. Publishing a review on someone else's PR

REQUIREMENTS N1, DESIGN §21, D114. Needs M32, and M42 for the PRs it applies to most. Sketch only; the design comes
first. Asked for by the operator (2026-10-15): on a review of a PR the loop does not own, where M32's `send to a
worker` does not apply, iterate on the review in canopy, by hand or with an agent, and then send it to GitHub as a
review on the PR. This is D114's revisit trigger, "the operator wants the web UI's shadow review published": D114
changes, with the operator's approval, from "posts nothing" to "posts nothing the operator has not approved, word for
word".

- Only for reviews of PRs that are not the loop's own (`review.query` matches, M42's requests): the loop's own PRs
  keep M32's send to a worker, and their reviews stay in the journal.
- A draft is a journal fact, versioned, made from a review run: its summary and findings, each finding's text the
  operator may edit, drop (M32's dismissal), or add to. Iterating with an agent is a run of its own that reads the PR
  and the draft, writes nothing anywhere, and reports a new version as a result line, as the reviewer does; the
  operator's notes to it are a reply on the draft. The draft's text is untrusted until the operator approves a
  version, since the reviewer and the reviser wrote it from the PR's text (T1).
- Publishing is the operator's act on one version, from the review's page or the CLI, refused `inside_run` as `send`
  is, and at most once per version. What reaches GitHub is that version verbatim: findings anchored on the diff as
  inline comments at their `path:line`, the rest in the review's body. A comment review only: canopy never approves or
  requests changes (TRUST_MODEL §6). The journal records what was posted, when, and where.
- canopy imports no GitHub client: the post goes through the agent runtime's MCP server or a command template, the
  harness checking afterwards that what was posted is the approved text. Open which, and whether canopy should only
  create a pending review for the operator to submit on GitHub themselves, so that submitting stays a human's click.
- TRUST_MODEL §6 (never submit a PR review, unless this changes it), T1, T5 (what a posted review says it is, with no
  bot identity, so it speaks in the operator's name), T6, and T8 (publishing from the web channel), and D114, with the
  operator's approval note in the PR.
- Open: whether a published review is followed on the next commit (M32's open question of a finding's identity across
  commits); whether the loop's own PRs ever get it, for a coworker's benefit; a bound on what one review may post.

Accept: written with the design, before work starts.

Status: not started.

## Deferred, with the trigger that would unblock each

- PR-scoped work (M14): when the operator keeps fixing CI or answering review on their own hand-written PRs by hand,
  often enough to want canopy to do it.
- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it, or when a repository wants to trust review verdicts.
- Second runtime (Copilot CLI, Claude Code): when a coworker asks. More than a config change: canopy's definitions,
  their permissions, and the D044 guard are written for OpenCode, so a runtime needs its own (REQUIREMENTS N4).
- Slack replies: when the operator wants to answer from Slack. A channel into the journal's conversation (DESIGN
  §22): a Socket Mode bridge running `canopy reply`, or the overseer reading Slack through MCP. Needs a T1
  change.
- Flaky CI triage (M25): when live use shows `fix-ci` attempts spent on failures the change did not cause. The design
  (DESIGN §23) and the milestone's bullets stand as written.
