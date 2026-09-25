# canopy design

- [1. Problem](#1-problem)
- [2. Goals](#2-goals)
- [3. Non-goals](#3-non-goals)
- [4. Principles](#4-principles)
- [5. Components](#5-components)
- [6. Tick](#6-tick)
- [7. Ticket phases and next actions](#7-ticket-phases-and-next-actions)
- [8. Dispatch and the worker contract](#8-dispatch-and-the-worker-contract)
- [9. Aggressive release](#9-aggressive-release)
- [10. Dependencies and stacking](#10-dependencies-and-stacking)
- [11. State model](#11-state-model)
- [12. Configuration](#12-configuration)
- [13. Agent runtime](#13-agent-runtime)
- [14. Attention list](#14-attention-list)
- [15. Failure handling](#15-failure-handling)
- [16. Open questions](#16-open-questions)
- [17. Trackers](#17-trackers)
- [18. Workspaces and multi-repo tickets](#18-workspaces-and-multi-repo-tickets)
- [19. Chores](#19-chores)
- [20. Notifications](#20-notifications)
- [21. Reviews](#21-reviews)

Normative. Code follows this document; changes to behavior change this document
in the same PR. Rationale for choices lives in `DECISIONS.md`.

## 1. Problem

A developer running several coding agents at once ends up hand-managing
checkouts and context switching every time CI fails or a review lands. Existing
in-house orchestration (Azimuth) encoded the workflow in code, could not be
grown, and never became something a second person could run. Hosted agents
cannot reach internal systems and require handing a vendor write access.

## 2. Goals

- Label a ticket, get a PR, without touching a terminal in between.
- The loop picks up CI failures and review feedback on its own.
- The developer sees one list of things that actually need a human.
- A coworker can install it in five steps and use it with zero new daily CLI.
- Adding a capability means adding a tool and a paragraph of prompt, not a
  schema or a state machine.
- Runs entirely on the developer's machine under their existing credentials.

## 3. Non-goals

- Replacing human review, approval, or merge.
- A hosted service, a background daemon, a network listener, a web UI, or a workflow DSL. `canopy loop` (§6) runs in
  the foreground, where the operator started it.
- Tracker-specific code. Any issue tracker with an MCP server works; provider differences live in config and optional
  provider skills (§17). A second VCS host is likewise a prompt and config concern, not code.
- Sandboxing agents (deferred; see TRUST_MODEL and ROADMAP).

## 4. Principles

1. **Ownership split.** The tracker and GitHub own facts about the world:
   ticket status, branches, PRs, CI, reviews. treehouse owns worktrees and
   leases. The SQLite journal owns facts about the loop: what it saw, decided,
   dispatched, and what came back. The journal is never consulted as a
   substitute for world facts. Before any action that matters, re-read live
   state. Drift is then a stale cache, not a correctness bug.
2. **Policy in prompts, guards in code.** What to do about a ticket is decided
   by the overseer prompt. What the loop may never do (exceed capacity, run two
   workers on one ticket, merge, retry forever) is enforced by the harness.
3. **Aggressive release.** A worktree is held only while an agent is actively
   working. Waiting on CI, review, or a human answer holds nothing. The pushed
   branch is the checkpoint.
4. **Deterministic core, judgment at the edges.** Python never calls an LLM.
   The overseer and workers are agent processes the harness runs and observes.
5. **Connectivity through the agent runtime.** The tracker (Jira, GitHub Issues, Linear, anything with an MCP server)
   and GitHub are reached via the runtime's MCP servers. The harness contains no tracker or VCS host code and never
   handles their credentials. It knows the tracker only as the strings in `[tracker]`.
6. **Smallest surface that works.** Five install steps. Daily surface is
   labels, ticket comments, PR review, and one attention list.

## 5. Components

The harness is one Python package, `canopy`, in layered subpackages (D041). Top to bottom: `__main__`; `cli`; `loop`;
the features, `runs` and `setup`; `core`; `infra`. A module imports from its own package and from lower layers only.
Features never import each other; what two of them share moves down a layer. `tests/canopy/test_layers.py` enforces
this, and fails on a module outside the packages it lists.

```
canopy (harness, Python)
  __main__.py      python -m canopy, how dispatch starts _run from the same installation

  cli/             the command line; only cli imports click, and only __main__ imports cli
    main.py        main(), the root group, exit codes
    common.py      opening the Context, refusals, the tick named by CANOPY_TICK_ID
    params.py      validated parameter types: ticket keys, reasons, slugs, cursors, bounded text
    setup.py       init, skill
    loop.py        loop, tick, tick --dry-run, status, decisions
    runs.py        dispatch, _run
    journal.py     decide, attention, ticket set

  loop/            the tick (§6), which drives the features below
    tick.py        lock, migrate, reconcile, run the overseer, close the tick, publish
    repeat.py      canopy loop: ticks one after another with a wait between them, its own lock, rich output
    state.py       the overseer's state block
    attention.py   the attention list from the journal; render attention.md, diff, notify

  runs/            worker runs on tickets (§8)
    dispatch.py    guards, lease, render the worker prompt, spawn detached _run
    policy.py      attempt limits and the fix-ci cooldown, derived from runs
    worker.py      canopy _run: branch setup, the worker, result parsing, push verification, slot return
    reconcile.py   dead runs marked crashed, stale leases returned, the capacity left

  setup/
    init.py        canopy init: config files, branch protection text, SSH remote warning, old agent definition copies

  core/            what every feature shares
    config.py      layered config: repository canopy.toml and user config.toml, scopes, validation
    context.py     the Context every command passes around: config, repository root, db connection, runner
    db.py          SQLite journal, migrations
    definitions.py the snapshot of agents/ and skills/ that agent runs load (§13); the guard against shadowing them
    prompts.py     prompt files and overrides; rendering worker prompts
    treehouse.py   status --json, get --lease --json, return --force --if-lease-id

  infra/           plumbing that knows nothing about tickets or agents
    procs.py       the only module that runs subprocesses (lint-enforced); a timeout kills the whole process group;
                   a child's PWD names its cwd (OpenCode runs tools in PWD); detached spawns and pid liveness
    lock.py        flock on <state_dir>/lock; a tick that cannot lock exits 0 with a log line
    logs.py        JSON-lines logging to <state_dir>/canopy.log, stamped with the tick id; operator-only files
    resources.py   finds migrations/ and .agents/ in a source checkout or bundled in the installed wheel
```

```
prompts/         overseer.md, worker-implement.md, worker-fix-ci.md, worker-resume.md
agents/          OpenCode agent definitions: canopy-overseer, canopy-worker
skills/          tracker-<provider>/: optional per-tracker guides (§17)
operator-skill/  SKILL.md: the canopy skill, for the operator's own agent sessions (§13); agent runs never load it
migrations/      NNNN_name.sql
```

`prompts/`, `agents/`, `skills/`, and `operator-skill/` live under `.agents/` in this repository. The wheel bundles
them, and `migrations/`, under `canopy/_data/` (D022).

Where later work goes:

- A feature is a package in the features layer with a command module in `cli/`: `chores` (§19), `notify` (§20),
  `reviews` (§21). `loop` calls a feature's reconcile and publish steps and its part of the state block. Deleting a
  feature is deleting its package, its command module, and those calls.
- A feature other features write to keeps its writing half in `core`: dispatch and `_run` record §20's notification
  events through `core`, and `notify` delivers them.
- Code that runs in its own process and must not share the harness's imports or dependencies is not a package here but
  a separate distribution, a uv workspace member under `packages/`. The first is §20's Slack sink, and the repository
  becomes a workspace when it lands; `canopy` stays the workspace root, so nothing above moves.
- A module that takes on a second concern splits into a package of the same name in the same layer, as `cli.py` did.

Roles:

- **Harness**: schedules, locks, guards, journals, renders. Runs the overseer
  once per tick and workers on demand.
- **Overseer**: an agent run with `overseer_cmd`. Reads the world through MCP
  and the harness's state summary, decides one next action per ticket, and
  acts only through `canopy dispatch`, `canopy decide`, and `canopy attention`.
  Read-only everywhere else.
- **Worker**: an agent run with `worker_cmd` inside a leased worktree with a
  task prompt. Writes code, pushes a branch, opens or updates a PR, comments on
  the ticket, prints a result line, exits. Never merges, approves, or moves a
  ticket to Done.

## 6. Tick

Ticks run one after another under `canopy loop` (below). `canopy tick` runs one, by hand or from a scheduler. Either
way, a tick does, in order:

1. Acquire the lock. If held, log and exit 0. No `ticks` row is written.
2. Apply pending migrations. Close any `ticks` row still `running` as `abandoned`: holding the lock proves its process
   is gone. Insert a `ticks` row; its id tags all logs.
3. **Reconcile local state.**
   - For each `runs` row with `status='running'`: if its pid (the `canopy _run` process) is dead or was never recorded,
     kill the process group of the worker `_run` started, if any of it is left (`runs.worker_pid`); mark the run
     `crashed`; run `treehouse return --force --if-lease-id` on its slot; log it. A zombie counts as dead. A pid
     reused by an unrelated process reads as alive, so that run is left running; this is a residual, not a guard.
   - For each leased slot in `treehouse status --json` with no live
     `runs` row and `lease_holder` matching our prefix: return it, log it.
   - Compute `capacity = max_workers - count(runs where status='running')`.
   - If `treehouse status` or a return fails, close the tick as `reconcile_failed` and stop. The overseer does not run.
   - Record the harness's attention items for runs (§14) as this tick's decisions.
4. **Render the overseer prompt**: `prompts/overseer.md` (or the override), plus a generated state block: a `## State`
   section holding one JSON object with the tick id, the current time, whether it is a dry run, the repository root,
   tracker config (provider, query, labels, needs-human label), trust config (authorized repliers, branch prefix, PR
   label), capacity, policy limits, running workers, and the `tickets` rows not marked done (phase, cursors, runs so far
   of each kind, when fix-ci may next run if that is still ahead, and the ticket's latest run: id, kind, status, branch,
   the base it started from, start and end).
5. **Run the overseer** with `overseer_cmd`, cwd = the repository root, timeout `overseer_timeout_minutes`, and
   `CANOPY_TICK_ID` set in its environment. `canopy dispatch`, `decide`, and `attention` read that variable to know
   which tick they belong to, and refuse if it is unset or names a tick that is not running (D020). The overseer's
   stdout and stderr go to `<state_dir>/ticks/<tick id>.log`, readable only by the operator, never to the journal.
   The run succeeded if it exited 0 and the last non-empty line of stdout is `tick complete`; anything else closes the
   tick as `overseer_failed`. A run that succeeded but recorded a tick-wide `skip` (`mcp_unavailable`,
   `tracker_unsupported`) closes the tick as `skipped`: the overseer could not see the world, so the tick is not `ok`
   and does not replace the attention list (D037).
   In `--dry-run`, the state block says so. `canopy dispatch` checks the same guards as in a live tick (§8), counting
   each dispatch this dry run already recorded as a running run, and records a refusal the same way; a dispatch the
   guards allow starts nothing and is recorded as `dispatch:<kind>` with rationale `dry run: not dispatched; would work
   on <branch>` and its cursors and context. `canopy ticket set` records phases, but in a dry run neither it nor
   `canopy dispatch --cursor` advances cursors, and `--done` does not mark the ticket done, so the first live tick still
   sees everything as new (D036). The overseer otherwise behaves as in a live tick, and so does the rest of the tick:
   reconcile closes dead runs and returns stale leases, and a dry-run tick's attention items are the attention list and
   are notified like a live tick's.
   `canopy decide` takes `wait`, `skip`, or `done`; only a tick-wide `skip` (such as `mcp_unavailable`) omits the key.
   Everything the overseer writes is rendered into the next tick's prompt, so the CLI bounds it: keys and attention
   reasons are validated, phases come from the table in §7, cursor ids must match `[A-Za-z0-9][A-Za-z0-9_.:/-]*`, and
   rationales, details, and worker context are cut at 2000 characters.
6. Close the `ticks` row with a summary.
7. **Publish attention** (§14): rewrite `attention.md` from the journal, and if `notify.cmd` is set and the list
   changed since the last notification, pipe the change to it. This comes after the tick is closed because the list is
   the latest `ok` tick's, and this tick may be it. It runs after a failed or skipped tick too, when the list is the one
   before. A failure here is logged and does not change the tick's status. Release the lock.

Workers dispatched during a tick outlive the tick. They are detached processes
owned by `canopy _run`.

### The loop

`canopy loop [--dry-run] [--every MINUTES] [--ticks N]` is how ticks are meant to run (D042). It runs in the foreground
until stopped:

1. Take `<state_dir>/loop.lock`. If another loop holds it, refuse and exit 1: two loops on one state dir would run the
   overseer twice as often. The tick lock is separate and each tick takes it as in step 1 above, so a `canopy tick`
   started by hand runs between the loop's ticks, or finds the lock busy.
2. Apply pending migrations; the loop reads the journal before its first tick.
3. Run a tick, exactly as `canopy tick` does, with `--dry-run` passed through. An error the tick code does not handle
   ends that tick as `error` in the loop's output: the traceback goes to the log and the loop goes on, as with a
   scheduler that starts each tick as its own process. The next tick closes the row it left `running` as `abandoned`.
4. Print what the tick did: its status, duration, and summary; each decision except `wait` and attention items, with
   its rationale; the attention items it added (`+`) and resolved (`-`); running workers and the list's size.
5. Wait, measured from the end of the tick, so a long tick never leads straight into the next. The pacing rule
   (`repeat.pace`) decides how long: today `--every`, else `loop.interval_minutes`, after every tick whatever its
   status. Pacing by what ticks cost is ROADMAP M13, and replaces this rule.
6. Repeat from 3, until `--ticks N` ticks have run or the operator stops the loop.

Stopping: SIGINT (Ctrl-C) or SIGTERM during the wait ends the loop at once. During a tick, the first one lets the tick
finish and the loop ends without waiting; both exit 0. A second one aborts the tick: the overseer's process group is
killed as on a timeout, the command exits 1, and the next tick closes the row as `abandoned`. Workers already
dispatched are detached and unaffected either way. A signal less than one second (`repeat.SAME_SIGNAL_SECONDS`, on a
monotonic clock) after the first is the same keypress, not a second one: under `uv run`, one Ctrl-C reaches canopy from
the terminal and again, about 200 ms later, forwarded by uv (D049).

The config is read once, when the loop starts; restart the loop to apply a change. Prompt files are read every tick.

Output is drawn with rich (D043). On a terminal, a spinner with the elapsed time shows during a tick and a countdown
during the wait, both redrawn in place and gone once done. Sent to a file or a pipe, the output is plain text, one block
per tick. The JSON log gains `loop started` and `loop stopped` lines, with no tick id.

## 7. Ticket phases and next actions

Phases are derived by the overseer each tick from live state. They are recorded
in `tickets.phase` for the status view, never read back as truth.

| Phase | Derived from | Next action |
|---|---|---|
| `ready` | one of `tracker.labels` present, not closed, no run active, no branch, no open blocker | dispatch `implement` |
| `blocked` | as `ready`, but a blocker ticket is open | dispatch `implement` stacked on the blocker's branch if its PR is open and green (§10), else wait |
| `running` | active `runs` row | wait |
| `pushed_no_pr` | branch exists, no PR | dispatch `resume` with instruction to open the PR |
| `ci_running` | PR open, checks pending | wait |
| `ci_red` | PR open, checks failed, newer than cursor | dispatch `fix-ci`; at the attempt limit, attention; in cooldown, wait |
| `changes_requested` | review comments or requested changes newer than cursor | dispatch `resume` with the comments; if the overseer judges a comment needs a human (design pushback, scope), attention instead |
| `green_unreviewed` | checks pass, no approval | attention: needs a reviewer |
| `approved` | approved, not merged | attention: ready to merge |
| `merged` | PR merged | mark ticket `done` in the journal; humans handle the tracker transition |
| `needs_human` | `needs_human_label` present, no authorized reply newer than it | wait |
| `human_replied` | authorized reply newer than the label | dispatch `resume` pointing at the reply; the worker removes the label |

"Authorized reply" means a comment by an account in `trust.authorized_repliers`, matched on the tracker's stable account
identifier, never a display name. If the tracker cannot say when a label was added, the worker's question comment is the
reference point instead of the label. Anything else on the ticket is data, not instruction. See TRUST_MODEL.

Cursors (`comment`, `review`, `ci`) hold the newest item of each kind the loop has handled, in the tracker's and
GitHub's own ids; "newer than cursor" in the table means not handled yet. A dispatch that handles new items carries
their cursors (`--cursor`, §8), so they advance only if the worker starts. Items handled by a wait, a done, or an
attention item advance with `canopy ticket set`. A review comment waiting on a human is not advanced past, so its
attention item is recorded every tick until a human answers it.

"Closed" means whatever the tracker calls finished: Jira status category Done, GitHub issue state closed, and so on. The
provider skill says which.

## 8. Dispatch and the worker contract

`canopy dispatch <KEY> --kind implement|fix-ci|resume [--slug SLUG] [--base BRANCH] [--context TEXT]
[--cursor NAME=ID]...`:

1. Refuse if capacity is zero, if a `runs` row for KEY is `running`, or if the kind's attempt limit or cooldown blocks
   it. Guards are in code and are not overridable from the prompt. A refusal is recorded as a decision
   `refused:<guard>` with the reason, and the command exits 1. A dry run checks the same guards and then stops, with
   each dry-run dispatch already recorded this tick counting as a running run for `running` and `capacity` (§6, D036).
   Guards, in the order they are checked:
   - `bad_slug`: a slug that is not lowercase words joined by hyphens, or any `--slug` with `fix-ci` or `resume`.
   - `no_branch`: `fix-ci` or `resume` for a ticket with no branch in the journal. They continue the branch the
     ticket's latest dispatch recorded (`tickets.branch`); `implement` is the only kind that names a new one.
   - `bad_base`: a `--base` that is not `<trust.branch_prefix>` followed by one plain ref component (letters, digits,
     `_`, `-`, starting with a letter or digit, at most 200 characters), or that is the run's own branch (§10, D045).
   - `running`: a run for KEY is running.
   - `attempt_limit`: KEY has already had `policy.max_<kind>_attempts` runs of this kind. Every run counts, whatever it
     ended as, and the count never resets (D030). The refusal also records the `attempt_limit` attention item (§14).
   - `cooldown`: `fix-ci` only, less than `policy.fix_ci_cooldown_minutes` after KEY's latest fix-ci run ended.
   - `capacity`: `max_workers` runs are running.

   Failures after the guards are recorded the same way: `no_slot` (the lease failed), `bad_prompt` (the worker prompt
   did not render), `spawn_failed`. None of them leaves a slot leased.
   Dispatches are serialized by a blocking `flock` on `<state_dir>/dispatch.lock`, held from the guard checks through
   the spawn, so two dispatches cannot both pass the capacity check or the attempt limit.
   `--cursor NAME=ID` pairs are applied as `canopy ticket set` would, but only once the worker has started: what a
   refused dispatch was meant to handle stays new for the next tick.
2. `treehouse get --lease --lease-holder canopy:<KEY> --json`. Record the
   `runs` row with slot path, lease id, holder, kind, base branch (`--base` if given, else treehouse's), branch,
   started_at.
3. Render the worker prompt for the kind, with KEY, tracker provider, branch name, base branch, PR label, needs-human
   label, timeout, the attempt number and the kind's limit, the PR the journal recorded for the ticket, the authorized
   repliers, whether the run is stacked on another ticket's branch (§10), the context, and the result contract below.
   An `implement` branch is `<trust.branch_prefix><KEY>-<slug>`; the overseer picks the slug from the ticket title,
   lowercase words joined by single hyphens, at most 40 characters, `work` if it gives none. The context is the overseer's `--context`: at most
   2000 characters that point the worker at what to read (links, comment ids, check names), never a copy of ticket or
   PR text (D031). The worker reads that text itself and checks a reply's author against the authorized repliers,
   which the harness renders from the user config. Placeholders are `{{NAME}}`, replaced in one pass;
   an unknown one is `bad_prompt`. The prompt is written to `<state_dir>/runs/<run_id>.prompt`, readable only by the
   operator.
4. Spawn `python -m canopy _run <run_id>` with the interpreter canopy runs under, detached (`setsid`, stdin from
   `/dev/null`, stdout and stderr appended to `<state_dir>/runs/<run_id>.log`, cwd the repository root). Record its
   pid in the run. Return immediately.

`canopy _run <run_id>` (hidden from `--help`):

1. Claim the run: set its pid to this process's pid, only if the run is `running` and its pid is unset or already this
   pid. Anything else is refused, so the overseer cannot start a second worker on a run. Drop `CANOPY_TICK_ID` from the
   environment, so the worker cannot act as the overseer of the tick that dispatched it.
2. In the slot: `git fetch --prune origin`, so a branch deleted on origin is gone here too; if `origin/<branch>` exists,
   `git checkout -B <branch> origin/<branch>`, else `git checkout --no-track -B <branch>
   origin/<base>`. `-B` because a branch left in the pool's repository by an earlier run on another slot would make
   `-b` fail; `--no-track` so that a bare `git push` never targets the base. Note the branch's commit. A base missing
   from origin, such as a stacked-on branch deleted when its PR merged, fails the run as `crashed` before the worker
   starts, with a note saying so, whether the branch is new or continued: the worker's prompt targets the PR at it.
3. Run `worker_cmd` with cwd = slot, timeout `worker_timeout_minutes`. Record the worker's pid in `runs.worker_pid`;
   the worker leads its own process group. The worker's stdout and stderr go to the run log.
4. Parse the last non-empty line of stdout as the result contract. Missing or invalid means `status='unknown'`; a
   timeout means `status='timeout'`.
5. Verify the branch is pushed (`git ls-remote origin refs/heads/<branch>` equals the local branch).
   If not and the branch has commits since step 2, push once, without force. If still not pushed, record
   `status='unpushed'`; the checkpoint invariant failed and a human looks.
6. Always: `treehouse return --force --if-lease-id <id> --if-lease-holder
   <holder> <slot>`. Trap ensures this runs on any exit path: a normal exit, an exception, and SIGTERM, SIGHUP, or
   SIGINT (the run is then `crashed`). SIGKILL cannot be trapped; reconcile handles it.
7. Update the `runs` row: ended_at, status, result_json. A git failure before or after the worker is `crashed`.
   `result_json` holds the validated result, text fields cut at 2000 characters, plus a `harness` note saying why the
   status differs from what the worker reported. A reported `pr` that is a plain `https://` URL is copied to
   `tickets.pr_url` for display.

Worker result contract, one JSON line, last line of stdout:

```json
{"status":"done|blocked|failed","branch":"agent/KEY-slug","pr":"https://...|null",
 "summary":"one paragraph","question":"only when blocked"}
```

Worker obligations, stated in every worker prompt:

- Work only inside the worktree. Push only to `agent/<KEY>-*`, never with force.
- Keep the runtime's attribution trailer on commits, or add a `Co-authored-by: canopy worker` trailer (TRUST_MODEL T5).
- Leave a comment on the ticket describing what was done and linking the PR.
- On `blocked`: post the question as a ticket comment, add
  `needs_human_label`, do not push half-finished speculative work beyond a
  WIP commit.
- Never approve, merge, close PRs, or transition the ticket to Done, including indirectly: no closing keywords
  (`Fixes #12`) or tracker commands (Jira smart commits) in commit messages, PR titles, or PR bodies.
- Push once. Do not poll CI. Do not retry.

## 9. Aggressive release

- Slots are held only for the duration of `_run`.
- Reacquisition lands on an arbitrary slot, so build caches must be
  slot-independent (for Bazel: shared `--disk_cache` or a remote cache,
  configured in the repository, not in canopy). canopy documents this; it does
  not manage it.
- treehouse `post_create` hooks (user-level config) are the place for
  per-slot environment setup. canopy does not duplicate them.

## 10. Dependencies and stacking

Rationale in D045.

- Blocker relations are read by the overseer through MCP, in whatever form the tracker has them (Jira "is blocked by"
  links, GitHub issue dependencies, and so on; the provider skill says where to look). A blocker is resolved when it
  is closed. Other relations (relates to, parent and child) are not blockers, and a tracker without blocker relations
  leaves every ticket unblocked. A relation is data: it can delay work, never authorize it.
- A ticket with an unresolved blocker and no branch of its own is `blocked`. The overseer records `wait` with rationale
  `blocked_by: <KEY>`, unless it stacks the ticket.
- Stacking: `canopy dispatch <KEY> --kind implement --base <blocker's branch>` starts the worker from the blocker's
  branch, and the worker opens its PR against that branch, so the PR shows only this ticket's commits. The overseer
  stacks only on a ticket's single unresolved blocker, only when the blocker's PR is open, not merged, and green, and
  reads the blocker's branch from that PR, not from the journal.
- The harness checks only the shape of `--base` (`bad_base`, §8): it must be under `trust.branch_prefix` and must not
  be the run's own branch. It does not look the base up in the journal, since the blocker may be in another operator's
  queue, and it cannot read PR state (D003). `_run` fails a run whose base is not on origin (§8 `_run` step 2).
- The base is not remembered. Every dispatch starts from `--base` if given, else the pool's base branch, and the run
  records it (`runs.base_branch`, shown as the latest run's `base` in the state block). While the blocker's PR is
  open, the overseer passes the same `--base` to the stacked ticket's `resume` and `fix-ci`. Once it merges, a
  `resume` without `--base` tells the worker to retarget the PR to the repository's base branch, merging that branch in
  if it conflicts; workers never rebase, since their pushes never force.
- Ordering is a decision the overseer makes each tick from live state and
  records in `decisions`. There is no plan file and no DAG config.

## 11. State model

Schema in `migrations/0001_init.sql`. Tables and purpose:

- `ticks`: one row per tick; id, timestamps, dry_run, status, summary. Status is `running`, `ok`, `skipped`,
  `overseer_failed`, `reconcile_failed`, or `abandoned`. `canopy decisions [TICK]` prints a tick and its decisions,
  the latest tick by default: the way to read a dry run's plan. A tick that cannot take the lock writes no row,
  although the schema comment lists `lock_busy`.
- `tickets`: one row per ticket key seen; last derived phase, branch, PR URL, cursors
  (`last_comment_id`, `last_review_id`, `last_ci_run_id`), done flag. Cursors make ticks incremental. Attempt counts
  and the fix-ci cooldown are not stored; they are derived from `runs` (D030, migration 0003).
- `runs`: one row per worker execution; kind, slot, lease identity, pid of `canopy _run`, pid of the worker agent
  (`worker_pid`, migration 0002), status, result_json. Status is `running`, `done`, `blocked`, `failed` (the three the
  worker reports), `unknown`, `timeout`, `unpushed`, or `crashed`. Source for capacity, crash detection, attempt
  counts, and the fix-ci cooldown.
- `decisions`: one row per overseer decision; tick id, ticket, action,
  rationale. Audit log and prompt-evaluation corpus.
- `notifications`: one row per attention item that `notify.cmd` was told about and that is still open, keyed by a
  fingerprint of its ticket and reason, so an open item is notified once (§14).

Rules: the DB never stores tokens or raw CI logs. `result_json` is a summary.

## 12. Configuration

Configuration is layered. Each layer overrides the one before it, key by key:

1. Built-in defaults in `config.py`.
2. **Repository file**, `canopy.toml` at the repository root. Committed and shared by everyone who runs canopy on the
   repository. Optional.
3. **User file**, `$XDG_CONFIG_HOME/canopy/config.toml` (default `~/.config/canopy/config.toml`). Personal to the
   operator, never committed. Required.

Every key has a scope. A **shared** key may be set in either file, and the user file wins. A **user-only** key may be
set only in the user file. A repository file that sets a user-only key is a config error: canopy names the key and
refuses to run. Unknown keys are errors in both files.

| Key | Scope | Why |
|---|---|---|
| `tracker.provider` | shared | a property of the repository's tracker |
| `tracker.query` | shared | the repository scopes it to a project; a user may narrow it |
| `tracker.needs_human_label` | shared | a signal to people; queues are already disjoint |
| `tracker.labels` | user-only | defines this operator's queue |
| `policy.*` | shared; the repository may only tighten | limits spend and retries |
| `trust.branch_prefix`, `trust.pr_label` | shared | team conventions for spotting agent work |
| `trust.authorized_repliers` | user-only | who may steer this operator's workers |
| `capacity.*` | user-only | the operator's machine and spend |
| `loop.*` | user-only | how often the overseer runs: the operator's spend |
| `runtime.*` | user-only | commands run on the operator's machine |
| `notify.*` | user-only | a command run on the operator's machine |
| `paths.*` | user-only | where prompts and state are read from |

Anyone who can push to the repository, or any branch the operator happens to have checked out, controls the repository
file. That is why keys that run commands, choose prompts, spend money, or authorize anyone are user-only. See
TRUST_MODEL T7.

Repository file, committed:

```toml
[tracker]
provider = "jira"            # jira | github | linear | any name; selects tracker-<provider> skill
needs_human_label = "needs-human"
query = 'project = PROJ AND statusCategory != Done'

[policy]
max_implement_attempts = 2
max_fix_ci_attempts = 2
fix_ci_cooldown_minutes = 30
max_resume_attempts = 3

[trust]
branch_prefix = "agent/"
pr_label = "agent"
```

User file, personal:

```toml
[tracker]
labels = ["agent-ready-yourname"]

[capacity]
max_workers = 2

[runtime]
overseer_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer {prompt}'
worker_cmd   = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker {prompt}'
overseer_timeout_minutes = 15
worker_timeout_minutes = 45

[loop]
interval_minutes = 15   # `canopy loop` waits this long after each tick ends

[trust]
authorized_repliers = ["tracker-account-id"]   # Jira accountId, GitHub login, ...

[paths]
prompt_overrides = "~/.config/canopy/prompts"
state_dir = "~/.canopy"

[notify]
cmd = ""   # optional; receives the attention diff on stdin
```

Built-in defaults are the values shown above, except `tracker.provider`, `tracker.query`, and `tracker.labels`, which
have no default and must be set, and `trust.authorized_repliers`, which defaults to empty (nobody can resume blocked
work).

Rules:

- **Queues are per operator.** `tracker.labels` is a non-empty list. A ticket is in this operator's queue if it carries
  any of them. Two operators must never share a label: the guards (one worker per ticket, attempt limits, cooldowns)
  see only the local journal, so two loops on one label both work the same tickets. canopy cannot detect this; choosing
  distinct labels is an operator responsibility (TRUST_MODEL §7).
- **The repository may only tighten policy.** A `policy.*` value from the repository file is used only if it is
  stricter than the built-in default: a lower attempt limit or a longer cooldown. Otherwise the default stands. The user
  file may set any value, including a looser one: repository policy is a shared default, not a limit a team can impose
  on an operator. The operator is fully trusted (TRUST_MODEL §3), and a harness on their machine could not enforce one
  anyway. The rule exists so a commit cannot loosen limits for operators who never set them.
- `trust.branch_prefix` must be non-empty and end in `/`, and is made of plain ref components: letters, digits, `_`,
  and `-`, each starting with a letter or digit, joined by `/`. Branch names reach git's argv.
- `canopy init` writes the user file if it is missing, with `tracker.labels = ["agent-ready-<$USER>"]`, and prints the
  label. It writes `canopy.toml` only if the repository has none. It never overwrites either file, and installs nothing
  else (§13). If the config does not load, for example a user file from an earlier canopy whose templates lack
  `{definitions_dir}`, it prints the error. It warns about copies of canopy's agent definitions in the repository's
  OpenCode config, which earlier versions installed there and which now stop runs (§13).
- Remotes should be HTTPS with a credential helper, not SSH (D038). `canopy init` runs
  `git remote get-url --push --all origin`, which applies `insteadOf` and `pushInsteadOf` rewrites, and prints a
  warning naming every URL git would reach over SSH: `ssh://`, `git+ssh://`, or the scp-like `[user@]host:path`. It
  is only a warning. Init still succeeds, and nothing else in canopy checks the remote.
- Reading is `tomllib`, merging is a key-by-key dict merge, and validation is pydantic models that carry each key's
  type, default, scope, and tighten direction (D026). Scope and tighten checks run per file before the merge, so errors
  name the file that caused them.

A command template is split into words with shell quoting rules (`shlex`), then `{prompt}` and `{definitions_dir}` are
replaced inside each word in one pass. No shell runs, so the prompt always lands in exactly one argument whatever it
contains (D023). Both templates must contain `{prompt}` exactly once and `{definitions_dir}`, the directory canopy's
agent definitions are in (§13), at least once; a template without it is a config error that prints the line to write
instead. The check catches templates from before D040; it cannot tell where the runtime reads the value. A template
that passes the directory somewhere OpenCode does not read it runs OpenCode's default agent, which allows everything, so
a custom template, such as a sandbox wrapper's, must still end up setting `OPENCODE_CONFIG_DIR` to it. `env` in the
default templates is the ordinary program, not a shell. `notify.cmd` is split the same way, gets its input on stdin, and
must not contain `{prompt}`.

Overrides in `prompt_overrides` replace files of the same name in `prompts/`. The default is `prompts/` next to the user
file, `~/.config/canopy/prompts` unless `XDG_CONFIG_HOME` says otherwise, and an empty value means the default.
`paths.*` values must be absolute or start with `~`: canopy runs from the repository root, so a relative path would let
the repository supply the operator's prompts or state (TRUST_MODEL T7).

`tracker.provider` is a free-form name. The harness does not branch on it; it passes it into prompts, which name the
`tracker-<provider>` skill; every shipped skill is in the definitions directory (§13). `tracker.query` is how the
overseer finds candidates: in the tracker's own search syntax where it has one (JQL, GitHub issue search), otherwise a
plain-language description. It finds tickets; it does not authorize them. See §17. The repository's query usually
leaves the label out; an operator can override it in the user file to include their labels and save the overseer some
reads.

## 13. Agent runtime

OpenCode. The harness depends on exactly one capability: run a named agent
non-interactively in a given cwd with a prompt, and read its stdout. That is
`opencode run --agent <name>`. Everything else (MCP connectivity, OAuth, tool
permissions) is the runtime's job.

Agent definitions ship in `agents/`, and agent runs load them from a directory canopy owns (below):

- `canopy-overseer`: read-only tools plus bash restricted to `canopy *` and `treehouse status*`. MCP: the tracker,
  GitHub.
- `canopy-worker`: edit and bash allowed within the worktree. MCP: the tracker (ticket comments, labels), GitHub
  (open/update PR, read reviews and checks).

When the tracker is GitHub Issues, the tracker and GitHub are the same MCP server.

The runtime is swappable by editing the two command templates. No interface.

### Where the runtime finds canopy's definitions

Rationale in D040 and D044.

canopy snapshots its bundled `agents/` and `skills/` into `<state_dir>/runtime/<digest>/`, named for a digest of their
contents (`definitions.py`). A snapshot is written to a temporary directory, renamed into place, and never changed by
canopy, so overlapping runs never load a partial set. The overseer run and each `_run` use the snapshot for the
installed canopy, creating it if missing. Reconcile removes other snapshots, and temporary directories more than an
hour old, when no run is live: a live run may be one of an earlier canopy, still loading its snapshot. OpenCode scans
both `agent/` and `agents/` (and `skill/` and `skills/`) in a config directory, and writes a `.gitignore` and a
`node_modules/` into each one it loads, the snapshot included.

Command templates name the current snapshot with `{definitions_dir}` (§12), which must appear in every template that
runs a canopy-shipped agent (`overseer_cmd`, `worker_cmd`, §19's `chore_cmd`, and §21's `review_cmd`):

```toml
overseer_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer {prompt}'
worker_cmd   = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker {prompt}'
```

Nothing is installed into repositories, and a leased worktree always has the definitions its run names. OpenCode merges
`OPENCODE_CONFIG_DIR` after the repository's config. A repository's definition of one of canopy's agents is merged into
canopy's, not replaced by it, and could loosen its bash rules (D044). So before starting an agent, the harness looks at
the OpenCode config in the directory the agent will start in (the repository root for the overseer, the worktree on the
run's branch for a worker) and refuses to start if it defines one of canopy's agents: a file named for one under
`.opencode/{agent,agents,mode,modes}/`, or an `opencode.json` or `opencode.jsonc` at the root or in `.opencode/` whose
text names one. The overseer's refusal fails the tick (`overseer_failed`, summary naming the files); a worker's is a
`crashed` run whose note names them, and its slot is returned. `canopy init` warns about the same files.

Customizing canopy is adding skills where the runtime already looks: in the repository (`.agents/skills/`,
`.claude/skills/`, `.opencode/skill/`) or the operator's home (`~/.agents/skills/`, `~/.claude/skills/`,
`~/.config/opencode/skill/`). canopy turns none of these off. Give a custom skill its own name; two skills with the same
name do not reliably override each other. A skill in `$HOME` that workers use must be a single `SKILL.md`: the worker's
`external_directory: deny` lets it load the skill but not read files next to it outside the worktree. A repository can
also define agents of its own under other names, MCP servers, and permissions (TRUST_MODEL T7).

### The operator's skill

Rationale in D047.

`canopy skill` prints a skill named `canopy` that teaches an agent in the operator's own session the canopy CLI, where
the state directory's files are, how to read the journal read-only, and how to answer "why was KEY not picked up".
canopy installs it nowhere: the operator saves it where their runtime reads skills, such as
`~/.agents/skills/canopy/SKILL.md`, and saves it again after upgrading. It is not in the definitions snapshot, so a copy
in `$HOME`, which canopy's own runs also load, never meets a second skill of the same name. Since those runs may load
it, it opens by telling an agent started by canopy (`CANOPY_TICK_ID` set, or a canopy prompt) to follow its prompt
instead. It grants nothing: the overseer's and worker's bash rules are what they run with either way.

## 14. Attention list

Rendered to `<state_dir>/attention.md` (`~/.canopy/attention.md` by default), readable only by the operator, after
every tick: grouped by reason, one line per item with ticket key, age, and detail (usually a link). Reasons are exactly
the attention rows in the phase table plus `crashed`, `unpushed`, `unknown_result`, `worker_failed`, `attempt_limit`.
`canopy status` prints the list too. Items disappear when their cause is gone; no manual dismissal.

The harness raises the run reasons itself, every tick, after reconcile (D028). A ticket not marked done whose latest run
ended `crashed` is `crashed`; `unpushed` is `unpushed`; `unknown` or `timeout` is `unknown_result`; `failed` is
`worker_failed`. The detail names the run, its kind and branch, the harness note or the worker's summary, and the run
log. The cause is gone when a newer run starts for the ticket or the ticket is marked done. The overseer does not
dispatch such a ticket again until an authorized replier has commented after the run ended; that is how a human says
"try again".

The overseer records an item with `canopy attention <KEY> <reason> --detail "<link or text>"`, every tick the cause
holds. It is stored as a decision with action `attention:<reason>`; there is no separate table (D020). The current list
is the attention decisions of the latest `ok` tick, so an item disappears the first tick that does not record it, and a
failed or `skipped` tick leaves the previous list standing. Dry-run ticks count like live ones. An item's age runs from
the first tick of its unbroken run. Reasons must match `[a-z][a-z0-9_]*`.

`attempt_limit` is raised both ways: the overseer records it when the state block shows a ticket at its limit for the
work it needs, and `canopy dispatch` records it with an `attempt_limit` refusal. Either way it lasts as long as the
overseer keeps asking for that work.

Notification (D032). An item is identified by its ticket and reason; its detail can be reworded without making it new.
When `notify.cmd` is set, each tick compares the list with the `notifications` table: items not in the table are new,
and rows whose item is no longer listed are resolved. If either exists, the command gets one message on stdin, a
summary line, a `+ KEY reason: detail` line per new item, a `- KEY reason` line per resolved one, and the path of
`attention.md`. Only when it exits 0 within 60 seconds are new items added to the table and resolved ones removed, so a
failed notification is retried next tick, an open item is never notified twice, and an item that comes back after
going away is new again.

## 15. Failure handling

- Worker crash: detected by pid liveness in reconcile; what is left of the worker is killed; slot returned; ticket
  goes to attention with `crashed`. Not auto-redispatched: the harness never restarts a run, and the overseer prompt
  waits for an authorized reply (§14). Every kind has an attempt limit in code, so an overseer that redispatches
  anyway stops at `policy.max_<kind>_attempts` (D030).
- Worker exits without a result, times out, reports `failed`, or leaves commits unpushed: `_run` returns the slot and
  records the status; the ticket goes to attention (§14).
- Stale lease without a run: returned in reconcile.
- treehouse unavailable or failing in reconcile: tick closes with `reconcile_failed`; the overseer does not run.
- Overseer timeout or bad output: tick closes with `overseer_failed`; nothing
  is dispatched; next tick retries. Three consecutive failures produce an
  attention item.
- MCP unavailable: the overseer reports it with a tick-wide `skip`; the tick closes as `skipped` and `canopy tick`
  exits 1; no decisions are made on partial data, and the attention list stays as it was (D037). The overseer prompt
  says so explicitly.
- Overseer asks for something the guards refuse: the refusal is recorded as a
  decision with the guard's reason.
- An error the tick code does not handle, in a tick `canopy loop` runs: the tick ends as `error` in the loop's output,
  the traceback is logged, and the loop goes on. The next tick closes the row as `abandoned` (§6).

## 16. Open questions

- Whether `ask` permissions in OpenCode agent definitions block or auto-deny
  under `opencode run`. Answered from OpenCode's source in M1: `ask` is auto-rejected and `deny` is enforced (D021).
  The live canary (`tests/canopy/test_opencode_canary.py`) is opt-in; its first real run confirms or overturns this.
- Whether a Slack notification path should use `notify.cmd` with a small script or the overseer posting via MCP.
  Planned answer (§20, D035): a sink command, with a Slack sink shipped in canopy. The overseer does not post.
- Whether `merged` should trigger a tracker transition. Default no; humans own
  ticket state.
- One operator on several repositories. The user file is shared across them, and `state_dir` and the lock are global.
  Whether the user file needs per-repository tables, and whether state should be per repository, stays open until
  someone does it. Planned answer: a workspace (§18), which keeps its own state and holds one queue for several
  repositories.

## 17. Trackers

canopy works with any issue tracker the agent runtime can reach through an MCP server. There is no adapter interface and
no tracker code in the harness. What differs between trackers is handled in three places, in order of preference:

1. **The contract below.** Agents can map it onto the tools a tracker's MCP server exposes without being told how. This
   is the default for any tracker.
2. **Config.** `tracker.provider`, `tracker.query`, the queue labels, `needs_human_label`, and
   `trust.authorized_repliers` in the tracker's own identity format.
3. **A provider skill**, `.agents/skills/tracker-<provider>/SKILL.md`, for what an agent would otherwise get wrong:
   identity fields, how "closed" is expressed, where blockers live, and text that silently triggers a tracker action
   (closing keywords, smart commits). Skills ship for `jira` and `github`. A skill is optional; add one when the
   `decisions` table shows the loop misreading a tracker, not in advance.

### Contract

What the loop needs from a tracker, stated as capabilities. Each is used by the role in parentheses.

| Capability | Used for |
|---|---|
| Find open tickets matching `tracker.query` (overseer) | candidate set |
| Read a ticket: title, body, labels, open or closed (both) | phase, task |
| List comments with a stable id, author account id, and timestamp (overseer) | cursors, authorized replies |
| Post a comment (worker) | reports and questions |
| Add and remove a label (worker) | `needs_human_label` |
| Read blocker relations (overseer, optional) | ordering, stacking |
| When a label was added (overseer, optional) | `human_replied` |

"Label" means the tracker's tagging primitive, whatever it is called. Without blocker relations, tickets are treated as
unblocked. Without label history, the worker's question comment is the reference point for `human_replied`. If a tracker
cannot do one of the required rows, the overseer records `skip` with rationale `tracker_unsupported: <capability>` and
the operator fixes the MCP setup or writes a skill.

### Authorization is the same everywhere

The query only finds tickets. A ticket is a candidate only if reading it shows one of `tracker.labels` present and the
ticket not closed. A sloppy or plain-language query can therefore waste a tick, but it cannot authorize work. Replies
are authorized only by `trust.authorized_repliers`, compared against the author's stable account id (Jira `accountId`,
GitHub login), never a display name.

### Ticket keys

A key is the tracker's short, human-readable id, as the provider skill defines it: `PROJ-123` for Jira, `GH-123` for
GitHub Issues. Keys appear in branch names, lease holders, file paths, and shell arguments, so `canopy dispatch`,
`decide`, `attention`, and `ticket set` reject any key that does not match `[A-Za-z0-9][A-Za-z0-9_-]*`. That guard is in
code.

## 18. Workspaces and multi-repo tickets

Planned for ROADMAP M6 to M8; none of it is built. Earlier sections describe one repository, which becomes the
workspace of one below. Rationale in D033.

### Shape

A workspace is a directory canopy manages. It holds a map of the repositories a queue's tickets touch, one primary
clone of each, the worktree pools, and canopy's state for that workspace. The loop runs from the workspace root.

```
~/work/acme/                 workspace root; canopy tick runs here
  canopy-workspace.toml      the map, and the shared config layer
  MAP.md                     prose: what each repository owns and how they depend on each other
  repos/api/                 primary clones, one per repository in the map
  repos/web/
  .treehouse/                every repository's treehouse pool
  desks/PROJ-12/             one per running worker: a link to each worktree its run leased
    api -> ../../.treehouse/<api pool>/3/api
    web -> ../../.treehouse/<web pool>/1/web
  .canopy/                   journal, locks, logs, attention.md; operator-only
```

A repository with no workspace file is a workspace of one: its map is the repository itself, its `canopy.toml` plays
the workspace file's part, and state and pools stay where §12 and treehouse put them today. There is one code path.

### The map

```toml
[workspace]
name = "acme"

[repos.api]
url = "https://github.com/acme/api.git"
summary = "Public REST API. Owns the order schema and the generated OpenAPI spec."

[repos.web]
url = "https://github.com/acme/web.git"
summary = "Customer web app. Consumes the api's generated client from a release."

# [tracker], [policy], [trust]: the shared keys of §12, as in a repository's canopy.toml.
```

- A repository name matches `[a-z][a-z0-9-]*`. It is a directory name, a treehouse leaf, and a `--repo` argument. The
  clone lives at `repos/<name>`, which is not configurable, so a map cannot point canopy outside the workspace.
- `summary` is one line, at most 200 characters, rendered into the overseer's state block. `MAP.md` is prose the
  overseer and workers read themselves: ownership, dependency direction, where contracts live, the order in which
  cross-repository changes land. Both are data, like ticket text. They help choose repositories and authorize nothing.
- Config layers are built-in defaults, the workspace file, then the user file. The workspace file takes the repository
  file's place with the same scopes and the same rule that repository policy may only tighten. The repositories' own
  `canopy.toml` files are not read inside a workspace: a workspace has one tracker and one queue.
- The map may be committed to a shared workspace repository, so a team maintains it together. It is then exposed like
  a repository file (TRUST_MODEL T7) and gets the same controls. `url` is read only by `canopy workspace sync`, an
  operator command that prints what it clones before cloning. Map URLs should be HTTPS (D038); `sync` warns about SSH
  ones as `canopy init` does and clones them anyway. A tick never clones a repository or changes a remote; a
  repository in the map with no clone is an attention item, `repo_missing`, and cannot be dispatched to.
- `canopy init --workspace` writes the skeleton and a `.gitignore` covering `repos/`, `.treehouse/`, `desks/`, and
  `.canopy/`.
- A workspace's state is always `<workspace>/.canopy/`, created readable only by the operator; `paths.state_dir`
  applies only to a workspace of one. Each workspace therefore has its own journal and locks.

### Worktrees live in the workspace

Every treehouse command canopy runs gets `TREEHOUSE_ROOT` set to the workspace root and runs in the repository's
primary clone, so each pool lives under `<workspace>/.treehouse/`. The variable outranks both treehouse config files,
so a repository's own `treehouse.toml` cannot move canopy's pools. `get` also passes
`--worktree-path '{pool}/{slot}/{repo}'`, pinning the layout the same way. canopy's pools are separate from the
operator's interactive ones under `~/.treehouse`, so an interactive `treehouse` never recycles a slot canopy uses, and
deleting the workspace removes everything canopy made. Build caches still have to be slot-independent (§9).

Reconcile runs `treehouse status --json` once per repository in the map and returns stale `canopy:` leases in each
pool. The overseer runs from the workspace root, which is not a repository, so the state block carries each pool's
leased slots in place of the overseer's own `treehouse status`. Lease holders stay `canopy:<KEY>`; pools are per
repository, so one ticket can hold a slot in several.

### Units

A ticket's work is divided into units, one per repository it changes. A unit has its own branch, PR, phase, review
and CI cursors, and attempt counts. The comment cursor stays per ticket. A single-repository ticket has one unit and
behaves as today.

A ticket's units are the repositories it has been dispatched to. Each dispatch names the units it covers with `--repo`
(repeatable; optional in a workspace of one), chosen by the overseer from the ticket, the summaries, and `MAP.md`. An
`implement` over several repositories is a joint change: one worker holds the whole change in one context and opens one
PR per repository, each linking the others. That is for changes that cannot build or pass tests separately, such as an
API and its client changed in lockstep, or a schema and the code reading it. `fix-ci` and `resume` normally name only
the unit whose PR needs the work.

A ticket that covers several repositories but is really several pieces of work is split instead (below). The overseer
prompt prefers splitting and implements jointly only when the ticket or `MAP.md` shows the halves cannot stand alone.

Guards (§8) change as follows:

- `running` stays per ticket: one worker per ticket, whatever its units (TRUST_MODEL §6).
- `unknown_repo`: a `--repo` not in the map, with no primary clone, or, for a split child, not the one recorded.
- `no_branch`: `fix-ci` and `resume` for a unit with no branch.
- `attempt_limit` counts per unit: a run counts against every unit it covers.
- `capacity` counts runs, not slots. A joint run over three repositories is one worker holding three slots.
- `no_slot`: leases are all or nothing. If any `treehouse get` fails, the slots already leased are returned before
  the refusal is recorded.

### Runs over several repositories

- The branch is `<trust.branch_prefix><KEY>-<slug>` in every repository. The slug is fixed by the ticket's first
  `implement`; later implements of other units reuse it and refuse `--slug`.
- `_run` does its branch setup (§8 step 2) and push verification (step 5) in each worktree, creates the desk with one
  link per worktree, and runs the worker with the desk as cwd. The trap removes the desk and returns every slot. A run
  is `unpushed` if any repository's branch is.
- The worker prompt lists each repository: its name, path in the desk, branch, base, the unit's PR if there is one,
  and its summary.
- The result contract's `"pr"` becomes `"prs"`, an object from repository name to PR URL or null. `tickets.pr_url`
  becomes the unit's.
- Worker obligations add: each PR's body links its sibling PRs and says which to merge first; the ticket comment lists
  every PR. Workers still never merge.

### Splitting

canopy splits a ticket in the tracker, and never schedules what it split. The children are ordinary tickets that start
without a queue label, so a human authorizes each one exactly as they authorize any ticket (TRUST_MODEL T1).

- The overseer dispatches `canopy dispatch <KEY> --kind split --repo api --repo web`. The overseer is read-only, so the
  tracker writes happen in a worker, like every other write.
- The split worker runs as `canopy-splitter`: a separate agent definition with read-only file and shell tools and the
  tracker MCP tools to create a ticket, link tickets, and comment. It has no label tools and no GitHub write tools. It
  runs in a desk of the named repositories' worktrees so it can read the code, and it pushes nothing. Where the
  runtime can restrict a create tool's arguments, the definition forbids labels on create; where it cannot, the check
  below still holds.
- It creates one child per repository. Each child's body names its repository (`canopy-repo: web`) for people to
  read, links the parent, and says what the child covers. Children that must land in order get the
  tracker's blocker relation (`web` is blocked by `api`), so M4's ordering works them in order. Children carry no
  queue label and are not assigned to anyone.
- On the parent it posts a comment listing the children and saying which label starts each one. Its result line adds
  `"children": {"PROJ-13": "api", "PROJ-14": "web"}`, each child's key and repository. `_run` validates it: every key
  a valid ticket key (§17), every repository one the split was dispatched with, each at most once. Anything else makes
  the run's status `unknown` and records nothing. A valid result is recorded in `split_children`, and a child's
  repository comes from there afterwards.
- The parent's phase becomes `split`: wait, with an attention item `split_unlabeled` naming each child that is still
  open and unlabeled. The overseer marks the parent `done` in the journal once every child is closed. canopy does not
  touch the parent's tracker state.
- A child is a candidate only if its queue label was added after the split run ended. The state block carries each
  split run's end time and children, and the overseer compares it with the tracker's label history. A label the split
  worker added itself, at creation or later, is therefore not counted, whatever the permissions allowed; the overseer
  records attention `split_self_labeled` for that child instead, and it stays out of the queue until a human removes
  the label and adds it again. A tracker without label history (the optional row of §17's contract) cannot tell the
  two apart, so there the overseer records `skip` with `tracker_unsupported: label history` instead of dispatching
  `split`.
- This check is the overseer's, not a harness guard: the harness never reads the tracker (D003), so it cannot see
  labels at all. It is the same kind of control as the check that a ticket carries a queue label in the first place
  (§17), and it has the same residual, stated in the trust model changes below.
- `split` has an attempt limit like every kind, `policy.max_split_attempts`, default 1.
- A child's work is ordinary: it is a one-repository ticket. `canopy dispatch` for a key in `split_children` refuses
  any `--repo` other than the one recorded there (`unknown_repo`), so editing the child's `canopy-repo` line later
  changes nothing. A ticket a human splits by hand has no such row; the overseer chooses its repository as for any
  ticket.

### Journal

- `ticket_units`: ticket key, repository, branch, PR URL, phase, `last_review_id`, `last_ci_run_id`. The ticket's
  displayed phase is its least advanced unit's.
- `run_slots`: run id, repository, slot path, lease id, lease holder, base branch. It replaces the slot columns of
  `runs` for new runs.
- `split_children`: parent key, child key, repository, split run id. Written only by `_run` from a validated split
  result.
- `tickets.repo` holds the workspace name.
- Attention items carry an optional repository, and an item is identified by ticket, repository, and reason, so two
  units at their fix-ci limit are two items. `canopy attention` takes `--repo`.

### Trust model changes needed

TRUST_MODEL is unchanged until the milestone that needs each change, whose PR carries the human approval:

- T1: the loop may create tickets, but never with a queue label. What a split creates starts only when a human labels
  it, and a label added during the split run does not count. The check is in the overseer prompt, backed by the
  splitter's permissions, because the harness cannot read the tracker. Residual: canopy acts as the operator, so the
  tracker cannot say who added a label, only when; a steered overseer that ignores the check can dispatch a
  self-labeled child, as it could dispatch an unlabeled ticket today.
- T4: a worker's edit permission covers the worktrees linked from its desk. M7 runs a canary like D021's to show that
  OpenCode's permission check allows edits through the desk's links and still denies paths outside them.
- T6: the write scope is the repositories of the units the run covers, not one repository. The splitter's is creating
  tickets, linking them, and commenting on the parent.
- T7: the workspace file is a repository file for this purpose. Clone URLs are read only by an operator command.
- §7: branch protection is needed in every repository in the map; `canopy init --workspace` prints the rules for each.

### Open

- Whether an unlabeled child should become a candidate when an authorized replier approves the split on the parent,
  instead of a label on each child.
- Whether a child's desk should also hold its blockers' unmerged branches, read-only by prompt, so the worker can build
  against them before they merge.
- Whether the overseer should ever split a ticket it has already started implementing jointly.

## 19. Chores

Planned for ROADMAP M9; none of it is built. Rationale in D034. Earlier sections describe the loop without chores; M9
updates them when it builds this: §5 gains the `chores` package (`_chore` and chore reconcile) and `cli/chores.py` (the
`canopy chore` commands), the overseer's role gains `canopy chore run` and `canopy chore wait`, §6 step 3 reconciles
chore runs, §11 lists `chore_runs`, §12 the chore keys, and §14 the chore items.

A chore is recurring work the operator defines and the overseer delegates: an agent run that is not about one of the
queue's tickets, holds no worktree, pushes nothing, and reports findings to the attention list. The motivating chore is
a build-health check: look at the CI build queue and recent builds, including other people's PRs, and report flaky
jobs, stuck builds, and PRs that have been waiting too long. Finding those takes judgment over logs and history, so it
is an agent run, possibly driving deterministic tooling the operator already has.

The operator writes the chore; the overseer only chooses when to run it, within limits the harness enforces. That keeps
the split of §4: the operator's config says what a chore is and the fastest it may recur, the overseer's judgment says
whether now is a good time, and a guard in code holds the limits whatever the overseer asks for.

### Definition

Chores are user-only config (§12): a chore names a prompt and a command, and spends money, so a repository file that
defines one is a config error (TRUST_MODEL T7).

```toml
[runtime]
chore_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore {prompt}'   # default

[capacity]
max_chores = 1            # chore runs at once; separate from max_workers

[chores.build-health]
prompt = "~/.config/canopy/chores/build-health.md"
cmd = 'opencode run --agent build-health {prompt}'
every_minutes = 120
when = """Weekdays, 08:00 to 18:00 America/New_York.
Skip it when the last run found nothing and nothing has merged to main since."""
timeout_minutes = 20
cwd = "~/src/build-tools"
```

- A chore name matches `[a-z][a-z0-9-]*`. It appears in file paths and on the command line.
- `prompt` is the operator's own file, absolute or starting with `~` like every `paths.*` value. Required.
- `cmd` is a command template with the rules of §12 (`{prompt}` exactly once, no shell). It defaults to
  `runtime.chore_cmd`. A chore that runs the operator's own tooling needs its own agent definition to allow it (below),
  so `cmd` is usually set.
- `every_minutes` is the shortest time between the starts of two runs, at least 15. It is a guard, not a schedule.
- `when` is plain language for the overseer: the hours a chore is worth running, and conditions that make a run
  pointless or urgent. Optional; without it the overseer runs a chore whenever it is due. It is operator-written, so it
  is an instruction, unlike anything a chore reads.
- `timeout_minutes` defaults to 15. `cwd` is where the chore runs, absolute or starting with `~`; by default a
  directory of its own, `<state_dir>/chores/<name>/`, created readable only by the operator.

### Off unless configured

Chores are opt-in and isolated, so one that turns out badly costs the operator a config edit, not a change to the loop:

- With no `[chores.*]` tables, nothing about chores reaches the overseer: the state block has no `chores` key, no
  chore decisions are recorded, and every `canopy chore run` refuses as `unknown_chore`. The overseer prompt's chore
  paragraph says to skip it when the key is absent. Ticket handling is the same as without M9.
- `capacity.max_chores = 0` turns every chore off without deleting any: the state block leaves them out, as above.
- Deleting a chore's table turns that chore off. The attention list shows only configured chores, so its findings and
  `chore_failed` item disappear at the next render and are notified as resolved (D032). Its `chore_runs` rows stay as
  history.
- Chores never change what the overseer does with tickets (below), so a noisy chore can clutter the attention list but
  cannot make the loop dispatch, or fail to dispatch, anything.

### Agent definitions and tooling

canopy ships `canopy-chore` in the definitions directory (§13) like the other definitions: no edits, no subagents, no
bash, and no MCP write tools where the runtime can deny them by name. It can read the tracker and GitHub, including PRs
that are not the operator's.

A chore that uses the operator's deterministic tools gets its own definition, copied from `canopy-chore` into the
operator's own runtime config (for OpenCode, `~/.config/opencode/agent/`, not the repository's `.opencode/agent/`, which
anyone who can push to the repository controls), with bash allowed for exactly those tools:

```yaml
permission:
  edit: deny
  task: deny
  bash:
    "*": deny
    "buildq *": allow        # the operator's read-only CLI for the build queue
```

The tools are the operator's to install: on `PATH` (`uv tool install` from the repository that holds them), or run from
a checkout that `cwd` points at. Credentials for CI systems belong to those tools or to the runtime's MCP servers, as
for the tracker (§4, principle 5). canopy never sees them and knows nothing about Jenkins, or any other CI system,
beyond what the operator's prompt says.

### Delegation

- The state block gains `chores`: for each configured chore its name, `every_minutes`, `when`, `due_at` (the earliest
  time the guard allows a new run), whether it is running, its latest run (id, status, start, end, summary), and its
  open findings (id, title, link), which are those of its latest `ok` run (below). A latest run that ended otherwise
  therefore shows its status and summary without replacing the findings.
- Each tick the overseer considers every chore whose `due_at` has passed and that is not running. It runs the chore
  with `canopy chore run <NAME> [--context '<text>']`, or records `canopy chore wait <NAME> --rationale "<text>"` when
  `when` says not now. Chores that are not due need no decision.
- `--context` follows D031: at most 2000 characters that point at what to look at (a PR, a job name, a build number),
  never a quote of untrusted text. An empty one renders as "None."
- Findings in the state block are there for deciding about the chore (a `when` such as "skip it when the last run
  found nothing"). The overseer does not use them when it decides about tickets; see Open.

`canopy chore run` requires `CANOPY_TICK_ID` like `dispatch` (D020) and refuses, recording `refused:<guard>`, on the
first of:

- `unknown_chore`: no chore of that name in the user config.
- `running`: a run of this chore is running.
- `not_due`: less than `every_minutes` since this chore's latest run started, whatever that run ended as.
- `chore_capacity`: `capacity.max_chores` chore runs are running.

In a dry run it checks the same guards, records `dispatch:chore` with rationale `dry run: not dispatched` or the
refusal, and starts nothing (D036). Chore decisions
are `decisions` rows with the chore's name in a new `chore` column and no ticket key: `dispatch:chore`, `wait`, and
`refused:<guard>`. Chore runs are serialized with dispatches by the same `dispatch.lock`.

### Runs

`canopy chore run` inserts a `chore_runs` row, renders the prompt, and spawns `python -m canopy _chore <run_id>`
detached, as dispatch spawns `_run` (§8 step 4). `_chore` claims the run by pid, drops `CANOPY_TICK_ID`, runs the
chore's command in its `cwd` with its timeout, records the agent's pid, parses the result, and closes the row. Output
goes to `<state_dir>/chores/<run_id>.log`. There is no lease, branch, or push, so there is nothing to return or verify.

The prompt is the operator's file followed by a generated `## Run` section holding one JSON object: the chore's name,
the current time, the run id, the overseer's context, the latest completed run's end time, summary, and findings (id,
title, link), and the result contract. The previous findings let a chore reuse the same id for the same problem and
say when one is gone. The rendered prompt is written to `<state_dir>/chores/<run_id>.prompt`, readable only by the
operator.

Result contract, one JSON line, last line of stdout:

```json
{"status":"ok|failed","summary":"one paragraph",
 "findings":[{"id":"flaky/checkout-service/test_retry","title":"one line","detail":"a paragraph","link":"https://..."}]}
```

- `ok` means the chore did its check; no findings means nothing needs a human. `failed` means it could not check (a
  tool broke, CI unreachable) and says why in the summary.
- A finding's `id` is stable across runs for the same problem, matches `[A-Za-z0-9][A-Za-z0-9_.:/-]*`, and is at most
  200 characters. `title` is at most 200 characters, `detail` at most 2000, `link` a plain `https://` URL or absent. At
  most 20 findings; ids unique within a run.
- Validated with pydantic (D026). Anything else is `unknown`, and the findings are not recorded.

`chore_runs` status is `running`, `ok`, `failed`, `unknown`, `timeout`, or `crashed`. Reconcile (§6 step 3) treats
running chore runs as it treats running worker runs: a dead `_chore` pid means the agent's process group is killed and
the run is `crashed`. Chore runs do not count against `max_workers`.

### Findings on the attention list

- A chore's open findings are those of its latest run that ended `ok`. A finding disappears when a later `ok` run does
  not report its id, the way an item disappears when its cause is gone (§14). A run that ends any other way leaves the
  previous findings standing.
- A chore whose latest run ended `failed`, `unknown`, `timeout`, or `crashed` also has a `chore_failed` item, raised by
  the harness after reconcile as for worker runs (D028). It goes away when a later run ends `ok`.
- `attention.md` gets a section per chore after the ticket items: one line per finding with its title, age, and link.
  A finding's age runs from the first run of the unbroken sequence of `ok` runs that reported its id.
- Notification follows D032, with a finding identified by its chore and id. The message line is
  `+ chore:<name> <id>: <title> <link>`. In `notifications`, a finding's row holds `chore:<name>` in `ticket_key`, which
  no ticket key can equal since the key pattern (§17) has no colon, and its id in `reason`.

### Journal

- `chore_runs`: id, tick id, chore name, pid of `_chore`, pid of the agent, started and ended times, status,
  `result_json` (the validated result, text cut to its limits), log path. Separate from `runs`, whose ticket, slot,
  lease, and branch columns a chore does not have.
- `decisions.chore`: nullable; a row carries a ticket key or a chore name, never both.

### Trust model changes needed

TRUST_MODEL is unchanged until M9, whose PR carries the human approval:

- T1: chores read text from people outside the operator's queue (other people's PRs, build logs). Their findings are
  data wherever they go: the attention list, the notification, and the overseer's state block.
- T3: add `every_minutes`, `running`, and `capacity.max_chores` to the controls in code, and to §6: never run a chore
  more often than its `every_minutes`, or more than `capacity.max_chores` chore runs at once.
- T6: a chore's only output is its result line. The shipped definition has no write tools. Residual: a chore steered by
  what it read can put up to 20 findings of its choosing in front of the operator and into `notify.cmd`, wherever that
  sends them, and a finding's link can carry data in its URL.
- T7: chores, `runtime.chore_cmd`, and `capacity.max_chores` are user-only.
- §7: an operator who allows a tool in a chore's definition is responsible for what that tool can do. canopy's controls
  assume chore tools only read.

### Open

- Whether a chore should ever write. Commenting on or retrying someone else's build acts as the operator on other
  people's work, which D010 kept out of the MVP. The likely first write is a ticket for a finding, created without a
  queue label like a split child (§18), so a human decides whether the loop works on it.
- Whether the operator needs `canopy chore try <NAME>`, a foreground run outside any tick that prints the result and
  records nothing, for writing chore prompts. Until then, run the chore's command by hand.
- Whether findings should inform ticket decisions, once chores have a track record in the journal: a finding that a
  check is flaky could make the overseer record attention for a ticket's red PR instead of dispatching `fix-ci`.
  Findings are written by an agent that read untrusted text, so they could only ever hold work back or raise attention,
  never make a ticket a candidate. Opt-in per chore when it comes, so a chore's reports can be trusted before its
  influence is.
- Where a chore runs in a workspace (§18). Chores come from the user file, which every loop the operator runs reads, so
  once state is per workspace (M6) each workspace would run every chore. M6 either gives a chore an optional list of
  the workspaces it runs in or moves chores into a user file table per workspace.
- Whether a repository should be able to offer chores that an operator opts into by name, the way it offers its tracker
  query.

## 20. Notifications

Planned for ROADMAP M10; none of it is built. Rationale in D035. It generalizes `notify.cmd` (§14, D032), which stays
and behaves as it does today. M10 updates the earlier sections when it builds this: §5 gains the `notify` package, the
event outbox in `core`, `cli/notify.py`, and the Slack sink's workspace member, §6 step 7 delivers to sinks, §11 lists
the new tables, §12 the sink keys, and §14 points here.

Notifications reach the operator away from the terminal: issues as they happen, progress on a schedule. The first
destination is a Slack channel. The harness stays a program that runs commands: a destination is a **sink**, a command
that reads one message on stdin. canopy ships one sink, for Slack. Another destination is a small program of the
operator's, not a change to canopy.

### Sinks

```toml
[notify.sinks.slack]
cmd = "canopy-notify-slack"            # the shipped sink; reads its webhook from a file of its own
events = ["attention", "loop", "runs"]
digest_every_minutes = 240

[notify.sinks.phone]
cmd = "curl -sS --fail --data-binary @- https://ntfy.sh/my-private-topic"
format = "text"
```

- Sinks are user-only (§12), like every `notify.*` key: they run commands (TRUST_MODEL T7).
- A sink name matches `[a-z][a-z0-9-]*`. At most 5 sinks, since each can hold the tick lock for its timeout.
- `cmd` follows the rules for `notify.cmd` (§12): split into argv, no shell, no `{prompt}`. It runs with cwd the
  repository root, the message on stdin, and a 60-second timeout. Exit 0 means delivered; anything else, a timeout
  included, means try again next tick. Its stdout is ignored and the tail of its stderr is logged.
- `format` is `json` (the default) or `text`.
- `events` lists the groups the sink receives: `attention`, `loop`, `runs`. Default `["attention", "loop"]`. M9 adds
  `chores`.
- `digest_every_minutes` is optional and at least 60 (Digest, below).
- `notify.cmd = "X"` is shorthand for a sink named `default` with `cmd = "X"`, `format = "text"`,
  `events = ["attention"]`, and no digest. Setting both `notify.cmd` and `[notify.sinks.default]` is a config error.

With no `notify.cmd` and no sinks, nothing below happens: no events are recorded and publishing is §14 without the
notification.

### Events

A closed set, written by the harness from the journal. Text fields are cut to the limits shown, on one line.

| Group | Kind | When | Fields |
|---|---|---|---|
| `attention` | `attention.opened` | a listed item the sink was not told of | ticket, reason, detail (500), since |
| `attention` | `attention.resolved` | an item the sink was told of left the list | ticket, reason |
| `runs` | `run.started` | dispatch started a worker | ticket, run, kind, branch, attempt, limit |
| `runs` | `run.ended` | a run's row was closed | ticket, run, kind, status, branch, pr, summary, question |
| `loop` | `loop.failing` | the latest 3 ticks all ended other than `ok` | count, latest status and tick, its log |
| `loop` | `loop.recovered` | the first `ok` tick after `loop.failing` | how many ticks failed |
| `loop` | `loop.sink_failing` | a sink has failed 3 deliveries in a row | sink, the tail of its stderr |

`summary` and `question` are cut at 300 characters. `question` is set only for a `blocked` run; a blocked worker waits
on the ticket's needs-human label, which is not an attention item, so `run.ended` is how a sink hears that a worker
asked something.

Attention stays a diff of state, per sink (D032). `notifications` gains a `sink` column, so each sink is told about
each open item once, and a sink that was down for a day gets the net change instead of every flip. The other kinds are
point events. They are written to an outbox table, `notify_events`, in the transaction that records the fact: the
dispatch that inserts the run, whatever closes the run's row (`_run`, or reconcile marking it `crashed`), and the
publish step for `loop.*`. Each sink has a cursor in `notify_sinks`, the last event id it delivered. `loop.failing` and
`loop.sink_failing` are recorded once per streak.

The migration gives every existing `notifications` row the sink `default`, the name `notify.cmd` becomes, and keeps its
fingerprint, so an operator who upgrades with `notify.cmd` set is not told again about items already notified. If the
config has no `default` sink, those rows go at the first publish like any removed sink's (Delivery, below), and each
named sink hears about every open item once, as a new sink does.

### Delivery

§6 step 7, after `attention.md` is written, for each sink in name order:

1. Gather the sink's attention diff if it takes `attention`, its events after its cursor in the groups it takes, and a
   digest if one is due. If there is nothing, skip the sink.
2. Render one message in the sink's format and run the command.
3. On exit 0, record the diff in `notifications` for this sink, move the cursor to the newest event gathered, and set
   the digest time. On anything else, change nothing, log the failure, and count it toward `loop.sink_failing`.

Bounds:

- At most 20 attention lines and 20 events in one message. The rest are counted in a closing line that points at
  `attention.md` and `canopy status`, and count as delivered.
- Events more than 24 hours old when a sink next succeeds are counted, not listed.
- A new sink's cursor starts at the newest event, so it gets no backlog. It hears about every open attention item on
  its first delivery, as `notify.cmd` does today.
- A sink removed from the config loses its `notify_sinks` and `notifications` rows at the next publish. Events every
  sink has passed are deleted after 7 days.
- Sinks run one after another under the tick lock, so a hung sink delays the next tick by up to 60 seconds, and five
  hung sinks by five minutes.

### Digest

- A sink with `digest_every_minutes` gets a digest at its first delivery, and then at the first delivery at least that
  long after its previous one.
- The digest covers the time since the sink's previous digest, from the journal only: ticks by status; runs started,
  by kind; runs ended, by status, with each `done` run's ticket and PR and each `blocked` run's ticket; the open
  attention list, counted by reason, with the oldest item's age; the workers running now.
- It is sent even when nothing happened ("24 ticks ok, nothing ran, nothing needs you"). A digest that stops arriving
  is how the operator learns that the loop, a scheduler, or the machine stopped running ticks, which canopy itself
  cannot report.
- No model writes it. A progress report that needs judgment, such as what changed on the operator's PRs today, is a
  chore (§19). Its summary reaches sinks as a `chore.ended` event in a `chores` group. Neither exists before chores do:
  if M10 lands first, its groups are the three above, and M9 adds `chores` and `chore.ended` to this section.

### Formats

`text` is lines for a person. A message holding only attention is exactly §14's, so `notify.cmd` does not change. Other
parts add a line per event and the digest's lines after the attention lines.

`json` is one object:

```json
{"version": 1, "sink": "slack", "repo": "/home/me/src/api", "sent_at": "2026-09-24T19:00:00Z",
 "attention": {"added": [{"ticket": "PROJ-3", "reason": "needs_reviewer", "detail": "https://...", "since": "..."}],
               "resolved": [{"ticket": "PROJ-4", "reason": "ready_to_merge"}],
               "open": 4, "path": "/home/me/.canopy/attention.md"},
 "events": [{"id": 88, "kind": "run.ended", "at": "...", "ticket": "PROJ-12", "run": 41, "run_kind": "implement",
             "status": "done", "branch": "agent/PROJ-12-add-retry", "pr": "https://...", "summary": "..."}],
 "omitted": 0,
 "digest": null,
 "text": "the same message in the text format"}
```

`attention` is null for a sink that does not take it. `omitted` counts what the bounds left out. `version` changes only
on an incompatible change; sinks ignore fields they do not know. `text` lets a sink that only forwards a string read one
field.

### The Slack sink

`canopy-notify-slack` is its own distribution, the first uv workspace member (D041): `packages/canopy-notify-slack/`,
module `canopy_notify_slack`, stdlib only (`urllib.request`, `json`), importing nothing from `canopy`. `canopy` depends
on it and lists the `canopy-notify-slack` script in its own `[project.scripts]`, so the install that puts `canopy` on
`PATH` puts it there too.

- It reads the `json` format on stdin, posts one message to a Slack incoming webhook, and exits 0 on a 2xx response
  and 1 otherwise, with Slack's reply on stderr. A rate-limited post is retried by the next tick like any failure.
- The webhook URL comes from a file: `--webhook-file PATH`, default `$XDG_CONFIG_HOME/canopy/slack-webhook`
  (`~/.config/canopy/slack-webhook`). The file must belong to the operator, be unreadable by group and others, and hold
  one `https://hooks.slack.com/` URL; otherwise the sink exits 2 saying which. The URL is never in canopy's config,
  argv, journal, or logs.
- The message has a header with the repository's directory name and the counts, a line per item or event with the
  ticket key, reason or status, and link, and the digest as a short block.
- Text from the journal is escaped for Slack's markup (`&`, `<`, `>`), so text written by an agent or an org member
  cannot mention `@channel` or a person, or show one link and point at another. Bare URLs stay clickable; Slack links
  them itself.
- Setup: create a Slack app with an incoming webhook for one channel, write its URL to the file with mode 600, add the
  `[notify.sinks.slack]` table, and run `canopy notify test slack`.

Two checks keep the network out of the harness, as D015 keeps processes in `canopy.infra.procs`: ruff's banned-api rule
(`TID251`) bans `urllib.request`, `http.client`, and `socket` everywhere in `src/canopy`, with no exception, and
`tests/canopy/test_layers.py` fails on any import of `canopy_notify_slack` from `src/canopy`. The harness reaches the
Slack sink only as a configured command, like any other, so the process that holds the journal and enforces the guards
never opens a connection or reads a sink's secret.

### Commands

- `canopy notify test [SINK]` sends a `test` message to every sink, or to one, now, outside any tick, and prints each
  result. It changes no cursor and no table. It refuses when `CANOPY_TICK_ID` is set, so the overseer cannot use it to
  page the operator.
- `canopy status` gains a line per sink: its last delivery, its consecutive failures and last error, and how many
  events wait for it.

### Two-way, later

Not in M10. Two rules shape it: nothing listens on the network (TRUST_MODEL §4), and the loop runs ticks in the
foreground (§6), holding no connection between them. Slack's interactive features (buttons, slash commands, the Events
API, Socket Mode) each need a listener or a long-running connection, so they are out. What fits, in order:

1. **Replies on the ticket.** Works with M10 as designed. Every message names the ticket and carries what links the
   journal has; a question is answered on the ticket, and an authorized reply resumes the worker as it does now. Slack
   is the pager; the ticket is the conversation.
2. **Replies in Slack, read by the overseer.** The overseer reads a Slack thread through a Slack MCP server each tick,
   as it reads ticket comments, and a reply by an authorized Slack account counts as an authorized reply. That needs
   one thread per ticket (a bot token and `chat.postMessage` instead of a webhook, with the sink reporting each
   ticket's thread on stdout for the harness to record and pass into the state block), Slack account ids among the
   authorized repliers, and a TRUST_MODEL T1 change, since it adds a second place authorization comes from.

The `json` format's `version` and the sink's stdout, which M10 ignores, are where that attaches.

### Trust model changes needed

TRUST_MODEL is unchanged until M10, whose PR carries the human approval:

- T2: the harness still makes no outbound call except through configured commands and never reads a token. canopy
  now ships one program that does both, the Slack sink. It runs only as a sink the operator configured, reads its
  webhook from the operator's own file, and lint keeps network modules and the sink out of the harness.
- T6: notifications carry text written by agents and org members (attention details, worker summaries and questions)
  off the machine to wherever a sink sends it. Controls: the harness sends only the fields in the table above, cut to
  their limits; the Slack sink escapes text so it cannot mention anyone or disguise a link. Residual: a steered agent
  chooses up to 500 characters per item that appear in the operator's channel, and a link can carry data in its URL,
  as §19 says of chore findings.
- §7: point a sink only at a place whose audience may read the tickets and PRs it quotes, and keep the webhook file
  readable only by the operator. People who can read the channel see what the loop does; they cannot steer it.

### Open

- Routing finer than groups (D032's revisit), such as `crashed` to a phone and `needs_reviewer` to Slack only.
- Digests at fixed times of day instead of an interval.
- Reminders for items open longer than some threshold.
- Links to tickets. The harness knows no tracker URLs (D003); a `tracker.ticket_url` template would let every message
  link its ticket.
- A sink secret read from a command (a password manager's CLI) instead of a file.

## 21. Reviews

Planned for ROADMAP M11; none of it is built. Rationale in D039. Earlier sections describe the loop without reviews; M11
updates them when it builds this: §5 gains the `reviews` package (`_review` and review reconcile) and `cli/reviews.py`
(`canopy review`), the overseer's role gains `canopy review run` and `canopy review wait`, §6 step 3 reconciles review
runs, §7 gains the phases below, §11 lists `review_runs` and `decisions.pr`, §12 the review keys, §13 the
`canopy-reviewer` definition, §14 the review items, and §20 a `reviews` event group.

A review is an adversarial read of one PR at one commit by a fresh agent run: no transcript of whoever wrote the
change, told to assume the change is wrong until the code shows otherwise. It posts one comment on the PR that says
what it is, and reports a verdict. It never approves, requests changes, pushes, or merges. Human review stays the gate
(§3); a review is there to make that review cheaper, and to catch what the author's own run could not see.

Two kinds of PR get reviews, and neither needs a ticket:

- **The loop's own PRs.** With `review.agent_prs` on, a ticket's PR is reviewed once its checks pass, before the
  overseer asks a human for review. Findings go back to a worker through `resume`, like a human's review comments.
- **PRs the operator names with `review.query`,** usually their own hand-written ones. These are reviewed and nothing
  else: the loop never pushes to them, fixes them, or opens a ticket for them. The comment on the PR is the whole
  output, and the operator decides what to do with it.

### Configuration

Every review key is user-only (§12), except the per-PR limit, which is a shared policy that the repository may only
tighten. A review spends money, runs a command, and comments as the operator (TRUST_MODEL T7).

```toml
[review]
agent_prs = true
query = 'repo:acme/api is:pr is:open author:@me -is:draft'
low_impact = """Only docs, comments, or tests change; or one dependency moves by a patch version."""

[runtime]
review_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer {prompt}'
review_timeout_minutes = 20

[capacity]
max_reviews = 1            # review runs at once, within max_workers; 0 turns reviews off
max_reviews_per_day = 20   # review runs started in any 24 hours

[policy]
max_reviews_per_pr = 3     # shared; the repository may only lower it
```

- `agent_prs` defaults to false. `query` is the VCS host's own PR search syntax, as `tracker.query` is the tracker's.
  It is empty by default, meaning no PRs besides the loop's own.
- `review.query` authorizes, unlike `tracker.query` (§17): only the operator writes it. It authorizes whatever it
  matches, so a query without an author filter sends reviews to other people's PRs, in the operator's name. That is
  allowed, and it is how a team gets reviews on every low-impact PR, but it is the operator's choice to make
  (TRUST_MODEL §7).
- `low_impact` is plain language for the reviewer, like a chore's `when`: which changes it may call `low`. Without it,
  the reviewer never reports `low`.
- `review_cmd` follows the rules for command templates (§12). Pointing it at a different model from `worker_cmd` is
  recommended, so the reviewer does not share the author's blind spots.

### Off unless configured

With no `[review]` table, or `capacity.max_reviews = 0`, nothing about reviews reaches the overseer: the state block
has no `reviews` key, the phase table is §7's as it stands, and every `canopy review run` refuses as `reviews_off`. A
test holds this. With `agent_prs` off, the phase table is also unchanged. A loop PR that `query` happens to match is
then reviewed like any other match: one comment, and no `resume` for its findings.

### Running a review

`canopy review run --pr URL --sha SHA [--ticket KEY] [--context '<text>']` requires `CANOPY_TICK_ID` like `dispatch`
(D020). `URL` is the PR's `https://` URL, which the harness treats as an opaque string and never parses. `SHA` is the
full head commit the overseer read. `--ticket` links an agent PR to its ticket. Under the dispatch lock, it refuses,
recording `refused:<guard>`, on the first of:

- `reviews_off`: see above.
- `bad_pr`: `URL` is not a plain `https://` URL of at most 300 characters, `SHA` is not 40 or 64 lowercase hex
  characters, or `--ticket` is not a valid key (§17).
- `running`: a review of this PR is running, or, with `--ticket`, a worker run for that ticket is: a review must not
  race the push it is meant to judge.
- `reviewed`: a review of this PR at this commit ended `done`. One review per commit, whatever the overseer asks.
- `review_limit`: this PR has had `policy.max_reviews_per_pr` review runs, whatever they ended as. This also records
  the `review_limit` attention item.
- `daily_limit`: `capacity.max_reviews_per_day` review runs started in the last 24 hours.
- `review_capacity`: `capacity.max_reviews` review runs are running.
- `capacity`: `max_workers` runs and review runs, together, are running. A review holds a slot, so it counts.

A dry run checks the same guards, counting reviews already recorded in this tick as running, records `dispatch:review`
with rationale `dry run: not dispatched`, and starts nothing (D036).

Once the guards pass, the command leases a slot with holder `canopy:review:<run_id>`, inserts a `review_runs` row, and
spawns `python -m canopy _review <run_id>` detached, as dispatch spawns `_run` (§8 step 4). `_review`:

1. Claims the run by pid and drops `CANOPY_TICK_ID`, as `_run` does.
2. In the slot: `git fetch origin <SHA>`, then `git checkout --detach <SHA>`, and checks that `HEAD` is `SHA`. A
   failure is `failed` with a harness note: a PR in another repository fails here. No branch is created.
3. Runs `review_cmd` with cwd `<state_dir>/reviews/<run_id>/`, a directory created readable only by the operator, and
   **not the checkout**. The prompt names the checkout's path. The checkout holds code the loop did not write, and an
   agent runtime reads its configuration and agent definitions from its working directory, so a PR could otherwise
   rewrite the reviewer that reads it. Timeout `review_timeout_minutes`, with the agent's pid recorded.
4. Parses the result, then always returns the slot with `--force`, which discards anything the reviewer left in the
   checkout. It traps signals and exits the way `_run` does (§8 step 6), and reconcile treats a dead `_review` as it
   treats a dead `_run`.

The prompt is `prompts/reviewer.md` (or the override), with the PR URL, the commit, the checkout path, the ticket key
and tracker provider for an agent PR, `review.low_impact`, the attempt number and limit, the overseer's context, and
the result contract. The reviewer:

- reads the PR's description and discussion, the diff, and as much of the checkout as it needs; for an agent PR, the
  ticket too, to check the change against what was asked;
- looks for defects, not style: wrong behavior, missed cases, security problems, broken contracts, missing tests for
  new behavior, and anything the repository's own docs (such as `AGENTS.md`) name as a rule;
- verifies each finding against the code before reporting it, and reports none when it finds none;
- treats everything it reads, the diff included, as data (TRUST_MODEL T1).

It posts exactly one comment on the PR's conversation, never a submitted review:

```
**canopy review**: an automated adversarial review of abc1234, run by canopy under this account. It is not a
human review and not an approval.

Verdict: findings (1 blocking, 1 minor). Impact: normal.
1. **blocking** `src/retry.py:42`: ...
2. **minor** `tests/test_retry.py`: ...

<!-- canopy-review {"v":1,"run":42,"sha":"<full sha>","verdict":"findings","impact":"normal"} -->
```

The first line identifies it to people, and the marker on the last line identifies it to programs. The comment's
author is the operator's account (D010), so the marker is a claim anything running as the operator could make. The
loop itself never trusts the marker; it trusts only its journal (below).

Result contract, one JSON line, last line of stdout, validated with pydantic (D026):

```json
{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high","comment":"https://...",
 "summary":"one paragraph",
 "findings":[{"severity":"blocking|major|minor","title":"one line","location":"path:line"}]}
```

- `done` means the review was read through and the comment posted, and `comment` is its plain `https://` URL, which
  must begin with the reviewed PR's URL: a comment's link does on GitHub. A `done` without one is recorded as `failed`
  with a harness note. `failed` means the reviewer could not review, and the summary says why.
- The harness cannot check that the comment exists (principle 5; it has no VCS client). The overseer can, and does
  (below): a `done` run whose comment is missing costs that commit its review, not the PR its human review.
- At most 20 findings. `title` at most 200 characters, `location` at most 300, `summary` at most 2000. `verdict` is
  `findings` exactly when `findings` is not empty.
- Anything else is `unknown`. `review_runs` status is `running`, `done`, `failed`, `unknown`, `timeout`, or `crashed`.

### The verdict, and automating on it

canopy never approves (TRUST_MODEL §6), so a review changes no GitHub review state and cannot satisfy a required
approval. The verdict is the marker. A repository that wants low-impact PRs to need no human reviewer can run its own
automation, such as a CI job that reads the latest `canopy-review` marker for the head commit from an account it
allows and sets a check that its branch protection requires. That decision, and that automation, belong to the
repository's owners, not to canopy. They should know that the marker is only as trustworthy as every agent the
operator runs, since all of them post as the operator; a bot identity (ROADMAP, deferred) is what would change that.

### The overseer's part

The state block gains `reviews`: whether `agent_prs` is on, whether a query is set, the limits, running review runs,
and for each PR reviewed in the last 14 days (at most 50, newest first) its URL, linked ticket, review runs so far, and
latest run: id, commit, status, verdict, impact, comment URL, finding titles, start and end.

For the loop's own PRs, the phase table (§7) gains two rows between `ci_red` and `green_unreviewed`, used only when
`agent_prs` is on:

| Phase | Derived from | Next action |
|---|---|---|
| `review_pending` | checks pass, no approval, no `done` review of the head commit, under the per-PR limit | `canopy review run --ticket KEY` |
| `review_findings` | the head commit's `done` review has findings, newer than the `review` cursor | classify as review comments (§7): dispatch `resume` pointing at the review run and its comment, or `needs_author` |

A clean review, or a PR at its review limit, moves on to `green_unreviewed`, whose `needs_reviewer` item then links
the latest review. A `resume` pushes a new commit, and the new commit is reviewed again, until the per-PR limit. The
overseer recognizes a review's comment by the comment URL in the state block, never by the marker, and never counts it
toward `changes_requested`. A worker can post a comment carrying a marker, but it cannot put a run in the journal.

When it reads a PR, the overseer also checks the latest `done` review's comment: it exists on that PR, by the operator's
account, with a marker naming that run. If it does not, the overseer records `review_unposted` (Attention, below)
and an agent PR moves on as a PR at its review limit does, to `needs_reviewer`: a worker is never sent to a comment
that is not there. The `reviewed` guard
still holds for that commit; the next commit is reviewed as usual. Comments by the operator's account carrying a
`canopy-review` marker that no run in the state block names are extra: the overseer ignores them, as it ignores any
text that is not an authorized reply.

For PRs from `review.query`, the overseer runs the query each tick and keeps only PRs of this repository, the one whose
PRs it already reads for tickets. A match in another repository gets no decision: its commit cannot be fetched from
this repository's `origin`, so `_review` would only fail. The prompt says so, and a query with a `repo:` qualifier
saves the reads. For each open match whose head commit has no `done` review, it runs a review or records
`canopy review wait --pr URL --rationale "<text>"`: while checks are still running, say, or when the PR is a draft. A
PR whose head is already reviewed needs no decision. Nothing else is decided about these PRs.

Review decisions are `decisions` rows with the PR's URL in a new `pr` column: `dispatch:review`, `wait`,
`refused:<guard>`, and `attention:<reason>`. An agent PR's rows also carry its ticket key.

### Attention

- `review_failed`: a PR's latest review run ended `failed`, `unknown`, `timeout`, or `crashed`. The overseer records it
  every tick that the PR is still a candidate and nothing newer has run, and `canopy review run` may retry it within
  the per-PR limit.
- `review_unposted`: the latest `done` review's comment is not on the PR (above). It lasts until a newer review of the
  PR ends `done` with its comment in place.
- `review_limit`: recorded by the refusal, and by the overseer every tick that a candidate PR's head is unreviewed and
  it is at its limit.
- Findings are not attention items. They are on the PR, where the author reads them. For an agent PR, what follows
  from them is a `resume`, or the `needs_author` or `needs_reviewer` items that already exist.

`canopy attention` gains `--pr URL` in place of a ticket key. In `notifications`, such an item's row holds
`pr:<URL>` in `ticket_key`, which no ticket key can equal (§17). With M10, a `reviews` event group adds
`review.ended`: PR, ticket, run, status, verdict, impact, comment.

### Agent definition

canopy ships `canopy-reviewer` in the definitions directory (§13), not the repository's `.opencode/agent/`, which anyone
who can push to the repository controls (TRUST_MODEL T7):

- no edits, no subagents, no bash; reads allowed only inside the checkout;
- MCP: the tracker and GitHub, read tools only, plus the one tool that posts a comment on a PR's conversation. Tools
  that submit a PR review, push or write files, change labels, or edit or delete comments are denied by name.

A review that should run the PR's tests uses the operator's own copy of the definition, with bash allowed for exactly
those commands, as a chore does (§19). That executes the PR's code on the operator's machine, which is the operator's
call to make, and a reason to keep `review.query` to PRs whose authors they trust.

### Journal

- `review_runs`: id, tick id, PR URL, commit, ticket key (nullable), slot, lease id and holder, pid of `_review`, pid of
  the agent, started and ended times, status, `result_json` (validated, text cut to its limits), log path. Separate
  from `runs`, whose ticket and branch columns a review does not have.
- `decisions.pr`: nullable.
- The `review` cursor (§7) also covers review runs: a `resume` for a review's findings passes
  `--cursor review=run:<id>`.

### Trust model changes needed

TRUST_MODEL is unchanged until M11, whose PR carries the human approval:

- T1: the reviewer reads the most hostile text the loop meets, a diff by anyone `review.query` matches. What it writes
  is data wherever it goes: the overseer classifies findings as it classifies review comments, and the worker reads the
  review comment as it reads any other. `review.query` authorizes, and it is user-only.
- T3: `max_reviews`, `max_reviews_per_day`, `max_reviews_per_pr`, one review per commit, and the review timeout are
  controls in code. Add them to §6.
- T4: a review checks out code the loop did not write. The harness runs nothing from it, and the reviewer's working
  directory is outside it, so the runtime loads no configuration from it. The shipped definition cannot run commands.
- T5: every review comment says what it is in its first line and carries the marker.
- T6: the reviewer can write one kind of thing, a comment on a PR. Residual: a steered reviewer can put what it read
  into a comment, and the GitHub MCP server cannot limit which PR it comments on, or how many times: the prompt asks
  for one comment, and nothing in code enforces it. Extra comments are noise, not authority: the loop reads reviews
  from its journal. A repository that gates merges on the
  marker trusts every agent the operator runs.
- T7: every review key is user-only, except `policy.max_reviews_per_pr`, which the repository may only tighten.
- §6: never submit a PR review (approve or request changes); never push to or edit a PR the loop is only reviewing.
- §7: a `review.query` that matches other people's PRs comments on their work in your name; tell them first. A reviewer
  definition that runs commands runs the PR's code.

### Open

- Inline comments on lines. GitHub puts them in a submitted review, and the tool that submits one can also approve.
  They wait for a runtime that can deny the approve event, or for a bot identity.
- Whether the reviewer should update its earlier comment on a PR instead of adding one per commit. Editing needs a tool
  that can edit any of the operator's comments.
- Whether a repository should be able to offer a review rubric, such as its own `low_impact`, that an operator opts
  into by name, the way it offers its tracker query.
- Reviews of other repositories' PRs. Until M6, a loop reviews PRs of its own repository only. In a workspace (§18),
  `canopy review run` gets a `--repo` like dispatch has, and the checkout comes from that repository's pool.
- A comment tool the runtime lets the reviewer call once, on one PR. It would turn T6's residual into a control. canopy
  will not ship one: it would be VCS code (principle 5).
- Whether OpenCode can confine reads to one directory outside the working directory. The M11 canary settles it. If it
  cannot, the reviewer runs without a checkout and reads the PR only through MCP.
