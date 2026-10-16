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

Status: deferred 2026-10-15. The operator judged the budget and the pacing rule unneeded once M36 to M39 make the
journal the source of truth for the world, so the overseer runs only when the journal leaves it something to judge.
Taken in part before that (2026-10-07, 2026-10-08, and 2026-10-13), with M15's session ids: worker, split, chore, and
review runs and each tick's overseer record their cost in dollars and tokens, so every agent run canopy starts is in
the spend, and the loop's per-tick block, `canopy tick`, `canopy status`, `canopy decisions`, and the web UI's
attention page (the last 24 hours and 30 days) show it, and its chores pages each chore's. A tick's cost is its
overseer's alone, so a worker's is not counted against the tick that dispatched it. An `overseer_cmd`, `review_cmd`,
or chore `cmd` in a user file from before needs `--format json` added.

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
  `opencode attach` to a running worker and prompt it. The listener follows TRUST_MODEL T8: a private bind address,
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
Checking a run's session against `opencode export` is SCENARIOS S30. What keeps it open: workers against OpenCode's
server. Decided (2026-10-16): `fix-ci` and `resume` start a fresh session, as every run does (DESIGN §8, A fresh
session per run), since a continued one would keep stale prompts and cost more than the short runs it replaces.
On request (2026-10-16), a public worker's prompt carries the ticket's latest three runs' reports
(`{{PREVIOUS_RUNS}}`, DESIGN §8), so a fresh session still learns what the runs before it concluded.
Taken in part on request (2026-10-13): the overseer names
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
  `exec srt --settings <policy> -- "$@"`), taking a role (`worker`, `setup`, `chore`, `review`) that picks the
  policy; and the policy template, §4.2's filesystem table and §4.3's network allowlist with the operator's hosts
  left to fill in. No Unix sockets, so sandboxed runs push over HTTPS. Not harness code: the harness sees only the
  command template, as today. First an example under `examples/sandbox/`; on the operator's request (2026-10-14) it
  ships with canopy, as the workspace member `packages/canopy-sandbox` (D041), and `canopy sandbox setup` copies the
  templates, installs the `srt` its lockfile pins with npm, and checks and prints what needs root (D117).
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
canary checks it, and `_run` and reconcile check `commondir` as they do the `.git` link. Caches that tools keep as git
repositories are settled too: git's variables, set for the whole run, sent the objects of Go's module sources and of
OpenCode's snapshots, which persist under its data directory, to the run's directory, so the wrapper now puts a `git`
of its own first on `PATH` that sets them in the run's worktrees only; pre-commit was never affected. OpenCode's MCP
servers are settled from its source: a local one is OpenCode's child and runs under the worker's policy, and one
started with `docker run` cannot work, since the sandbox refuses Unix sockets, which the canary now checks.
`review_cmd`, HOST_ISOLATION §7's last open wrapping question, is settled as a role of its own, `review`, with a
template that reads the checkout through the review directory's link and writes none of it, no object directory, and
no `github.com`; the canary runs its HOME and state attempts as `review` too, and checks that a review writes nothing
in the checkout. Run against the fake `srt`, every review denial fails and its positive control passes.
TRUST_MODEL T4 and T6 name the sandbox as an opt-in control, with its residuals: the shared kernel, the unwrapped
overseer and harness calls, `/tmp/claude`, and exfiltration through an allowed host with the credentials a run holds
(D118).
HOST_ISOLATION's settled parts are DESIGN §24 now, with its answered questions beside what they settled; HOST_ISOLATION
keeps the problem, goals, and options, and points each later section there.
Giving sandboxed runs caches of their own, §24's open question on build caches, found that the templates let a run
write `~/.cache/opencode`, from which OpenCode imports packages and runs programs, the unsandboxed overseer's
included: a way out of the sandbox at the next tick. Each role now caches in `~/.cache/canopy/sandbox/<role>/`, setup
in the worker's, through `@CACHE@` and the cache variables the wrapper sets; the canary checks that no run writes the
operator's OpenCode cache or another role's, and that a role's cache persists; `canopy sandbox setup` says when a
template it kept still writes the operator's caches. Whether OpenCode's data and state directories, which the
templates also leave writable and the overseer also reads, are another way out is DESIGN §24's open question now.
Tracing it found that the data directory is: a `wellknown` entry in `auth.json`, the active account in `opencode.db`,
and a planted snapshot git directory each make the overseer's OpenCode, or the operator's, run what a worker chose;
the state directory is not (DESIGN §24, Open).
Next: data of the sandbox's own, once the operator settles how sandboxed runs get their credentials; then the canary on
the operator's Linux and macOS machines.

## M27. Session transcripts in the web UI

A run's and a tick's OpenCode session, its text, tool calls, and model calls, read back from its log
(`core/transcript.py`).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the check against `opencode export` is SCENARIOS S30. A running run's events
reach its log only when it ends, because `procs.run` captures stdout whole.
Next: watching a run live needed the worker's stdout streamed to its log, taken on request (2026-10-15): its events
reach the log as it prints them, and its session, spend, and latest tool call its row (DESIGN §8); the live check is
SCENARIOS S38.

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

The overseer's fixed prompt and its tracker's skill are the body of its agent definition in canopy's snapshot, where
the runtime caches them across ticks, and a tick's message is the state block alone; a prompt override gets a snapshot
of its own (DESIGN §6 step 4, §13).

Status: done 2026-10-15.
Learned: closed on the operator's request with the tests with the fakes passing, before the live measurement; the
before and after cache check and the 15% re-measurement are SCENARIOS S33. Measured since (MEASUREMENTS 2026-10-15
F23): a warm tick's first step cost 57% less, 15% of the tick, as predicted, but most ticks were cold, at the base
interval and through the night, so the realized saving was about 3%.
Next: M37's state block grows with the connectors' facts, so S33 is worth running again once it lands.

## M35. Temporary notices to workers

`canopy notice 'TEXT' [--for DURATION]`, and the web UI's settings page and banner, set and clear one notice at a
time, a journal fact that lapses on its own (`core/notice.py`): `implement`, `fix-ci`, and `resume` workers and
reviews hear it as `{{NOTICE}}`, chores as `notice` in their `## Run` object, and splits not at all; the overseer reads
the recent ones and holds a failed check the notice explains, raising `notice_rerun` once it ends; setting or clearing
one wakes the loop, and its lapse is a gate (DESIGN §6, §8, §14, §22; TRUST_MODEL T1, T8).

Status: done 2026-10-15.
Learned: closed on the operator's request with the tests with the fakes passing, before the live check during an
outage, which is SCENARIOS S37. The open questions settled small: 1 KiB, four hours by default and seven days at most,
and no repository scoping until real use asks for it (DESIGN §8, Open). A lapse commits nothing, so the web UI's
stream, which reads again only on a commit, watches the lapse of the notice it sent.
Next: once M25 is built, `triage-ci` reruns a held check where triage is on, in place of `notice_rerun`, and §23 says
so.

## M36. Connectors: the world observed into the journal, in shadow

MEASUREMENTS 2026-10-12 F6, F9, F10; 2026-10-13 F13, F14, F16, F17; 2026-10-15 F25 to F29; D003's revisit and
D008's. Needs M28 and M34.
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

- The contract. On stdin, one JSON object naming what to observe: the tracker query, every ticket not marked done, every
  PR URL on an unfinished unit (merged and closed included, 2026-10-13 F16), the repositories, the branch prefix
  (`trust.branch_prefix`), and `review.query` when set. On stdout, one JSON line per observation: `ticket` (key, title,
  body cut, open or closed, labels, updated at, blocker keys, label events when the tracker has them), `comment`
  (ticket, id, author account id, time, body cut), `pr` (url, repository, number, head sha, base ref, open, merged, or
  closed, draft, mergeable, mergeable state, author login, labels), `branch` (repository, name, head sha, for each
  branch under the branch prefix, so `pushed_no_pr` and a PR the journal has no unit for are observed), `check` (pr,
  head sha, context name, status, conclusion, run id, url), `review` (pr, id, review or review comment, author login,
  whether a bot, state, time, body cut, url, and for a review comment its thread, and whether that is resolved or
  outdated), and last an `end` line naming what it covered, so a connector cut off mid-way does not read as everything
  else having vanished. Unknown kinds are skipped. Ids, states, times, and bounded text; never logs or diffs. The
  tracker query is paged by the connector (REQUIREMENTS R1's gap), and CI is observed by named context, every one of
  them, never the combined status (2026-10-12 F9), which stops at 30 contexts (2026-10-15 F25). A ticket a watched
  ticket names as its blocker is observed too, whether or not the query returns it. PR labels, branches, thread state,
  every context, and blockers are what the overseer used to decide that the first draft left out (2026-10-15 F28). Open,
  and settled before the derivation reads a pending check: where the contexts that are not CI (ones that stay pending
  until a human acts) are configured, per repository, since counting one as CI holds a green PR at `ci_running`
  (2026-10-15 F28). The GitHub connector reads every watched PR in one GraphQL query a poll, not REST calls per PR,
  which would cost 15 to 18 times the overseer's MCP calls today (2026-10-15 F29), and pages any PR's contexts past the
  first page of 100 before its `end` line covers that PR.
- The journal: one table per kind (`observed_tickets`, `observed_prs`, `observed_branches`, `observed_checks`,
  `observed_reviews`), each row keyed by the source's id and replaced on each observation with its `observed_at`; a
  subject the `end` line did not cover keeps its old rows and their age. Comments go into `messages` as mirrored
  comments do now, with the workers' marks read in code (D069). `connector_runs` records each run: when, status, counts,
  the tail of stderr.
- Config, private (TRUST_MODEL T7): `[connect.sources.<name>]` with `cmd` (argv, no shell, as a sink's), `kind`
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
- Proposed (2026-10-15), for the operator to settle: the tracker connector's query first, on its own, as the one part of
  this milestone that changes what the overseer does. Run in code each tick, its result is in the state block as the
  tickets the query returned, less the tickets marked done that DESIGN §7's `recently_done` names, and the overseer
  reads those instead of running the query. When that run failed or its result is older than `connect.max_age_minutes`,
  the block says so and the overseer runs the query itself that tick, as today. A cheaper overseer skipped the query and
  read only the block's tickets, which stalls new work with no tick failing (2026-10-15 F31, DESIGN §7). A tick whose
  query was due now fails without `canopy queried` (DESIGN §6 step 5), which catches a skipped query but not a result
  read short or named short. TRUST_MODEL T1, with the approval note.
- Tests with the fakes: `tests/fakes/connector` prints configured lines; a line out of bounds is refused and the
  rest kept; a cut-off output keeps the previous observations; the derivation over journals written by hand, one
  case per row of the phase table, each a snapshot test (syrupy) as the state block's are.

Accept: written with the design, before work starts. Live, once built: a day of `canopy loop` with both connectors
against the real queue, and a MEASUREMENTS section giving the agreement between the derivation and the overseer per
phase row, counted by distinct situation as well as by decision (2026-10-15 F26), each disagreement read and
attributed (the rationale says which side was right), and what the connectors cost (calls and seconds per tick, no
tokens).

Status: not started.

## M37. The overseer reads the journal

Needs M36's measurement, with the disagreements that were the derivation's fixed, and M48's second stage, which
waits on the operator's approval note. Sketch only; the design comes first. This is M30's cut, taken from the journal
rather than a probe, and it is where the trust model gains its first code checks on what the overseer claims.

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
- The `mirror` tool is retired (M48 retired the heredoc, D081): the tracker connector writes comments. Open: whether
  a tracker with no connector keeps the live-read procedure, or a connector is required (recommended: required; the
  two shipped cover the operator's trackers, and the contract is a page of Python for another).
- TRUST_MODEL T1 (labels, repliers, and reviewers checked in code; the overseer's MCP narrowed to stale subjects),
  T2 (a connector's credentials), T7 (`connect.*`), with the approval note; DESIGN §6, §7, §17, §22; D003 edited in
  place (M48 superseded D081).

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
  with M25), only for a check whose run started while no notice (M35) was in force: for one that ran during a
  notice, the row stays the overseer's, even after the notice ends, since whether the notice explains the failure is
  judgment, which M35 keeps out of code; `review run` for `review_pending` and for
  `review.query`'s PRs. Each is a `decisions` row with `by = harness`, so the corpus, `canopy decisions`, and the
  tick's page show every decision and who made it. `ci_red` was the row the overseer overruled most, on facts
  outside it: a PR humans had shelved with labels, an outage, a stacked ticket's open blocker, a build still running
  (2026-10-15 F27). Its `fix-ci` moves only if M36's day, with PR labels observed, shows the derivation right; until
  then it stays the overseer's.
- The priority order across both deciders is the overseer prompt's step 4 today (a human waiting, then conflicts and
  red CI, then a pushed branch with no PR, then `ready`) and nowhere in the design: it goes into §7, and the
  harness keeps it. The harness records its decisions before the overseer and makes its dispatches after it; the
  state block names them and the capacity they take, so the overseer dispatches its human-waiting tickets first and
  its `ready` tickets only into what remains, and a `ready` dispatch past that is refused `reserved`.
- The attention list from observations: `green_unreviewed`, `approved`, `untrusted_review`, `attempt_limit`,
  `split_unlabeled`, `split_self_labeled`, `review_failed`, and `review_limit` are the harness's, open while their
  cause holds in the journal, like the run reasons (§14). No re-recording rule, which M28's prompt fix (the
  overseer's open items in its state block) works around and this removes, so an item cannot flap (2026-10-13 F17)
  or go because the overseer left it out on partial data. This is the fix for issue #219, an outage tick that closed
  `ok` and resolved items it could not read: no item hangs on the overseer recording it again, so nothing in `tick.py`
  needs to tell a partial tick from a whole one, and a tick that did work during an outage keeps it. The
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
- The overseer's definition loses the tracker and GitHub MCP servers: it has canopy's tools (M48) and nothing else,
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
- Open: whether runs go in parallel; chores' `when`, which needs no ticket; whether one run may still see the queue;
  a model per run, chosen by the ticket's phase: the strongest for `ready`, review feedback, and a free-text reply,
  a cheaper one for the rest. That is a split overseer's saving without two standing overseers, whose split by job
  buys only the cheaper model's price, since finding new work was 0.2% of overseer spend (2026-10-15 F31).

Accept: written with the design, before work starts.

Status: not started.

## M41. Limits and trust settings from the web UI

REQUIREMENTS R16, DESIGN §12 and §22. Needs M20 and M49. Asked for by the operator (2026-10-14): change a pool's slots
or a trust setting from the web UI without opening a config file. Today the web channel asks for a reload and writes
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
- Where it writes: the workspace's private file (M49) only, never the workspace file (shared, perhaps committed, T7)
  nor the user file, which serves every workspace. A key whose value came from the user file is written to the
  private file, where it shadows the user file's for this workspace alone, and the page says so before the save.
  Edited in place, keeping the operator's comments and layout, so a TOML writer joins the runtime dependencies with
  its DECISIONS entry; `tomllib` only reads. Rejected: a file of canopy's own layered after the private file (a hand
  edit to the private file would be silently overridden), and writing the file anew with the stdlib (its comments
  lost).
- How: the request carries a hash of the private file as the page read it. The server holds a lock from reading the
  file to replacing it, so two requests cannot both pass the check on the same hash; a file whose hash differs is
  refused as `stale`, checked again just before the replace, so a hand edit is lost only if it lands in that last
  moment. The change is applied to a copy and validated by `config.load`, as any `canopy` command would read it; a
  refusal writes nothing and gives the loader's message. The file is replaced atomically, keeping its mode, and
  refused when it is a symlink or not the operator's (D053's check). Then the loop is asked to reload through the
  existing path (`loop.reread`).
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
- API: `GET /config`, each editable key's value, the file it came from, its ceiling, and the private file's hash;
  `PATCH /config`, the changed keys and that hash. The settings page edits them, beside Reload.
- TRUST_MODEL T8: "It cannot write config" becomes the allowlist, ceilings, and stricter-only keys above, and its
  residual gains a stolen session raising limits up to their ceilings, which outlives a new secret until the operator
  sees it. With the operator's approval note in the PR. DESIGN §12 marks the keys the page edits and their ceilings,
  and §22 the routes and the settings page. DECISIONS: an entry for what the web channel may write to config (a rule
  the trust boundary relies on), and one for the TOML writer.
- Tests with the fakes: an allowed key written and reloaded, the file's comments kept; a key outside the allowlist, a
  stricter-only key loosened, a count over its ceiling, a stale hash, two requests on one hash, an invalid value, and
  a symlinked private file each refused with the file unchanged; neither the workspace file nor the user file ever
  written; Playwright for the form.
- Open: the ceilings' values; whether the page also shows the keys it cannot edit, read-only, with the file each came
  from.

Accept: the tests above pass. Live: while `canopy loop` runs, the operator changes `capacity.slots_per_repo` and
removes a trusted reviewer from the settings page; the next tick leases under the new size and reads the shorter list;
and the private file keeps its comments, with only those two values changed.

Status: not started.

## M42. Other people's PRs, reviewed on request

A review request is a journal fact the operator makes for a PR the loop does not own, by its URL alone, with `canopy
start URL --review` or the web UI's pull requests page, and ends with `canopy stop URL`; it authorizes one review of
that PR at its head, as `review.query` would, and turns reviews on by itself. The overseer reads each one through MCP,
finds its repository by the map's clone URL, which the state block now carries, and reviews its head, or ends it with
`canopy review end` once the PR merged or closed first or is in none of the workspace's repositories; the harness ends
it when its review ends `done` (DESIGN §21, §22; `core/review_requests.py`, migration 0029).

Status: done 2026-10-16.
Learned: closed on the operator's request with the tests with the fakes and Playwright passing, before the live check
against a coworker's PR, which is SCENARIOS S39. The operator cut watching a PR, reviewed again at each new commit
until it merges, as more than MVP needs; asking again after a push reviews the new head. The operator asked that a
request name no repository, since the overseer already matches `review.query`'s PRs to one. The request needed no new
authority in code: it is the run's purpose (`request`) and one more source for `reviews_on`, and every guard of
`canopy review run` holds unchanged. Ending a request in the transaction that closes its `done` review keeps a crashed
`_review` from leaving it ended unreviewed.
Next: watching is on the deferred list. The open questions stay in DESIGN §21 (Review requests). M43's publishing
applies to these reviews first.

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

## M44. Plans before implementing

REQUIREMENTS R18, DESIGN §25, and the parts of §7, §8, §14, §20, and §22 it changes. Asked for by the operator
(2026-10-15), and taken next, ahead of M36: a ticket can be planned before it is implemented, the operator approves
the plan before work starts, and the plan is kept on disk to read later. Today the `implement` worker plans
inside its own session, and only its summary survives. M36 to M40 take up the new phases and kind as they reshape
the state block and the overseer.

- A new run kind, `plan`, dispatched with `canopy dispatch KEY --kind plan --repo NAME...`, before the ticket's first
  `implement`. It runs as `canopy-planner` with `runtime.plan_cmd`, in a desk of the named repositories' worktrees at
  their base branches, detached, as a split does (§18): no branch, no unit, nothing pushed or verified. It counts
  toward `capacity.max_workers` and has the worker's timeout. `policy.max_plan_attempts`, default 3, limits plan runs
  per ticket, and `canopy grant KEY plan` adds one.
- The planner writes its plan to one file in its desk and nothing else anywhere. Its definition allows no other edit,
  and has no shell, web fetch, or subagent tools, and its tracker tools are the private worker's (§22): the tracker
  server's tools denied by a wildcard, then only `tracker.read_tools` allowed, so it reads the ticket but cannot
  comment, label, or create. With no read tools known, the dispatch is refused as `no_read_tools`. On a public ticket
  it checks the queue label as every worker does.
- Its prompt, `worker-plan.md`, asks for a plan a later worker can follow: what changes in each repository and why,
  the files and interfaces it touches, the tests that will show it works, what is out of scope, and the open risks. It
  carries the operator's messages, standing instructions, and notice, and on a re-plan the plan it replaces, as a
  file in its desk, and the operator's reply to it. The plan is the markdown it writes to `.canopy-new-plan.md` in its
  desk; its result line is `{"status":"done|blocked|failed","summary":"...","question":"<only when blocked>"}` (§25).
  `_run` reads the file as every plan file is read: a `done` plan is a regular file, non-empty, and at most 100,000
  characters; anything else makes the run `unknown` and records no plan. A `blocked` plan records its question as a
  worker message (§22), on a public ticket too, since the planner cannot post one; the operator answers with `canopy
  reply`.
- Whether a ticket is planned: `policy.plan`, `"off"` (default, as today) or `"approve"`, shared config that a
  repository may only tighten to `"approve"`. The operator overrides it for one ticket: `canopy plan KEY` asks for a
  plan (and makes a new one if the ticket has one), `canopy plan KEY --skip` waives it, and `canopy start KEY --plan`
  starts a private ticket with one. Asking for a plan and `--skip` supersede a waiting or approved plan at once, so
  the next tick dispatches a new `plan` or the `implement`. Each refuses as `inside_run` when `CANOPY_TICK_ID` or
  `CANOPY_RUN_ID` is set, and `--skip` and asking for a plan refuse as `bad_plan` while a plan run is running.
  Asking for a plan also refuses once the ticket has a branch; `--skip` there drops the plan from later runs.
- Approval: `canopy plan KEY --approve` approves the newest plan as its file stands, the operator's edits included,
  and records the file's hash; it refuses `inside_run`, and `bad_plan` when the newest plan is not waiting (unless it
  is approved and its file changed since), a plan run for the ticket is running, or its file is missing or no longer
  a plan. `implement` and `resume` refuse `plan_changed` when the approved plan's file is missing, unreadable, or no
  longer has its approved hash; the operator approves it again, or, for a file that is gone, asks for a new plan or
  `--skip`s it. A reply (`canopy reply KEY`) newer than the plan asks for changes: the overseer dispatches `plan` again
  with the reply in its context, and the new plan supersedes the old. An approval after such a reply, before the new
  plan run starts, wins: it is the operator's later word, and the reply reaches the `implement` as an operator
  message, as any message does.
- A hard guard in code: an `implement` for a ticket that needs a plan, by `policy.plan` or its own setting, and has no
  approved plan is refused as `unplanned`. A `plan` for a ticket with a branch, or for a split's parent, is
  `bad_plan`. A `--slug`, `--base`, or `--request` on a plan is `bad_slug`, `bad_base`, or `bad_request`.
- Phases (§7): a ticket whose latest plan run ended `blocked`, with no operator message since, is `needs_human` with
  attention `awaiting_reply`, so it is not planned again until the operator answers; `ready` with a plan needed and
  none waiting dispatches `plan`; `plan_proposed`, the newest plan waiting
  and no operator message after it, is attention `plan_review` with no run, so the slot is free while the operator
  reads; `plan_proposed` with an operator message after it dispatches `plan` again; `ready` with an approved plan
  dispatches `implement`. The state block gains each ticket's plan: whether one is needed, and the newest plan's id,
  status, and time, never its text.
- Workers: `_run` writes the approved plan from the journal to `.canopy-plan.md` in the worker's cwd, ignored through
  the repository's `info/exclude` in a one-repository run, and removes it before the slot is returned (§25, The plan
  file). `implement` and `resume` prompts carry `{{PLAN}}`, the file's name and the plan's headings or `None.`, never
  its text, and an override without it is `bad_prompt` once the ticket has an approved plan, as for
  `{{OPERATOR_MESSAGES}}` (D093). The prompt says to follow it, to leave the file out of every commit, and to say in the
  summary where the work left it and why. A plan is model-written from ticket text: it describes the work, as the ticket
  does, and the prompt's obligations come before it. The operator's approval authorizes the `implement`, not what the
  plan's text asks for.
- Showing it: `canopy show KEY` prints the newest plan, its status, and when it was approved; `canopy show KEY --plans`
  every plan, oldest first, the newest with its open comments. The web UI's ticket page shows the newest plan in the
  plan editor (§25, Commenting on a plan), where the operator edits it and comments on its passages, with `Approve`,
  `Ask for changes` (the open comments, each with its passage, and a note, as one reply), and `Skip`, and lists
  earlier plans. `POST /tickets/{key}/plan` with `approve`, `request`, or `skip`, through the same code as the CLI,
  so with the same refusals. A `plan.proposed` event goes to the operator's sinks (§20), with the ticket's title and
  no plan text.
- Storage: each plan is a file of its own, `<state_dir>/plans/<KEY>/<run>.md`, named for its plan run, operator-only,
  never deleted by canopy (§25, Where plans live). A migration adds `plans` (id, ticket key, run id, created at, status
  `proposed`, `approved`, or `superseded`, the SHA-256 and size of the file as written, the approved hash, approved at
  and channel; no body) and the ticket's own plan setting (unset, `plan`, or `skip`), set only by the operator's
  channels. `plan_threads` and `plan_replies` hold the operator's comments, the ticket's, anchored by their passage's
  words. The web UI's editor saves an edit to the plan's file, refusing one the file changed under. `canopy forget`
  supersedes a waiting or approved plan, so a forgotten ticket is planned again under `"approve"`. Its hash joins
  `SHIPPED`, and a row per table `SEED`, in `tests/canopy/test_db.py`.
- TRUST_MODEL: T1 says an approved plan is data, not an operator instruction; T3 counts plan runs toward capacity and
  attempts; T6 gives the planner no write scope; T8 adds the plan route to the web channel's writes. With the
  operator's approval note in the PR, for those, the overseer prompt, the new prompt, and the `canopy-planner`
  definition.
- Tests with the fakes: under `"approve"`, a dry-run tick dispatches `plan` for a ready ticket; a `done` plan is written
  to its file and recorded `proposed`, and raises `plan_review`; an edit to the file before `--approve` is what the
  worker gets; an edit after it makes `implement` refuse `plan_changed` until approved again, as does a missing file,
  which `--skip` gets past on a ticket with a branch; an edit between dispatch and `_run`'s check crashes the run before
  the worker starts; a symlinked `plans/` or ticket directory refuses the write; a plan file with no row is never read,
  and a name already taken is never overwritten; `implement` is refused `unplanned` until `canopy plan --approve`, then
  finds `.canopy-plan.md` in its cwd, ignored by git, and the plan's headings in its prompt, and the file is gone once
  the slot is returned; a pushed head holding the file gets a harness note; a reply makes the next plan supersede the
  first; `--skip` lets `implement` through; an empty plan or one over the bound is `unknown`; a `blocked` plan records
  its question; `plan`, `--skip`, and `--approve` refuse inside a run; the planner's definition denies the tracker's
  write tools; the web route approves; a comment asked for through the web route reaches the next plan's prompt; an
  edit saved from the web UI is the file `--approve` takes, and one the file changed under is refused; Playwright for
  the ticket page's buttons. The editor's own tests are in: a plan written back as read, HTML and images kept as
  characters, anchors that survive edits and find nothing for a passage that is gone, and the
  change request (Vitest), and commenting, editing, resolving, and asking for changes in a browser (Playwright).
- Open: a plan-and-go mode (`policy.plan = "auto"`) that implements without waiting, if the operator wants plans
  without the gate; whether a ticket that already has a branch can be planned again before a large `resume`; whether
  plans help, compared by attempts and spend per ticket (M33) on planned and unplanned tickets; whether M38 makes the
  plan gate the harness's decision rather than the overseer's.

Accept: the tests above pass. Live: under `"approve"`, a ticket is planned, the operator asks for one change from the
web UI by commenting on its passage, approves the second plan from the CLI, and the `implement` that follows names
the plan in its summary. A week later the plan is still on the ticket's page. Nothing about the plan appears on the
ticket.

Status: in progress. The plan editor is in, over mock data at `/plan-editor`: Markdown in and out, comments anchored
by their words, and Ask for changes composing the reply (`ui/src/lib/plan-*.ts`, D120). Plans' files and rows are
in (`core/plans.py`, migration 0033): written once and never replaced, read bounded, approved by the file's hash, and
superseded by `canopy forget`. Plan runs are in: `canopy dispatch --kind plan` with its guards, `canopy-planner`,
`worker-plan.md`, and `_run` writing a `done` plan to its file and recording it `proposed`, with the copy of the plan
it replaces in its desk. The planner writes its plan to a file in its desk rather than its final message (§25, The
prompt). What keeps it open: `canopy grant KEY plan`, the CLI, `policy.plan`, the guards and phases, the
worker's copy, the threads' tables, and the ticket page.

## M45. canopy's own worktree pools, replacing treehouse in stages

D002, D107, D118. DESIGN §8, §9, §18, and §24. Needs M17, and M26's `commondir` check, which is in. Asked for by the
operator (2026-10-13): drop treehouse, so installing canopy needs no Go and its leases live in the journal. Asked again
(2026-10-16): slowly, with a lot of verification before treehouse goes.

Four stages, in order, each in its own PRs. A stage starts only once the one before has passed its check, recorded on
the `Status:` line. Until the last stage, treehouse stays installed and one config setting goes back to it.

What every stage holds to:

- **One interface, two pools.** `core/treehouse.py`'s four operations (`status`, `lease`, `return_slot`, `destroy`)
  become the interface every caller uses. treehouse is one implementation and `core/pool.py` the other; no caller
  learns which one it has.
- **The contract is the spec.** One test suite states each guarantee as a case, written against the interface, and
  runs it against real treehouse, the fake, and canopy's pool. A behavior with no case is not a guarantee. Where
  canopy's pool differs on purpose, DESIGN §18 says so and the case says which pool expects what.
- **The host stays safe.** Every git canopy's pool runs goes through `hostgit.argv` (D107), and a step in a slot after
  a run comes after `_run`'s link and `commondir` check (D118).

What treehouse does that canopy relies on or works around, from its source at the pinned `1185dc6` (checked in stage
1; DESIGN §18, What a pool guarantees, lists what the contract suite holds it to):

- Reuse and return reset a slot with `read-tree --reset -u` and `clean -fd`, no `-x`, and move HEAD to the base's tip,
  detached: ignored files (build outputs, `node_modules`, Bazel's links) survive, except those seeding wrote, which
  the reset removes first; untracked files and commits no branch holds do not.
- A slot is reused only when it is unleased, a worktree of this clone, clean (`status --porcelain
  --untracked-files=all`), has no process with its cwd inside it, and its HEAD is merged (an ancestor, or the same
  content as a squash) into the base or the base it was last leased on. A clean slot holding unmerged commits shows
  `available` and is passed over.
- `return` is conditional on the lease id and holder (exit 1 otherwise) and forced, so exit 3 never happens. It ends
  processes in the slot first (SIGTERM, then SIGKILL after two seconds), and parks the slot on its lease's base.
- Seeding copies the untracked, ignored files `.worktreeinclude` (or `--include-file`) selects, on every lease. A
  seed target already in the slot fails the lease, and treehouse then holds a reused slot under a `quarantined:`
  holder. A symlink is written as a regular file holding its target.
- `destroy` keeps a slot that is leased, in use, dirty, unverifiable, or unmerged into the default branch, and runs
  `git fetch` and `ls-remote` on `origin` first. `status` rewrites treehouse's state, forgets a slot whose directory
  is gone, and records a worktree it finds unrecorded as held; it moves no file.

**Stage 1, the contract.** No behavior changes.

- `tests/canopy/test_pool_contract.py`: a case for each guarantee above and each one `core/treehouse.py`'s callers
  depend on (reconcile, dispatch, reviews, sync, the worktrees page). It runs against the fake on every `make check`,
  and against real treehouse when `treehouse` is on `PATH` (`make pool-contract`).
- A CI job, Linux and macOS, that builds treehouse at the pinned commit with `make treehouse` and runs the suite. Go
  is a CI-only dependency, like Node for the sandbox canary. Where the fake and real treehouse disagree, the fake is
  fixed.
- DESIGN §18 gains "What a pool guarantees", the list the suite checks, each line naming its case.
- Check: the suite passes against real treehouse on both platforms and against the fake.

**Stage 2, canopy's pool in shadow.** Built beside treehouse, wired to no caller.

- Leases are journal rows: a migration adds `slots` (repository, name, path, lease id and holder, leased at, base,
  the paths seeding wrote). A lease claims its row under the pool's own lock before it touches the worktree, in a
  transaction of its own rather than the run's, since the run is recorded only after its slots are leased; a lease
  with no run is reconcile's to return, as treehouse's is (DESIGN §18, canopy's pool).
- Layout: `<workspace>/pools/<repo>/<N>/<repo>`, with no hash of the remote, since a workspace's repository names are
  unique. The declared size is the only limit; a pool with none declared stops at 16, treehouse's default
  `max_trees`.
- Lease, reuse, return, and seeding as treehouse does them (above). Processes in a slot are found through `/proc` on
  Linux and `lsof` through `procs` on macOS, so no new dependency. `destroy` uses the fetched refs, no network call.
- The contract suite runs against canopy's pool too, every case, nothing skipped for one pool only, plus real-git
  tests for two leases at once and a crash between `worktree add` and the journal row.
- Shadow: each tick's reconcile also classifies every treehouse slot with canopy's own checks and logs a
  `pool_shadow_mismatch` line wherever they disagree. It changes nothing. Each mismatch the operator explains becomes
  a contract case, and canopy's checks are fixed until it passes.
- Check, live: a week of `canopy loop` on the real queue with the shadow on, whose every mismatch is explained, has a
  case, and passes.

**Stage 3, by choice, then by default.**

- `pools.backend`, private (§12): `"treehouse"` (default) or `"canopy"`. The journal records which pool made each
  lease, and a lease is always returned through that pool, so switching with runs in flight is safe.
- Switching to canopy, `canopy workspace sync` moves each idle treehouse slot into `pools/` with `git worktree move`,
  keeping its ignored files. Switching back costs only warm caches: treehouse makes fresh slots and sync removes
  canopy's idle ones.
- `post_create` does not run under canopy's pool; the operator's guide says how to move a hook to `runtime.setup_cmd`
  (§9).
- Check, live, before the default changes: a week on `"canopy"` in which a Bazel or `node_modules` cache in a reused
  slot survives, no slot is left leased without a live run, and one switch back and forward with a run in flight
  loses nothing. Then the default becomes `"canopy"`, in its own PR.

**Stage 4, treehouse removed,** once a tagged release has shipped with `"canopy"` as the default.

- Goes: treehouse's implementation, `pools.backend` (a config still setting it is warned about, then ignored), the
  fake and its fixture, `make treehouse` and the CI job, README's install step, and the mock's pool hashes.
- Docs: D002 (rewritten as settled), D033's last `Rejected` line, D066's first bullet, DESIGN §8, §9, §18, §22, and
  §24, REQUIREMENTS R2, README, GETTING_STARTED, PRIOR_ART, and TRUST_MODEL, with the operator's approval note.

Open: whether a seeded symlink is copied as a link (treehouse writes its target text into a regular file), checked
against TRUST_MODEL T4; whether sync warms a new slot (what `post_create` did for M17) or the first run's `setup_cmd`
is enough.

Accept: each stage's check, in order. Then `make install-check` and `make binary` pass with no `treehouse` on `PATH`,
and a fresh install from README on a machine with no Go runs a day of `canopy loop`.

Status: in progress. Stage 1 passed its check 2026-10-16: the contract suite passes against the fake, and against real
treehouse at the pinned commit in CI on Linux and macOS. Stage 2 is built: canopy's pool passes every contract case, and
reconcile's shadow logs `pool_shadow_mismatch`; its check, a week of `canopy loop` with the shadow on, is the
operator's. Stage 3's choice is built too, ahead of stage 2's check at the operator's request (2026-10-16):
`pools.backend` picks the pool, each lease goes back to the pool the journal says made it, and sync moves idle slots
across on a switch. The default stays `"treehouse"` until stage 3's live check passes.

## M46. Workers file follow-up tickets

REQUIREMENTS N3, DESIGN §18. Sketch only; the design comes first. Asked for by the operator (2026-10-16): a worker
should be able to file follow-up work and properly linked TODOs, and canopy should work them. The split worker, a
whole run kind whose only output is tickets, has never run live and is not worth keeping on its own. The operator moved
the authorization line: a human's queue label on a ticket authorizes it and the follow-ups its runs file, since that
work happens on a branch in a leased worktree and lands only through a PR a human reviews and merges. "Humans should
authorize work, but I'm not super worried about the prospect of an agent authorizing itself to work in a sandboxed copy
of the repo." Humans still authorize everything that lands; canopy still never merges (TRUST_MODEL §6).

- Any `implement`, `fix-ci`, or `resume` worker may create tickets: in its ticket's project, linked to its ticket as
  the parent, with the repository in the body (`canopy-repo: web`) when one applies, no assignee, and no labels. It
  reports them in its result as `"created": {"PROJ-14": "web", "PROJ-15": null}`. `_run` validates them as it
  validates a split's children today (a valid key, new to the journal, not the parent, a mapped repository or null)
  and records them, with the run that made them, in a table generalized from `split_children` by a new migration.
- A follow-up the journal records is a candidate without a queue label: its authorization is its parent's. Dispatch
  names no `--label` for it, and refuses it while the parent is stopped or forgotten. The worker's re-read (D051) is
  that the ticket links its parent.
- None of this stops a steered agent from authorizing work for itself, and M46 does not try. A worker can already add
  a queue label to any ticket it can reach, and every label check is agent judgment (TRUST_MODEL T1). So M46 drops the
  split's label-history checks rather than generalize them. What bounds an agent that authorizes its own work is the
  harness's guards in code (capacity, attempt limits, cooldowns, never merge) and a human reviewing every PR before
  it lands.
- Volume bounds, in code: at most `policy.max_follow_ups` recorded per run (default 5), and only one generation deep.
  They keep a well-meaning worker from fanning out; they do not stop a steered one. Anything past them is an ordinary
  ticket, worked only with a queue label, and the harness raises attention naming it.
- Splitting stops being a kind. An authorized reply asking for a split is guidance to the ticket's next run, which
  files the children as follow-ups, ordered with the tracker's blocker relation as now. `multi_repo` attention stays
  for a ticket nobody asked to split.
- Removed: `--kind split`, `--request`, the `split` phase, `split_unlabeled` and `split_self_labeled`, `split_cmd`
  and `policy.max_split_attempts` (to `REMOVED_KEYS`), the `canopy-splitter` definition and its sandbox role,
  `worker-split.md`, SCENARIOS S2 and S15, and M44's `bad_plan` for a split's parent. Old `runs` rows of kind
  `split` stay as history. The detached desk a split runs in stays, since M44's planner runs in one.
- The worker definitions allow the tracker's create and link tools. On GitHub, `issue_write` already creates issues
  and only the prompt kept the worker from it (TRUST_MODEL T6), so the line this moves was mostly prompt-deep already.
- Private tickets are unchanged: their workers write nothing to the tracker.
- TRUST_MODEL T1 (from "the loop may create tickets, but never decides to" to "a worker may file follow-ups to its
  ticket, worked under its ticket's authorization; authorization checks on tickets are best effort, and the backstops
  are the guards in code and review of what lands") and T6 (a worker's write scope adds creating and linking tickets
  in its ticket's project), a decision entry for the new line, and the overseer prompt, worker
  prompts, and definitions, with the operator's approval note in the PR.
- Open: what a parent's phase is once its work has moved into follow-ups; whether a private ticket's worker should
  file journal-only follow-ups; whether an operator who wants the old line should get a private switch that makes
  follow-ups wait for a label.

Accept: written with the design, before work starts.

Status: not started.

## M47. Garbage collection

DESIGN §26, D030, D086, D107. Asked for by the operator (2026-10-16): a plan for removing what canopy keeps forever.
Almost everything is kept: every run's, tick's, chore run's, and review's log and prompt, `canopy.log` unrotated, the
harness's attention rows recorded again each tick, a journal nothing checkpoints or vacuums, and loose objects in the
primary clones. Four stages, in order, each in its own PRs, a stage starting only once the one before has passed its
check, recorded on the `Status:` line.

What every stage holds to: no row a guard counts is deleted (`runs`, `run_slots`, `review_runs`, grants,
dismissals), nor a tick, ticket, message, or the overseer's own decisions; nothing a live run uses is touched; no
remote branch is deleted; and no flag shortens retention, which only the user file sets (§26, What it never removes).

**Stage 1, measure.** Nothing is removed.

- `canopy gc --dry-run [--json]`: for each kind in §26's table, the count, the bytes, and what a pass with the
  proposed defaults would remove. It refuses when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set; TRUST_MODEL T1 adds
  `gc` to the commands that do, with the operator's approval note in the PR.
- `[retention]` in the user file (§26, Configuration), validated in full now (non-negative integers), so a later
  stage changes no key; read by nothing but the dry run yet.
- Check: the operator runs it on their live workspace, the result is a dated section of `MEASUREMENTS.md`, and the
  defaults in §26 are set from it.

**Stage 2, files.**

- The pass in reconcile, at most daily on a live tick, recording each in `gc_passes` (a new migration): run, tick,
  chore, and review files past their retention, and files with no row. A failed pass is logged and the tick goes on.
- `canopy.log` rotated past `log_max_mib`, its size checked on every live tick, every process logging through
  `WatchedFileHandler`.
- The web UI's transcript, prompt, and diff views say "removed after N days" for a file retention removed.
- Tests with the fakes: a live run's files, a running tick's, and a symlink are never removed; a dry tick runs no
  pass; a file with no row goes only after an hour.
- Check: a week of the operator's loop with the pass on; each day's `gc_passes` row matches what the dry run
  predicted, and no page the operator opens fails.

**Stage 3, the journal.**

- The pass deletes harness-raised attention rows older than both the attention list's 1000-tick window and
  `journal_days`, then runs `PRAGMA wal_checkpoint(TRUNCATE)`. `canopy gc --vacuum` runs `VACUUM` while no run is
  live and the disk has room for a copy of the journal.
- Tests: with rows on both sides of the window, the attention list, each item's open-since, and the notification
  diff are the same before and after a pass; with fewer than 1000 `ok` ticks, a pass deletes no row.
- Check: on the operator's journal, the attention list and `canopy status` are unchanged across a pass, and the file
  shrinks after `--vacuum` by about what the dry run said.

**Stage 4, outside the journal.**

- `canopy gc --git`: `loose-objects` and `incremental-repack` maintenance in each primary clone with no leased slot,
  under `dispatch.lock`, through `hostgit.argv`.
- `canopy gc --caches`: empties the sandbox's per-role caches while no run of that role is live.
- The dry run lists remote branches no open run or unit names, for the operator to delete.
- Check: `--git` on a clone whose slots hold unpushed commits keeps every one of them, and a run after it pushes
  normally; a SCENARIOS entry, since it is worth running again on each git upgrade.
- Open: whether the pass runs `--git` on its own, weekly, after that check.

Status: not started.

## M48. The overseer's tools over MCP

DESIGN §27, D020, D081. Asked for by the operator (2026-10-16): the overseer acts through MCP tools canopy serves,
not by running the `canopy` CLI through bash. Needs nothing; taken before M37, so that M37 and M38 rewrite the
overseer's prompt once, against tools. Workers are out of scope (§27, Why). Four stages, in order, each in its own
PRs, a stage starting only once the one before has passed its check, recorded on the `Status:` line.

**Stage 0, measure and read.** Nothing is built.

- From the operator's tick logs, a dated section of `MEASUREMENTS.md`: the overseer's bash calls per tick, and how
  many failed on usage, quoting, or a refused command. That is the baseline stage 2 is held to, and if such failures
  are rare, the operator decides whether the rest is still worth building.
- From OpenCode's source, as §24 read it: the inline config's form, how it merges with the operator's and the
  workspace's, whether it reaches OpenCode's children, what a run does when a local server fails to start, and the
  protocol versions its client asks for.
- Check: both written down; §27's "How the overseer gets them" revised first if OpenCode differs from it.

**Stage 1, the server.** Nothing the overseer runs changes.

- The overseer's verbs move below `cli/` into `loop/tools.py`, each a function over a pydantic request model that
  holds §6's bounds and the rules across fields; the click commands build the request and call it. The CLI's tests
  pass unchanged.
- `canopy _mcp` in `loop/mcp.py` (§27, The server): the five methods, one tool per verb, refusals as tool errors,
  nothing listed or served outside a running tick or under `CANOPY_RUN_ID`.
- `procs` gains a way to remove a variable from a child's environment, for the entry's (§27).
- A DECISIONS entry: canopy serves MCP itself, over stdio only, to the overseer only; the `mcp` SDK rejected.
- Tests: a stdio client in `tests/canopy/helpers.py` drives `canopy _mcp` inside a tick. Each tool records what its
  command records, a refusal is `isError` and the server keeps serving, an unknown field is refused, and no tool is
  listed outside a tick or with `CANOPY_RUN_ID` set. One parameterized test sends each refusal through both a tool and
  its command. A spawned run's environment lacks a removed variable.
- Check: `make check`, and a hand-run `canopy _mcp` in a dry tick answering an OpenCode client.

**Stage 2, the overseer switches.** With the operator's approval note.

- The harness gives the overseer's run the server's entry and removes it from every run it starts; the definition
  allows each tool by exact name and denies `bash`, `treehouse status*` included; every other definition denies
  `canopy_*`; `definitions.shadowing` refuses a workspace config that names a `canopy` server; §6's preflight starts
  the server and sends `initialize`, closing the tick `canopy_unavailable` if it fails.
- The prompt names tools, not commands; a mirror's body is a field; the state block drops the heredoc delimiter.
- TRUST_MODEL T1 and T7; DESIGN §6, §13, §22; D020 edited in place, D081 superseded.
- Tests with the fakes: the fake agent gains `FAKE_AGENT_TOOLS`, tool calls it makes through the server its config
  names, and the dry-run end-to-end test plays the overseer through them; a worker dispatched through a tool starts
  without the entry; a server that cannot start closes the tick `canopy_unavailable`.
- Check: a day of the operator's loop, a dated section of `MEASUREMENTS.md`: no bash call in any overseer transcript,
  no tick failed for a call the overseer could not make, duties met at least as often as the baseline's, and
  tool-result tokens per tick no higher.

**Stage 3, MCP only.** The operator's end state (2026-10-16): the CLI keeps the verbs only while the tools settle.

- The overseer's verbs leave the CLI (`dispatch`, `decide`, `queried`, `attention`, `ticket set`, `mirror` if M37 has
  not retired it, `review run`, `review wait`, `review end`, `chore run`, `chore wait`), and `OverseerCommand` and its
  completion filter with them. Tests that drove a command drive its tool. D020 names the tools alone.
- Open: tool results as JSON rather than the CLI's text (§27, Open).
- Check: `make install-check`'s dry tick passes against the fakes, its overseer acting through the tools.

Status: not started.

## M49. Config per workspace

REQUIREMENTS R19, DESIGN §12 and §18, TRUST_MODEL T7, D016, D053, D066. Asked for by the operator (2026-10-16): most
settings live with the workspace they serve, not in one user file every workspace shares. Needs nothing; taken before
M41, so that the settings page writes the file this milestone adds.

- Why: the user file serves every workspace, but most of its keys belong to one. The queue labels; the authorized
  repliers and trusted reviewers, each in its tracker's identity format; `review.query`; `runtime.setup_cmd` and
  `runtime.pr_skill`; `tracker.mcp_server`; chores; the loop's pacing; and capacity, which each workspace's journal
  already counts on its own. Two `canopy loop`s in two workspaces take `serve.port` from the one file and collide.
- The file: `<state_dir>/config.toml`, the workspace's **private file**, the operator's alone. Layered last: defaults,
  the workspace file, the user file, then the private file, key by key; `[chores]` comes whole from the last file that
  sets it, as today. User-only keys become **private** keys: set in the user file or the private file, never in the
  shared workspace file. §12's table renames the scope and changes no key's.
- The user file becomes optional, for what serves every workspace: the runtime templates, the comment marks, the
  commit trailer, notification sinks. Without it canopy reads the private file alone; without either, the error names
  the private file and `canopy init`. An existing user file keeps working unchanged, so nothing migrates.
- What stays in the user config directory, as files rather than keys: the secrets (`listener-secret`, `slack-webhook`,
  `slack-token`) and the sandbox templates (`sandbox/<role>.json`), which every workspace's runs share.
  `paths.prompt_overrides` still defaults to `prompts/` there.
- No key is held to the user file, the commit trailer and the comment marks included (the operator, 2026-10-16): a
  workspace whose team marks agent work its own way sets its own.
- A `paths.*` value in the private file may be relative, and resolves against the state directory:
  `worker_instructions = "worker-instructions.md"` names `<state_dir>/worker-instructions.md`, private and under the
  provenance check below. Not against the workspace root, which may be a shared checkout, where a file anyone who can
  push may change would choose a prompt (T7). In the user file a `paths.*` value stays absolute or starts with `~`.
- Provenance: D053 checks permissions, not provenance, so a `.canopy/` checked out of a shared workspace repository
  under umask 077 passes it. Today that plants a journal; with the private file it would run commands
  (`runtime.worker_cmd`). So canopy refuses a state directory any of whose paths git tracks: one `git ls-files` at the
  workspace root through `core/hostgit.py` whenever config is loaded, none tracked when the root is in no repository,
  and a refusal when git fails otherwise. That closes the journal's half of the residual too. The private file itself
  is opened without following a symlink and must be a regular file of the operator's, not group or world writable.
- `canopy init` writes the private file instead of the user file, with the labels and the empty trust lists to fill
  in when no user file sets them, and still no key whose default serves. It never overwrites either file.
- Errors name the file: a private key in the workspace file says to set it in the private file, and a validation
  error names the files a key may come from. `loop.reread` reads the private file like any `canopy` command.
- Sandbox: no new path. The private file is under `.canopy/`, which the templates already deny (§24); the canary adds
  it to what a sandboxed run can neither read nor write. An unsandboxed run can write it, as it can the user file
  today: TRUST_MODEL's residual for unsandboxed runs is unchanged.
- Docs, in the PR that builds it, with the operator's approval note: TRUST_MODEL T7 (private keys from the user file
  or the private file, and the provenance control); DESIGN §12 (layers, scopes, the file, the `paths.*` rule) and
  §18 (pool sizes in either file); `README.md` and `docs/GETTING_STARTED.md`, where `canopy init` writes; D016 edited
  in place, and D066 to "Pool sizes are private config".
- Tests with the fakes: a key in the private file wins over the same key in the user file and the workspace file; a
  private key in the workspace file is refused, naming the private file; a private file and no user file runs; with
  neither, the error names `canopy init`; a tracked `.canopy/config.toml`, and a tracked journal, refused in a
  workspace that is a git repository; a symlinked, foreign, or group-writable private file refused; `canopy init`
  writes the private file, not the user file; a reload takes up a change to the private file; two workspaces' private
  files set different `serve.port`s and each loads its own; a relative `paths.*` value in the private file resolves
  under the state directory, and one in the user file is still refused.

Accept: the tests above pass, and `make install-check`, with `canopy init` writing the private file. Live: the
operator moves the keys that belong to one workspace into its private file, leaving the rest in the user file; the
loop there runs as before, and a second workspace with its own private file reads its own labels and port.

Status: in progress. Built 2026-10-16: the private file layered last, private keys in it or the user file, the
provenance check and the private file's own, `canopy init` writing it, and the tests above; `make install-check` passes
with init writing the private file. Left: the live check, the operator's.

## Deferred, with the trigger that would unblock each

- Spend-paced loop (M13): when, with M39 built, overseer spend per day still runs past what the operator will pay
  (`canopy spend` shows it). The cost recording is in; the budget and the pacing rule are what remain.
- PR-scoped work (M14): when the operator keeps fixing CI or answering review on their own hand-written PRs by hand,
  often enough to want canopy to do it.
- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it, or when a repository wants to trust review verdicts.
- Second runtime (Copilot CLI, Claude Code): when a coworker asks. More than a config change: canopy's definitions,
  their permissions, and the D044 guard are written for OpenCode, so a runtime needs its own (REQUIREMENTS N4).
- Slack replies: when the operator wants to answer from Slack. A channel into the journal's conversation (DESIGN
  §22): a Socket Mode bridge running `canopy reply`, or the overseer reading Slack through MCP. Needs a T1
  change.
- Watching a PR (M42's watch mode): when the operator asks canopy to review the same coworker's PR again after each
  push often enough to want it to follow the PR until it merges. DESIGN §21 (Review requests) says what it needs.
- Flaky CI triage (M25): when live use shows `fix-ci` attempts spent on failures the change did not cause. The design
  (DESIGN §23) and the milestone's bullets stand as written.
