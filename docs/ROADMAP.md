# canopy roadmap

Milestones are sequential. Each has acceptance criteria that must be met before
the next begins. Acceptance criteria that involve running against real systems
are the operator's job; the agent building the repo stops and asks.

Each milestone ends with a `Status:` line. It is the only place milestone
progress is tracked. Keep it current in the same PR that changes it:

- `Status: not started.` or `Status: in progress.` while work is open.
- When the acceptance criteria are met, replace it with:

  ```
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
- Live, from an empty journal (after the migrations were squashed, #60 and D068), with OpenCode 1.18.32: GH-64 went from label
  to PR #69 unattended, its slot returned and its `runs` row correct. GH-65's `_run` and worker, killed with SIGKILL,
  were `crashed` on the next tick with the slot returned; an authorized reply then resumed its branch to PR #70.
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
acceptance: two tickets in two repositories, each run's worktree under the workspace root), docs, D052, and D053 are in.
Until M7 a ticket stays in the repository of its first dispatch (D052), and the overseer records `multi_repo` for one
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
- Lift D052's one repository per ticket: `implement` may add a unit. Decide DESIGN §18's open question on sequenced
  PRs (a follow-up after the first merged, or the next repository once the first lands) before designing units, since
  it decides whether a unit can start after the ticket's first PR has merged.
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
settles §19's open question on workspaces: a chore may list the workspaces it runs in. The overseer prompt, the
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
  run. Worker and split runs do (D071); the overseer, chores, and reviews read the same events but record nothing yet.
- A spend budget in the user config, and a pacing rule that lengthens the wait when recent ticks cost more and returns
  to `loop.interval_minutes` when they cost less.
- Spend in the loop's per-tick block and in `canopy status`.
- Open: what the budget's unit is (per day, per tick, or both); whether a worker's cost counts against the tick that
  dispatched it. How the runtime reports cost is settled by D071: OpenCode's JSON events on stdout.

Accept: written with the design, before work starts.

Status: in progress. Taken in part on request (2026-10-07), with M15's session ids: worker and split runs record their
cost in dollars and tokens, and `canopy status` shows it per recent run (D071). Not designed yet: the budget, the
pacing rule, and spend in the loop's per-tick block.

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

REQUIREMENTS R10. Needs M2. Sketch only; the design comes first.

- Where pools live: a user-only key for the pool root in a workspace, so the pools can sit on a fast disk apart from
  the workspace, or a documented reason to keep the workspace there instead (§18 pins `TREEHOUSE_ROOT` for T7's sake).
- A personal `.worktreeinclude` manifest passed as `treehouse get --include-file`, user-only.
- Setup that runs after `_run` checks out the run's branch and fails the run when it fails, unlike treehouse's
  `post_create` (PRIOR_ART "Open design questions"): a user-only command template, or an upstream treehouse change.
- Bazel: a canary for the worker's `external_directory: deny` against reads through `bazel-out/`; a documented
  `.bazelrc` recipe for a shared disk and repository cache; whether returning a slot should stop its Bazel server.

Accept: written with the design, before work starts, and like every milestone's, a real run of what it delivers.

Status: not started.

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

REQUIREMENTS R11, DESIGN §22, D072. Needs M3. Sketch only; the design comes first.

- A `messages` table, in a new migration. `_run` records each run's report and question there, for every ticket.
- `canopy queue add|remove|list`, `canopy reply`, and `canopy conversation`, writing through `core/conversation.py`
  and refusing inside canopy's runs (`CANOPY_TICK_ID`, and `CANOPY_RUN_ID`, which `_run`, `_chore`, and `_review` set).
- `canopy dispatch` takes a queued key without `--label`, checking the queue row in code, and refuses a private
  `split`.
- The private worker prompt variant and `canopy-worker-private`, with the tracker's write tools denied by name.
- The overseer: private tickets in the state block with their new operator messages, and their phases read from them.
  A prompt change, which needs the operator's approval.
- `awaiting_reply` on the attention list, raised by the harness; `run.ended` carries the question's message id.
- The loop's wait ends early on an operator message (D073).
- TRUST_MODEL T1, T6, and the overseer prompt as DESIGN §22 proposes, with the operator's approval note.

Accept: a fakes-based test: a queued ticket with no label is dispatched to the private worker definition, the fake
worker ends `blocked`, the question is on the attention list and in `canopy conversation`, `canopy reply` ends the
loop's wait, and the `resume` prompt carries the reply. Live, the operator takes a real ticket privately, answers a
question from the CLI, the PR lands for review, and the ticket shows nothing canopy wrote.

Status: not started.

## M19. Tracker comments in the journal

REQUIREMENTS R12, DESIGN §22, D072. Needs M18. Sketch only; the design comes first.

- `canopy ticket mirror`, overseer-only, bounded, idempotent on the ticket and comment id.
- The overseer prompt mirrors every comment past a ticket's comment cursor, skipping worker-marked ones (D069). A
  prompt change, which needs the operator's approval.
- `canopy conversation KEY` shows mirrored comments with their source, for public tickets as for private ones.
- Open: whether PR review comments join the journal here or later.

Accept: fakes-based tests of the command's bounds, refusals, and idempotence. Live, a working session's decisions show
each new comment mirrored once, and M13's spend records show what mirroring adds to a tick.

Status: not started.

## M20. Web UI

REQUIREMENTS N1, DESIGN §22, D055, D073. Needs M18; M19 makes it one inbox. Sketch only; the design comes first.

- `src/canopy/serve/`, run by `canopy loop` from a thread; `--no-serve`; `serve.enabled`, `serve.bind`, `serve.port`,
  all user-only. The network ban extended to `http.server` and `socketserver`, with `serve/` alone exempt.
- TRUST_MODEL T8's bind and secret rules; escaping of every journal value; a per-session token on writes.
- Pages for the attention list, running and recent runs, and tickets with their conversations; reply, take privately,
  and release, through the same functions as the CLI.
- Open: how the browser gets the listener secret; whether stdlib `http.server` is enough or the UI earns a dependency
  (its own `DECISIONS.md` entry); whether M15's session attach belongs in the UI.

Accept: written with the design, before work starts, and like every milestone's, a real run of what it delivers.

Status: not started.

## Deferred, with the trigger that would unblock each

- Sandboxed workers: when a T4 or T6 incident happens, or before any second
  team adopts it. Proposal: `HOST_ISOLATION.md`.
- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it, or when a repository wants to trust review verdicts (D039).
- Second runtime (Copilot CLI, Claude Code): when a coworker asks. More than a config change: canopy's definitions,
  their permissions, and the D044 guard are written for OpenCode, so a runtime needs its own (REQUIREMENTS N4).
- Slack replies: when the operator wants to answer from Slack. A channel into the journal's conversation (DESIGN
  §22): a Socket Mode bridge running `canopy reply`, or the overseer reading Slack through MCP. Needs a T1 change.
