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
  `.opencode/agent/` runs the worker as OpenCode's default agent, with no denies.

Accept: one real ticket goes from label to open PR unattended, with the slot
returned and a correct `runs` row. A killed worker is detected on the next tick
and its slot returned.

Status: in progress. Code, fakes-based acceptance tests (`tests/canopy/test_reconcile.py`), docs, and D028 and D029 are
in. Not built: D040's definitions directory, which the live run needs. Waiting on the operator: one real ticket from
label to open PR, a killed worker on a real run, a first live run of the OpenCode canary, and the human approval the new
worker definition and the overseer prompt change need. It was started on request before M1 closed (2026-09-24).

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

Status: in progress. Code, fakes-based tests (`tests/canopy/test_fix_ci_resume.py` holds the fix-ci half of the
acceptance; `tests/canopy/test_attention.py`), docs, and D030 to D032 are in. Waiting on the operator: a real PR with a
failing check taken through fix-ci to the limit, a real blocked worker answered once by an authorized and once by an
unauthorized account (prompt behavior the fakes cannot show), and the human approval the overseer prompt change needs.
M2's acceptance run is also still open; this milestone was started on request before M1 closed. Not done
here, and not listed by any milestone: DESIGN §15's attention item after three consecutive overseer failures.

## M4. Dependencies and stacking

- Blocker detection via the tracker's blocker relations in the overseer prompt (DESIGN §17; Jira links and GitHub
  dependencies via their skills).
- `dispatch --base` and PR base handling in `_run` and the worker prompt. M2 refuses `--base` as `not_implemented`.

Accept: two linked tickets are worked in order; the second's PR targets the
first's branch when the first is open and green.

Status: not started.

## M5. Shareable

- `skill/` OpenCode skill for the canopy CLI.
- `uv tool install` path verified from a clean machine.
- README install steps performed by a second person without help. Their
  friction becomes issues.
- License decided and added.

Accept: a coworker runs it against their own ticket.

Status: not started.

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

Status: not started.

## M7. Joint multi-repo runs

- `ticket_units`, `run_slots`, repeated `--repo`, all-or-nothing leases.
- Desks, per-repository branch setup and push verification, `prs` in the result contract, sibling PR links.
- Per-unit phases, cursors, and attempt counts; attention items with a repository.
- The desk permission canary, and the TRUST_MODEL T4, T6, T7, and §7 changes with human approval.

Accept: one real ticket touching two repositories gets two linked PRs from one run. A joint run killed mid-way is
detected on the next tick and all its slots are returned.

Status: not started.

## M8. Split tickets

Needs M4's blocker ordering.

- `dispatch --kind split`, `prompts/worker-split.md`, the `canopy-splitter` agent definition, `children` in the result
  contract validated into `split_children`, the child's recorded repository enforced by dispatch,
  `policy.max_split_attempts`.
- Overseer prompt: choose split or joint; the `split` phase and `split_unlabeled` attention; a child is a candidate
  only if its label was added after the split run ended, and `split_self_labeled` attention when one was not.
- The TRUST_MODEL T1 and T6 changes for creating tickets, with human approval.

Accept: a real ticket covering two repositories is split into two linked children, the second blocked by the first,
with no queue label on either. Nothing is dispatched for them until the operator labels them; then they are worked in
order, one PR each.

Status: not started.

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

Status: not started.

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
  modules in `src/canopy`, and the layer test refusing imports of the sink. `uv tool install canopy` still installs
  both in one step (a check on a clean machine, as M5's).
- The TRUST_MODEL T2, T6, and §7 changes, with human approval.
- DESIGN §5, §6, §11, §12, and §14 updated, and §20's planned note removed. README's daily surface names sinks.

Accept: with the Slack sink on a real channel, one real ticket's dispatch, a blocked worker's question, and its PR each
reach the channel once, and an attention item is posted once when it opens and once when it resolves. With the webhook
file removed, Slack fails for several ticks while a second sink keeps delivering and reports `loop.sink_failing`;
restoring the file delivers what was missed in one message. A digest arrives on its interval, including a quiet one.

Status: not started.

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

Status: not started.

## M12. The loop

DESIGN §6, D042, and D043. Needs nothing after M1; taken out of order on request (2026-09-24).

- `canopy loop` with `--dry-run`, `--every`, and `--ticks`; `loop.interval_minutes`, user-only.
- `<state_dir>/loop.lock`; SIGINT and SIGTERM stop after the current tick, and a second one aborts it.
- rich output: a block per tick, with a spinner and a countdown on a terminal and plain text off one.
- README's install step and daily surface use the loop instead of cron or launchd.

Accept: fakes-based tests of the wait, both kinds of stop, the lock, and a tick that raises
(`tests/canopy/test_loop.py`). The operator runs `canopy loop --dry-run` against the real queue for a working session,
finds each tick's block legible, and stops it with Ctrl-C both during a tick and during the wait.

Status: in progress. Code, tests, and docs are in. Waiting on the operator's session against the real queue.

## M13. Spend-paced loop

D042's pacing rule, fed by what ticks cost. Needs M12. Sketch only; the design comes first.

- Record what each overseer run and each worker run cost, in tokens and dollars, in the journal next to its tick or
  run.
- A spend budget in the user config, and a pacing rule that lengthens the wait when recent ticks cost more and returns
  to `loop.interval_minutes` when they cost less.
- Spend in the loop's per-tick block and in `canopy status`.
- Open: how the runtime reports cost (OpenCode's JSON output, its session store, or a command of its own) without the
  harness growing runtime-specific parsing (D009); what the budget's unit is (per day, per tick, or both); whether a
  worker's cost counts against the tick that dispatched it.

Accept: written with the design, before work starts.

Status: not started.

## Deferred, with the trigger that would unblock each

- Sandboxed workers: when a T4 or T6 incident happens, or before any second
  team adopts it. Proposal: `HOST_ISOLATION.md`.
- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it, or when a repository wants to trust review verdicts (D039).
- Second runtime (Copilot CLI, Claude Code): when a coworker asks; expected to
  be a config change plus prompt tweaks, not code.
- Web UI: not planned.
