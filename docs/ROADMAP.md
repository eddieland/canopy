# canopy roadmap

Milestones are sequential. Each has acceptance criteria that must be met before
the next begins. Acceptance criteria that involve running against real systems
are the operator's job; the agent building the repo stops and asks.

Each milestone ends with a `Status:` line. It is the only place milestone
progress is tracked. Keep it current in the same PR that changes it:

- `Status: not started.` or `Status: in progress.` while work is open.
- When the acceptance criteria are met, replace it with:

  ```text
  Status: done YYYY-MM-DD.
  Learned: what surprised us or turned out different from the plan.
  Next: how that changes later milestones, docs, or open questions.
  ```

  Keep `Learned` and `Next` to a few bullets or sentences each. A lasting
  rationale for a behavior goes in the design (`design/`), next
  to the behavior; it goes in `DECISIONS.md` only when the choice meets that file's bar, something
  every future developer must know. The entry here just points to it. Edit a
  later milestone's bullets directly when `Next` calls for it.

The operator may close a milestone on real use before every live check in its Accept has run. Its `Learned` says
so, and each check still unrun goes to `SCENARIOS.md`, the live checks worth running again.

## M0. Skeleton

- Repository layout per DESIGN §5. `pyproject.toml`, `Makefile`,
  `uv.lock`.
- `canopy --version`, `canopy --help`.
- `make check`: ruff format check, ruff lint, pyrefly strict (D017), pytest. All green on an
  empty test.
- GitHub Actions running `make check` on push and PR.
- `tests/fakes/treehouse` and `tests/fakes/agent` executables with fixtures
  that put them on `PATH`.
- `procs.py` with the single subprocess boundary and a fake-able runner.

Accept: CI green; fakes exercised by at least one test each.

Status: done 2026-09-23.
Learned:

- `tests/canopy/__init__.py` made pytest import the test directory as a package named `canopy`, shadowing
  `src/canopy`. Test directories now have no `__init__.py`. (Superseded by D019: every test directory, the root
  included, has one.)
- treehouse's real shapes, read from its source (commit `1185dc6`): `status --json` is an array whose `name` is a
  string and whose `leased_at` is `null` when unleased; `get --lease --json` also returns `base_branch`; `return` exits
  0 returned, 1 failed or lease mismatch, 3 dirty and not forced. The fake follows these.
- The subprocess boundary is enforced by ruff's banned-api rule rather than by review (D015). A timeout kills the
  child's whole process group, since agent runtimes spawn children of their own.
Next:
- M1's `treehouse.py` should treat `return` exit 3 as distinct from 1: retrying a dirty return loops. canopy always
  passes `--force`, so 3 should not happen; if it does, it is an attention item, not a retry.
- M1 code that runs processes takes a `procs.Runner`. The PATH fakes cover most tests; add an in-process fake runner
  only when a test needs one.

## M1. Read-only tick

- `config.py` (layered repository and user files with per-key scope checks, DESIGN §12), `db.py` with migrations,
  `lock.py`, `treehouse.py`.
- `canopy init` writes the user config if missing (default label `agent-ready-<$USER>`), writes `canopy.toml` if the
  repository has none (asking for the tracker provider), installs agent definitions to `.opencode/agent/` and the
  `tracker-<provider>` skill if one ships, prints required branch protection rules. It never overwrites either config.
- Ticket key validation (`[A-Za-z0-9][A-Za-z0-9_-]*`) in every CLI subcommand that takes a key.
- `canopy tick --dry-run`: lock, migrate, reconcile (no-op on fresh state),
  render the overseer prompt with state block, run `overseer_cmd`, record
  `ticks` and `decisions`. `canopy dispatch` refuses in dry-run.
- `canopy decide` and `canopy attention` CLI subcommands writing to the journal.
- `canopy status` prints the attention list and running workers.
- Canary test resolving DESIGN §16 question 1: an agent definition with a
  denied tool, run under `opencode run`, must be unable to use it. Record the
  outcome in `DECISIONS.md`.

Accept: e2e test against fakes passes. The operator judges real `canopy tick --dry-run` plans sensible for an empty
queue and for a labeled candidate. No dispatches happen.

Status: done 2026-09-24.
Learned:

- Interactive dry runs found plans a live tick would not carry out: a dry-run dispatch now checks the guards (D036), a
  dry-run `ticket set --done` no longer marks a ticket done, and a tick-wide `skip` closes the tick as `skipped`.
  `canopy decisions [TICK]` prints a plan without SQL.
- The first real runs failed on setup, not on the loop: a missing then outdated treehouse, then no GitHub MCP server in
  the overseer's runtime (`mcp_unavailable: github`). With the server configured, tick 5 planned nothing on an empty
  queue and tick 6 planned `dispatch:implement` for eddieland/canopy#21.
- The original acceptance, several days of daily dry runs, measured calendar time on a near-empty queue. It now asks
  for sensible plans on an empty queue and a labeled candidate. M2's live runs, which produce at most a branch and a
  PR for review, test the same judgment against the real guards.
Next:
- The live OpenCode canary is still unrun: both attempts on 2026-09-24 hit an OpenCode server error before the model
  acted, which the test reports as a failed positive control (eddieland/canopy#21). It stays in M2's open items.
- Workers open PRs and comment through the GitHub MCP server, so the worker's runtime needs write scope the overseer's
  read-only server does not give it (TRUST_MODEL T1, T6). Set that up before M2's live run.

## M2. Dispatch implement

- `dispatch.py` guards, lease, detached `_run`.
- `_run`: branch setup, worker execution with timeout, result parsing, push
  verification, unconditional lease return via trap, `runs` update.
- Reconcile: dead pid detection, stale lease return.
- `prompts/worker-implement.md` with the result contract.
- Attention items for `crashed`, `unpushed`, `unknown_result`.
- `.agents/agents/canopy-worker.md` is still a copy of the overseer definition. Write the worker's own permissions
  (edit and bash inside the worktree), with the ordering rules in D021. Needs human approval like any `agents/` change.
- Lift the M1 stopgaps: `canopy tick` without `--dry-run`, and `canopy dispatch` outside a dry run (D020).
- Agent definitions and skills from a directory canopy owns (DESIGN §13, D040): `<state_dir>/runtime/`, the
  `{definitions_dir}` placeholder required in `overseer_cmd` and `worker_cmd`, `canopy init` no longer installing
  definitions, and the canary's precedence check. Before the live run: until then a worktree without a committed
  `.opencode/agent/` runs the worker as OpenCode's default agent, with no denies. With it, the guard against a
  repository defining one of canopy's agents (D044).

Accept: one real ticket goes from label to open PR unattended, with the slot
returned and a correct `runs` row. A killed worker is detected on the next tick
and its slot returned.

Status: done 2026-10-07.
Learned:

- Live, from an empty journal (after the migrations were squashed, #60 and D068), with OpenCode 1.18.32: GH-64 went from
  label to PR #69 unattended, its slot returned and its `runs` row correct. GH-65's `_run` and worker, killed with
  SIGKILL, were `crashed` on the next tick with the slot returned; an authorized reply then resumed its branch to
  PR #70.
- An empty journal rebuilds its view from the tracker, but every comment cursor starts empty, so an old authorized
  comment reads as new: the overseer tried a `resume` that the `no_branch` guard refused.
- The worker's write MCP tools (`create_pull_request`, `add_issue_comment`) cannot set labels. The `agent` label lands
  only when the model happens to use `gh` (on #61 and #70, not on #62 and #69).
Next: give the worker a reliable way to label, or have the harness do it; M3's `needs-human` label depends on the same.

## M3. Fix-CI and resume

- Phases `ci_red`, `changes_requested`, `needs_human`, `human_replied` in the
  overseer prompt.
- `prompts/worker-fix-ci.md`, `prompts/worker-resume.md`.
- Attempt counters, cooldowns, `attempt_limit` attention. Include `implement`: M2 has no attempt limit on it in code,
  only the overseer prompt.
- Lift M2's `not_implemented` refusals for `fix-ci`, `resume`, and `--context` (D029).
- Cursors updated per ticket so ticks are incremental.
- `attention.py` render, diff, `notify.cmd`.

Accept: a PR with a failing check gets exactly one fix attempt per cooldown
window and stops at the limit. A blocked worker's question appears on the
ticket; an authorized reply resumes it; an unauthorized reply does not.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use. Of Accept's live checks, an unauthorized reply not resuming and an authorized one
  resuming were run (2026-10-07); a failing check taken to the limit and a conflicted PR were not. They are SCENARIOS
  S9 to S11.
- A reply from an account not in `authorized_repliers` moves its comment cursor past it, but the overseer checks a
  comment's author when it reads it, so adding an account later authorizes its earlier comments too.
- A worker told to ask first posted one concrete question and added `needs-human` with `gh`, since its MCP tools
  cannot label (M2's Next).
- A bot's review comment (Sourcery) resumed a ticket as `changes_requested`. Bot reviews drive `resume` though they
  never count as approval.
Next: DESIGN §15's three-failure attention item is M10's `loop.failing`.

## M4. Dependencies and stacking

- Blocker detection via the tracker's blocker relations in the overseer prompt (DESIGN §17; Jira links and GitHub
  dependencies via their skills).
- `dispatch --base` and PR base handling in `_run` and the worker prompt. M2 refuses `--base` as `not_implemented`.

Accept: two linked tickets are worked in order; the second's PR targets the
first's branch when the first is open and green.

Status: done 2026-10-07.
Learned:

- Live: GH-67, blocked by GH-66 through GitHub's issue dependencies, waited while GH-66 was being implemented and
  reviewed, and was dispatched with `--base` on GH-66's branch once PR #71 was open and green. Its PR #73 targets that
  branch.
- The overseer's rationale while waiting said the blocker's PR "has not merged", though it stacks on a green PR rather
  than waiting for a merge; the decision was right and its wording was not.
Next: nothing checks what happens to a stacked PR when its base merges (GitHub retargets it if the base branch is
deleted); watch it on #73. The `agent` label was missing on #73 as on #69 (M2's Next).

## M5. Shareable

- `skill/` OpenCode skill for the canopy CLI.
- `uv tool install` path verified from a clean machine.
- README install steps performed by a second person without help. Their
  friction becomes issues.
- License decided and added.

Accept: a coworker runs it against their own ticket.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the second person. A second person installing from README without help,
  and a coworker running canopy on their own ticket, are SCENARIOS S5.
- `uv tool install canopy` was wrong, since the PyPI name is another project's (D046). README installs from git,
  verified from an empty HOME on 2026-09-25, and `tests/install-check.sh` repeats that in CI on Linux and macOS. For a
  machine without a credential for this repository, a version tag releases one executable per platform (D067).
- The skill is for the operator's own agent sessions: `canopy skill` prints it and agent runs do not load it.
Next: the license is proprietary for now. M26 is to prove the sandbox before a second team adopts canopy.

## M6. Workspace

DESIGN §18 and D033. Tickets still touch one repository each; the workspace makes several repositories one queue.

- `canopy-workspace.toml` and `MAP.md`, found by walking up from the current directory like `.git`. The workspace file
  replaces the repository file layer; a repository with no workspace file is a workspace of one, and every existing test
  passes unchanged.
- `canopy init --workspace`: skeleton, `.gitignore`, branch protection rules for every repository in the map.
- `canopy workspace sync`: clone missing repositories into `repos/<name>`, report an `origin` that differs from the map.
- `TREEHOUSE_ROOT` and `--worktree-path` on every treehouse call; reconcile per repository; `repo_missing` attention.
- State under `<workspace>/.canopy/`. The state block lists repositories and summaries.
- `canopy dispatch --repo NAME`, exactly one, with the `unknown_repo` guard.

Accept: a two-repository workspace; one real ticket in each repository goes from label to open PR, from one queue,
with every worktree under the workspace root.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use: canopy runs only from a workspace (#146), and the live sessions have run from
  one. The run Accept describes, one ticket in each of two repositories from one queue, is SCENARIOS S13.
- A workspace's `.canopy/` sits inside what may be a shared checkout, so it, and any definitions snapshot, must be
  private to the operator (D053).
Next: nothing changes for later milestones.

## M7. Joint multi-repo runs

- `ticket_units`, `run_slots`, repeated `--repo`, all-or-nothing leases.
- Desks, per-repository branch setup and push verification, `prs` in the result contract, sibling PR links.
- Per-unit phases, cursors, and attempt counts; attention items about a unit, and `canopy attention --repo`. M6 added
  the `repo` column and items about a repository (`repo_missing`); M7 gives ticket items one.
- Lift the rule of one repository per ticket: `implement` may add a unit. Decide DESIGN §18's open question on
  sequenced PRs (a follow-up after the first merged, or the next repository once the first lands) before designing
  units, since it decides whether a unit can start after the ticket's first PR has merged.
- The desk permission canary, and the TRUST_MODEL T4 and T6 changes with human approval (T7 and §7 changed in M6).

Accept: one real ticket touching two repositories gets two linked PRs from one run. A joint run killed mid-way is
detected on the next tick and all its slots are returned.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without a live joint run. One ticket touching two repositories taken to two
  linked PRs, and a joint run killed mid-way, are SCENARIOS S14.
- The desk canary (OpenCode 1.18.32, 2026-10-07) passed when the workspace root was not a git checkout and failed when
  it was: OpenCode took the enclosing repository as its project and allowed a write by absolute path beside the desk.
  The canary checks both (TRUST_MODEL T4).
Next: run the canary (S1) before a real joint run in a workspace that is a git checkout.

## M8. Split tickets

Needs M4's blocker ordering.

- `dispatch --kind split`, `prompts/worker-split.md`, the `canopy-splitter` agent definition, `children` in the result
  contract validated into `split_children`, the child's recorded repository enforced by dispatch,
  `policy.max_split_attempts`.
- Overseer prompt: split only when an authorized replier asks for it (`--request`), never on its own judgment;
  the `split` phase and `split_unlabeled` attention; a child is a candidate only if its label was added after the split
  run ended, and `split_self_labeled` attention when one was not.
- The TRUST_MODEL T1 and T6 changes for creating tickets, with human approval.

Accept: a real ticket covering two repositories, whose split an authorized replier asked for in a comment, is split into
two linked children, the second blocked by the first, with no queue label on either. Nothing is dispatched for them
until the operator labels them; then they are worked in order, one PR each.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, with no live split. A split needs an authorized replier's comment asking for it,
  and without one a multi-repository ticket stays one ticket. The live split is SCENARIOS S15, after S2 checks that
  OpenCode applies the splitter's name patterns to MCP tools.
- Rebuilt on M7's desks from the draft PR #54, which was written before them.
Next: S2 belongs in the OpenCode canary once someone writes it.

## M9. Chores

DESIGN §19. Needs only M3's attention list and notification; nothing in M4 to M8.

- `[chores.<name>]`, `runtime.chore_cmd`, and `capacity.max_chores` in the user config, user-only. With no chores, or
  `max_chores = 0`, the state block and the overseer's decisions are exactly what they were before M9 (a test).
- Migration: `chore_runs` and `decisions.chore`.
- `canopy chore run` with the `unknown_chore`, `running`, `not_due`, and `chore_capacity` guards; `canopy chore wait`.
- `canopy _chore`: detached run, prompt with the `## Run` section, result contract validated with pydantic; reconcile
  for chore runs.
- The state block's `chores`; findings and `chore_failed` on the attention list and in notifications.
- The overseer prompt's chore paragraph and `canopy chore` in its tool list, the `canopy-chore` agent definition, and
  the TRUST_MODEL T1, T3, T6, T7, and §7 changes, with human approval.
- DESIGN §5, §6, §11, §12, and §14 updated for chores, and §19's planned note removed.

Accept: a real build-health chore runs for several working days. The journal shows it never started sooner than
`every_minutes` after its previous run, and the `decisions` table shows the overseer following `when`. Its findings
reach the attention list and are notified once, and each disappears after a run that no longer reports it. A chore run
killed mid-way is detected on the next tick as `crashed` with a `chore_failed` item. Deleting the chore from the config
clears its items at the next tick.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the several working days of a build-health chore, which are SCENARIOS
  S22. `examples/chores/build-health.md` is a prompt to start one from.
- Building it settled DESIGN §19's open question: a chore may list the workspaces it runs in. A chore's `days` and
  `hours` became a guard in code, so `when` holds only judgment.
- Writing the first prompt asked for `canopy chore try`, which runs a chore by hand and records nothing, and
  `canopy reply chore:NAME`, a note the chore's next runs follow.
Next: M23 answers a chore's finding from the browser.

## M10. Notification sinks

DESIGN §20 and D035. Needs only M3's attention list and notification; nothing in M4 to M9, so it can be taken sooner
if the operator asks.

- `[notify.sinks.<name>]` (`cmd`, `format`, `events`, `digest_every_minutes`), user-only, and `notify.cmd` as the
  `default` shorthand. The existing notify tests pass unchanged.
- Migration: `notify_events`, `notify_sinks`, and `notifications.sink`, with existing rows assigned to `default` so an
  upgrade with `notify.cmd` set re-notifies nothing (a test).
- The `notify` package: events recorded by dispatch, run close, and publish through an outbox in `core`; per-sink
  delivery with cursors, bounds, and pruning; the digest; the `text` and `json` formats.
- `loop.failing` after three consecutive failed ticks, the notification half of DESIGN §15's three-failure item.
- `canopy notify test`, and a line per sink in `canopy status`.
- The uv workspace, with the Slack sink as its first member (`packages/canopy-notify-slack`, D041) and the
  `canopy-notify-slack` script in canopy's own install, tested against a local HTTP server; the `TID251` ban on network
  modules in `src/canopy`, and the layer test refusing imports of the sink. One `uv tool install` still installs
  both (`tests/install-check.sh`, M5's clean-machine check).
- A desktop sink (`notify-send` on Linux, `osascript` on macOS) ships before Slack: the operator wants the desktop
  first, and a wrapper script of their own is the custom layer REQUIREMENTS H2 rules out (N2). DESIGN §20 gains it.
- The TRUST_MODEL T2, T6, and §7 changes, with human approval.
- DESIGN §5, §6, §11, §12, and §14 updated, and §20's planned note removed. README's daily surface names sinks.

Accept: before Slack, the desktop sink shows one real ticket's blocked question and an attention item as desktop
notifications on the operator's machine, once each. With the Slack sink on a real channel, one real ticket's dispatch, a
blocked worker's question, and its PR each reach the channel once, and an attention item is posted once when it opens
and once when it resolves. With the webhook file removed, Slack fails for several ticks while a second sink keeps
delivering and reports `loop.sink_failing`; restoring the file delivers what was missed in one message. A digest arrives
on its interval, including a quiet one.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use. The desktop sink and the Slack sink on a real channel, as Accept describes them,
  are SCENARIOS S24 and S25. The Slack sink gained a bot token, its own name and emoji, and Block Kit (2026-10-12).
- DESIGN §15's three-failure attention item is not built: the attention list is the latest `ok` tick's, so
  `loop.failing` is its notification half and the whole of it.
- The repository is a uv workspace, the Slack sink its first member; one `uv tool install` installs canopy and both
  sinks (`tests/install-check.sh`).
Next: nothing changes for later milestones.

## M11. Reviews

DESIGN §21. Needs M3's `resume`, cursors, and attention list; nothing in M4 to M10, so it can be taken sooner
if the operator asks. If M10 has landed, add the `reviews` event group; if not, M10 adds it.

- `[review]`, `runtime.review_cmd`, `runtime.review_timeout_minutes`, `capacity.max_reviews`, and
  `capacity.max_reviews_per_day`, user-only; `policy.max_reviews_per_pr`, shared and tighten-only. With no `[review]`
  table, or `max_reviews = 0`, the state block and the overseer's decisions are exactly what they were before M11 (a
  test).
- Migration: `review_runs` and `decisions.pr`.
- `canopy review run` with its guards, `canopy review wait`, and `canopy attention --pr`.
- `canopy _review`: lease, detached checkout at the commit, the reviewer run outside the checkout, the result
  contract validated with pydantic, unconditional slot return; reconcile for review runs.
- `prompts/reviewer.md`, the `canopy-reviewer` agent definition installed into the operator's runtime config, and a
  canary: the reviewer can read the checkout and nothing else outside its working directory, and cannot call a denied
  MCP tool. The reviewer posts nothing (D114): its findings stay in the journal.
- `canopy dispatch --kind resume --review-run ID`, which hands a worker a review's findings from the journal, and
  `canopy review show`, where the operator reads reviews.
- The overseer prompt: the `review_pending` and `review_findings` phases and the `review.query` paragraph (this
  repository's PRs only), with human approval.
- The TRUST_MODEL T1, T3 to T7, §6, and §7 changes, with human approval.
- DESIGN §5, §6, §7, §11, §12, §13, and §14 updated, and §21's planned note removed.

Accept: with `agent_prs` on, one real ticket's PR is reviewed once its checks pass. A finding goes back through
`resume --review-run`, the new commit is reviewed again, and the ticket reaches `needs_reviewer`, with nothing of the
review on the PR. With a `review.query` that matches the operator's own hand-written PR, each new head commit gets
exactly one review in `canopy review show` and nothing happens to the PR: no comment, no push, no ticket, no GitHub
review. A review run killed
mid-way is detected on the next tick, its slot returned, and `review_failed` raised. A PR at its limit gets no more
reviews.

Status: in progress. Code, fakes-based tests (`tests/canopy/test_reviews.py`), and docs are in. Checked live on
2026-10-07 with OpenCode 1.18.32: the reviewer canary passes, and with `agent_prs` on, PR #69 got one identified
`clean` comment at its commit and no GitHub review. Accept's other live checks are SCENARIOS S19 to S21. What keeps it
open: on 2026-10-12 all seven review runs of a live session ended `unknown` within about 15 seconds, the reviewer's
last line not a valid result, and the overseer's retries for them cost $2.21 (MEASUREMENTS 2026-10-12, F4). Not
diagnosed yet; next is a failed review run's log. On 2026-10-13 the operator decided that reviews post nothing on the
PR (D114): the comment, its marker, and `review_unposted` are gone, the reviewer needs no write tool (so the
`add_issue_comment` grant the 2026-10-07 check needed is moot), and findings reach a worker through `--review-run` and
the operator through `canopy review show`.

## M12. The loop

DESIGN §6, D042, and D043. Needs nothing after M1; taken out of order on request (2026-09-24).

- `canopy loop` with `--dry-run`, `--every`, and `--ticks`; `loop.interval_minutes`, user-only.
- `<state_dir>/loop.lock`; SIGINT and SIGTERM stop after the current tick, and a second one aborts it.
- rich output: a block per tick, with a spinner and a countdown on a terminal and plain text off one.
- README's install step and daily surface use the loop instead of cron or launchd.

Accept: fakes-based tests of the wait, both kinds of stop, the lock, and a tick that raises
(`tests/canopy/test_loop.py`). The operator runs `canopy loop --dry-run` against the real queue for a working session,
finds each tick's block legible, and stops it with Ctrl-C both during a tick and during the wait.

Status: done 2026-10-13.
Learned:

- Checked live on 2026-10-07: `canopy loop --every 3` ran 6 ticks against the real queue, dispatching, reviewing, and
  resuming; Ctrl-C during a tick stopped it when that tick finished, and Ctrl-C during the wait stopped it at once
  (exit 0). The loop has been the operator's daily surface since. A working session's legibility is SCENARIOS S26.
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
and the web UI's attention page (the last 24 hours and 30 days) show it. A tick's cost is its overseer's alone, so a
worker's is not counted against the tick that dispatched it. An `overseer_cmd`, `review_cmd`, or chore `cmd` in a user
file from before needs `--format json` added. What keeps it open: the budget and the pacing rule are not designed.

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
continue a session, and workers against OpenCode's server.

## M16. Worktree setup for large monorepos

REQUIREMENTS R10, DESIGN §9 and §18, D033. Needs M2. Taken on request (2026-10-09).

- Where pools live: no pool root of their own. A fast disk takes the whole workspace, for reasons DESIGN §18 gives:
  git keeps each worktree's files in its clone, and treehouse pools by repository and remote URL, so a root every
  workspace shared would merge their pools (D033).
- `paths.worktree_include`, user-only: a personal `.worktreeinclude`, passed on every `treehouse get` as
  `--include-file`. It replaces the committed manifest, since treehouse reads one; a missing file is `no_slot`.
- `runtime.setup_cmd` and `runtime.setup_timeout_minutes`, user-only: run in each slot of a worker run once `_run`
  has checked out the run's branch, and a failure or timeout ends the run `crashed` before its worker starts.
- Bazel: an opt-in canary that a worker reads through `bazel-out/`, `bazel-bin/`, and `bazel-testlogs/` and is refused
  the output base by its own path; a `.bazelrc` recipe for a shared disk and repository cache in `docs/BAZEL.md`; an idle
  slot's server ends by `startup --max_idle_secs`, not when the slot is returned.

Accept: in a Bazel repository, with the recipe in the operator's `~/.bazelrc`, a personal manifest that seeds a
gitignored file, and a `setup_cmd` that runs `bazel fetch` on the run's branch, a real `implement` run's worker finds
the seeded file in its slot and its `bazel test` hits the disk cache another slot filled. A `setup_cmd` that exits 1
ends a real run `crashed` with no worker started and its slot returned. The Bazel canary passes under the pinned
OpenCode. A slot's Bazel server exits once idle for `--max_idle_secs` after its run.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the Bazel run Accept describes or the Bazel canary's first real run.
  They are SCENARIOS S7 and S1.
- Pools get no root of their own: a fast disk takes the whole workspace (DESIGN §18, D033).
Next: run S1 before relying on a worker's reads through Bazel's links.

## M17. Declared repositories and pools

DESIGN §18 and D066. Needs M6. Taken on request (2026-10-07).

- `capacity.slots_per_repo` and `[capacity.repo_slots]`, user-only; with neither, every pool behaves as before (the
  existing tests pass unchanged).
- Leases in a workspace stay within the declared size: dispatch and reviews refuse `no_slot` rather than grow a pool,
  and a slot treehouse makes past the size anyway is returned and destroyed.
- `canopy workspace sync` converges: fills each pool by leasing as `canopy-sync` and returning, trims idle slots with
  treehouse's unforced `destroy`, and removes clones the map dropped when nothing in them would be lost. `--dry-run`.
  It holds the tick lock.
- `canopy workspace add [NAME=]URL...`, and the same URLs on `canopy init --workspace`: append them to the map,
  then sync.
- The fake treehouse gains `destroy`.

Accept: `canopy init --workspace` with two real clone URLs, in an empty directory with sizes declared, clones both and
makes each pool its size, and `post_create` runs
in the new slots during sync, not during the first run. Lowering a size removes idle slots and never a leased one; a
dispatch into a full pool is refused `no_slot`. Dropping a repository from the map removes its clone and slots, and a
clone with an unpushed commit is kept and reported.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the run Accept describes, which is SCENARIOS S6.
- treehouse's `max_trees` (16 by default) must be at least the largest declared size; canopy cannot set it.
Next: nothing changes for later milestones.

## M18. Private tickets

REQUIREMENTS R11, DESIGN §22, D072, D075. Needs M3. Sketch only; the design comes first.

- A `messages` table, in a new migration that backfills ended runs' reports and questions. `_run` records each run's
  report and question there, for every ticket.
- `canopy start`, `stop` (with `--now`, and the `stopped` run status), `reply`, and `show` for ticket references, and
  started subjects in `canopy status`, writing through `core/conversation.py`, with `start`, `stop`, and `reply`
  refusing inside canopy's runs (`CANOPY_TICK_ID`,
  and `CANOPY_RUN_ID`, which `_run`, `_chore`, and `_review` set).
- `canopy dispatch` needs no `--label` for a started ticket, checking the start record in code, and refuses a private
  `split`.
- The private worker prompt variant and `canopy-worker-private`, allowing only the tracker's read tools by name and
  denying the rest of its server and the known tracker CLIs in bash; verify OpenCode enforces that wildcard deny.
- `tracker.read_tools`, with defaults for Atlassian's remote MCP and GitHub's MCP server named from their tool lists;
  `canopy start` refuses `no_read_tools` without them. D044's guard refuses a private run whose worktree config names
  the tracker's tools.
- `dispatch` picks the private worker in code for a started ticket and refuses a stopped one; `stop` marks the
  record stopped rather than deleting it; `start`, `stop`, and `dispatch` serialize on it, and `_run` re-reads it
  before the worker starts.
- The overseer: private tickets in the state block with their new operator messages, and their phases read from them.
  A prompt change, which needs the operator's approval.
- `awaiting_reply` on the attention list, raised by the harness; `run.ended` carries the question's message id.
- The loop's wait ends early on an operator message (D073).
- TRUST_MODEL T1, T6, and the overseer prompt as DESIGN §22 proposes, with the operator's approval note. Sandboxing
  is not a prerequisite: the operator accepted T1's forged-reply residual (D076).

Accept: a fakes-based test: a started ticket with no label is dispatched to the private worker definition, the fake
worker ends `blocked`, the question is on the attention list and in `canopy show`, `canopy reply` ends
the loop's wait, and the `resume` prompt carries the reply. Live, the operator starts a real ticket privately, answers a
question from the CLI, the PR lands for review, and the ticket shows nothing canopy wrote.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use: all five tickets of the first live session were started privately from the web UI
  (MEASUREMENTS 2026-10-12). The full run Accept describes is SCENARIOS S16. OpenCode's wildcard deny with named allows
  was confirmed in its source (1.18.35), not in a run; that is S3.
- With Atlassian's server, `?tools=all` in its URL lets a private worker read comments; without it only the primary
  read tools are reachable.
Next: a start does not end the loop's wait (MEASUREMENTS F3); M28 takes it.

## M19. Tracker comments in the journal

REQUIREMENTS R12, DESIGN §22, D072. Needs M18. Sketch only; the design comes first.

- `canopy mirror`, overseer-only, bounded, idempotent on the subject and comment id.
- The overseer prompt mirrors every comment past a subject's own mirror cursor, worker-marked ones (D069) included;
  the cursor starts empty, so a subject's history is mirrored once. A
  prompt change, which needs the operator's approval.
- `canopy show REF` shows mirrored comments with their source, for public tickets as for private ones.
- Open: whether PR review comments join the journal here or later.

Accept: fakes-based tests of the command's bounds, refusals, and idempotence. Live, a working session's decisions show
each new comment mirrored once, and M13's spend records show what mirroring adds to a tick.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the working session Accept describes, which is SCENARIOS S17. That
  OpenCode's `canopy *` rule admits a heredoc command was read in its source (1.18.35), not seen in a run; that is S4.
- The open question is settled: PR review comments join the journal with PR subjects, in M14.
Next: nothing changes for later milestones.

## M20. Web UI

REQUIREMENTS N1, DESIGN §22, D055, D073, D074, D079. Needs M18; M19 makes it one inbox. Sketch only; the design comes
first.

- `src/canopy/serve/`, run by `canopy loop` from a thread; `--no-serve`; `serve.enabled`, `serve.bind`, `serve.port`,
  all user-only. FastAPI on uvicorn (D074), imported nowhere else, serving the app built from `ui/` (D079).
- TRUST_MODEL T8's bind and secret rules; escaping of every journal value; a per-session token on writes.
- Pages for the attention list, running and recent runs, and tickets with their conversations; reply, start, and
  stop, through the same functions as the CLI. Forget too, behind the ticket's key typed out (§22). Taken on request
  (2026-10-12).
- A worktrees page: each pool's slots from `treehouse status --json`, read when the page asks and every 30 seconds
  while it is open, with the running run or review holding each. Taken on request (2026-10-08).
- The release binary (D067) bundles the built UI and builds on every platform it ships for.
- Settled: the browser gets the listener secret from the operator's sign-in, once; M15's session attach joins
  the UI once M15 runs workers against OpenCode's server.

Accept: written with the design, before work starts, and like every milestone's, a real run of what it delivers.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use: the first live session was driven from the web UI on loopback (MEASUREMENTS
  2026-10-12). Serving on a private address, and the worktrees page reading the real pools, are SCENARIOS S28.
- The design settled both open questions: the browser signs in once with the listener secret and keeps a cookie signed
  with it, and M15's session attach waits on M15's server.
- The list lagging a reply read as a bug, so a reply no `ok` tick has read yet says so, and its answered question is
  marked until the next tick drops it.
Next: M15's session attach joins the UI once M15 runs workers against OpenCode's server.

## M21. Idle-paced loop

DESIGN §6 (Idle pacing). Needs M12. Independent of M13: cost bounds spend, idleness says whether a tick was worth
running, and the loop waits the longer of the two.

- `repeat.pace` decides whether the tick was idle from the journal and doubles the wait per idle tick in a row, from
  `--every` or `loop.interval_minutes` up to `loop.idle_max_minutes` (user-only, default 120) and never below `base`,
  ending no later than the earliest `fix-ci` cooldown end or chore `due_at` still ahead.
- The wait also ends early when a run, chore run, or review run ends after the tick rendered its state, with the
  operator message's one-minute floor.
- The idle count and the chosen wait in the loop's per-tick block and in its log lines.
- Config validation: `loop.idle_max_minutes` at least `loop.interval_minutes`; a cap not above `base` turns idle
  pacing off.
- Fakes-based tests: idle ticks lengthen the wait to the cap; each condition that is not idle resets it; a cooldown end
  and a chore's `due_at` shorten it, and one already past does not; a run ending during or after the tick, and an
  operator message, end it early; a cap not above `base`, from config or `--every`, keeps today's pacing.
- Open: whether `--every` should turn idle pacing off for a watched session, or keep it from a shorter base.

Accept: the tests above pass with the fakes. The operator leaves `canopy loop` running overnight against the real
queue and finds, in the loop's output and log, waits reaching the cap after a quiet evening and back at
`loop.interval_minutes` within one tick of the first morning activity, and each run's end followed by a tick within
a couple of minutes.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the overnight run, which is SCENARIOS S27. The two-hour session on
  2026-10-12 could not test it: after its first ticks, every tick followed a run ending, an operator message, or a
  failed overseer, each not idle by design. It found what can keep a quiet night from backing off: ticks that fail
  after doing their work, and overseer churn (MEASUREMENTS 2026-10-12, F2, F5, F7), which M28 takes.
- Two refinements of DESIGN's sketch: a ticket's `skip` and the chore refusals that lift by themselves
  (`chore_capacity`, `not_due`, `outside_hours`) count as quiet, and idle pacing off is all of it off, gates and run
  wakes included.
- The open bullet is settled as DESIGN has it: a shorter `--every` keeps idle pacing from that base.
Next: M29 waits on S27's overnight run and its re-measurement.

## M22. Trusted reviewers

REQUIREMENTS R13, DESIGN §7, D089. Needs M3's `resume` and M20's reply. Taken on the operator's request (2026-10-08).

- `trust.trusted_reviewers`, user-only and empty by default, with `canopy:review` for canopy's own reviewer.
- `untrusted_review` in the overseer's phase table and on the attention list; the `review` cursor waits on it.
- `canopy reply` and the web UI's reply on a public ticket the journal has, as the operator's go-ahead: in the state
  block under `operator`, and in the public `resume` prompt as `{{OPERATOR_MESSAGES}}`.
- Resume workers told who is trusted (`{{TRUSTED_REVIEWERS}}`), addressing anyone else's comments only as an operator
  message says.
- Fakes-based tests: the config, the state block's trusted list and operator messages, the cursor, and the resume
  prompt with and without a go-ahead.
- Every public worker hears the operator (D093): `{{OPERATOR_MESSAGES}}` in the `implement` and `fix-ci` prompts too,
  with the workers' questions a reply answers; an override without it refused once the ticket has a message; a reply
  on a ticket with no branch rides its `implement`, and one after a failed run is "try again".

Accept: the tests above pass with the fakes. Live: a review bot's comment on a loop PR waits as `untrusted_review`
without a dispatch; a reply from the web UI resumes it with the reply as the worker's instruction and nothing of it on
the ticket; a listed reviewer's comment resumes as before.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the live run Accept describes, which is SCENARIOS S18.
- D093 followed: every public worker hears the operator, with `{{OPERATOR_MESSAGES}}` in the `implement` and `fix-ci`
  prompts too.
Next: nothing changes for later milestones.

## M23. Chores in the web UI

REQUIREMENTS N1 and C5, DESIGN §19 and §22. Needs M9 and M20. Asked for by the operator (2026-10-09): a chore's
finding reaches the web UI's attention list, but the browser can neither show the chore nor answer it, so a finding
sends the operator back to the terminal.

- The design first, in DESIGN §22 and `ui/DESIGN.md`: the routes, the pages, and where a chore's attention item leads.
- `GET /chores`: each configured chore as `canopy status` lists it: running, or its latest run and next due time; its
  `days` and `hours`; its open findings.
- `GET /chores/{name}`: what `canopy show chore:NAME` prints: open findings, the latest runs with status, session, and
  cost, and the operator's notes. 404 for a chore not defined for this workspace.
- `POST /chores/{name}/replies`: `conversation.reply` with channel `web`, as `canopy reply chore:NAME`, behind the same
  session token and `Origin` check as the ticket writes. Nothing that runs a chore: the overseer decides when one runs
  (§19), and `canopy chore try` stays in the CLI.
- A chores page in the navigation and a page per chore. A chore's attention item opens the chore's notes and a note
  form beside the list, as a ticket's opens its conversation.
- Tests over the mock journal: the routes, the 404, a note recorded with channel `web` that the chore's next prompt
  carries; a Playwright test answering a chore's finding from the attention list.

Accept: the tests above pass. Live: with M9's build-health chore running, the operator answers one of its findings
from the browser, and the chore's next run's prompt carries the note.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the live run Accept describes, which is SCENARIOS S23 after S22.
- The chores' journal view moved down to `core` (`chore_view`, `chore_window`, `chore_result`) so the server, a
  feature, can read it as the CLI does. A note no run has started since says it waits for the next run.
Next: nothing changes for later milestones.

## M24. Ticks in the web UI

REQUIREMENTS N1 and C5, DESIGN §6 and §22. Needs M20. Asked for by the operator (2026-10-09): the `decisions` table is
the overseer's reasons for what the loop did and the evaluation corpus for prompt changes, and only `canopy decisions`
shows it.

- The design first, in DESIGN §22 and `ui/DESIGN.md`: the routes and the pages.
- `GET /ticks`: the latest ticks, newest first, at most 50: status, dry run, start and end, summary, the overseer's
  session and cost, and how many decisions.
- `GET /ticks/{id}`: what `canopy decisions ID` prints: the tick and its decisions, each with its subject (ticket,
  unit, repository, chore, or PR), action, and rationale. 404 for no such tick.
- A ticks page and a page per tick; the header's latest tick links to its page. A ticket's page lists the latest
  decisions about it across ticks, so "why has the loop not picked this up" is answered where the ticket is.
- Reads only. A rationale is the overseer's text: untrusted, rendered as text, cut as `canopy decisions` cuts it.
- Tests over the mock journal: the routes, the 404, a ticket's decisions across ticks; a Playwright test from the
  header's tick to its decisions.
- Settled: a tick's page names the overseer's output (`ticks/<id>.log`) and does not serve it; M27 serves its
  session's events.

Accept: the tests above pass. Live: after a day of `canopy loop` on the real queue, the operator finds in the browser
why a ticket was or was not dispatched in a given tick, and it matches `canopy decisions`.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use; the day-long check Accept describes is SCENARIOS S29.
- The latest tick carries how many decisions it recorded, so the stream sends it as a running tick records them and
  the open pages follow. A unit's decisions name its repository after the ticket, which `canopy decisions` leaves out.
Next: nothing changes for later milestones.

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
  killed after the worker leaves cleanup to reconcile, which refuses a slot whose link changed.

Accept: the tests above pass, and the canary passes in CI on Linux. Live: the canary passes on the operator's Linux and
macOS machines, then a day of `canopy loop` with sandboxed workers pushes and opens PRs as before, and a worker run that
tries to read `~/.ssh` or write `~/.config/canopy` is refused.

Status: not started.

## M27. Session transcripts in the web UI

REQUIREMENTS R6 and N1, DESIGN §13 and §22. Needs M20 and M24. Asked for by the operator (2026-10-12): to explore
what an OpenCode session did, its tool calls above all, in the browser rather than through `opencode export`.

- `core/transcript.py` reads a session's events back from the file they were printed to, the run's log or the tick's
  output: only the session the journal recorded, each event validated (D026), control characters dropped, and bounded
  (32 MiB of the file, 2000 entries, 2 million characters, 20,000 per text and 5,000 per tool input). A symlink, a
  FIFO, or anything else that is not a regular file is not read.
- `GET /runs/{id}`, `GET /runs/{id}/transcript`, and `GET /ticks/{id}/transcript`, 404 for no such run or tick. Reads
  only, and never on the stream.
- A run's page, opened from its id in any list of runs, and the tick page's transcript under its decisions: the agent's
  text, each tool call opening to its input and output, each model call's cost, and the runtime's errors.
- A run's log and a tick's output are shown from the workspace root, as worktrees are.
- TRUST_MODEL T8: the listener serves agent output from a file, which holds whatever a tool read.
- Tests: the reader against OpenCode's event shapes, the routes over the mock journal, and Playwright from the runs page
  to a run's tool calls.

Accept: the tests above pass. Live: after a day of `canopy loop`, the operator opens a worker run's page and a tick's,
and finds the tool calls `opencode export <id>` shows for the same session, and a failed run's runtime error.

Status: done 2026-10-13.
Learned:

- Closed on the operator's real use, without the check Accept describes, which is SCENARIOS S30.
- OpenCode 1.19.0's `run --format json` prints `text`, `reasoning` (only with `--thinking`), `tool_use` (once a call
  completes or fails), `step_start`, `step_finish`, and `error`, each with `sessionID` and a `timestamp` in
  milliseconds.
- A running run's events reach its log only when it ends, because `procs.run` captures stdout whole. A subagent
  (`task`) shows as one tool call whose output is its answer; its own session is not in the log.
Next: watching a run live needs the worker's stdout streamed to its log.

## M28. Overseer reliability from the first live session

MEASUREMENTS 2026-10-12, F1 to F3 and F5. Needs M12 and M21's code. Asked for by the operator (2026-10-12): a quarter
of the first session's overseer spend bought nothing, mostly for reasons a check in code can catch, and the same
reasons keep idle pacing from counting a quiet tick as idle.

- The overseer's `canopy` works before the overseer is paid for. The tick either puts this canopy's own launcher
  first on the overseer's PATH, or checks, through `procs`, that `canopy --version` runs from the overseer's
  environment. When it cannot, the tick closes without running the overseer, with a status of its own, and raises an
  attention item saying why. Settle which in DESIGN §6; the release launcher (`SCIE_BOOT`) and a source install both
  have to work.
- `tick complete`: the overseer prompt's last step made harder to miss, with the operator's approval note in the PR.
  Open: whether the harness should also accept a run that exited 0, recorded its decisions, and printed the done line
  on its own line before a summary. That loosens DESIGN §6's contract, so it is a design change, not a prompt one.
- A ticket started or stopped from the web UI or the CLI (`starts`) ends the loop's wait as an operator message does,
  with the same one-minute floor, and counts against idleness the same way. DESIGN §6 (The loop, Idle pacing) and §22
  (Waking the loop).
- Churn, measured before it is fixed: the loop's `loop waits` log line says when a tick changed a phase or the
  attention list with no run, message, start, or gate since the tick before. Prompt changes follow only when the
  `decisions` table shows a pattern.
- Tests with the fakes: a missing or failing `canopy` closes the tick without starting the fake overseer; a start ends
  the wait; a fake overseer that prints a summary after `tick complete` is handled as the contract settles.

Accept: the tests above pass. Live: a working session re-measured (MEASUREMENTS) has no tick that ran the overseer
without a working `canopy`, no `overseer_failed` tick that recorded its decisions, and every web-UI start picked up
within about a minute.

Status: not started.

## M29. Probe-gated overseer

MEASUREMENTS 2026-10-12, F7 to F10; D003's revisit. Needs M28 and M21's overnight run (SCENARIOS S27). Sketch only;
the design comes first. Taken only if a re-measurement after both shows that the steady state's spend or its latency
(up to `loop.idle_max_minutes` on a teammate's comment or a CI result) is still worth the trust change. The first
session says a gate saves little while the operator is active (F8).

- A `probe_cmd` command template, run through `procs`, prints one JSON line of fingerprints. Per ticket: updated
  time, latest comment id, labels, open or closed, and the keys the tracker query returns. Per PR: head SHA, the
  result of each named CI context, latest review or review-comment id, mergeable, draft, and open, merged, or closed.
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
- An example GitHub probe: one GraphQL query through `gh` for every open PR the journal knows. A Jira one if the
  operator's setup allows it without a new token.
- TRUST_MODEL T2 with the operator's approval note, D003, and DESIGN §6 and §12.
- Open: how the probe learns which subjects to watch (argv, stdin, or reading nothing and listing by query); how often
  it polls (2 minutes matched the first session's median latency, F10); whether a cold-cache overseer run after a
  long gap changes the arithmetic (MEASUREMENTS: Spend).

Accept: written with the design, before work starts.

Status: not started.

## M30. Fewer re-reads per tick

MEASUREMENTS 2026-10-12, F6. Needs M29's probe. Sketch only; the design comes first. Re-reading the tracker and GitHub
was 29% of every tick's cost, productive ticks included, and most of it was things that had not changed.

- The probe's facts in the state block: per unit, head SHA, named CI results, latest review id, mergeable, and draft;
  per ticket, labels, state, and latest comment id with its author's account id. Ids, states, and account ids only; no
  comment, review, or PR text enters the state block.
- The overseer prompt reads a PR or a ticket in full only when a fact changed since its cursor, with the operator's
  approval note in the PR.
- The provider skill reaches the overseer without a tool call on every tick, inside the cached part of its prompt.
- TRUST_MODEL T1 and T2: what canopy now asserts about the world, and that the tracker and GitHub stay the source of
  authority (DESIGN §22), with the operator's approval note.
- Open: whether canopy should then check `trust.authorized_repliers` against comment authors in code, which would close
  D003's "cannot verify who wrote a comment".

Accept: written with the design, before work starts. Live, once built: a re-measurement shows tool-result tokens per
tick at half the first session's (about 19k) or less, with no action missed.

Status: not started.

## M31. Search in the web UI

REQUIREMENTS N1, DESIGN §22. Needs M20 and M27. Asked for by the operator (2026-10-13): one box that finds a ticket,
or the run or tick that said something, without knowing which page holds it. Reasonably efficient, and nothing that
cannot be done well.

- `core/search.py` reads the journal on each request: tickets by key, branch, and their units' branches and PRs (a
  branch's slug is the ticket title's words); every message, a run's report and question among them; chore runs'
  summaries and findings; decisions' rationales; and ticks' summaries. Every word of the query, as a substring, in one
  field; at most 20 hits a source, newest first, each with a one-line snippet.
- `GET /search?q=`, 422 for a query under 2 or over 200 characters or of more than 8 words. Reads only, not on the
  stream.
- A search box atop the nav, focused by `/`, opening `/search?q=` as the operator types: hits grouped by source, the
  query's words marked in each snippet, each hit linking to the page that holds it.
- Not searched, each said in DESIGN §22 with why: ticket titles (the journal holds none), transcripts (a log per run,
  up to 32 MiB, read whole), and review runs (no page shows them).
- Tests: the search over a real journal (each source, the bounds, LIKE's wildcards taken literally), the route over
  the mock journal, and Playwright from the box to a hit's page.

Accept: the tests above pass. Live: on a journal from a week of `canopy loop`, the operator finds a ticket by a word
of its title and a run by a phrase from its summary, and a search nothing matches answers in under a second.

Status: in progress. Code, tests, and docs are in (2026-10-13). Measured before choosing a plain scan: SQLite's `LIKE`
reads about 1.6 ms per MB of text when nothing matches (56 MB of messages in 90 ms), and stops at the limit when
hits are many, so an FTS5 index, with its migration and triggers, waits until a real journal is slow. Waiting on the
operator: the live search Accept describes.

## M32. Shadow PR reviews in the web UI

REQUIREMENTS N1, DESIGN §21 and §22. Needs M11 and M20. Asked for by the operator (2026-10-13): canopy's reviews stay
off the PR (D114), so canopy shows them itself, as a PR review of its own that only the operator sees.

- A PR's page: each review run at its commit, the verdict, and each finding with its detail, anchored on the diff at
  its `path:line` where the line is in the diff.
- What the operator does from there, such as dismissing a finding or sending some findings to a worker, through the
  journal's existing channels (`canopy reply`, the overseer), never a write to the PR.
- Open: whether the diff is read by the harness (`git diff` of the review's commit in a slot) or kept from the review
  run, and how a finding is tracked across commits.

Status: not started.

## Deferred, with the trigger that would unblock each

- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it, or when a repository wants to trust review verdicts.
- Second runtime (Copilot CLI, Claude Code): when a coworker asks. More than a config change: canopy's definitions,
  their permissions, and the D044 guard are written for OpenCode, so a runtime needs its own (REQUIREMENTS N4).
- Slack replies: when the operator wants to answer from Slack. A channel into the journal's conversation (DESIGN
  §22): a Socket Mode bridge running `canopy reply`, or the overseer reading Slack through MCP. Needs a T1
  change.
