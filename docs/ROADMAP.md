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

  Keep `Learned` and `Next` to a few bullets or sentences each. Anything that
  deserves a lasting rationale goes in `DECISIONS.md`. The entry here just
  points to it. Edit a later milestone's bullets directly when `Next`
  calls for it.

## M0. Skeleton

- Repository layout per `DESIGN.md` §5. `pyproject.toml`, `Makefile`,
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
  dry-run `ticket set --done` no longer marks a ticket done, and a tick-wide `skip` closes the tick as `skipped` (D037).
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
  only the overseer prompt (D028).
- Lift M2's `not_implemented` refusals for `fix-ci`, `resume`, and `--context` (D029).
- Cursors updated per ticket so ticks are incremental.
- `attention.py` render, diff, `notify.cmd`.

Accept: a PR with a failing check gets exactly one fix attempt per cooldown
window and stops at the limit. A blocked worker's question appears on the
ticket; an authorized reply resumes it; an unauthorized reply does not.

Status: in progress. Code, fakes-based tests (`tests/canopy/test_fix_ci_resume.py`, `tests/canopy/test_attention.py`),
docs, and D030 to D032 are in. Checked live on 2026-10-07:

- A reply from an account not in `authorized_repliers` did not resume GH-65, and its comment cursor moved past it; with
  the account added back, the same comment resumed it. The overseer checks a comment's author when it reads it, so
  adding an account authorizes its earlier comments too.
- GH-68's worker, told by the ticket to ask first, posted one concrete question, added `needs-human` with `gh` (its MCP
  tools cannot label; see M2), and reported `blocked`. One tick earlier the overseer had raised `needs_author` itself
  instead of dispatching; it dispatched on the next.
- A review comment on PR #71 from a bot (Sourcery) was classified as a concrete change and resumed GH-66 as
  `changes_requested`. Bot reviews drive `resume` though they never count as approval.

Waiting on the operator: an authorized answer on GH-68 that resumes it, a real PR with a failing check taken
through fix-ci to the limit, and a PR that conflicts with its base taken through `conflicted` (D070) to a clean merge.
DESIGN §15's three-failure attention item is M10's `loop.failing`.

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

Status: in progress. The skill, the install check, and the license are in (D046, D047). The skill is for the
operator's own agent sessions: `canopy skill` prints it and agent runs do not load it. `uv tool install canopy` was
wrong, since the PyPI name is another project's; README now installs from git, verified from an empty HOME on
2026-09-25, and `tests/install-check.sh` repeats that in CI on Linux and macOS. The license is proprietary for now.
For a machine without a credential for this repository, a version tag releases one executable per platform (D067),
which the install check also covers.
Waiting on the operator: a second person following README's install steps without help, with their friction filed as
issues, and a coworker running canopy against their own ticket.

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_workspace.py` holds the harness's half of the
acceptance: two tickets in two repositories, each run's worktree under the workspace root), docs, and D053 are in.
Until M7 a ticket stays in the repository of its first dispatch, and the overseer records `multi_repo` for one
that needs several. A workspace's `.canopy/` sits inside what may be a shared checkout, so it, and any definitions
snapshot, must be private to the operator (D053). The workspace file is new repository-controlled config, so the
TRUST_MODEL T7 and §7 changes moved here from M7. The overseer prompt and TRUST_MODEL changes need human approval in
their PR. Waiting on the operator: the real two-repository run. Started on request while M2 to M5 wait on their live
runs.

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_units.py`), docs, and D058 to D060 are in. The desk
canary ran against OpenCode 1.18.32 on 2026-10-07: it passes when the workspace root is not a git checkout, and fails
when it is, because OpenCode takes the enclosing repository as its project and allowed a write by absolute path beside
the desk. Per D059, no real joint run in a workspace that is a checkout until that is resolved (keep the workspace out
of git, or fall back to the first unit's worktree as the working directory). Waiting on the operator: one real ticket
touching two repositories taken to two linked PRs, and a real joint run killed mid-way.

## M8. Split tickets

Needs M4's blocker ordering.

- `dispatch --kind split`, `prompts/worker-split.md`, the `canopy-splitter` agent definition, `children` in the result
  contract validated into `split_children`, the child's recorded repository enforced by dispatch,
  `policy.max_split_attempts`.
- Overseer prompt: split only when an authorized replier asks for it (`--request`, D061), never on its own judgment;
  the `split` phase and `split_unlabeled` attention; a child is a candidate only if its label was added after the split
  run ended, and `split_self_labeled` attention when one was not.
- The TRUST_MODEL T1 and T6 changes for creating tickets, with human approval.

Accept: a real ticket covering two repositories, whose split an authorized replier asked for in a comment, is split into
two linked children, the second blocked by the first, with no queue label on either. Nothing is dispatched for them
until the operator labels them; then they are worked in order, one PR each.

Status: in progress. Code, fakes-based tests (`tests/canopy/test_split.py` holds the harness's half of the acceptance: a
requested split reads a desk of worktrees at their bases, pushes nothing, and records the children its worker reports;
invalid children are recorded nowhere; each child is dispatched only in its recorded repository), docs, D061, and D062
are in. Rebuilt on M7's desks from the draft PR #54, which was written before them; a split needs an authorized
replier's comment asking for it (D061), and without one a multi-repository ticket stays one ticket. The overseer prompt,
the `canopy-splitter` definition, and the TRUST_MODEL T1 and T6 changes need human approval in their PR. Not yet checked
live: that OpenCode applies the splitter's name patterns to MCP tools; run the canary with them before the real split.
Waiting on the operator: a real two-repository ticket split on request, its children labeled by hand and worked in
order. Started on request while M2 to M7 wait on their live runs.

## M9. Chores

DESIGN §19 and D034. Needs only M3's attention list and notification; nothing in M4 to M8.

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_chores.py` holds the harness's half of the acceptance:
the guards, findings listed and notified once and resolved when no longer reported, a killed chore run crashed with
`chore_failed`, a deleted chore's items cleared, and no `chores` key without chores), docs, and D063 are in. D063
settles §19's open question on workspaces: a chore may list the workspaces it runs in. `canopy chore try` (D098)
runs a chore by hand, recording nothing, for writing the build-health prompt. A chore's `days` and `hours` (D099)
are a guard in code, so `when` holds only judgment. `canopy reply chore:NAME` (D100) leaves the chore a note its next
runs follow. `examples/chores/build-health.md` is a prompt to start the live run from. The overseer prompt, the
`canopy-chore` definition, and the TRUST_MODEL T1, T3, T6, T7, §6, and §7 changes need human approval in their PR.
Waiting on the operator: a real build-health chore over several working days. Started on request while M2 to M8 wait
on their live runs.

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_notify.py` holds the harness's half of the acceptance:
per-sink delivery, a sink failing for several ticks while another delivers and reports `loop.sink_failing` once, the
failed sink's catch-up in one message, digests on their interval including a quiet one, `loop.failing` and
`loop.recovered`, bounds, and the upgrade from `notify.cmd` re-notifying nothing; `tests/canopy/test_sinks.py` the
desktop sink against fake `notify-send` and `osascript`, and the Slack sink against a local HTTP server), docs, and
D064 are in. The repository is a uv workspace, with the Slack sink its first member; one `uv tool install` installs
canopy and both sinks (`tests/install-check.sh`). The `chores` group came with it, since M9 landed first. DESIGN §15's
three-failure attention item is not built: the attention list is the latest `ok` tick's, so `loop.failing` is its
notification half and the whole of it. The TRUST_MODEL T2, T6, and §7 changes need human approval in their PR.
Waiting on the operator: the desktop sink on their machine, then the Slack sink on a real channel, as Accept says.
Started on request while M2 to M9 wait on their live runs.

## M11. Reviews

DESIGN §21 and D039. Needs M3's `resume`, cursors, and attention list; nothing in M4 to M10, so it can be taken sooner
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
  MCP tool.
- The overseer prompt: the `review_pending` and `review_findings` phases, the `review.query` paragraph (this
  repository's PRs only), recognizing review comments by the journal, and checking that the latest review's comment
  exists, with human approval.
- The TRUST_MODEL T1, T3 to T7, §6, and §7 changes, with human approval.
- DESIGN §5, §6, §7, §11, §12, §13, and §14 updated, and §21's planned note removed.

Accept: with `agent_prs` on, one real ticket's PR is reviewed once its checks pass. A finding goes back through
`resume`, the new commit is reviewed again, and the ticket reaches `needs_reviewer` with no review comment counted as a
human's. With a `review.query` that matches the operator's own hand-written PR, each new head commit gets exactly one
identified comment and nothing else happens to the PR: no push, no ticket, no GitHub review. A review run killed
mid-way is detected on the next tick, its slot returned, and `review_failed` raised. A PR at its limit gets no more
reviews.

Status: in progress. Code, fakes-based tests (`tests/canopy/test_reviews.py`), docs, and D065 are in. Checked live on
2026-10-07 with OpenCode 1.18.32: the reviewer canary passes, and with `agent_prs` on, PR #69 got one identified
`clean` comment at its commit and no GitHub review. The canary checks reads only; the reviewer also needs the runtime's
write MCP `add_issue_comment` allowed for `canopy-reviewer`, which README step 3 does not say. Without it, three
reviews ended `unknown` (the reviewer exited with no result line) and were retried on the same commit, with no
`review_failed` item until the third. Waiting on the operator: a finding taken through `resume` and re-reviewed to
`needs_reviewer`, `review.query` on the operator's own PR, a review killed mid-way, and a PR at its limit.

## M12. The loop

DESIGN §6, D042, and D043. Needs nothing after M1; taken out of order on request (2026-09-24).

- `canopy loop` with `--dry-run`, `--every`, and `--ticks`; `loop.interval_minutes`, user-only.
- `<state_dir>/loop.lock`; SIGINT and SIGTERM stop after the current tick, and a second one aborts it.
- rich output: a block per tick, with a spinner and a countdown on a terminal and plain text off one.
- README's install step and daily surface use the loop instead of cron or launchd.

Accept: fakes-based tests of the wait, both kinds of stop, the lock, and a tick that raises
(`tests/canopy/test_loop.py`). The operator runs `canopy loop --dry-run` against the real queue for a working session,
finds each tick's block legible, and stops it with Ctrl-C both during a tick and during the wait.

Status: in progress. Code, tests, and docs are in. Checked live on 2026-10-07: `canopy loop --every 3` ran 6 ticks
against the real queue, dispatching, reviewing, and resuming; Ctrl-C during a tick stopped it when that tick finished,
and Ctrl-C during the wait stopped it at once (exit 0). The closing line does not say a signal stopped it. Waiting on
the operator: whether each tick's block is legible over a working session.

## M13. Spend-paced loop

D042's pacing rule, fed by what ticks cost. Needs M12. Sketch only; the design comes first.

- Record what each overseer run and each worker run cost, in tokens and dollars, in the journal next to its tick or
  run. Worker, split, and chore runs (D071) and each tick's overseer do; reviews read the same events but record
  nothing yet.
- A spend budget in the user config, and a pacing rule that lengthens the wait when recent ticks cost more and returns
  to `loop.interval_minutes` when they cost less. Idle ticks are M21's: the loop waits the longer of the two rules,
  within M21's gate deadlines.
- Spend in the loop's per-tick block and in `canopy status`.
- Open: what the budget's unit is (per day, per tick, or both); whether a worker's cost counts against the tick that
  dispatched it. How the runtime reports cost is settled by D071: OpenCode's JSON events on stdout.

Accept: written with the design, before work starts.

Status: in progress. Taken in part on request (2026-10-07), with M15's session ids: worker and split runs record their
cost in dollars and tokens, and `canopy status` shows it per recent run (D071). Taken in part again on request
(2026-10-08): each tick records its overseer's session and cost, the default `overseer_cmd` asks for events, and the
loop's per-tick block, `canopy tick`, `canopy status`, and `canopy decisions` show it. A tick's cost is its overseer's
alone, so a worker's is not yet counted against the tick that dispatched it. Waiting on the operator: an
`overseer_cmd` in a user file from before needs `--format json` added. The web UI's attention page shows what the
last 24 hours cost (2026-10-08, D095). Chore runs record theirs, the default `chore_cmd` asks for events, and the
spend counts them (2026-10-08); a chore `cmd` of the operator's needs `--format json` added. Not designed yet: the
budget and the pacing rule.

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
  runtime-specific output beyond one validated field (D009, D026). Done with `--format json` (D071), which also gives
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
`canopy status` lists the ten most recent runs with their outcome, PRs, summary, cost, run log, and session id (D071).
Waiting on the operator: a real run under the pinned OpenCode with the default `worker_cmd`, whose session id opens its
transcript (`opencode export <id>`); an operator's user file from before needs `--format json` added to `worker_cmd`.
Not started: whether `fix-ci` and `resume` continue a session, and workers against OpenCode's server.

## M16. Worktree setup for large monorepos

REQUIREMENTS R10, DESIGN §9 and §18, D033, D105, D106. Needs M2. Taken on request (2026-10-09).

- Where pools live: no pool root of their own. A fast disk takes the whole workspace, for reasons DESIGN §18 gives:
  git keeps each worktree's files in its clone, and treehouse pools by repository and remote URL, so a root every
  workspace shared would merge their pools (D033).
- `paths.worktree_include`, user-only: a personal `.worktreeinclude`, passed on every `treehouse get` as
  `--include-file`. It replaces the committed manifest, since treehouse reads one; a missing file is `no_slot`.
- `runtime.setup_cmd` and `runtime.setup_timeout_minutes`, user-only: run in each slot of a worker run once `_run`
  has checked out the run's branch, and a failure or timeout ends the run `crashed` before its worker starts (D105).
- Bazel: an opt-in canary that a worker reads through `bazel-out/`, `bazel-bin/`, and `bazel-testlogs/` and is refused
  the output base by its own path; a `.bazelrc` recipe for a shared disk and repository cache in `docs/BAZEL.md`; an idle
  slot's server ends by `startup --max_idle_secs`, not when the slot is returned (D106).

Accept: in a Bazel repository, with the recipe in the operator's `~/.bazelrc`, a personal manifest that seeds a
gitignored file, and a `setup_cmd` that runs `bazel fetch` on the run's branch, a real `implement` run's worker finds
the seeded file in its slot and its `bazel test` hits the disk cache another slot filled. A `setup_cmd` that exits 1
ends a real run `crashed` with no worker started and its slot returned. The Bazel canary passes under the pinned
OpenCode. A slot's Bazel server exits once idle for `--max_idle_secs` after its run.

Status: in progress. Code, fakes-based tests (`tests/canopy/test_worktree_setup.py` holds the harness's half of the
acceptance), the canary, docs, and D105 and D106 are in. Waiting on the operator: the real run Accept describes, and
the canary's first real run (`CANOPY_OPENCODE_CANARY=1`).

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_pools.py` holds the harness's half of the acceptance),
docs, and D066 are in. Waiting on the operator: the real run Accept describes. treehouse's `max_trees` (16 by default)
must be at least the largest declared size; canopy cannot set it.

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_private.py` holds the harness's half of the
acceptance), docs, and D080 are in; TRUST_MODEL T1 and T6 and the overseer prompt wait on the operator's approval note
in the PR. OpenCode's wildcard deny with named allows was confirmed by reading its source (1.18.35), not yet in a live
run. Waiting on the operator: the live run Accept describes. With Atlassian's server, `?tools=all` in its URL lets a
private worker read comments; without it only the primary read tools are reachable.

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_mirror.py` holds the harness's half of the acceptance),
docs, and D081 are in; TRUST_MODEL T1, T3, and T6 and the overseer prompt wait on the operator's approval note in the
PR. The open question is settled: PR review comments join the journal with PR subjects, in M14. That OpenCode's
`canopy *` rule admits a heredoc command was read in its source (1.18.35), not yet seen in a live run. Waiting on the
operator: the live run Accept describes.

## M20. Web UI

REQUIREMENTS N1, DESIGN §22, D055, D073, D074, D079. Needs M18; M19 makes it one inbox. Sketch only; the design comes
first.

- `src/canopy/serve/`, run by `canopy loop` from a thread; `--no-serve`; `serve.enabled`, `serve.bind`, `serve.port`,
  all user-only. FastAPI on uvicorn (D074), imported nowhere else, serving the app built from `ui/` (D079).
- TRUST_MODEL T8's bind and secret rules; escaping of every journal value; a per-session token on writes.
- Pages for the attention list, running and recent runs, and tickets with their conversations; reply, start, and
  stop, through the same functions as the CLI. Forget too, behind the ticket's key typed out (D112). Taken on request
  (2026-10-12).
- A worktrees page: each pool's slots from `treehouse status --json`, read when the page asks and every 30 seconds
  while it is open, with the running run or review holding each (D090). Taken on request (2026-10-08).
- The release binary (D067) bundles the built UI and builds on every platform it ships for.
- Settled: the browser gets the listener secret from the operator's sign-in, once (D082); M15's session attach joins
  the UI once M15 runs workers against OpenCode's server.

Accept: written with the design, before work starts, and like every milestone's, a real run of what it delivers.

Status: in progress. Built (2026-10-08): the design (DESIGN §22) settles both open questions: the browser signs in
once with the listener secret and keeps a cookie signed with it (D082), and M15's session attach waits on M15's server,
with session ids on the runs page meanwhile. `canopy loop` serves from a thread unless `--no-serve` or
`serve.enabled = false`, `serve.*` user-only, nothing served without a safe secret file (`canopy secret` makes one);
pages for the attention list, runs, and tickets with their conversations, with reply, start, stop, and stop now through
`core.conversation` and `runs.halt`; an event stream over SQLite's `data_version`; `python -m canopy.serve --mock` over
a seeded journal for development and the end-to-end tests; the install check proves an install bundles and serves the
UI. TRUST_MODEL T8 and §6 wait on the operator's approval note in the PR. The worktrees page is in too (2026-10-08),
tested against the fake treehouse. A reply no `ok` tick has read yet says so, and its answered question is marked so
until the next tick drops it (2026-10-08, D097): the list lagging a reply read as a bug. Waiting on the operator: a real
run, the loop serving a real journal to a browser on loopback and on a private address, with the worktrees page reading
the real pools.

## M21. Idle-paced loop

DESIGN §6 (Idle pacing), D083. Needs M12. Independent of M13: cost bounds spend, idleness says whether a tick was worth
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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_idle_pacing.py`), docs, and D083's update are in
(2026-10-09). Two refinements of DESIGN's sketch: a ticket's `skip` and the chore refusals that lift by themselves
(`chore_capacity`, `not_due`, `outside_hours`) count as quiet, since the overseer skips every unlabeled ticket the
journal remembers each tick; and idle pacing off is all of it off, gates and run wakes included. On the open bullet,
the build follows DESIGN: a shorter `--every` keeps idle pacing from that base. Waiting on the operator: the overnight
run above, and whether `--every` should turn it off instead.

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_trusted_reviewers.py`), docs, and D089 are in. The
operator approved the TRUST_MODEL and prompt changes in the PR (2026-10-08). D093's follow-up is in, with its tests in
the same file; its TRUST_MODEL and prompt changes wait on the operator's approval note in its PR. Waiting on the
operator: the live run above.

## M23. Chores in the web UI

REQUIREMENTS N1 and C5, DESIGN §19 and §22, D100. Needs M9 and M20. Asked for by the operator (2026-10-09): a chore's
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

Status: in progress. The design (DESIGN §19, §22, `ui/DESIGN.md`), the routes, the pages, and their tests are in:
`tests/canopy/test_web_chores.py` over the mock journal, and Playwright answering a chore's finding from the
attention list. The chores' journal view moved down to `core` (`chore_view`, `chore_window`, `chore_result`) so the
server, a feature, can read it as the CLI does. Chores are on the event stream (`chores.updated`), and a note no run
has started since says it waits for the next run. TRUST_MODEL T8's list of web writes gains the note; it waits on the
operator's approval note in the PR. Waiting on the operator: the live run Accept describes.

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
- Settled: a tick's page names the overseer's output (`ticks/<id>.log`) and does not serve it (D104).

Accept: the tests above pass. Live: after a day of `canopy loop` on the real queue, the operator finds in the browser
why a ticket was or was not dispatched in a given tick, and it matches `canopy decisions`.

Status: in progress. The design (DESIGN §6, §22, `ui/DESIGN.md`), the routes, the pages, and their tests are in:
`tests/canopy/test_web_ticks.py` over the mock journal, and Playwright from the header's tick to its decisions and from
a ticket's decisions to their tick. The open question is settled by D104. The latest tick now carries how many
decisions it recorded, so the stream sends it as a running tick records them and the open pages follow. A unit's
decisions name its repository after the ticket, which `canopy decisions` leaves out. Waiting on the operator: the live
run Accept describes.

## M25. Flaky CI triage

REQUIREMENTS R14, DESIGN §23, D102, D103. Needs M3. Asked for by the operator (2026-10-09): a check that fails for a
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

HOST_ISOLATION, TRUST_MODEL T4 and T6, D107, D108, D109, D110. Needs M2. Asked for by the operator (2026-10-12), ahead
of the deferred list's trigger: the sandbox should be proven on the operator's machines before a second team adopts
canopy, not built after an incident.

- The per-run object directory (HOST_ISOLATION §4.2). `_run` makes `<state_dir>/runs/<id>.objects/` before step 2 and
  passes it to `setup_cmd` and the worker as `CANOPY_GIT_OBJECTS`, never as git's own variables. When the worker left
  anything in it, step 5 runs with `GIT_OBJECT_DIRECTORY` and `GIT_ALTERNATE_OBJECT_DIRECTORIES` set, and then, on
  every exit path, each slot is checked out detached at step 2's commit, its HEAD reflog expired, and the directory
  deleted, before the slot is returned. An unsandboxed run leaves it empty, and nothing changes for it.
- `run_slots` records each slot's `.git` link (a new migration), so reconcile's `end_run` does the same cleanup for a
  run whose `_run` is gone, after the same link check `_run` makes; this closes D108's SIGKILL gap.
- `examples/sandbox/`: `canopy-sandbox`, the wrapper HOST_ISOLATION §4.1 describes (resolve the cwd's worktrees and
  their git directories, write a per-run `srt` policy, drop `BASH_ENV`, map `CANOPY_GIT_OBJECTS` to git's variables,
  `exec srt --settings <policy> -- "$@"`), taking a role (`worker`, `setup`, `chore`) that picks the policy; and the
  policy template, §4.2's filesystem table and §4.3's network allowlist with the operator's hosts left to fill in. No
  Unix sockets, so sandboxed runs push over HTTPS (D110). Examples, not harness code: the harness sees only the
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

## Deferred, with the trigger that would unblock each

- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it, or when a repository wants to trust review verdicts (D039).
- Second runtime (Copilot CLI, Claude Code): when a coworker asks. More than a config change: canopy's definitions,
  their permissions, and the D044 guard are written for OpenCode, so a runtime needs its own (REQUIREMENTS N4).
- Slack replies: when the operator wants to answer from Slack. A channel into the journal's conversation (DESIGN
  §22): a Socket Mode bridge running `canopy reply`, or the overseer reading Slack through MCP. Needs a T1
  change.
