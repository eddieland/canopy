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
- [22. Conversations](#22-conversations)
- [23. Flaky CI (M25)](#23-flaky-ci-m25)

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
- A hosted service, a background daemon, or a workflow DSL. `canopy loop` (§6) runs in the foreground, where the
  operator started it. A listener is allowed only on loopback or the operator's private network, behind the operator's
  secret (TRUST_MODEL T8, D055); none is built yet.
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
6. **Smallest surface that works.** Five install steps. Coworkers' daily surface is labels, ticket comments, and PR
   review. The operator's is the web UI `canopy loop` serves (§22): one attention list, the runs, and every ticket's
   conversation, with the CLI's verbs for the same.

## 5. Components

The harness is one Python package, `canopy`, in layered subpackages (D041). Top to bottom: `__main__`; `cli`; `loop`;
the features, `runs`, `setup`, `chores`, `notify`, `reviews`, and `serve`; `core`; `infra`. A module imports from its
own package and lower layers only. Features never import each other; what two share moves down a layer.
`tests/canopy/test_layers.py` enforces this and fails on a module outside the packages it lists.

```text
canopy (harness, Python)
  __main__.py      python -m canopy, how dispatch starts _run from the same installation

  cli/             the command line; only cli imports click, and only __main__ imports cli
    main.py        main(), the root group, exit codes
    common.py      opening the Context, refusals, the tick named by CANOPY_TICK_ID
    params.py      validated parameter types: ticket keys, reasons, slugs, cursors, bounded text
    setup.py       init, init --workspace, skill, secret (the web UI's listener secret, §22)
    loop.py        loop (serving the web UI unless --no-serve), tick, tick --dry-run, status, decisions
    runs.py        dispatch, _run
    conversation.py start, stop, reply, forget, show: the operator's verbs on a subject (§22)
    journal.py     decide, attention, ticket set
    workspace.py   workspace sync
    chores.py      chore run, chore wait, chore try, _chore
    notify.py      notify test
    reviews.py     review run, review wait, _review

  loop/            the tick (§6), which drives the features below
    tick.py        lock, migrate, reconcile, run the overseer, close the tick, publish
    repeat.py      canopy loop: ticks one after another with a wait between them, its own lock, rich output
    pacing.py      how long the loop waits: idle ticks, gates, and what wakes it early (§6, Idle pacing)
    web.py         the web UI for canopy loop: the listener secret checked, the server's backend wired, started
    state.py       the overseer's state block
    attention.py   the attention list from the journal; render attention.md, diff, notify

  runs/            worker runs on tickets (§8)
    dispatch.py    guards, leases (all or nothing), render the worker prompt, spawn detached _run
    policy.py      attempt limits and the fix-ci cooldown per unit, derived from runs and run_slots
    worker.py      canopy _run: branch setup and the operator's setup command in each slot, the worker, result
                   parsing, push verification, slot return; a split's run, its children validated into split_children
    desks.py       a joint run's desk: one link per worktree it leased (§18)
    reconcile.py   dead runs marked crashed, their slots and desks cleaned up, stale leases returned, the capacity left
    halt.py        canopy stop --now: a stopped ticket's run killed and closed as reconcile closes a dead one (§22)

  chores/          the operator's recurring chores (§19); what the web UI reads of them is in core (chore_*.py)
    start.py       canopy chore run: guards, the prompt with its `## Run` section, spawn detached _chore
    execute.py     canopy _chore: the chore's command in its cwd, result parsing, closing its row
    trial.py       canopy chore try: one foreground run outside any tick that records nothing
    reconcile.py   chore runs whose _chore is gone marked crashed

  notify/          notification sinks (§20)
    deliver.py     each sink in turn: its attention diff, events, digest; one message; the loop's own events
    message.py     the message in text or json, its bounds, the digest
    journal.py     sinks' cursors and failures, what each was told, the outbox's reads and pruning
    desktop.py     canopy-notify-desktop: the desktop sink, a separate command

  reviews/         adversarial reviews of PRs (§21)
    start.py       canopy review run: guards, the slot, the reviewer's prompt, spawn detached _review
    execute.py     canopy _review: checkout at the commit, the reviewer outside it, result checks, slot return
    result.py      the result contract, validated with pydantic
    view.py        the state block's reviews
    reconcile.py   review runs whose _review is gone: reviewer killed, slot returned, marked crashed

  serve/           the web UI's server (§22, D079); the only package that imports fastapi, starlette, or uvicorn
    app.py         create_app(): the guard, the API under {base}/api, the single-page app under {base}/
    api.py         the JSON and SSE routes: session, meta, attention, runs, tickets, and the operator's verbs
    auth.py        sign-in with the listener secret, the signed session cookie, the per-session token on writes
    secret.py      the listener secret's file: read with its checks, written by `canopy secret`
    backend.py     what the loop hands the server: config, journal, the attention list, ending a run; a Context per
                   request
    views.py       journal rows as the API's models: attention items, runs, tickets, messages
    live.py        the event stream: data_version read once a second, changed lists sent whole
    schema.py      the API's pydantic models, the source of the UI's generated TypeScript types
    spa.py         the built app: hashed assets, index.html for routes with a <base href> and a CSP, never for /api
    guard.py       Host and Origin checks, and security headers on every response
    options.py     ServeOptions: loopback or private host, port, base path, mock data
    server.py      the server's thread for canopy loop: uvicorn without signal handlers, restarted with a backoff
    mock.py        a journal seeded from fixtures, and the changes its stream shows
    __main__.py    python -m canopy.serve --mock: serve for development and tests, or print the OpenAPI schema

  setup/
    init.py        canopy init: config files, branch protection text, SSH remote warning, old agent definition copies
    workspace.py   canopy init --workspace: the skeleton; canopy workspace sync: converge clones and pools (§18)

  core/            what every feature shares
    agent_output.py an agent's stdout: its text, and OpenCode's JSON events' session id and cost (§13)
    chore_view.py  each configured chore: due time, runs, open findings; chore_failed items; its state block part
                   (§19), read by the loop, the CLI, chores, and the web UI
    chore_window.py a chore's days and hours: whether a run may start now, and when it next may
    chore_result.py a chore's result contract, validated with pydantic
    config.py      layered config: the workspace file or repository canopy.toml, and user config.toml; scopes
    context.py     the Context every command passes around: config, workspace, db connection, runner
    contract.py    what every agent result contract is built from: bounded text, plain URLs, the last stdout line
    conversation.py references, start records, the operator's messages, runs' reports and questions, with the guards
                   every channel shares (§22)
    db.py          SQLite journal, migrations
    items.py       the attention item: its subject, fingerprint, and age
    outbox.py      the events notification sinks receive, recorded with the fact they report (§20)
    definitions.py the snapshot of agents/ and skills/ that agent runs load (§13), the private worker's rendered from
                   config; the guards against shadowing them and against naming the tracker's tools (§22)
    prompts.py     prompt files and overrides; rendering worker prompts
    treehouse.py   status, get --lease, return, destroy; a Pool per repository, with its declared size (§18)
    hostgit.py     git as the harness runs it: hooks, the filesystem monitor, and submodule fetches off; a slot's
                   `.git` link, read and put back (§8)
    workspace.py   the workspace: its map, repositories, their pools, the private state directory (§18)

  infra/           plumbing that knows nothing about tickets or agents
    procs.py       the only module that runs subprocesses (lint-enforced); a timeout kills the whole process group;
                   a child's PWD names its cwd (OpenCode runs tools in PWD); detached spawns and pid liveness
    lock.py        flock on <state_dir>/lock; a tick that cannot lock exits 0 with a log line
    stopping.py    SIGTERM, SIGHUP, and SIGINT become an exception the cleanup of _run and _chore catches
    logs.py        JSON-lines logging to <state_dir>/canopy.log, stamped with the tick id; operator-only files and
                   directories
    resources.py   finds migrations/, .agents/, and the built UI in a source checkout or bundled in the wheel
```

```text
prompts/         overseer.md, worker-implement.md, worker-fix-ci.md, worker-resume.md, worker-split.md, reviewer.md,
                 and the private variants worker-implement-private.md, worker-fix-ci-private.md,
                 worker-resume-private.md
agents/          OpenCode agent definitions: canopy-overseer, canopy-worker, canopy-worker-private, canopy-splitter,
                 canopy-chore, canopy-reviewer
skills/          tracker-<provider>/: optional per-tracker guides (§17)
operator-skill/  SKILL.md: the canopy skill, for the operator's own agent sessions (§13); agent runs never load it
migrations/      NNNN_name.sql
packages/        uv workspace members: separate programs canopy ships, run only as commands
  canopy-notify-slack/  the Slack sink (§20); stdlib only, imports nothing from canopy
scripts/         build-binary.sh: the single executable a release ships (D067)
ui/              the web UI (D079): a Vite and React app, its own rules in ui/AGENTS.md and ui/DESIGN.md
hatch_build.py   the wheel's build hook: builds ui/ with npm and bundles ui/dist as canopy/_data/ui
```

`prompts/`, `agents/`, `skills/`, and `operator-skill/` live under `.agents/` in this repository. The wheel bundles
them, with `migrations/`, under `canopy/_data/` (D022).

A release is one executable per platform (D067): a pex in venv mode holding canopy, canopy-notify-slack, and the
dependencies `uv.lock` pins, inside a scie with its own Python. It unpacks into the operator's cache once, so
`resources.py` finds the bundled files, and `sys.executable` imports canopy, as dispatch, chores, and reviews need to
start `_run`, `_chore`, and `_review` via `python -m canopy`. Its run name picks the command: `canopy`, or a link named
`canopy-notify-desktop` or `canopy-notify-slack`. `make binary` builds it for the current platform; the release
workflow builds each platform's, runs the install check on each, and attaches them to the tag's release. The version
is the tag's (D085): pushing `v0.2.0` releases 0.2.0, and a build between tags names its distance from the last one
and its commit.

Where later work goes:

- A feature is a features-layer package plus a `cli/` command module: `chores` (§19), `notify` (§20), `reviews`
  (§21). `loop` calls its reconcile and publish steps and its state block part. Deleting a feature deletes those three.
- A feature others write to keeps its writing half in `core`: dispatch, `_run`, `_chore`, and reconcile record §20's
  events through `core.outbox`; `notify` delivers them.
- Code that runs in its own process and must not share the harness's imports or dependencies is a uv workspace member
  under `packages/`, such as §20's Slack sink. `canopy`, the workspace root, lists the sink's script among its own, so
  one install puts both on `PATH`.
- A module that takes on a second concern splits into a same-named package in the same layer, as `cli.py` did.

Roles:

- **Harness**: schedules, locks, guards, journals, renders. Runs the overseer once per tick and workers on demand.
- **Overseer**: an agent run with `overseer_cmd`. Reads the world through MCP and the state summary, decides one next
  action per ticket, and acts only through `canopy dispatch`, `canopy decide`, `canopy attention`, `canopy chore run`,
  `canopy chore wait` (§19), `canopy review run`, `canopy review wait` (§21), and `canopy mirror` (§22). Read-only
  everywhere else.
- **Worker**: an agent run with `worker_cmd` in a leased worktree with a task prompt. Writes code, pushes a branch,
  opens or updates a PR, comments on the ticket, prints a result line, exits. Never merges, approves, or moves a ticket
  to Done. A private ticket's worker runs with `private_worker_cmd` and writes nothing to the ticket (§22).

## 6. Tick

`canopy loop` (below) runs ticks one after another; `canopy tick` runs one, by hand or from a scheduler. A tick does,
in order:

1. Acquire the lock. If held, log and exit 0, writing no `ticks` row.
2. Apply pending migrations. Close any `ticks` row still `running` as `abandoned`: holding the lock proves its process
   is gone. Insert a `ticks` row; its id tags all logs. Migrations wait while any `running` run's `_run`, chore run's
   `_chore`, or review run's `_review` is alive, since it writes the old schema (D060); so does the error for a journal
   with migrations this canopy does not know (D068). Until then, the tick and any command that opens the journal fail
   saying so.
3. **Reconcile local state.**
   - Each `runs` row with `status='running'` whose pid (the `canopy _run` process) is dead or never recorded: kill what
     is left of the worker's process group (`runs.worker_pid`), mark the run `crashed`, run
     `treehouse return --force --if-lease-id` on every slot it leased (`run_slots`), remove its desk if it was a joint
     run, and log it. A zombie counts as dead. A pid reused by an unrelated process reads as alive, so that run stays
     running: a residual, not a guard.
   - Each leased slot in `treehouse status --json` with no live `runs` row and `lease_holder` matching our prefix:
     return it and log it. In a workspace this covers every cloned repository's pool, and a run's slots go back to the
     pools of the repositories they record (§18). In a workspace of several, a desk canopy made whose ticket has no
     running run is removed; anything else under `desks/` is left alone.
   - Each `chore_runs` row with `status='running'` whose `_chore` is dead or never recorded: kill what is left of its
     agent's process group and mark it `crashed` (§19). Chore runs hold no slot and take no worker capacity.
   - Each `review_runs` row with `status='running'` whose `_review` is dead or never recorded: kill what is left of its
     reviewer, remove its directory, return its slot, and mark it `crashed` (§21). This runs before the worker runs'
     reconcile, and a running review's lease is never returned as stale.
   - `capacity = max_workers - count(runs and review runs where status='running')`: a review holds a slot.
   - If `treehouse status` or a return fails, close the tick as `reconcile_failed` and stop; the overseer does not run.
   - Record on the tick the newest message in the journal and the time: every message up to it, and every run,
     chore run, and review run that started or ended before it, was there for this tick to read (`ticks.message_id`,
     `ticks.read_at`). The latest `ok` tick's message is what the web UI calls acknowledged (§22); idle pacing reads
     both (below).
   - Record as this tick's decisions the harness's attention items for runs (§14), `awaiting_reply` for each started
     ticket whose latest question has no operator message after it (§22), `chore_failed` for each configured chore
     whose latest ended run did not end `ok` (§19), and `repo_missing` for each mapped repository with no clone.
4. **Render the overseer prompt**: `prompts/overseer.md` (or the override), plus a generated `## State` section holding
   one JSON object: tick id, current time, whether it is a dry run, repository root; the workspace (name, whether it is
   a single repository, the path of `MAP.md` if any) and its repositories (name, path, summary, whether cloned, its
   pool's leased slots, §18); tracker config (provider, query, labels, needs-human label); trust config (authorized
   repliers, branch prefix, PR label); capacity; policy (limits and stacking); running workers and their repositories;
   and the `tickets` rows not marked done. Each ticket has its phase, branch, and comment, message, and mirror cursors
   (§22); its units (§18), each with repository, branch, PR, phase, review and ci cursors, runs so far of each kind, and
   when fix-ci may next run if still ahead; and its latest run (id, kind, status, branch, each repository it leased in
   with its starting base, start and end). A ticket the operator started has a `private` object (§22): its start
   record's status, its message cursor, the operator's messages newer than it, and the question awaiting a reply, if
   any. `chores` (§19) is present only when chores are configured. `mirror` holds the per-tick mirror limit and this
   tick's heredoc delimiter (§22).
5. **Run the overseer** with `overseer_cmd`, cwd = the repository root (the workspace root in a workspace, §18), timeout
   `overseer_timeout_minutes`, and `CANOPY_TICK_ID` in its environment. `canopy dispatch`, `decide`, `attention`, and
   `mirror` refuse if it is unset or names a tick that is not running (D020). Its stdout and stderr go to
   `<state_dir>/ticks/<tick id>.log`, readable only by the operator, never to the journal. The session id and cost
   the runtime reported (§13) go on the `ticks` row, whether or not the run succeeded. The run succeeded if it
   exited 0 and the last non-empty line of its text (§13) is `tick complete`; otherwise the tick closes as
   `overseer_failed`. A successful run that recorded a tick-wide `skip` (`mcp_unavailable`, `tracker_unsupported`)
   closes the tick as `skipped`, which leaves the attention list standing (D037).

   In `--dry-run` (D036), the state block says so. `canopy dispatch` checks the live guards (§8), counting each
   dispatch this dry run already recorded as a running run, and records refusals the same way. An allowed dispatch
   starts nothing and is recorded as `dispatch:<kind>` with its cursors, context, and rationale
   `dry run: not dispatched; would work on <branch>` (plus `in <repositories>` in a workspace). `canopy ticket set`
   records phases, but neither it nor `canopy dispatch --cursor` advances cursors, and `--done` does not mark the
   ticket done. `canopy mirror` records the comment and moves no mirror cursor. The rest of the tick is live: reconcile
   closes dead runs and returns stale leases, and the tick's attention items become the attention list and are notified.

   `canopy decide` takes `wait`, `skip`, or `done`; only a tick-wide `skip` (such as `mcp_unavailable`) omits the key.
   What the overseer writes is rendered into the next prompt, so the CLI bounds it: keys and attention reasons are
   validated, phases come from §7's table, cursor ids must match `[A-Za-z0-9][A-Za-z0-9_.:/-]*`, and rationales,
   details, and worker context are cut at 2000 characters.
6. Close the `ticks` row with a summary.
7. **Publish attention** (§14): rewrite `attention.md` from the journal, then deliver to each notification sink (§20)
   the list's change since that sink last heard, the events it takes, and a digest when due; `notify.cmd` is the sink
   `default`. This follows the close because the list is the latest `ok` tick's, which may be this one; after a failed
   or skipped tick it is the one before. A failure here is logged and does not change the tick's status. Release the
   lock.

Workers dispatched during a tick outlive it, as detached processes owned by `canopy _run`.

### The loop

`canopy loop [--dry-run] [--every MINUTES] [--ticks N] [--no-serve]` is how ticks are meant to run (D042), in the
foreground until stopped:

1. Take `<state_dir>/loop.lock`; if another loop holds it, refuse and exit 1. Each tick still takes the separate tick
   lock (step 1 above), so a hand-run `canopy tick` runs between the loop's ticks or finds the lock busy.
2. Apply pending migrations before the first tick. Start the web UI's server in a thread, unless `--no-serve` or
   `serve.enabled = false`; without a usable listener secret, say why and serve nothing (§22). The header names its
   URL.
3. Run a tick exactly as `canopy tick` does, passing `--dry-run` through. An error the tick code does not handle ends
   that tick as `error` in the loop's output; the traceback goes to the log and the loop goes on. The next tick closes
   the row left `running` as `abandoned`.
4. Print the tick's status, duration, and summary; each decision except `wait` and attention items, with its
   rationale; attention items added (`+`) and resolved (`-`); running workers, the list's size, what the tick's
   overseer cost in dollars and tokens when the runtime reported it, and the wait that follows.
5. Wait, measured from the end of the tick, for `--every`, else `loop.interval_minutes`, whatever the tick's status,
   lengthened after idle ticks and ended at a gate (Idle pacing, below). This pacing rule is `pacing.wait`; ROADMAP
   M13 will lengthen it by tick cost. An operator message recorded since the tick began, such as a `canopy reply`, ends
   the wait early, but no sooner than a minute after the tick began (`repeat.WAKE_MIN_SECONDS`; §22); so does a run
   ending (below). On a terminal, pressing `t` (`repeat.TICK_NOW_KEY`, either case) ends it at once, with no floor
   (D088); keys pressed during the tick are dropped.
6. Repeat from 3 until `--ticks N` ticks have run or the operator stops the loop.

Stopping: SIGINT (Ctrl-C) or SIGTERM during the wait ends the loop at once. During a tick, the first lets the tick
finish and ends the loop without waiting; both exit 0. A second aborts the tick: the overseer's process group is killed
as on a timeout, the command exits 1, and the next tick closes the row as `abandoned`. Dispatched workers are
unaffected. A signal less than one second (`repeat.SAME_SIGNAL_SECONDS`, monotonic clock) after the first is the same
keypress. The web UI's server stops with the loop.

Config is read once at loop start; restart to apply a change. Prompt files are read every tick.

Output uses rich (D043). On a terminal, a spinner with elapsed time shows during a tick and a countdown during the
wait, redrawn in place and cleared when done. To a file or pipe, output is plain text, one block per tick. The JSON log
gains `loop started` and `loop stopped` lines, with no tick id, a `loop waits` line per tick, and a line when a key, a
message, or a run ending ends a wait.

Keys are read by `infra/keys.py`, only when output goes to a terminal and stdin is a terminal the loop holds in the
foreground: the terminal is put in cbreak mode (no Enter, no echo; Ctrl-C and Ctrl-Z still signal) for as long as the
loop runs and restored when it stops. Otherwise no keys are read, and the header and countdown do not mention them.

### Idle pacing

ROADMAP M21, D083; `loop/pacing.py`. A tick that finds nothing new costs a full overseer run and buys nothing, however
cheap that run was, and most ticks overnight and at weekends are like that. So the loop waits longer after each idle
tick in a row, and wakes early on the events that end idleness that it can see itself.

A tick is **idle** when all of these hold, each read from the journal by the loop:

- It closed `ok`. Any other status is not idle and resets the count: a failing tick keeps today's pacing.
- Its decisions are only `wait`, a ticket's `skip` (such as `not_labeled`, every tick), attention items, and refusals
  that lift by themselves (`pacing.QUIET_REFUSALS`): `running`, `capacity`, and `chore_capacity` (on a run ending),
  `cooldown`, `not_due`, and `outside_hours` (at a known time, below), and `attempt_limit` (never). Any dispatch,
  `done`, `mirror` (a new tracker comment), or other refusal makes it not idle. A tick-wide `skip` closes the tick
  `skipped`, which is not idle already.
- The attention list after it is the list before it, compared as the loop's per-tick block already compares them.
- No ticket or unit changed its phase, branch, a cursor, or `done`, and no ticket was seen for the first time.
- No run, chore run, or review run started or ended, and no operator message was recorded, after the previous tick
  read the journal for the overseer's state (`ticks.read_at` and `ticks.message_id`, §6 step 3). Something the
  previous tick could not have seen keeps this one from counting as idle, even when it happened while the previous
  tick was still running. The previous tick is the journal's, whatever ran it; one that never read the journal, such
  as a `reconcile_failed` tick or the first tick of all, makes this one not idle.

The wait after a tick is then:

- `base` (`--every`, else `loop.interval_minutes`) after a tick that is not idle;
- after the n-th idle tick in a row, `max(base, min(base * 2^n, loop.idle_max_minutes))`. With the defaults, 30, 60,
  120, then 120 for as long as nothing changes. It is never shorter than `base`, so idle pacing is off whenever the
  cap is not above `base`: set `loop.idle_max_minutes` to `loop.interval_minutes`, or pass an `--every` at or above
  it. Off, the loop paces as before M21: `base` after every tick, no gate shortens it, and only an operator message
  wakes it. A shorter `--every` keeps idle pacing, from that base.

`loop.idle_max_minutes` (user-only, default 120) is at least `loop.interval_minutes` when set; left unset under a
longer interval, it is no error and idle pacing is off. The count lives in the loop, not the journal: a restarted loop
starts at `base`, and a hand-run `canopy tick` between the loop's ticks counts like any other. When M13's cost pacing
is built, the wait is the longer of the two rules' waits, and what follows bounds that combined wait.

Whatever pacing chose, the wait ends no later than the earliest harness gate still ahead when the tick ends, both what
the state block shows: a `fix-ci` cooldown's end (§8) and a configured chore's `due_at` (§19). A gate opening is acted
on when it opens, even sooner than `base`. One already open, such as a chore the overseer passed over because its `when`
says not now, sets no deadline, so it cannot make the loop spin.

Besides an operator message, the wait ends early, with the same one-minute floor (`repeat.WAKE_MIN_SECONDS`), when a
run, chore run, or review run ended after the tick read the journal for the overseer's state (`ticks.read_at`): after
anything that tick could have seen. A run that ends while the overseer is running is picked up a minute after the tick
began, not a full interval later. The tick that follows is not idle, so the wait after it is `base` again, and the tick
after that looks for the CI on a worker's push at today's pace. That holds at any count, so a long wait never sits on
canopy's own work.

What idle pacing cannot see is the world: a teammate's review comment or a PR's CI going red is picked up at the next
tick, up to `loop.idle_max_minutes` late, or later only when M13's budget asks for a longer wait. That cap is the
trade, and the operator's knob. A sink's digest (§20) is due at a delivery, so it can lag by as much. The header names
the cap, the per-tick block shows the count with the wait, as `idle 3, next tick in 1h 00m at 03:41` (no count after a
tick that was not idle), and the `loop started` log line records `idle_max_minutes`; each tick's `loop waits` line
records whether it was idle, the count, and the wait chosen, in seconds.

## 7. Ticket phases and next actions

The overseer derives phases each tick from live state. They are recorded in `tickets.phase` for the status view, never
read back as truth. The PR phases, `pushed_no_pr` to `merged`, are a unit's (§18), recorded in `ticket_units.phase`:
`canopy ticket set` needs `--repo` for one in a workspace of several, and implies the repository in a workspace of one.

| Phase | Derived from | Next action |
|---|---|---|
| `ready` | one of `tracker.labels` present, not closed, no run active, no branch, no open blocker | dispatch `implement` |
| `blocked` | as `ready`, but a blocker ticket is open | dispatch `implement` stacked on the blocker's branch if its PR is open and green (§10), else wait |
| `running` | active `runs` row | wait |
| `pushed_no_pr` | branch exists, no PR | dispatch `resume` with instruction to open the PR |
| `conflicted` | PR open, GitHub reports it conflicts with its base | dispatch `resume` to merge the base in |
| `ci_running` | PR open, checks pending | wait |
| `ci_red` | PR open, checks failed, newer than cursor | dispatch `fix-ci`; at the attempt limit, attention; in cooldown, wait |
| `review_pending` | with `review.agent_prs`: checks pass, no approval, head commit not reviewed (§21) | review it |
| `review_findings` | with `review.agent_prs` and `canopy:review` trusted: findings on the head's review, newer than the cursor | as comments (§7) |
| `changes_requested` | a trusted reviewer's comments or requested changes newer than cursor | dispatch `resume` with the comments; if the overseer judges a comment needs a human (design pushback, scope), attention instead |
| `untrusted_review` | review feedback newer than cursor from a reviewer not in `trust.trusted_reviewers`, with no operator message about it | attention: the operator says what to do with `canopy reply` (below) |
| `green_unreviewed` | checks pass, no approval | attention: needs a reviewer |
| `approved` | approved, not merged | attention: ready to merge |
| `merged` | every unit's PR merged, and no other repository left to change (§18) | mark ticket `done` in the journal; humans handle the tracker transition |
| `needs_human` | `needs_human_label` present, no authorized reply newer than it | wait |
| `human_replied` | authorized reply newer than the label, or an operator message newer than the message cursor | dispatch `resume` pointing at the reply; the worker removes the label |
| `split` | a split's parent (§18) | wait; `split_unlabeled` for unlabeled children; done once every child is closed |

A unit is `conflicted` when GitHub reports that its PR does not merge cleanly into its base (`mergeable` false,
`mergeable_state` `dirty`); a mergeability GitHub has not computed yet is not a conflict. GitHub runs no
`pull_request` checks on a PR it cannot merge, so a conflicting PR's checks are pending with nothing running, or are the
results of an earlier head. `conflicted` therefore comes before every CI and review phase: before `ci_running`,
`ci_red`, `review_pending`, `green_unreviewed`, and `approved`. Its `resume` points at the conflict and the base, and
carries `--base` for a stacked PR (§10); the worker merges the base into the branch and pushes without force. Review
comments or findings newer than the `review` cursor ride the same `resume`, with their cursor. A conflict has no cursor:
it is a state of the PR, not an item, so it is new for as long as it lasts. A `resume` that pushes a merge ends it; one
that is still there after that push means the base moved again, and the `resume` attempt limit bounds the repeats
(D030, D070).

"Authorized reply" means a comment by an account in `trust.authorized_repliers`, matched on the tracker's stable account
identifier, never a display name, that is not a worker's (§8: one carrying the configured comment marks). A worker's
comment is never review feedback either. If the tracker cannot say when a label was added, the worker's question comment
is the reference point instead of the label. Anything else on the ticket is data, not instruction. See TRUST_MODEL.

**Trusted reviewers** (D089). Review feedback is a PR's reviews, review comments, and requested changes, and canopy's
own review findings (§21). `trust.trusted_reviewers`, user-only, lists whose feedback a worker may address without the
operator's go-ahead: VCS host logins, matched in full and case-insensitively, and `canopy:review` for canopy's own
review runs, which post as the operator and are recognized by their comment URL in the journal (§21), never by author.
It is empty by default: nobody is trusted until listed, so a review bot's comment never starts a fixup on its own.

- A trusted reviewer's feedback newer than the unit's `review` cursor is `changes_requested` (or `review_findings`), and
  the overseer classifies it as before: concrete changes go to a `resume`, design questions to `needs_author`.
- Anyone else's is `untrusted_review`: the overseer records the attention item every tick, naming the PR, the
  reviewers, and the newest item, and does not move the `review` cursor past it. It never dispatches for it on its own
  judgment. A trusted reviewer's feedback on the same unit still goes to a worker, with the cursor no further than the
  item before the first untrusted one.
- The operator answers in canopy, with `canopy reply KEY` or the web UI (§22), never on the ticket. An operator message
  newer than the ticket's message cursor is an instruction, like an authorized reply. When it speaks to the untrusted
  feedback, however loosely ("use your best judgement on the bot's review"), the ticket is `human_replied`: a `resume`
  whose context names the message and the review items, carrying `--cursor message=` and `--cursor review=`. When it
  says to leave the feedback, the overseer moves both cursors with `canopy ticket set`.
- The resume worker's prompt names the trusted reviewers (`{{TRUSTED_REVIEWERS}}`) and carries the operator's messages
  (`{{OPERATOR_MESSAGES}}` on a public ticket, `{{CONVERSATION}}` on a private one, §22). It addresses a review comment
  by anyone else only as an operator message about it says, and otherwise leaves it alone and says so in its summary:
  the overseer's classification is checked again by the worker, as labels are (D051). The review comment stays data
  either way; the operator's message is the instruction.

Which reviewer wrote a comment is read by agents through the VCS host's MCP server, so the gate is the overseer's
judgment, checked again by the worker: the harness cannot tell a review comment's author (D003). What it can check, it
does: only the operator's channels write operator messages, and the cursors advance only with a run that starts.

A private ticket (§22), one the operator started with `canopy start`, needs no label, and its own phases come from the
journal: `needs_human` when its latest run ended `blocked` and no operator message came after it, `human_replied` when
an operator message is newer than its message cursor. Its PR phases are as above.

Cursors (`comment`, `review`, `ci`, and a private ticket's `message`, a journal message id) hold the newest item of each
kind the loop has handled, in the tracker's and GitHub's own ids, except `review`, which holds a time (below); "newer
than cursor" means not handled yet. The comment cursor is the ticket's; the review and ci cursors are each unit's, since
each unit has its own PR. In a workspace of several, `canopy ticket set` names the unit with `--repo`, and a dispatch
that carries one names exactly one repository; in a workspace of one the unit is implied. A dispatch that handles new
items carries their cursors (`--cursor`, §8), so they advance only if the worker starts. Items handled by a wait, a
done, or an attention item advance with `canopy ticket set`. A review comment waiting on a human is not advanced past,
so its attention item is recorded every tick until a human answers it.

The `review` cursor is the time of the newest review feedback handled, in UTC as `YYYY-MM-DDTHH:MM:SSZ` (D096): a
review's `submitted_at`, an inline review comment's `created_at`, or, for canopy's own review run (§21), the
`created_at` of its comment. GitHub numbers reviews and review comments separately, and review runs are canopy's own,
so no id orders all three. In that one form, times compare as strings; an item at the cursor's own second is handled, as
a review's inline comments share its second. `--cursor review=` refuses any other form, so a cursor the overseer
writes is always comparable. A cursor an earlier canopy wrote is an id, or `run:<id>`; the overseer is told to look up
that item's time and write it, and to treat a cursor that names nothing as empty. Until it has, that unit's review
state is as ambiguous as before (D096).

"Closed" means whatever the tracker calls finished: Jira status category Done, GitHub issue state closed, and so on. The
provider skill says which.

## 8. Dispatch and the worker contract

`canopy dispatch <KEY> --label LABEL --kind implement|fix-ci|resume|split [--repo NAME]... [--slug SLUG] [--base BRANCH]
[--request COMMENT_ID] [--context TEXT] [--cursor NAME=ID]...`:

Each `--repo` names a unit of the ticket, its work in one repository (§18); naming several makes a joint run. In a
workspace of one, the ticket has one unit and `--repo` may be left out.

1. Check the guards. They are in code and not overridable from the prompt. A refusal is recorded as a decision
   `refused:<guard>` with the reason, and the command exits 1. A dry run checks the same guards and stops, counting
   each dry-run dispatch already recorded this tick as a running run for `running` and `capacity` (§6, D036). In
   order:
   - `unauthorized`: no `--label`, or one not in `tracker.labels`, compared case-insensitively. The decision records
     the label in its configured spelling; the refusal does not list the configured labels. This does not prove the
     label is on the ticket; the worker's own read is the independent check (step 3, D051). A `split` without
     `--request` is refused here too (§18). A started ticket (§22) needs no `--label`: its start record is checked
     instead, in code, and a `--label` given for it is ignored.
   - `stopped`: the ticket's start record is stopped (§22), whatever label is passed. `private`: a `split` of a
     started ticket, since a split creates tickets in the tracker. `no_read_tools`: a started ticket when no tracker
     tools are known for its worker (§22).
   - `bad_request`: `--request` on a kind other than `split`.
   - `unknown_repo`: in a workspace, no `--repo`, or one not in the map or with no primary clone; for a split's child,
     any repository but the one the split recorded for it. Naming a repository the ticket has no unit in yet adds that
     unit (§18, D058). In a workspace of one, a given `--repo` must be the repository's name. A repository named twice
     is one unit. A `--repo` that is not a repository name at all (`[a-z][a-z0-9-]*`) is a usage error, like a bad key.
   - `bad_split`: a `split` in a workspace of one, naming fewer than two repositories, for a ticket with a branch, or
     for a split's child; and any dispatch for a ticket a split already made children of (§18). A split's `--slug` is
     `bad_slug` and its `--base` `bad_base`.
   - `bad_slug`: a slug that is not lowercase words joined by hyphens; any `--slug` with `fix-ci` or `resume`; or, on
     a later `implement`, a `--slug` naming another branch than the ticket's. The ticket's first `implement` names its
     branch, and every later dispatch continues it in every unit (D059).
   - `no_branch`: `fix-ci` or `resume` for a ticket with no `tickets.branch`, or, in a workspace of several, naming a
     unit no `implement` has covered.
   - `bad_base`: a `--base` that is not `<trust.branch_prefix>` plus one plain ref component (letters, digits, `_`,
     `-`, starting with a letter or digit, at most 200 characters), or that is the run's own branch (§10, D045).
   - `running`: a run for KEY is running.
   - `attempt_limit`: a named unit has already had `policy.max_<kind>_attempts` runs of this kind. A run counts against
     every unit it covered, whatever it ended as; the count never resets (D030). A split's count is the ticket's. The
     refusal also records the `attempt_limit` attention item (§14), about that unit in a workspace of several.
   - `cooldown`: `fix-ci` only, less than `policy.fix_ci_cooldown_minutes` after the latest fix-ci run covering a named
     unit ended.
   - `capacity`: `max_workers` runs and review runs, together, are running (§21).

   Later failures are recorded the same way: `no_slot` (a lease failed, or would grow a workspace's pool past its
   declared size, §18), `bad_prompt` (the worker prompt did not render), `spawn_failed`. None leaves a slot leased:
   leases are all or nothing, so when any repository's `get` fails, slots already leased for the dispatch are returned
   before the refusal is recorded. A `get` that exits 0 with unparseable output is `no_slot` too: canopy returns the
   slot at once if it can read the path, lease id, and holder; if not, the rationale says so and the next reconcile
   returns it (§6 step 3). A blocking `flock` on `<state_dir>/dispatch.lock`, held from the guard checks through the
   spawn, serializes dispatches so two cannot both pass the capacity check or the attempt limit. `--cursor NAME=ID`
   pairs are applied as `canopy ticket set` would, only once the worker has started, so what a refused dispatch was
   meant to handle stays new for the next tick.
2. `treehouse get --lease --lease-holder canopy:<KEY> --json` in each named repository's pool (§18). Record the `runs`
   row (kind, branch, started_at, whether it is private) and a `run_slots` row per slot (repository, slot path, lease
   id, holder, and base branch: `--base` if given, else treehouse's). Each repository becomes a unit of the ticket, with
   the run's branch.
3. Render the worker prompt for the kind with: KEY, tracker provider, branch name, PR label, needs-human label, timeout,
   the attempt number (one more than the most runs of the kind in any unit covered) and the kind's limit, a
   `{{REPOSITORIES}}` section listing each repository's path, base branch, journaled PR, and summary, the authorized
   repliers, the trusted reviewers and, on a public ticket, the operator's latest messages (§7), the queue labels,
   whether the run is stacked on another ticket's branch (§10), how to open a PR (`{{OPEN_PR}}`, below), the context,
   and the result contract below, whose `prs` skeleton (`{{PRS}}`) names each repository.
   - Every worker reads the ticket first and, if it is closed or carries none of the queue labels, reports `failed`
     with a summary starting `not authorized:` and changes nothing. That run counts toward the attempt limit.
   - The branch is `<trust.branch_prefix><KEY>-<slug>`, named by the first `implement`. The overseer picks the slug
     from the ticket title: lowercase words joined by single hyphens, at most 40 characters, `work` if none is given.
   - The context is the overseer's `--context`: at most 2000 characters pointing at what to read (links, comment ids,
     check names), never a copy of ticket or PR text (D031). The worker reads that text itself and checks a reply's
     author against the authorized repliers, rendered from the user config.
   - Placeholders are `{{NAME}}`, replaced in one pass. An unknown one is `bad_prompt`, as is a worker prompt without
     `{{LABELS}}`, so an older override fails closed (D051). A joint run's prompt also needs `{{REPOSITORIES}}` and
     `{{PRS}}`, its worker's only way to learn its repositories; an override without them still serves runs in one
     repository. For older overrides, `{{SLOT}}` is the worker's working directory and `{{BASE}}` and `{{PR_URL}}` the
     one repository's base and PR. With `runtime.pr_skill` set, an `implement` or `resume` prompt without
     `{{OPEN_PR}}` is `bad_prompt` too, so an override that still names the GitHub MCP fails closed (D078). A public
     ticket's prompt without `{{OPERATOR_MESSAGES}}` is `bad_prompt` once the operator has written to the ticket in
     canopy (§22, D093), and still renders for a ticket the operator never wrote to.
   - A started ticket's run renders the kind's private variant, `worker-<kind>-private.md` (§22): no label check, no
     tracker writes, and `{{CONVERSATION}}`, the ticket's latest journal messages, which an override must keep.
     The start record is read again in the transaction that inserts the run, so a `canopy stop` that commits first
     refuses the dispatch (`stopped`) and its leases are returned.
   - The prompt is written to `<state_dir>/runs/<run_id>.prompt`, readable only by the operator.
4. Spawn `python -m canopy _run <run_id>` with canopy's own interpreter, detached (`setsid`, stdin from `/dev/null`,
   stdout and stderr appended to `<state_dir>/runs/<run_id>.log`, cwd the repository or workspace root). Record its
   pid in the run and return immediately.

`canopy _run <run_id>` (hidden from `--help`):

1. Claim the run: set its pid to this process's, only if the run is `running` and its pid is unset or already this
   pid; refuse otherwise, so the overseer cannot start a second worker on a run. Drop `CANOPY_TICK_ID` from the
   environment so the worker cannot act as the dispatching tick's overseer. Read the ticket's start record again
   (§22): a private run whose ticket was stopped since, or a public run whose ticket was started privately since, ends
   `stopped` before any git step, and its slots are returned.
2. Before any git step, read each slot's `.git` file, a worktree's link to the pool's git directory. In each slot:
   `git fetch --prune origin`, then `git checkout --detach origin/<branch>` if it exists, else
   `git checkout --detach origin/<base>`. No run makes a local branch: a pool's slots share the repository's branch
   refs, so one would be state every slot sees, and the worker pushes HEAD by refspec (D109). Detached, a bare
   `git push` has no branch to target under git's default `push.default`; under `matching`, or with a
   `remote.origin.push`, it pushes what those name, which is why the prompts push by refspec. A local branch of the
   run's name that an earlier canopy left, and that origin's branch (or the base) already holds, is deleted; one with
   commits origin lacks is kept. Note HEAD's commit and the length of HEAD's reflog. A base missing from origin (such
   as a stacked-on branch deleted when its PR merged) fails the run as `crashed` before the worker starts, with a
   note, whether the branch is new or continued. Then, with `runtime.setup_cmd` set, run it in each slot in turn (§9,
   D105): cwd the slot, `CANOPY_REPO` the repository's name, `CANOPY_BRANCH` the run's branch (HEAD is detached, so
   git does not name it), `CANOPY_RUN_ID` the run's id, timeout `runtime.setup_timeout_minutes`, output appended to
   the run log. An exit other than 0, a timeout, or a command that
   cannot start fails the run as `crashed` before the worker starts, with a note naming the repository in a workspace;
   the slots are returned as on any exit (step 6).
3. Run `worker_cmd` (`private_worker_cmd` for a private run, §22), timeout `worker_timeout_minutes`, with
   `CANOPY_RUN_ID` set to the run's id and cwd = the slot, or for a joint run the desk (§18), which
   `_run` makes now with one link per slot. Record the worker's pid in `runs.worker_pid`; the worker leads its own
   process group. Its stdout and stderr go to the run log.
4. Parse the last non-empty line of the worker's text as the result contract: its stdout, or the text of OpenCode's
   JSON events (§13). Missing or invalid means `status='unknown'`; a timeout means `status='timeout'`. Record the
   session id and cost the events reported on the run at once, also after a timeout, so a git failure after this step
   does not lose them.

   A split (§18) differs: step 2 checks each slot out at its base, detached, with no branch, and runs no setup, since
   the splitter has no shell; step 3 runs `split_cmd` in the desk; step 4 parses and validates the split's result;
   step 5 is skipped, since a split pushes nothing.
5. If any slot's `.git` file no longer holds what step 2 read, record `status='crashed'`, with a note naming each such
   slot, and run no git in any slot of the run: the file may now point at a git directory the worker made (D108).
   Otherwise, in each slot, verify the branch is pushed (`git ls-remote origin refs/heads/<branch>` equals HEAD). If not
   and HEAD holds commits past step 2's, push once, without force: `git push origin HEAD:refs/heads/<branch>`. Then,
   since HEAD alone holds a detached worker's commits, look in HEAD's reflog entries since step 2 for commits that
   neither HEAD, origin's branch, nor any of origin's branches holds: a worker that checked something else out left
   them behind. If any slot's push failed or left commits behind, record `status='unpushed'`, naming each repository
   in a workspace: the checkpoint invariant failed and a human looks.
6. Always: remove a joint run's desk, put back any slot's `.git` file the run changed (a slot whose file cannot be put
   back is not returned, and the next reconcile returns it), and
   `treehouse return --force --if-lease-id <id> --if-lease-holder <holder> <slot>` for every slot, in its repository's
   pool. A trap runs this on any exit path: normal exit, exception, and SIGTERM, SIGHUP, or SIGINT (the run is then
   `crashed`). SIGKILL cannot be trapped; reconcile handles it.
7. Update the `runs` row: ended_at, status, result_json, and in the same transaction record the run's messages about
   its ticket (§22): a `report`, its summary (else the harness's note, else the status) with each PR on a line, and
   for a `blocked` run its `question`. A git failure before or after the worker is `crashed`.
   `result_json` holds the validated result, text fields cut at 2000 characters, plus a `harness` note saying why the
   status differs from what the worker reported. `prs` is kept to the run's repositories, or filled from `pr` for a
   run in one; each plain `https://` URL is copied to its unit's `pr_url`, for display and the next run's prompt.

Every git the harness runs, here, in a review (§21), and in `canopy init` and `canopy workspace sync`, goes through
`core/hostgit.py`, which adds `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c fetch.recurseSubmodules=false
-c protocol.ext.allow=never` (D107). A slot shares its git directory with the pool and the primary clone, and a worker
can write there, so without them a hook or monitor it planted would run on the host, outside the worker, in step 2 or
5 or in a later run or review. A command named in that directory's config (a filter driver,
`remote.<name>.uploadpack`) still runs; closing that takes a git directory the worker cannot write (HOST_ISOLATION
§4.2). The worker's own git is unaffected, so its push runs the repository's hooks; step 5's fallback push runs none,
so a repository whose push needs one (Git LFS's `pre-push`) depends on the worker pushing.

Worker result contract, one JSON line, last line of the worker's text (§13):

```json
{"status":"done|blocked|failed","branch":"agent/KEY-slug","prs":{"api":"https://...|null"},
 "summary":"one paragraph","question":"only when blocked"}
```

`prs` maps each repository the run worked in to its PR. A single-URL `pr`, as older prompt overrides print, is still
read for a run in one repository.

Worker obligations, stated in every worker prompt:

- Work only inside the worktree, or a joint run's desk. Push only to `agent/<KEY>-*`, never with force, once per
  repository, as `git push origin HEAD:refs/heads/<branch>` from the detached HEAD; create no local branch. A resume
  that merges its base merges `origin/<base>`, which step 2 fetched, and does not fetch.
- Keep the runtime's attribution trailer on commits, or add a `Co-authored-by: canopy worker` trailer (TRUST_MODEL T5).
- Mark every comment and reply it posts, on the ticket or a PR: start it with `trust.comment_prefix` (`CANOPY:` by
  default) and end it with `trust.comment_suffix` (empty by default), each when it is set (D069). Below.
- Open each PR through the GitHub MCP, or, with `runtime.pr_skill` set, only with that skill (below).
- Comment on the ticket describing what was done and linking every PR. In a joint run, each PR's body links its sibling
  PRs and says which merges first.
- On `blocked`: post the question as a ticket comment, add `needs_human_label`, and push nothing half-finished or
  speculative beyond a WIP commit. A private ticket's worker posts nothing on the ticket: its result line's `summary`
  and `question` are its report and question (§22).
- Never approve, merge, close PRs, or transition the ticket to Done, including indirectly: no closing keywords
  (`Fixes #12`) or tracker commands (Jira smart commits) in commit messages, PR titles, or PR bodies.
- Push once. Do not poll CI. Do not retry.

Everything posts as the operator (D010), who is usually an authorized replier, so without a mark a worker's PR reply
would read back as new review feedback and spend a `resume` attempt, and its ticket comment could pass for an
authorized reply. A comment that carries every mark set, starting with the prefix if there is one and ending with the
suffix if there is one, outside any quote, is a worker's, whoever its author. The overseer, which reads the marks from
the state block's `trust`, and workers never read one as an authorized reply, a split request, or review feedback: it
makes no ticket `human_replied` or `changes_requested`, is not a new comment for `green_unreviewed`, and needs no
handling, so a cursor may advance past it (§7). The marks can only take authority away, so they need no protection:
anyone who marks a comment of theirs only silences it, and a comment without them is judged as before. They are plain
text, which every tracker's markup keeps as written (Jira's would show or drop an HTML comment), and they tell a person
reading the PR or ticket what wrote the comment. The harness never reads comments; the marks are for the agents that
do. Worker prompts get them as `{{MARK_COMMENTS}}`, the instruction to mark, and `{{WORKER_COMMENT}}`, how to recognize
a marked comment. Changing the marks leaves earlier workers' comments reading as the operator's. A prompt override
without the placeholders still renders, and its workers' comments read as the operator's, as they all did before D069.

How a worker opens a PR is the one step an operator may need done their own way: an employer's tooling that adds
metadata, a stacked-PR tool, or a host the GitHub MCP serves badly (D078). `runtime.pr_skill`, user-only, names a skill
of the operator's, which `implement` and `resume` workers then open every PR with, and in no other way; with it unset
they use the GitHub MCP. Workers get the instruction as `{{OPEN_PR}}`. A skill that is not available fails the run: the
worker opens no PR and reports `failed` with a summary starting `no PR skill:`, rather than falling back to the MCP
whose PRs the operator set the skill to avoid. The skill is ordinary customization (§13): it sits where the runtime
reads skills, under a name no repository canopy works in uses, since OpenCode picks either of two same-named skills and
a repository's could stand in for the operator's. Any program it runs must be on the `PATH` of the shell that runs
canopy, which workers inherit. It changes only how the PR is opened; every other obligation above still holds. The
branch is `{{BRANCH}}`, pushed without force, and `_run` still checks it is on origin (step 5). A program that pushes by
itself is past the bash rules, which match the command text, so branch protection governs (TRUST_MODEL T1). The PR
targets the listed base, carries the ticket key and `trust.pr_label` with no closing keywords, and its URL goes in the
result's `prs`. The overseer and later workers still read the PR through the GitHub MCP, so it must be one that server
can read. `fix-ci` and `split` open no PRs and ignore the key. Updating an existing PR, such as retargeting a stacked
one, stays with the MCP.

## 9. Aggressive release

- Slots are held only for the duration of `_run`.
- Reacquisition lands on an arbitrary slot, so build caches must be slot-independent: for Bazel, a shared disk cache
  or a remote one (below), configured in the operator's or the repository's `.bazelrc`, not in canopy. canopy
  documents this; it does not manage it.
- In a workspace, the operator may declare each pool's size; `canopy workspace sync` makes the slots ahead of time, so
  their hooks and build caches are warm before the first run lands in one (§18).

### Setting up a slot

Three steps, all the operator's, in the order they run (D105):

1. **Seeding.** On every `get`, a reused slot's too, treehouse copies ignored files from the primary clone into the
   slot: those the committed `.worktreeinclude` selects, or, with `paths.worktree_include` set, those the operator's
   own manifest selects instead. canopy passes it as `--include-file`, by its absolute path, on every lease: a run's,
   a review's, and sync's. treehouse reads one manifest, so a personal one replaces the committed one; copy in the
   committed lines to keep them. Its lines are git's exclude-file patterns and select only ignored files, so it can
   seed local config (`user.bazelrc`, `.env.local`) and never a tracked file. A missing file fails the lease, `no_slot`
   (§8), before treehouse touches a slot.
2. **`post_create` hooks**, in the user-level treehouse config, run after seeding when a slot is made or reused: on
   the base, before `_run` checks out the run's branch. A failing hook is printed and the lease stands. They suit
   setup that depends on the base alone, such as a toolchain or a warm fetch.
3. **`runtime.setup_cmd`**, user-only, runs in each slot of a worker run after `_run` checks out its branch (§8
   `_run` step 2), and fails the run when it fails. It suits setup that depends on the branch or must succeed:
   installing the branch's dependencies, generating code its build needs. It is split into words as `notify.cmd` is,
   with no shell and no placeholders. Splits and reviews run none: their agents have no shell.

`setup_cmd` runs the branch's code (a lockfile's install scripts, a generator) on the operator's machine, outside the
agent runtime's permissions. It is the code the worker's own shell runs a moment later, but outside any sandbox around
`worker_cmd`, so it is wrapped the same way (HOST_ISOLATION §4.4, TRUST_MODEL T4). A broken setup crashes every run it
meets, each spending an attempt (D030) and raising `crashed` (§14), whose note names it.

### Bazel

The operator's guide, with a `.bazelrc` recipe, examples of each setup step, sizing, and checks, is
[BAZEL.md](BAZEL.md). What canopy relies on:

- Bazel keys a workspace's output base on the workspace's path. Slots keep their paths across leases, so each slot's
  output base stays warm for whichever run leases it next. Slots share work only through what the operator's
  `.bazelrc` shares: a disk cache and a repository cache, or a remote cache.
- canopy does not stop a slot's Bazel server when it returns the slot (D106). `--max_idle_secs` ends it once no run
  has used the slot for that long, so a run that reuses the slot soon after finds it warm.
- `bazel-out/`, `bazel-bin/`, and `bazel-testlogs/` are links from the slot into its output base, outside the
  worktree. The worker's `external_directory: deny` is checked against the path as written, as the desk canary found
  for edits (ROADMAP M7), so the worker reads its outputs and test logs through the links and is refused the output
  base by its own path. That is no boundary: the worker's shell reads either (HOST_ISOLATION §1). The canary
  (`tests/canopy/test_opencode_canary.py`) checks it; it is opt-in, and its first real run confirms it.

## 10. Dependencies and stacking

Rationale in D045 and D054.

- The overseer reads blocker relations through MCP, in whatever form the tracker has them (Jira "is blocked by" links,
  GitHub issue dependencies; the provider skill says where to look). A blocker is resolved when it is closed. Other
  relations (relates to, parent and child) are not blockers; a tracker without blocker relations leaves every ticket
  unblocked. A relation is data: it can delay work, never authorize it.
- A ticket with an unresolved blocker and no branch of its own is `blocked`. The overseer records `wait` with rationale
  `blocked_by: <KEY>`, unless it stacks the ticket.
- Stacking: `canopy dispatch <KEY> --label <label> --kind implement --base <blocker's branch>` starts the worker from
  the blocker's branch, and the worker opens its PR against that branch, so the PR shows only this ticket's commits.
  The overseer stacks only on a ticket's single unresolved blocker, only when the blocker's PR is open, not merged, and
  green, and reads the blocker's branch from that PR, not from the journal.
- `policy.stacking` (§12) defaults to `"auto"`: the overseer stacks when the conditions above hold. `"never"`: a
  blocked ticket waits until its blocker has landed (closed, and its PR merged if it had one). A blocker whose PR
  closed without merging never landed; the blocked ticket gets `needs_author` attention instead of a dispatch.
  `"never"` governs starting a ticket; one already stacked keeps its stacked PR, `resume`, and `fix-ci`. The state
  block carries it with the other policy and the overseer prompt follows it. The harness adds no guard (D054): a
  `--base` dispatch under `"never"` is not refused.
- The harness checks only the shape of `--base` (`bad_base`, §8): under `trust.branch_prefix`, and not the run's own
  branch. It does not look the base up in the journal (the blocker may be in another operator's queue) and cannot read
  PR state (D003). `_run` fails a run whose base is not on origin (§8 `_run` step 2).
- The base is not remembered. Every dispatch starts from `--base` if given, else the pool's base branch, in every
  repository it names, and the run records each (`run_slots.base_branch`, shown in the latest run's `repos` in the
  state block). While the blocker's PR is open, the overseer passes the same `--base` to the stacked ticket's `resume`
  and `fix-ci`. Once it merges, a `resume` without `--base` tells the worker to retarget the PR to the repository's
  base branch, merging that branch in if it conflicts. Workers never rebase, since their pushes never force.
- Ordering is decided by the overseer each tick from live state and recorded in `decisions`. There is no plan file
  and no DAG config.

## 11. State model

The schema is `migrations/0001_init.sql`, the whole schema as of v0.1; a journal that applied the pre-squash
migrations is not upgraded (D068). Each later change is a new migration. Tables:

- `ticks`: one row per tick; id, timestamps, dry_run, status, summary, and what it read up to (`message_id`, `read_at`,
  §6 step 3). Status is `running`, `ok`, `skipped`, `overseer_failed`, `reconcile_failed`, or `abandoned`. What the
  runtime reported about its overseer run (§13), in the same columns as `runs`: `session_id`, `cost_usd`, and tokens by
  kind, all NULL when it reported nothing. A tick's cost is its overseer's alone; each run it dispatched records its
  own. `canopy decisions [TICK]` prints a tick (the latest by default), its overseer's session and cost, and its
  decisions; `--ticket KEY` filters decisions by exact ticket key and reports when none match. This is the way to read a
  dry run's plan. The web UI shows the same: its ticks page lists the latest 50, a tick's page its decisions, and a
  ticket's page the latest decisions about it across ticks (§22). A tick that cannot take the lock writes no row.
- `tickets`: one row per ticket key seen; the workspace root (`repo`), the ticket's own last derived phase, its
  branch (named by its first implement), the comment cursor (`last_comment_id`), a private ticket's message cursor
  (`last_message_id`, §22), the mirror cursor (`last_mirrored_id`, §22), done flag, and, once the operator forgot its
  work, when, with its newest run and message then (`forgotten_at`, `forgotten_run_id`, `forgotten_message_id`, §22).
  Cursors make ticks incremental. Attempt counts and the fix-ci cooldown are derived from `runs` and `run_slots`, not
  stored (D030).
- `ticket_units`: one row per unit, a ticket's work in one repository (§18); ticket, repository, branch, PR URL, the
  unit's phase, and its cursors (`last_review_id`, which holds a time despite its name (§7), and `last_ci_run_id`).
- `runs`: one row per worker execution; ticket, kind, branch (empty for a split, which works on none), pid of `canopy
  _run`, pid of the worker agent (`worker_pid`), status, result_json. Status is `running`, `done`, `blocked`,
  `failed` (the three the worker reports), `unknown`, `timeout`, `unpushed`, `crashed`, or `stopped` (§22); `private`
  marks a run on a started ticket. Source for capacity, crash
  detection, attempt counts, and the fix-ci cooldown. What the runtime reported (§13): the session id (`session_id`),
  the dollar cost (`cost_usd`), and tokens by kind (`tokens_input`, `tokens_output`, `tokens_reasoning`,
  `tokens_cache_read`, `tokens_cache_write`), all NULL when it reported nothing.
- `run_slots`: one row per slot a run leased; the repository whose pool it came from, slot path, lease id and holder,
  and the base branch the run started from there. A joint run has one per repository.
- `review_runs`: one row per review run; the PR's URL, the commit, the ticket of an agent PR, the repository and slot,
  pids, times, status, the validated result (§21). `decisions.pr` names the PR of a decision about a review.
- `split_children`: one row per ticket a split created; its parent, the repository it covers, and the split run.
  Written only by `_run` from a validated split result (§18).
- `decisions`: one row per overseer decision; tick id, ticket, action, rationale, and for an attention item about a
  repository or a ticket's unit, that repository (`repo`). Audit log and prompt-evaluation corpus.
- `chore_runs`: one row per chore run; the chore, pids of `_chore` and its agent, times, status, the validated result
  (§19). `decisions.chore` names the chore of a decision about one, which has no ticket key.
- `notifications`: one row per notification sink and open attention item it was told about, keyed by the sink and a
  fingerprint of the item's ticket, reason, and repository if any, so an open item is notified once per sink (§14,
  §20).
- `notify_events`: the outbox of point events for sinks, and `notify_sinks`: each sink's cursor, last delivery, last
  digest, and failures in a row (§20).
- `messages`: one row per message of a subject's conversation (§22), keyed by subject kind and id; source, kind,
  channel, the run of a worker's message, the body, the message a reply answers, and an operator message's submission
  id; for a mirrored tracker comment, its comment id (unique per subject), author, time, and whether the body was cut.
  Ids never repeat (`AUTOINCREMENT`). Migration 0003 backfilled every ended run's report and question.
- `starts`: one row per subject the operator started privately (§22); `started` or `stopped`, with when and through
  which channel. Never deleted: a stopped ticket stays private.

Rules: the DB never stores credentials or raw CI logs (token counts are usage, not credentials). `result_json` is a
summary.

In a workspace of one, the ticket's one unit is renamed to the repository's current name the next time canopy writes
it, and every lookup ignores the name, so renaming the checkout never strands a ticket (D033). `repo` in
`ticket_units` and `run_slots` is nullable, a remnant of pre-workspace journals; canopy never writes null there.

## 12. Configuration

Configuration is layered. Each layer overrides the one before it, key by key:

1. Built-in defaults in `config.py`.
2. **Repository file**, `canopy.toml` at the repository root. Committed, shared by everyone who runs canopy on the
   repository. Optional. In a workspace, the workspace file `canopy-workspace.toml` takes its place with the same scopes
   and rules, and the repositories' own `canopy.toml` files are not read (§18).
3. **User file**, `$XDG_CONFIG_HOME/canopy/config.toml` (default `~/.config/canopy/config.toml`). Personal, never
   committed. Required.

Every key has a scope. A **shared** key may be set in either file; the user file wins. A **user-only** key may be set
only in the user file; a repository file that sets one is a config error that names the key, and canopy refuses to
run. Unknown keys are errors in both files.

| Key | Scope | Why |
|---|---|---|
| `tracker.provider` | shared | a property of the repository's tracker |
| `tracker.query` | shared | the repository scopes it to a project; a user may narrow it |
| `tracker.needs_human_label` | shared | a signal to people; queues are already disjoint |
| `tracker.labels` | user-only | defines this operator's queue |
| `tracker.mcp_server`, `tracker.read_tools` | user-only | what a private ticket's worker may call (§22) |
| `policy.*` | shared; the repository may only tighten | limits spend, retries, and stacking |
| `trust.branch_prefix`, `trust.pr_label` | shared | team conventions for spotting agent work |
| `trust.authorized_repliers` | user-only | who may steer this operator's workers |
| `trust.trusted_reviewers` | user-only | whose review feedback reaches a worker without the operator's go-ahead (§7) |
| `trust.comment_prefix`, `trust.comment_suffix` | user-only | they silence the comments that carry them (§8) |
| `capacity.*` | user-only | the operator's machine and spend |
| `loop.*` | user-only | how often the overseer runs: the operator's spend |
| `runtime.*` | user-only | commands run on the operator's machine |
| `notify.*` | user-only | a command run on the operator's machine |
| `paths.*` | user-only | where prompts and state are read from |
| `chores.*` | user-only | a chore runs a command and a prompt, and spends money (§19) |
| `review.*` | user-only | `review.query` authorizes comments in the operator's name (§21) |
| `serve.*` | user-only | a listener on the operator's machine, and where (§22, TRUST_MODEL T8) |

Whoever controls the repository file (anyone who can push, or any branch checked out) must not run commands, choose
prompts, spend money, or authorize anyone; those keys are user-only (TRUST_MODEL T7).

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
max_split_attempts = 1       # per ticket (§18)
stacking = "auto"            # auto | never (§10); "never" is stricter

[trust]
branch_prefix = "agent/"
pr_label = "agent"
```

User file, personal:

```toml
[tracker]
labels = ["agent-ready-yourname"]
mcp_server = ""         # optional; the tracker's MCP server as OpenCode names it; default by provider (§22)
# read_tools = [...]    # optional; the only tools of it a private ticket's worker may call; default by provider

[capacity]
max_workers = 2

[runtime]
overseer_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer --format json {prompt}'
worker_cmd   = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --format json {prompt}'
split_cmd    = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-splitter --format json {prompt}'
overseer_timeout_minutes = 15
worker_timeout_minutes = 45
pr_skill = ""           # optional; the skill workers open PRs with instead of the GitHub MCP (§8)
setup_cmd = ""          # optional; runs in each slot at the run's branch, before the worker (§9)
setup_timeout_minutes = 30
# private_worker_cmd: worker_cmd with `--agent canopy-worker-private`, for a ticket started with `canopy start` (§22)

[loop]
interval_minutes = 15   # `canopy loop` waits this long after each tick ends
idle_max_minutes = 120  # and up to this long after idle ticks in a row (§6, Idle pacing)

[trust]
authorized_repliers = ["tracker-account-id"]   # Jira accountId, GitHub login, ...
trusted_reviewers = ["github-login", "canopy:review"]   # whose PR feedback a worker addresses unasked (§7)
comment_prefix = "CANOPY:"   # every worker comment starts with it (§8)
comment_suffix = ""          # and ends with this, if set

[paths]
prompt_overrides = "~/.config/canopy/prompts"
state_dir = "~/.canopy"
# worktree_include = "~/.config/canopy/worktreeinclude"   # optional; replaces the committed .worktreeinclude (§9)

[notify]
cmd = ""   # optional; receives the attention diff on stdin: the sink `default` (§20)

[notify.sinks.desktop]         # optional; any number up to 5 (§20)
cmd = "canopy-notify-desktop"
events = ["attention", "loop", "runs"]

[serve]                 # the web UI `canopy loop` serves (§22)
enabled = true
bind = "127.0.0.1"      # loopback, or a private address; never a wildcard or public one
port = 8765
base_path = ""          # a path prefix such as "/canopy", for a proxy
```

Built-in defaults are the values shown, except: `tracker.provider`, `tracker.query`, and `tracker.labels` have no
default and must be set; `trust.authorized_repliers` defaults to empty (nobody can resume blocked work), and so does
`trust.trusted_reviewers` (every review waits for the operator). A trusted reviewer is `canopy:review` or a login of at
most 100 characters with no whitespace, colon, or backtick.

`trust.comment_prefix` and `trust.comment_suffix` are each empty or one line of at most 80 characters, with a letter or
digit, no backtick, and no surrounding spaces, and at least one is set.

Rules:

- **Queues are per operator.** `tracker.labels` is a non-empty list; a ticket carrying any of them is in this
  operator's queue. Two operators must never share a label: the guards (one worker per ticket, attempt limits,
  cooldowns) see only the local journal. canopy cannot detect sharing; it is the operator's responsibility
  (TRUST_MODEL §7).
- **The repository may only tighten policy.** A repository `policy.*` value is used only if stricter than the built-in
  default: a lower attempt limit, a longer cooldown, or `stacking = "never"`. Otherwise the default stands. The user
  file may set any value, including a looser one; the rule only stops a commit from loosening limits for operators who
  never set them (TRUST_MODEL §3).
- `trust.branch_prefix` must be non-empty, end in `/`, and consist of plain ref components (letters, digits, `_`, `-`,
  each starting with a letter or digit) joined by `/`. Branch names reach git's argv.
- `canopy init --workspace`, or plain `canopy init` anywhere inside a workspace, sets up a workspace instead (§18).
- `canopy init` writes the user file if missing, with `tracker.labels = ["agent-ready-<$USER>"]` and an empty
  `trust.authorized_repliers` and `trust.trusted_reviewers` to fill in, and prints the label. It writes `canopy.toml`
  only if the repository has none, with `tracker.provider` and an example `tracker.query`. Neither file gets a key whose
  default serves: a default written into a file is pinned there, and a later canopy's never reaches it (D087). It never
  overwrites either file and installs nothing else (§13). If the config does not load (for example, templates lacking
  `{definitions_dir}`), it prints the error. It warns about copies of canopy's agent definitions in the repository's
  OpenCode config, which stop runs (§13).
- `capacity.slots_per_repo` and `[capacity.repo_slots]` declare each repository's pool size in a workspace (§18).
  Unset (the default) leaves pools unmanaged. User-only, so a team's map cannot grow the operator's disk use.
- Remotes should be HTTPS with a credential helper, not SSH (D038). `canopy init` runs
  `git remote get-url --push --all origin`, which applies `insteadOf` and `pushInsteadOf` rewrites, and warns naming
  every URL git would reach over SSH: `ssh://`, `git+ssh://`, or scp-like `[user@]host:path`. Only a warning: init
  still succeeds, and nothing else checks the remote.
- Reading is `tomllib`, merging is a key-by-key dict merge, and validation is pydantic models carrying each key's type,
  default, scope, and tighten direction (D026). Scope and tighten checks run per file before the merge, so errors name
  the file that caused them.

A command template is split into words with `shlex`, then `{prompt}` and `{definitions_dir}` are replaced inside each
word in one pass. No shell runs, so the prompt is always exactly one argument (D023). Every agent template must contain
`{prompt}` exactly once and `{definitions_dir}` (the definitions directory, §13) at least once; a template without it
is a config error that prints the line to write instead. The check cannot tell where the runtime reads the value: a
custom template, such as a sandbox wrapper's, must still set `OPENCODE_CONFIG_DIR` to it, or OpenCode runs its default
agent, which allows everything (D040). `env` in the default templates is the ordinary program, not a shell.
`notify.cmd` is split the same way, gets its input on stdin, and must not contain `{prompt}`.

Overrides in `prompt_overrides` replace files of the same name in `prompts/`. An override must keep what the guards rely
on: an overseer override must pass `--label` on every `canopy dispatch`, and a worker override must include
`{{LABELS}}` and the authorization check that uses it (§8, D051); a worker override without it is refused as
`bad_prompt`. The default is `prompts/` next to the user file, `~/.config/canopy/prompts` unless `XDG_CONFIG_HOME`
says otherwise; an empty value means the default. `paths.*` values must be absolute or start with `~`, since canopy
runs from the repository root and a relative path would let the repository supply them (TRUST_MODEL T7). In a
workspace, `paths.state_dir` is ignored: the state is always `<workspace>/.canopy/` (§18).

`tracker.provider` is a free-form name the harness never branches on; prompts use it to name the `tracker-<provider>`
skill, and every shipped skill is in the definitions directory (§13). `tracker.query` is how the
overseer finds candidates: in the tracker's search syntax where it has one (JQL, GitHub issue search), otherwise plain
language. It finds tickets; it does not authorize them (§17). The repository's query usually omits the label; an
operator can override it in the user file to include their labels and save the overseer reads.

## 13. Agent runtime

OpenCode. The harness depends on one capability: run a named agent non-interactively in a given cwd with a prompt and
read its stdout, `opencode run --agent <name>`. MCP connectivity, OAuth, and tool permissions are the runtime's job.

Agent definitions ship in `agents/`; agent runs load them from a directory canopy owns (below):

- `canopy-overseer`: read-only tools plus bash restricted to `canopy *` and `treehouse status*`. MCP: the tracker,
  GitHub.
- `canopy-worker`: edit and bash within the worktree. MCP: the tracker (ticket comments, and labels through its issue
  edit tool), GitHub (open/update PR, its label where a tool sets one, read reviews and checks); merge, review
  submission, closing, transition, ticket creation, delete, fork, API file and branch writes, and other agents or
  workflow runs denied by name (D084).
- `canopy-reviewer`: no edits, shell, or subagents; reads only through the link to its checkout. MCP: read
  tools and the one tool that comments on a PR's conversation; submitting a review, pushing, writing files, labels,
  and edits denied by name (§21).
- `canopy-chore`: no edits, shell, or subagents; MCP write tools denied by name (§19). A chore that runs the operator's
  own tools uses the operator's own copy of it.
- `canopy-splitter`: read-only file tools in its desk; no edit, shell, or subagents. MCP: the tracker
  (create and link tickets, comment), with tools for labels, assignees, edits, PRs, branches, and files denied by name
  (§18).

None has web tools: every definition denies `webfetch`, `websearch`, and `codesearch` (TRUST_MODEL T1, D077).

When the tracker is GitHub Issues, the tracker and GitHub are the same MCP server. The runtime is swappable by editing
the command templates. No interface.

### What a run prints

Every agent's output is read the same way (`core/agent_output.py`, D071). A template either prints the agent's text on
stdout, or asks OpenCode for `--format json`, which prints one JSON event per line. If any line of stdout is an event
(a JSON object with a string `type` and a `sessionID`), the agent's text is the `part.text` of each `text` event, one
per line; otherwise it is stdout itself. Every result contract (the overseer's done line, §8, §18, §19, §21) is the
last non-empty line of that text, so a template may switch formats without changing a prompt.

From events the harness also reads, each validated (D026):

- the session id: the first `sessionID` of at most 100 letters, digits, `_`, and `-`. The operator opens the
  transcript with OpenCode's own tools (`opencode export <id>`, or `opencode --session <id>` in the run's directory).
- the cost: the sum over `step_finish` events, one per model call, of `part.cost` in dollars and `part.tokens` (input,
  output, reasoning, cache read, cache write), each call's cost at most $1,000,000 and each count at most 10^12. If one
  does not validate, the run reports no cost rather than too little. Events with no model call cost nothing. A run
  killed mid-call (a timeout) reports what its finished calls cost, a lower bound. A subagent's calls are its own
  session's, and not counted.

The default `overseer_cmd`, `worker_cmd`, `split_cmd`, and `chore_cmd` ask for events. A tick records what its
overseer reports on the tick (§6), `_run` what a worker or split reports on the run (§8, §11), and `_chore` what a
chore reports on its chore run (§19). Other templates may ask for them too; what reviews report is not recorded yet
(ROADMAP M13). A tick's output file and a run log hold the events as
printed.

### Where the runtime finds canopy's definitions

Rationale in D040 and D044.

canopy snapshots its bundled `agents/` and `skills/` into `<state_dir>/runtime/<digest>/`, named for a digest of their
contents (`definitions.py`). One definition is rendered from the user config first: `canopy-worker-private` gets the
tracker's MCP server and the tools of it a private worker may call (§22), so a change to those keys makes a new snapshot
rather than changing one. A snapshot is written to a temporary directory, renamed into place, and never changed, so
overlapping runs never load a partial set. The overseer run and each `_run` use the installed canopy's snapshot,
creating it if missing. A snapshot canopy made is readable only by the operator; one that is a symlink, someone else's,
or open to others (for example from a checkout of a shared workspace, §18) is refused: the overseer's refusal fails the
tick, a worker's is a `crashed` run. When no run is live, reconcile removes other snapshots and temporary directories
over an hour old; a live run may be an earlier canopy's, still loading its snapshot. OpenCode scans both `agent/` and
`agents/` (and `skill/` and `skills/`) in a config directory, and writes a `.gitignore` and `node_modules/` into each
one it loads, the snapshot included.

Command templates name the current snapshot with `{definitions_dir}` (§12), required in every template that runs a
canopy-shipped agent (`overseer_cmd`, `worker_cmd`, `private_worker_cmd`, `split_cmd`, §19's `chore_cmd`, §21's
`review_cmd`):

```toml
overseer_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer --format json {prompt}'
worker_cmd   = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --format json {prompt}'
```

Nothing is installed into repositories, and a leased worktree always has the definitions its run names. OpenCode merges
`OPENCODE_CONFIG_DIR` after the repository's config, so a repository's definition of a canopy agent is merged into
canopy's and could loosen its bash rules (D044). Before starting an agent, the harness checks the OpenCode config in the
agent's start directory (the repository root for the overseer, the worktree on the run's branch for a worker) and
refuses if it defines one of canopy's agents: a file named for one under `.opencode/{agent,agents,mode,modes}/`, or an
`opencode.json` or `opencode.jsonc` at the root or in `.opencode/` whose text names one. The overseer's refusal fails
the tick (`overseer_failed`, summary naming the files); a worker's is a `crashed` run whose note names them, and its
slot is returned. `canopy init` warns about the same files. A private run (§22) is also refused where that config
names any tool of the tracker's MCP server (`<server>_`), since a rule merged after canopy's could reopen a write tool.

Customizing canopy is adding skills where the runtime already looks: the repository (`.agents/skills/`,
`.claude/skills/`, `.opencode/skill/`) or the operator's home (`~/.agents/skills/`, `~/.claude/skills/`,
`~/.config/opencode/skill/`). canopy turns none of these off. Give a custom skill its own name; same-named skills do not
reliably override each other. A `$HOME` skill that workers use must be a single `SKILL.md`: the worker's
`external_directory: deny` lets it load the skill but not read files next to it outside the worktree. A repository can
also define its own agents under other names, MCP servers, and permissions (TRUST_MODEL T7). A skill only adds to what
a prompt says; when the operator needs workers to open PRs differently from what the prompt says, `runtime.pr_skill`
names the skill and the prompt then says to use it (§8, D078). Prefer that to a prompt override.

### The operator's skill

Rationale in D047.

`canopy skill` prints a skill named `canopy` that teaches an agent in the operator's own session the canopy CLI, where
the state directory's files are, how to read the journal read-only, and how to answer "why was KEY not picked up".
canopy installs it nowhere: the operator saves it where their runtime reads skills, such as
`~/.agents/skills/canopy/SKILL.md`, and again after upgrading. It is not in the definitions snapshot, so a `$HOME` copy,
which canopy's own runs also load, never meets a same-named skill. It opens by telling an agent started by canopy
(`CANOPY_TICK_ID` set, or a canopy prompt) to follow its prompt instead. It grants nothing: the overseer's and worker's
bash rules apply either way.

## 14. Attention list

After every tick the list is rendered to `<state_dir>/attention.md` (`~/.canopy/attention.md` by default), readable
only by the operator: grouped by reason, one line per item with ticket key, age, and detail (usually a link).
`canopy status` prints it too, after a line for the last tick: its status, how long ago it started, its summary, and
its overseer's cost when the runtime reported it. Items disappear when their cause is gone; there is no manual
dismissal.

`canopy status` also lists the tickets the operator started (§22), each with its status, phase, and the message it
awaits a reply to, running workers, and the ten runs that ended most recently, newest first: ticket, kind,
status, how long ago it ended, and each PR it reported; its harness note or else its summary, on one line with control
characters dropped and cut at 160 characters; and its session id, its cost and tokens when the runtime reported them
(§13), and its run log.

Reasons are exactly the attention rows in the phase table plus `crashed`, `unpushed`, `unknown_result`, `worker_failed`,
`attempt_limit`, a private ticket's `awaiting_reply` (§22), and in a workspace `repo_missing` and the overseer's
`multi_repo`, `split_unlabeled`, and `split_self_labeled` (§18). Chores add `chore_failed` and their findings, listed by
chore after the ticket items (§19). Reviews add `review_failed`, `review_unposted`, and `review_limit`, about a PR
(§21). In a workspace of several, an item about one unit of a ticket names its repository and is shown as `KEY (repo)`.

The harness raises the run reasons itself, every tick, after reconcile (D028). For a ticket not marked done, its latest
run's status maps to a reason: `crashed` to `crashed`, `unpushed` to `unpushed`, `unknown` or `timeout` to
`unknown_result`, `failed` to `worker_failed`. The detail names the run, its kind and branch, the harness note or the
worker's summary, and the run log. The cause is gone when a newer run starts for the ticket or the ticket is marked
done. The overseer does not dispatch such a ticket again until an authorized replier comments after the run ended;
that is how a human says "try again". An operator message after the run ended says it too (§22, D093), the only way
on a private ticket.
`blocked` and `stopped` raise nothing here.

The harness raises `awaiting_reply` every tick for each started ticket, not done, whose latest question has no operator
message after it (§22). Its detail is the question's message id and text, one line, and how to answer it. Its cause is
gone once the operator replies, and the item with it at the next `ok` tick; until then the web UI marks it answered.

The harness also raises `repo_missing` every tick for each repository in the workspace map with no clone at
`repos/<name>`. It has no ticket key, carries the repository's name, and is shown under that name. Its cause is gone
once `canopy workspace sync` (or anything else) puts the clone there.

The overseer records an item with `canopy attention <KEY> <reason> [--repo NAME] --detail "<link or text>"`, every tick
the cause holds. `--repo` names the unit it is about, such as the PR waiting on a reviewer; in a workspace of one it is
ignored, since naming the only repository would make every item new. The item is stored as a decision with action
`attention:<reason>`, not in a separate table (D020). The current list is the attention decisions of the latest `ok`
tick: an item disappears the first tick that does not record it, and a failed or `skipped` tick leaves the previous
list standing. Dry-run ticks count like live ones. An item's age runs from the first tick of its unbroken run. Reasons
must match `[a-z][a-z0-9_]*`.

`attempt_limit` is raised two ways: the overseer records it when the state block shows a ticket at its limit for the
work it needs, and `canopy dispatch` records it with an `attempt_limit` refusal. Either way it lasts as long as the
overseer keeps asking for that work. In a workspace of several, the refusal's item names the unit at its limit.

Notification (D032). An item is identified by its ticket, reason, and repository if it has one, so two units at their
fix-ci limit are two items; rewording its detail does not make it new. Each notification sink (§20), `notify.cmd`
among them, keeps its own record of what it was told. When `notify.cmd` is set, each tick compares the list with its
rows in the `notifications` table: unrecorded items are new, and rows whose item is no longer listed are resolved. If
either exists, the command gets one message on stdin: a summary line, a `+ KEY reason: detail` line per new item, a
`- KEY reason` line per resolved one, and the path of `attention.md`. Only when it exits 0 within 60 seconds are new
items added to the table and resolved ones removed. So a failed notification is retried next tick, an open item is
never notified twice, and an item that returns after going away is new again.

## 15. Failure handling

- Worker crash: detected by pid liveness in reconcile; what is left of the worker is killed; every slot returned and a
  joint run's desk removed; ticket goes to attention with `crashed`. Not auto-redispatched: the harness never restarts
  a run, and the overseer prompt waits for an authorized reply (§14). Every kind has an attempt limit in code, so an
  overseer that redispatches anyway stops at `policy.max_<kind>_attempts` (D030).
- Worker exits without a result, times out, reports `failed`, or leaves commits unpushed: `_run` returns the slot and
  records the status; the ticket goes to attention (§14).
- Stale lease without a run: returned in reconcile.
- treehouse unavailable or failing in reconcile: tick closes with `reconcile_failed`; the overseer does not run.
- Overseer timeout or bad output: tick closes with `overseer_failed`; nothing is dispatched; next tick retries. Three
  consecutive ticks that end other than `ok` produce a `loop.failing` notification for sinks that take `loop`, once per
  streak, and `loop.recovered` at the next `ok` tick (§20). There is no attention item for this: the attention list is
  the latest `ok` tick's, so a failing loop cannot add to it.
- MCP unavailable: the overseer reports it with a tick-wide `skip`; the tick closes as `skipped` and `canopy tick`
  exits 1; no decisions are made on partial data, and the attention list stays as it was (D037). The overseer prompt
  says so explicitly.
- Overseer asks for something the guards refuse: the refusal is recorded as a decision with the guard's reason.
- An error the tick code does not handle, in a tick `canopy loop` runs: the tick ends as `error` in the loop's output,
  the traceback is logged, and the loop goes on. The next tick closes the row as `abandoned` (§6).

## 16. Open questions

- Whether `ask` permissions in OpenCode agent definitions block or auto-deny
  under `opencode run`. Answered from OpenCode's source in M1: `ask` is auto-rejected and `deny` is enforced (D021).
  The live canary (`tests/canopy/test_opencode_canary.py`) is opt-in; its first real run confirms or overturns this.
- Whether a Slack notification path should use `notify.cmd` with a small script or the overseer posting via MCP.
  Answered in M10 (§20, D035): a sink command, with a Slack sink shipped in canopy. The overseer does not post.
- Whether `merged` should trigger a tracker transition. Default no; humans own
  ticket state.
- One operator on several repositories. Answered in M6 by the workspace (§18): one queue, one user file, and state
  per workspace under its root. Separate repositories that are not one queue stay separate workspaces of one, which
  share `paths.state_dir` and so its journal and locks.

## 17. Trackers

canopy works with any issue tracker the agent runtime can reach through an MCP server. There is no adapter interface and
no tracker code in the harness. Tracker differences are handled in three places, in order of preference:

1. **The contract below.** Agents map it onto the tools a tracker's MCP server exposes without being told how. This is
   the default for any tracker.
2. **Config.** `tracker.provider`, `tracker.query`, the queue labels, `needs_human_label`, and
   `trust.authorized_repliers` in the tracker's own identity format.
3. **A provider skill**, `.agents/skills/tracker-<provider>/SKILL.md`, for what an agent would otherwise get wrong:
   identity fields, how "closed" is expressed, where blockers live, and text that silently triggers a tracker action
   (closing keywords, smart commits). Skills ship for `jira` and `github`. A skill is optional; add one when the
   `decisions` table shows the loop misreading a tracker, not in advance.

### Contract

What the loop needs from a tracker, as capabilities, each used by the role in parentheses.

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
cannot do a required row, the overseer records `skip` with rationale `tracker_unsupported: <capability>`, and the
operator fixes the MCP setup or writes a skill.

### Authorization is the same everywhere

The query only finds tickets. A ticket is a candidate only if reading it shows one of `tracker.labels` present and the
ticket not closed, so a sloppy or plain-language query can waste a tick but cannot authorize work. Replies are
authorized only by `trust.authorized_repliers`, compared against the author's stable account id (Jira `accountId`,
GitHub login), never a display name.

### Ticket keys

A key is the tracker's short, human-readable id, as the provider skill defines it: `PROJ-123` for Jira, `GH-123` for
GitHub Issues. Keys appear in branch names, lease holders, file paths, and shell arguments, so `canopy dispatch`,
`decide`, `attention`, and `ticket set` reject, in code, any key that does not match `[A-Za-z0-9][A-Za-z0-9_-]*`.

## 18. Workspaces and multi-repo tickets

ROADMAP M6 to M8 and M17; rationale in D033, D058, D059, D061, D062, and D066. Earlier sections describe one
repository: the workspace of one below.

### Shape

A workspace is a directory canopy manages: a map of the repositories a queue's tickets touch, one primary clone of
each, the worktree pools, and canopy's state. The loop runs from the workspace root.

```text
~/work/acme/                 workspace root; canopy tick runs here
  canopy-workspace.toml      the map, and the shared config layer
  MAP.md                     prose: what each repository owns and how they depend on each other
  repos/api/                 primary clones, one per repository in the map
  repos/web/
  .treehouse/                every repository's treehouse pool
  desks/PROJ-12/             one per running joint run: a link to each worktree it leased
    api -> ../../.treehouse/<api pool>/3/api
    web -> ../../.treehouse/<web pool>/1/web
  .canopy/                   journal, locks, logs, attention.md; operator-only
```

A repository with no workspace file is a workspace of one, on the same code path: its map is itself, its `canopy.toml`
plays the workspace file's part, and state and pools stay where §12 and treehouse put them. Its name (state block,
`--repo`) is its directory's name, lowercased, with characters a repository name cannot hold turned into hyphens.

canopy finds the workspace by walking up from the current directory to the nearest `canopy-workspace.toml`, so it
works from inside `repos/` too; with none, the nearest `.git` above names the workspace of one.

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

- A repository name matches `[a-z][a-z0-9-]*` (a directory name, a treehouse leaf, a `--repo` argument). Its clone is
  at `repos/<name>`, not configurable, so a map cannot point outside the workspace.
- `summary` is one line, at most 200 characters, rendered into the overseer's state block. `MAP.md` is prose the
  overseer and workers read: ownership, dependency direction, where contracts live, landing order. Both are data, like
  ticket text, and authorize nothing.
- Config layers: built-in defaults, the workspace file, the user file. The workspace file takes the repository file's
  place, same scopes, repository policy may only tighten. Repositories' own `canopy.toml` files are not read inside a
  workspace: one tracker, one queue.
- A map committed to a shared repository is a repository file (TRUST_MODEL T7). `url` is read only by the operator
  commands `canopy workspace sync`, which prints what it clones first, and `canopy workspace add`, which writes it. Map
  URLs should be HTTPS (D038); `sync` warns about SSH ones as `canopy init` does and clones them anyway. A tick never
  clones or changes a remote; a mapped repository with no clone is attention `repo_missing` and cannot be dispatched
  to.
- `canopy init --workspace` writes, overwriting nothing: the workspace file (asking for the tracker provider), a
  `MAP.md`, a `.gitignore` covering `repos/`, `.treehouse/`, `desks/`, and `.canopy/` (an existing one gains only
  missing lines), and the user file if missing. It prints the branch protection rules with every mapped repository
  they must be configured in. Plain `canopy init` inside a workspace does the same.
  `canopy init --workspace [NAME=]URL...` also does `canopy workspace add` with the URLs, before printing the rules.
- `canopy workspace add [NAME=]URL...` appends a `[repos.<name>]` table per URL, with an empty summary, then syncs. The
  name is the URL's last path segment without `.git`, reduced as a workspace of one's name is (`Web_App` is
  `web-app`), unless given as `NAME=URL`. A URL already listed (compared as sync compares `origin`) is left alone. A
  name already given another URL, or a URL with no usable name, refuses the whole command; nothing is written. The map
  is appended to as text, keeping comments and layout, under the tick lock after rereading it, via a temporary file
  renamed over it. The result is parsed as a map before sync runs.
- `canopy workspace sync` prints each clone, then runs `git clone -- <url> repos/<name>` with credential prompts and
  git's `ext::` transport off. For an existing clone it reports an `origin` differing from the map's URL (ignoring a
  trailing `/` or `.git`) and changes no remote. It also sizes pools and removes unlisted clones (below). It exits 1 if
  a clone failed, if `repos/<name>` exists and is not a clone, or if anything declared could not be reached. It prints
  a URL's credential as `***`; `canopy init --workspace` names repositories without URLs.
- A workspace's state is always `<workspace>/.canopy/`, created readable only by the operator, so each workspace has
  its own journal and locks; `paths.state_dir` applies only to a workspace of one. A `.canopy/` that is a symlink,
  someone else's, or open to others stops every command with a config error until removed (D053). A definitions
  snapshot inside it is checked the same way before each run loads it (§13).

### Worktrees live in the workspace

Every treehouse command canopy runs has `TREEHOUSE_ROOT` set to the workspace root and runs in the repository's
primary clone, so pools live under `<workspace>/.treehouse/`. The variable outranks both treehouse config files, so a
repository's `treehouse.toml` cannot move them, and `get` passes `--worktree-path '{pool}/{slot}/{repo}'` to pin the
layout. These pools are separate from the operator's interactive ones under `~/.treehouse`, so an interactive
`treehouse` never recycles canopy's slots. Build caches must still be slot-independent (§9).

There is no key to put a workspace's pools anywhere else (D033). For a fast disk, put the workspace on it. git keeps
each worktree's index and HEAD, and every object it writes, in the primary clone's `.git`, so a pool on another disk
than its clone still does git's work on the clone's. treehouse names a pool after the repository and a hash of its
remote URL, so one pool root that every workspace shared (the user file serves them all) would put two workspaces'
clones of a repository in one pool, where each sync and each declared size would count the other's slots. Build
outputs need not follow the workspace: Bazel's live under `--output_user_root`, wherever the operator's `.bazelrc`
puts it (§9). A workspace of one's pool is wherever treehouse's own `root` config puts it.

Reconcile runs `treehouse status --json` once per mapped repository with a clone and returns stale `canopy:` leases. A
repository with no clone has no pool; the tick records `repo_missing` (§14) and dispatch refuses it. A run's slot is
returned through the pool of the repository it records; if that clone is gone, treehouse runs at the workspace root
and finds the pool from the slot's path (two levels below it). The overseer runs at the root, not a repository, so the
state block carries each pool's leased slots instead of its own `treehouse status`. Lease holders stay `canopy:<KEY>`;
one ticket can hold a slot in several pools.

### Declared repositories and slots

The map declares the repositories; the user file declares each pool's slots (D066). `canopy workspace sync` converges
on both, and a tick never grows a pool past its declared size.

```toml
# ~/.config/canopy/config.toml
[capacity]
slots_per_repo = 2      # every repository's pool, in any workspace
[capacity.repo_slots]
api = 4                 # by repository name; wins over slots_per_repo
```

- Pool sizes are user-only (§12). `repo_slots` may name repositories this map does not list. With neither key (the
  default) a pool is unmanaged: treehouse's `max_trees` bounds it and sync leaves it alone.
- Only a workspace's pools are sized. A workspace of one's pool is wherever treehouse's config puts it (by default the
  interactive pool under `~/.treehouse`); canopy neither caps nor converges it.
- **Leases stay within the size.** Before `treehouse get`, dispatch (§8) and a review (§21) read the pool. If as many
  slots as its declared size are busy, the lease is refused as `no_slot` without asking treehouse; a size of 0 refuses
  every lease. If treehouse makes a slot anyway (the available ones are not reusable, such as one recorded for another
  clone), canopy returns it, destroys it, and refuses. A pool under its size grows normally.
- **Sync fills each pool**: it leases with holder `canopy-sync` and `--no-fetch` until the pool has enough slots, then
  returns those leases. Holding each lease forces treehouse to make the next slot new, and `post_create` runs then,
  not in a run's lease. Reconcile never touches `canopy-sync` (not a `canopy:` holder); each sync returns leftover
  `canopy-sync` leases before counting. If treehouse refuses to grow the pool, usually because its `max_trees` is below
  the declared size, sync reports the repository failed; canopy cannot set `max_trees`, which treehouse reads only from
  its own config files.
- **Sync trims each pool**: it removes available slots, highest name first, with `treehouse destroy --yes` and no
  `--include-*` flags, so treehouse removes only a clean, merged, idle, unleased slot; one it keeps is passed over.
  Busy slots over the size wait for a later sync. A pool kept over its size by a slot with work in it makes sync exit
  1.
- **Sync removes clones the map no longer lists.** Anything under `repos/` the map does not name, except dot entries,
  is removed with its pool's slots only when nothing would be lost: a directory with a `.git`, not a symlink; empty
  `git status --porcelain --ignored` (ignored files count: a primary clone holds the local config `.worktreeinclude`
  seeds into slots) and `git stash list`; every commit reachable from `HEAD`, a branch, or a tag on a remote-tracking
  ref; and every slot in its pool available and destroyed by treehouse unforced. Anything else is kept and reported,
  and sync exits 1. treehouse's record of the emptied pool stays under `.treehouse/`.
- Sync holds the tick lock, waiting for a running tick to end. Runs in progress keep their leases, counted as busy.
- `canopy workspace sync --dry-run` reports what it would clone, make, and remove, changing nothing. It runs the
  read-only checks, so a clone it would keep a real sync keeps; what it would remove, treehouse may still keep. An
  uncloned repository is previewed with every slot to make.
- A lease sync cannot return, its own or a dead sync's, makes the pool `failed` and sync exit 1.

### Units

A ticket's work is divided into units, one per repository it changes, each with its own PR, phase, review and CI
cursors, and attempt counts. Per ticket stay the comment cursor, the ticket's own phase (`ready`, `blocked`,
`needs_human`, and the others not about a PR), and the branch, which every unit shares (D059). A single-repository
ticket has one unit.

A ticket's units are the repositories it has been dispatched to. Each dispatch names its units with `--repo`
(repeatable; optional in a workspace of one), chosen by the overseer from the ticket, the summaries, and `MAP.md`. An
`implement` over several repositories is a joint change: one worker, one PR per repository, each linking the others,
for changes that cannot build or pass tests separately. `fix-ci` and `resume` normally name only the unit needing
work.

A later `implement` naming a repository the ticket has no unit in adds one, also after another unit's PR merged: a
sequenced change, authorized by the ticket's label (D058). A repository has at most one unit per ticket; a follow-up PR
after its unit merged is a new ticket a human files (TRUST_MODEL T1). The overseer marks the ticket done when every
unit's PR has merged and no other repository is left to change.

A multi-repository ticket stays one ticket, worked jointly or in sequence as the overseer judges (D061), and is split
(below) only when an authorized replier asks in a comment on it. One that is several independent pieces with no such
request gets `multi_repo` attention: a human asks for a split, splits it by hand, or narrows it.

Guards (§8) change as follows:

- `running` stays per ticket: one worker per ticket, whatever its units (TRUST_MODEL §6).
- `unknown_repo`: in a workspace, no `--repo`, or one not in the map or with no primary clone; for a split child, any
  repository but the one recorded, or more than one.
- `bad_slug`: a later `implement` whose `--slug` names another branch than the ticket's.
- `no_branch`: `fix-ci` and `resume` for a unit with no branch.
- `attempt_limit` counts per unit: a run counts against every unit it covers.
- `cooldown`: from the end of the latest fix-ci run covering the unit.
- `capacity` counts runs, not slots: a joint run over three repositories is one worker holding three slots.
- `no_slot`: leases are all or nothing; if any `treehouse get` fails, slots already leased are returned before the
  refusal is recorded.

Harness attention items for runs (§14) stay per ticket, their detail naming the repositories that failed. An
`attempt_limit` refusal's item and the overseer's items about a PR name their unit.

### Runs over several repositories

- The branch is `<trust.branch_prefix><KEY>-<slug>` in every repository. The ticket's first `implement` fixes the slug;
  later implements reuse it and refuse a `--slug` naming another.
- `_run` does branch setup (§8 step 2) and push verification (step 5) in each worktree. A one-repository run's worker
  runs in the worktree; a joint run's runs in its desk, `desks/<KEY>/`, made just before it starts, with a relative
  link per worktree named for its repository. The trap removes the desk and returns every slot; reconcile does both
  for a run whose `_run` died. A desk is made only in a `desks/` that is not a symlink, and removal never follows its
  links. canopy marks its desks with a `.canopy-desk` file and removes only marked ones; anything else under `desks/`
  is the operator's, and something unmarked where a desk goes refuses the run. A run is `unpushed` if any repository's
  branch is.
- Before a joint run's worker starts, the shadowing check (§13) covers each worktree, `desks/`, and the workspace root,
  since OpenCode may read config above the desk.
- The worker prompt lists each repository: name, path (in the desk for a joint run), branch, base, the unit's PR if
  any, and summary.
- The result contract's `"pr"` becomes `"prs"`, an object from repository name to PR URL or null; each URL is recorded
  as its unit's `pr_url`.
- Worker obligations add: each PR's body links its sibling PRs and says which to merge first; the ticket comment lists
  every PR. Workers still never merge.

### Splitting

Rationale in D061 and D062. canopy splits a ticket in the tracker only when asked and never schedules what it split:
children start without a queue label, so a human authorizes each (TRUST_MODEL T1).

- The overseer dispatches a split only when an authorized replier's comment on the ticket, newer than its comment
  cursor, asks for a split into separate tickets; never on its own judgment.
  `canopy dispatch <KEY> --label <label> --kind split --request <comment id> --repo api --repo web` names that
  comment. A split without `--request` is `unauthorized`; `--request` on another kind is `bad_request`. The harness
  cannot read the comment (D003), so `--request` is a recorded claim, like `--label`; the splitter reads it and creates
  nothing unless an authorized replier wrote it and it asks for a split. A split prompt override without `{{REQUEST}}`
  or `{{REPOSITORIES}}` is `bad_prompt`.
- `bad_split` refuses a split in a workspace of one, over fewer than two repositories, of a ticket that has a branch
  (split it by hand), or of a split's child. `--slug` is `bad_slug` and `--base` `bad_base`: a split has no branch.
  `policy.max_split_attempts`, default 1, limits `split` attempts per ticket, never per unit.
- The split worker runs with `runtime.split_cmd` as `canopy-splitter`: an agent definition with no edit, shell, web
  fetch, or subagent tools, and MCP tools whose names suggest labels, assignees, edits to existing tickets, PRs,
  branches, or files denied by pattern. Where the runtime can restrict a create tool's arguments, a definition could
  also forbid labels on create; the check below holds regardless.
- It runs like a joint run, in a desk of the named repositories' worktrees, with the worker's timeout. Its prompt
  carries the first 20,000 characters of `MAP.md`, since it may not read outside its desk. `_run` checks each worktree
  out at its base branch, detached, makes no branch, pushes and verifies nothing, and records no branch or unit
  (`runs.branch` is empty). Slots are returned and the desk removed on every exit path; reconcile treats a dead split
  run like any other.
- It creates one child per repository with a share of the work, if each share can be built and reviewed alone;
  otherwise it creates nothing and reports `failed` saying why. Each child's body names its repository
  (`canopy-repo: web`) for people, links the parent, and says what it covers. Children that must land in order get
  the tracker's blocker relation (`web` blocked by `api`), so M4's ordering applies. Children carry no queue label and
  no assignee.
- It comments on the parent listing the children and which label starts each. Its result line is
  `{"status":"done|failed","summary":"...","children":{"PROJ-13":"api","PROJ-14":"web"}}`, listing every child it
  created even when `failed`. `_run` validates: each key a valid ticket key (§17) of at most 100 characters, new to the
  journal (never a split's child, never dispatched, never in `tickets`) and not the parent; each repository one the
  split was dispatched with, at most once; a `done` split names at least one child. `blocked` is not a split status.
  Anything else makes the run `unknown` and records nothing; its stored result keeps the note but none of the children.
  A valid result goes into `split_children`, also when the run timed out after printing it, and is the source of a
  child's repository afterwards, in a workspace of one too.
- The parent's phase becomes `split`: wait, with attention `split_unlabeled` naming each child still open and
  unlabeled. Any dispatch for it is `bad_split`. The overseer marks the parent `done` in the journal once every child
  is closed; canopy does not touch its tracker state.
- A child is a candidate only if its queue label was added after the split run ended. The state block carries
  `split_children` (parent, repository, split run, `split_ended_at`) until parent and child are both done, and the
  overseer compares it with the tracker's label history. A label the split worker added, at creation or later, does
  not count: the overseer records `split_self_labeled` for that child, which stays out of the queue until a human
  removes the label and adds it again. On a tracker without label history (the optional row of §17's contract) the
  overseer does not split; it records `multi_repo` saying why.
- This check is the overseer's, not a harness guard, since the harness never reads the tracker (D003): the same kind
  of control as the queue-label check (§17), with the same residual (TRUST_MODEL T1).
- A child is an ordinary one-repository ticket. `canopy dispatch` for a key in `split_children` refuses any `--repo`
  but the recorded one (`unknown_repo`), so editing its `canopy-repo` line changes nothing, and refuses another split
  (`bad_split`). A ticket split by hand has no such row; the overseer chooses its repository as for any ticket.

### Journal

- `ticket_units`: ticket key, repository, branch, PR URL, phase, `last_review_id`, `last_ci_run_id`. `tickets.phase`
  is the ticket's own; the state block shows it and each unit's.
- `run_slots`: run id, repository, slot path, lease id, lease holder, base branch. `runs` has no slot columns.
- `split_children`: child key, parent key, repository, split run id; written only by `_run` from a validated split
  result.
- `tickets.repo` holds the workspace root.
- Attention items carry an optional repository and are identified by ticket, repository, and reason, so two units at
  their fix-ci limit are two items. `canopy attention` takes `--repo`.

### Trust model changes

TRUST_MODEL items this section relies on, each approved with the milestone that needed it:

- T1 (M8): the loop may create tickets, never on its own decision and never with a queue label; the check is in the
  overseer prompt, backed by the splitter's read of the request and its permissions.
- T4 (M7): a worker's edit permission covers the worktrees linked from its desk. The desk canary
  (`tests/canopy/test_opencode_canary.py`), like D021's, shows OpenCode allows edits through the links and denies
  paths beside them.
- T6 (M7, M8): the write scope is the repositories of the run's units; the splitter's is creating and linking tickets
  and commenting on the parent.
- T7 (M6): the workspace file is a repository file; clone URLs are read only by an operator command; state directory
  and definitions snapshots are private to the operator (D053).
- §7 (M6): branch protection is needed in every mapped repository; `canopy init --workspace` prints the rules for each.

### Open

- Whether an authorized replier's approval of the split on the parent, rather than a label on each child, should make
  an unlabeled child a candidate. The request that started the split is not that approval.
- Whether a child's desk should also hold its blockers' unmerged branches, read-only by prompt, to build against.
- Whether a started ticket should ever be split. `bad_split` refuses it now; a human splits one by hand.
- Whether a follow-up PR after a unit merged, for late review feedback, should be possible inside the ticket, on an
  authorized replier's comment. D058 leaves it to a new ticket; revisit if filing those proves friction.

## 19. Chores

Rationale in D034, D063, D099, and D100.

A chore is recurring work the operator defines and the overseer delegates: an agent run about no queue ticket, with no
worktree and no push, that reports findings to the attention list (for example, a build-health check over CI, other
people's PRs included). The operator's config defines the chore and its fastest recurrence; the overseer decides when;
guards in code hold the limits (§4).

### Definition

Chores are user-only (§12); one in a repository file is a config error (TRUST_MODEL T7).

```toml
[runtime]
# the default
chore_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore --format json {prompt}'

[capacity]
max_chores = 1            # chore runs at once; separate from max_workers

[chores.build-health]
prompt = "~/.config/canopy/chores/build-health.md"
cmd = 'opencode run --agent build-health --format json {prompt}'
every_minutes = 120
days = ["mon", "tue", "wed", "thu", "fri"]
hours = "08:00-18:00"
timezone = "America/New_York"
when = "Skip it when the last run found nothing and nothing has merged to main since."
timeout_minutes = 20
cwd = "~/src/build-tools"
workspaces = ["acme"]     # optional; default every workspace
```

- A chore name matches `[a-z][a-z0-9-]*`.
- `prompt` (required) is the operator's file, absolute or starting with `~` like every `paths.*` value.
  `examples/chores/build-health.md` is one to start from: it checks CI through the GitHub MCP server's read tools, so
  it runs under the shipped `canopy-chore`.
- `cmd` follows §12 (`{prompt}` exactly once, no shell); default `runtime.chore_cmd`. A chore using the operator's own
  tools needs its own agent definition (below), so `cmd` is usually set.
- `every_minutes`, at least 15, is the shortest time between two run starts. A guard, not a schedule.
- `days`, `hours`, and `timezone` (optional) say when a run may start, checked in code (D099). `days` lists `mon` to
  `sun`, empty for every day; `hours` is `HH:MM-HH:MM`, ending after it starts on the same day (`24:00` is the end
  of the day); `timezone` is an IANA name, by default the machine's local time. They bound only a run's start: one
  running when the window closes runs to its end or timeout.
- `when` (optional) is plain language for the overseer: when a run is worth it, pointless, or urgent. Without it the
  overseer runs a chore whenever due. Being operator-written, it is an instruction; nothing a chore reads is. Clock
  times belong in `days` and `hours`, which cost no judgment and no `wait` decision every tick.
- `timeout_minutes` defaults to 15. `cwd`, absolute or starting with `~`, defaults to `<state_dir>/chores/<name>/`,
  created readable only by the operator. The shadowing check (§13) covers `cwd` and every directory above it before
  the agent starts: OpenCode config there that defines one of canopy's agents makes the run `crashed`.
- `workspaces` names workspaces: a map's `[workspace] name`, or a workspace of one's repository name (§18). Empty (the
  default) means every workspace whose loop reads the user file. A chore in two workspaces runs in each, each with its
  own journal (D063).

### Off unless configured

- No `[chores.*]` tables: the state block has no `chores` key (the overseer prompt skips its chore paragraph), no chore
  decisions are recorded, and `canopy chore run` refuses as `unknown_chore`. Ticket handling is unchanged.
- `capacity.max_chores = 0` turns every chore off the same way without deleting any.
- Deleting a chore's table turns it off. Only configured chores reach the attention list, so its findings and
  `chore_failed` item go at the next render and are notified as resolved (D032). Its `chore_runs` rows stay.
- Chores never affect what the overseer does with tickets: they cannot cause or prevent a dispatch.

### Agent definitions and tooling

canopy ships `canopy-chore` in the definitions directory (§13): no edits, no subagents, no bash, and no MCP write tools
where the runtime can deny them by name. It can read the tracker and GitHub, including other people's PRs.

A chore using the operator's deterministic tools gets its own definition, copied from `canopy-chore` into the
operator's runtime config (for OpenCode `~/.config/opencode/agent/`, never the repository's `.opencode/agent/`), with
bash allowed for exactly those tools:

```yaml
permission:
  edit: deny
  task: deny
  bash:
    "*": deny
    "buildq *": allow        # the operator's read-only CLI for the build queue
```

The operator installs the tools, on `PATH` (`uv tool install`) or in a checkout `cwd` points at. CI credentials belong
to the tools or the runtime's MCP servers (§4, principle 5); canopy never sees them and knows nothing of Jenkins or any
CI system.

### Delegation

- The state block's `chores` lists per configured chore: name, `every_minutes`, `when`, `due_at` (earliest time the
  `not_due` and `outside_hours` guards allow a run: `every_minutes` after the latest start, moved to when the window
  next opens), whether running, latest run (id, status, start, end, summary), and open findings (id, title,
  link) from its latest `ok` run, which a later non-`ok` run does not replace.
- Each tick the overseer decides each chore past `due_at` and not running. It runs it with
  `canopy chore run <NAME> [--context '<text>']`, or records `canopy chore wait <NAME> --rationale "<text>"` when
  `when` says not now. Chores not due need nothing.
- `--context` follows D031: at most 2000 characters pointing at what to look at, never quoting untrusted text. Empty
  renders as "None."
- Findings inform only decisions about the chore, never about tickets (see Open).

`canopy chore run` requires `CANOPY_TICK_ID` like `dispatch` (D020) and refuses, recording `refused:<guard>`, on the
first of:

- `unknown_chore`: no such chore in the user config, not for this workspace, or `max_chores` is 0.
- `running`: a run of this chore is running.
- `not_due`: less than `every_minutes` since this chore's latest run started, however it ended.
- `outside_hours`: now is outside the chore's `days` and `hours`, in its `timezone`.
- `chore_capacity`: `capacity.max_chores` chore runs are running.

A dry run checks the same guards, counting chores it already ran as running, records `dispatch:chore` with rationale
`dry run: not dispatched` or the refusal, and starts nothing (D036). A live run's rationale is `chore run <id>` plus
any context. `canopy chore wait` refuses an unconfigured chore and records nothing. Chore decisions (`dispatch:chore`,
`wait`, `refused:<guard>`) are `decisions` rows with the chore in the `chore` column and no ticket key. `dispatch.lock`
serializes chore runs with dispatches.

### Runs

`canopy chore run` inserts a `chore_runs` row, renders the prompt, and spawns `python -m canopy _chore <run_id>`
detached, like `_run` (§8 step 4). `_chore` claims the run by pid, drops `CANOPY_TICK_ID`, runs the command in `cwd`
with the timeout, records the agent's pid, parses the result, and closes the row. Output goes to
`<state_dir>/chores/<run_id>.log`. No lease, branch, or push, so nothing to return or verify.

The prompt is the operator's file plus a generated `## Run` section holding one JSON object: chore name, current time,
run id, the overseer's context, the operator's notes (below), the latest ended run (id, status, end time, summary), the
latest `ok` run's open findings (id, title, link), so ids can be reused, and the result contract. It is written to
`<state_dir>/chores/<run_id>.prompt`, readable only by the operator.

Result contract, one JSON line, last line of the agent's text (§13):

```json
{"status":"ok|failed","summary":"one paragraph",
 "findings":[{"id":"flaky/checkout-service/test_retry","title":"one line","detail":"a paragraph","link":"https://..."}]}
```

- `ok`: the check ran; no findings means nothing needs a human. `failed`: it could not check, and the summary says why.
- A finding's `id` is stable across runs for the same problem, matches `[A-Za-z0-9][A-Za-z0-9_.:/-]*`, at most 200
  characters, unique within a run. `title` is one line cut at 200, `detail` cut at 2000, `link` absent or a plain
  `https://` URL of at most 500. `summary` is cut at 2000. At most 20 findings.
- Validated with pydantic (D026). Anything else is `unknown`, with no findings recorded.

`chore_runs` status is `running`, `ok`, `failed`, `unknown`, `timeout`, or `crashed`. Reconcile (§6 step 3) treats
them like worker runs: a dead `_chore` pid gets the agent's process group killed and the run `crashed`. Chore runs do
not count against `max_workers`.

### Notes from the operator

`canopy reply chore:<NAME> '<text>'`, or the note form on the chore's page in the web UI (§22), records a note to a
chore: a message on its subject (§22), from the operator, refused `unknown` for a chore not defined for this workspace
(D100). It is how the operator answers a finding without
editing the prompt file: "leave out flaky/checkout/test_retry until 2026-10-15, the fix is merging".

- Every later run's `## Run` section, a try's included, carries the latest 10 notes as `operator_notes` (id, time,
  text), oldest first. The prompt tells the agent to follow them as it follows the operator's file, a later note
  winning over an earlier one. They are the operator's words, so they are instructions; the overseer's context is not.
- Nothing clears a note; it falls out after 10 newer ones. A note saying "until" a date is the agent's to compare
  against the run's `now`. To take one back, write a newer note.
- Notes reach neither the overseer's state block nor the attention list, and do not wake the loop.
- `canopy show chore:<NAME>` lists them after the open findings, and the web UI's chore page beside them.

### Trying a chore

`canopy chore try <NAME> [--context '<text>']` is the operator's, for writing a chore (D098). It renders the prompt a
run starting now would get, with `run_id` null in its `## Run` section, runs the chore's command in its `cwd` with its
timeout and the shadowing check, and validates the result line as `_chore` does. It prints the agent's text, its
stderr and exit code, the validated result, what it cost when the runtime reported it, and the status, and exits 0
only on `ok`.

- It records nothing: no `chore_runs` row, no decision, no notification, nothing on the attention list. The next tick
  sees no change, and the `not_due` guard does not count it.
- No guard applies, and it works with `capacity.max_chores = 0`, so a chore can be written before the loop runs any.
  It still needs a chore defined for this workspace.
- It refuses `inside_run`, like `start` and `reply` (§22), and the agent sees `CANOPY_RUN_ID=chore-try`. The
  overseer's bash allows only `canopy ...`, which cannot unset `CANOPY_TICK_ID`, so the loop cannot try a chore.

### Findings on the attention list

- Open findings are those of the chore's latest `ok` run; one disappears when a later `ok` run omits its id (§14). A
  non-`ok` run leaves them standing.
- A latest run ended `failed`, `unknown`, `timeout`, or `crashed` also raises a `chore_failed` item, after reconcile
  as for worker runs (D028), cleared by a later `ok` run.
- `attention.md` gets a section per chore after the ticket items, headed `chore:<name>`, one line per finding: title,
  link, age, id. Age runs from the first of the unbroken sequence of `ok` runs reporting the id. `canopy status` lists
  them the same way plus a line per configured chore: running, or latest run and next due time.
- Notification follows D032, keyed by chore and finding id. Line: `+ chore:<name> <id>: <title> <link>`. Its
  `notifications` row holds `chore:<name>` in `ticket_key` (no ticket key has a colon, §17) and the id in `reason`. A
  `chore_failed` row also holds `chore:<name>`; its line is `+ chore:<name> chore_failed: <detail>`.

### Journal

- `chore_runs`: id, tick id, chore name, pid of `_chore`, pid of the agent, started and ended times, status,
  `result_json` (validated result, text cut to limits), log path, and what the runtime reported (§13): `session_id`,
  `cost_usd`, and tokens by kind, as `runs` has them, NULL when it reported nothing. Separate from `runs`, whose
  ticket, slot, lease, and branch columns do not apply. `canopy show chore:<NAME>` shows the latest run's session and
  cost, and the web UI's spend counts chore runs.
- `decisions.chore`: nullable; a row carries a ticket key or a chore name, never both.

### Trust model changes

Approved with M9:

- T1: chores read text from outside the operator's queue (other people's PRs, build logs). Findings are data
  everywhere: attention list, notification, state block.
- T3: `every_minutes`, `running`, and `capacity.max_chores` are controls in code; §6: never run a chore more often than
  its `every_minutes`, or more than `capacity.max_chores` at once.
- T6: a chore's only output is its result line; the shipped definition has no write tools. Residual: a steered chore
  can put up to 20 findings of its choosing before the operator and into `notify.cmd`, and a link can carry data.
- T7: chores, `runtime.chore_cmd`, and `capacity.max_chores` are user-only.
- §7: the operator is responsible for any tool allowed in a chore's definition. canopy assumes chore tools only read.

### Open

- Whether a chore should ever write (acting on others' work, which D010 kept out). Likely first: a ticket for a
  finding, without a queue label like a split child (§18), so a human decides.
- Whether findings should inform ticket decisions once chores have a track record (a flaky-check finding raising
  attention instead of dispatching `fix-ci`). Only to hold work back or raise attention, never to make a ticket a
  candidate, and opt-in per chore.
- Whether `workspaces` should become a per-workspace table in the user file (D063).
- Whether a repository should offer chores operators opt into by name, as it offers its tracker query.

## 20. Notifications

Rationale in D035 and D064. This generalizes `notify.cmd` (§14, D032), which stays and behaves as it did.

Notifications reach the operator away from the terminal (REQUIREMENTS N2). A destination is a **sink**, a command
that reads one message on stdin. canopy ships a desktop sink and a Slack sink; others are the operator's programs.

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

- Sinks are user-only (§12), like every `notify.*` key (TRUST_MODEL T7).
- A sink name matches `[a-z][a-z0-9-]*`. At most 5 sinks, since each can hold the tick lock for its timeout.
- `cmd` follows `notify.cmd`'s rules (§12): split into argv, no shell, no `{prompt}`. It runs in the repository root
  with the message on stdin and a 60-second timeout. Exit 0 means delivered; anything else, timeout included, means
  retry next tick. Stdout is ignored; the tail of stderr is logged.
- `format` is `json` (the default) or `text`.
- `events` lists the groups the sink receives: `attention`, `loop`, `runs`, `chores`, `reviews`. Default
  `["attention", "loop"]`.
- `digest_every_minutes` is optional and at least 60 (Digest, below).
- `notify.cmd = "X"` is shorthand for a sink named `default` with `cmd = "X"`, `format = "text"`,
  `events = ["attention"]`, and no digest. Setting both `notify.cmd` and `[notify.sinks.default]` is a config error.

An event is recorded only when some sink takes its group; with no `notify.cmd` and no sinks, publishing is §14
without the notification.

### Events

A closed set, written by the harness from the journal. Text fields are cut to the limits shown, on one line.

| Group | Kind | When | Fields |
|---|---|---|---|
| `attention` | `attention.opened` | a listed item the sink was not told of | ticket, reason, detail (500), since |
| `attention` | `attention.resolved` | an item the sink was told of left the list | ticket, reason |
| `runs` | `run.started` | dispatch started a worker | ticket, run, kind, branch, attempt, limit |
| `runs` | `run.ended` | a run's row closed | ticket, run, kind, status, branch, pr, prs, summary, question, message |
| `chores` | `chore.ended` | a chore run's row was closed (§19) | chore, run, status, summary, how many findings |
| `reviews` | `review.ended` | a review run's row was closed (§21) | pr, ticket, run, status, verdict, impact, comment |
| `loop` | `loop.failing` | the latest 3 ticks all ended other than `ok` | count, latest status and tick, its log |
| `loop` | `loop.recovered` | the first `ok` tick after `loop.failing` | how many ticks failed |
| `loop` | `loop.sink_failing` | a sink has failed 3 deliveries in a row | sink, the tail of its stderr |

`summary` and `question` are cut at 300 characters, each PR URL at 500. `pr` is the run's first PR, `prs` every PR a
joint run reported. In the `json` format a run's kind is `run_kind` (`kind` is the event's). `question` is set only for
a `blocked` run; the needs-human label is not an attention item, so `run.ended` is how a sink hears of the question.
`message` is the journal id of the message the run recorded (§22): its question for a `blocked` run, its report
otherwise, so a channel can say what a reply answers.

Attention is a diff of state per sink (D032): `notifications` has a `sink` column, so each sink hears of each open
item once, and a sink that was down gets the net change. The other kinds are point events in an outbox table,
`notify_events`, written in the transaction that records the fact: dispatch inserting the run; whatever closes a run's
row (`_run`, or reconcile marking it `crashed`) or a chore run's (`_chore`, its reconcile); the publish step for
`loop.*`. Ids never repeat (`AUTOINCREMENT`), so pruning cannot reuse an id a cursor passed. Each sink's cursor in
`notify_sinks` is the last event id it delivered. `loop.failing` and `loop.sink_failing` are recorded once per
streak.

Because `notify.cmd` is the sink `default`, switching between the two re-notifies nothing. Without a `default` sink,
its rows go at the first publish like any removed sink's, and each named sink hears of every open item once.

### Delivery

§6 step 7, after `attention.md` is written, for each sink in name order:

1. Gather the sink's attention diff if it takes `attention`, its events after its cursor in the groups it takes, and a
   digest if one is due. If there is nothing, skip the sink, moving its cursor past events of groups it does not take.
2. Render one message in the sink's format and run the command.
3. On exit 0, record the diff in `notifications` for this sink, move the cursor to the newest event gathered, set the
   digest time, and reset the failure count. Otherwise change nothing else, log `notify command failed` with the
   sink's name, and count the failure; the third in a row records `loop.sink_failing` once, in the same transaction.
   A sink that takes `loop` hears of its own failing when it recovers.

Bounds:

- At most 20 attention lines and 20 events per message. The rest are counted in a closing line pointing at
  `attention.md` and `canopy status`, and count as delivered.
- Events over 24 hours old when a sink next succeeds are counted, not listed.
- A new sink's cursor starts at the newest event (no backlog); its first delivery lists every open attention item.
- A removed sink loses its `notify_sinks` and `notifications` rows at the next publish. Events every sink has passed
  are deleted after 7 days, except the newest `loop.failing` or `loop.recovered`, kept to tell a week-long streak from
  a new one. `loop.recovered` counts every failed tick of the streak.
- Sinks run in turn under the tick lock: each hung sink delays the next tick by up to 60 seconds.

### Digest

- A sink with `digest_every_minutes` gets a digest at its first delivery, then at the first delivery that long after
  the previous one.
- It covers the time since the previous digest (the first, one interval back), from the journal only:
  ticks by status; runs started, by kind; runs ended, by status, with each `done` run's ticket and PR and each `blocked`
  run's ticket; the open attention list, counted by reason, with the oldest item's age; the workers running now.
- It is sent even when nothing happened ("24 ticks ok, nothing ran, nothing needs you"): a missing digest shows ticks
  stopped, which canopy cannot report itself.
- No model writes it. A report needing judgment is a chore (§19), reaching sinks as `chore.ended` (`chores` group).

### Formats

`text` is lines for a person. Attention alone is exactly §14's message, so `notify.cmd` output is unchanged. Event
lines, then digest lines, follow the attention lines, then the closing path line. Without attention changes a message
starts `canopy: N events`, or `canopy digest` for a digest alone. Event lines start `>` for a run started, `<` for a
run or chore run ended, `!` for the loop's own events, `*` for a test.

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

`attention` is null for a sink that does not take it; `added` and `resolved` items also carry their `repo`. Each
event carries its fields and `line` (its text-format line); the digest its counts and `lines`. `omitted` counts what
the bounds left out. `version` changes only on an incompatible change; sinks ignore unknown fields. `text` serves a
sink that only forwards a string.

### The desktop sink

`canopy-notify-desktop` is a script in canopy's own install (`canopy.notify.desktop`), stdlib only (D064). It runs only
as a configured sink command, never inside the harness.

```toml
[notify.sinks.desktop]
cmd = "canopy-notify-desktop"
events = ["attention", "loop", "runs"]   # runs: a blocked worker's question arrives as run.ended
```

- It reads a `json` message's `text` field, or a `text` message as is. Body: the lines without the closing path line,
  at most 12 lines and 1000 characters. Title: `canopy`, or `canopy: <repository directory name>` from `json`.
- Linux: `notify-send --app-name=canopy -- TITLE BODY`. macOS: `osascript` with a fixed script reading title and body
  from its arguments. Neither is built into a shell command or script, so agent or org-member text runs nothing.
- Exit 0 when the tool succeeded, 1 when it failed, 2 when it is not installed or stdin is empty.

### The Slack sink

`canopy-notify-slack` is its own distribution, a uv workspace member (D041): `packages/canopy-notify-slack/`, module
`canopy_notify_slack`, stdlib only (`urllib.request`, `json`), importing nothing from `canopy`. `canopy` depends on it
and lists the `canopy-notify-slack` script in its `[project.scripts]`, so installing `canopy` puts it on `PATH`.

- It reads `json` on stdin, posts one message to a Slack incoming webhook, and exits 0 on 2xx, else 1 with Slack's
  reply on stderr. A rate-limited post is retried next tick like any failure.
- The webhook URL comes from a file: `--webhook-file PATH`, default `$XDG_CONFIG_HOME/canopy/slack-webhook`
  (`~/.config/canopy/slack-webhook`). The file must be a regular file (checked before it is opened), belong to the
  operator, be unreadable by group and others, and hold one `https://hooks.slack.com/` URL whose parsed host is that
  host; otherwise the sink exits 2 saying which. The URL is never in canopy's config, argv, journal, or logs.
- Message: a header with the repository directory name and counts, a line per item or event (ticket key, reason or
  status, link), and the digest as a short block. Posted as `{"text": ...}`, at most 45 lines.
- Journal text is escaped for Slack markup (`&`, `<`, `>`), so it cannot mention `@channel` or a person, or disguise a
  link. Bare URLs stay clickable.
- Setup: create a Slack app with an incoming webhook for one channel, write its URL to the file with mode 600, add the
  `[notify.sinks.slack]` table, and run `canopy notify test slack`.

Two checks keep the network out of the harness (as D015 keeps processes in `canopy.infra.procs`): ruff's banned-api
rule (`TID251`) bans `urllib.request`, `http.client`, and `socket` everywhere in `src/canopy`, no exceptions, and
`tests/canopy/test_layers.py` fails on any import of `canopy_notify_slack` from `src/canopy`. The harness runs the
Slack sink only as a configured command.

### Commands

- `canopy notify test [SINK]` sends a `test` message to every sink, or one, now, outside any tick, and prints each
  result. It changes no cursor or table, and refuses when `CANOPY_TICK_ID` is set, so the overseer cannot page.
- `canopy status` shows a line per sink: last delivery, consecutive failures and last error, events waiting.

### Two-way, later

Not built. A listener must follow TRUST_MODEL T8 (D055): loopback or private network, behind the operator's secret.
Slack's Events API and slash commands need inbound internet access, so they stay out; Socket Mode connects outward and
could fit T8 once something long-running holds the connection. What fits, in order:

1. **Replies on the ticket.** Works now: messages name the ticket and carry the journal's links; an authorized reply
   on the ticket resumes the worker. Slack is the pager; the ticket is the conversation.
2. **Replies in Slack, read by the overseer** through a Slack MCP server each tick, a reply by an authorized Slack
   account counting as authorized. Needs one thread per ticket (a bot token and `chat.postMessage` instead of a
   webhook, the sink reporting each thread on stdout for the harness to record and pass into the state block), Slack
   account ids among the authorized repliers, and a TRUST_MODEL T1 change.

It attaches at the `json` format's `version` and the sink's stdout, ignored today. §22 plans the conversation these
replies would join: the journal records it, and Slack becomes one channel into it.

### Trust model changes

Approved with M10:

- T2: the harness makes no outbound call except through configured commands and reads no token. The Slack sink does
  both, but runs only as a configured sink, reads its webhook from the operator's file, and lint keeps network modules
  and the sink out of the harness.
- T6: notifications carry agent- and org-member-written text off the machine. Controls: only the table's fields, cut
  to limits; Slack escaping. Residual: a steered agent picks up to 500 characters per item shown in the channel, and a
  link can carry data (as §19 says of findings).
- §7: point a sink only where the audience may read the tickets and PRs it quotes; keep the webhook file readable only
  by the operator. Channel readers see what the loop does but cannot steer it.

### Open

- Routing finer than groups (D032's revisit), such as `crashed` to a phone and `needs_reviewer` to Slack only.
- Digests at fixed times of day instead of an interval.
- Reminders for items open longer than some threshold.
- Links to tickets. The harness knows no tracker URLs (D003); a `tracker.ticket_url` template would let every message
  link its ticket.
- A sink secret read from a command (a password manager's CLI) instead of a file.

## 21. Reviews

Rationale in D039 and D065.

A review is an adversarial read of one PR at one commit by a fresh agent run, with no transcript of the author's run,
told to assume the change is wrong until the code shows otherwise. It posts one comment on the PR that says what it
is, and reports a verdict. It never approves, requests changes, pushes, or merges. Human review stays the gate (§3).

Two kinds of PR get reviews, and neither needs a ticket:

- **The loop's own PRs.** With `review.agent_prs` on, a ticket's PR is reviewed once its checks pass, before the
  overseer asks a human for review. Findings go back to a worker through `resume`, like a human's review comments.
- **PRs the operator names with `review.query`.** Reviewed and nothing else: the loop never pushes to them, fixes
  them, or opens a ticket for them. The comment is the whole output.

### Configuration

Every review key is user-only (§12), except the per-PR limit, a shared policy the repository may only tighten
(TRUST_MODEL T7).

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

- `agent_prs` defaults to false. `query` is the VCS host's PR search syntax, empty by default. Reviews are on when
  `max_reviews` is above 0 and either is set.
- `review.query` authorizes, unlike `tracker.query` (§17). Without an author filter it reviews other people's PRs in
  the operator's name; allowed, and the operator's choice (TRUST_MODEL §7).
- `low_impact` is plain language for the reviewer, like a chore's `when`: which changes it may call `low`. Without it,
  the reviewer never reports `low`.
- `review_cmd` follows the command template rules (§12). A different model from `worker_cmd` is recommended.

### Off unless configured

With no `[review]` table, neither `agent_prs` nor `query` set, or `capacity.max_reviews = 0`, nothing about reviews
reaches the overseer: no `reviews` key in the state block, §7's phase table unchanged, and every `canopy review run`
refuses as `reviews_off`. A test holds this. With `agent_prs` off the phase table is also unchanged, and a loop PR
that `query` matches is reviewed like any other match: one comment, no `resume`.

### Running a review

`canopy review run --pr URL --sha SHA [--ticket KEY] [--repo NAME] [--context '<text>']` requires `CANOPY_TICK_ID` like
`dispatch` (D020). `URL` is the PR's `https://` URL, an opaque string the harness never parses. `SHA` is the full head
commit the overseer read. `--ticket` links an agent PR to its ticket. Under the dispatch lock, it refuses, recording
`refused:<guard>`, on the first of:

- `reviews_off`: see above.
- `bad_pr`: `URL` is not a plain `https://` URL of at most 300 characters, `SHA` is not 40 or 64 lowercase hex
  characters, or `--ticket` is not a valid key (§17).
- `unknown_repo`: in a workspace of several, no `--repo`, or one not in the map or with no clone. The slot comes from
  that repository's pool. In a workspace of one `--repo` may be left out.
- `running`: a review of this PR is running, or, with `--ticket`, a worker run for that ticket is.
- `reviewed`: a review of this PR at this commit ended `done`. The refusal names its verdict and comment.
- `review_limit`: this PR has had `policy.max_reviews_per_pr` review runs, however they ended. Also records the
  `review_limit` attention item.
- `daily_limit`: `capacity.max_reviews_per_day` review runs started in the last 24 hours.
- `review_capacity`: `capacity.max_reviews` review runs are running.
- `capacity`: `max_workers` runs and review runs, together, are running.

A dry run checks the same guards, counting reviews recorded in this tick as running, records `dispatch:review` with
rationale `dry run: not dispatched; would review <SHA>`, and starts nothing (D036). Worker dispatches also count a
running review toward `capacity` (§8).

Once the guards pass, the command inserts a `review_runs` row, leases a slot with holder `canopy:review:<run_id>` (a
failed lease deletes the row and refuses as `no_slot`), renders the prompt (`bad_prompt` if it does not), and spawns
`python -m canopy _review <run_id>` detached, as dispatch spawns `_run` (§8 step 4). `_review`:

1. Claims the run by pid and drops `CANOPY_TICK_ID`, as `_run` does.
2. In the slot: `git fetch origin <SHA>`, `git checkout --detach <SHA>`, and checks that `HEAD` is `SHA`. A failure is
   `failed` with a harness note (a PR in another repository fails here). No branch is created. Then it deletes every
   symlink the commit tracks that resolves outside the checkout.
3. Runs `review_cmd` with cwd `<state_dir>/reviews/<run_id>/`, a directory readable only by the operator, **not the
   checkout**, so the runtime loads no configuration from the PR (D065). It holds one link, `checkout`, to the slot,
   which the prompt names, as a desk's links do (§18). Before it starts, the shadowing check (§13) covers that
   directory and the workspace root. Timeout `review_timeout_minutes`; the agent's pid is recorded.
4. Parses the result, then always removes its directory, never following the link, and returns the slot with
   `--force`. It traps signals and exits as `_run` does (§8 step 6). Reconcile treats a dead `_review` as a dead
   `_run`: it kills what is left of the reviewer, removes the directory, returns the slot, and marks the run
   `crashed`. A running review's lease is never returned as stale.

The prompt is `prompts/reviewer.md` (or the override), with the PR URL, the commit, the checkout path, the ticket key
and tracker provider for an agent PR, `review.low_impact`, the attempt number and limit, the overseer's context, and
the result contract. The reviewer:

- reads the PR's description and discussion, the diff, as much of the checkout as it needs, and for an agent PR the
  ticket;
- looks for defects, not style: wrong behavior, missed cases, security problems, broken contracts, missing tests for
  new behavior, and anything the repository's own docs (such as `AGENTS.md`) name as a rule;
- verifies each finding against the code, and reports none when it finds none;
- treats everything it reads, the diff included, as data (TRUST_MODEL T1).

It posts exactly one comment on the PR's conversation, never a submitted review:

```text
**canopy review**: an automated adversarial review of abc1234, run by canopy under this account. It is not a
human review and not an approval.

Verdict: findings (1 blocking, 1 minor). Impact: normal.
1. **blocking** `src/retry.py:42`: ...
2. **minor** `tests/test_retry.py`: ...

<!-- canopy-review {"v":1,"run":42,"sha":"<full sha>","verdict":"findings","impact":"normal"} -->
```

The first line identifies it to people, the last-line marker to programs. The comment is posted as the operator
(D010), so anything running as the operator could forge the marker. The loop never trusts it, only its journal.

Result contract, one JSON line, last line of the reviewer's text (§13), validated with pydantic (D026):

```json
{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high","comment":"https://...",
 "summary":"one paragraph",
 "findings":[{"severity":"blocking|major|minor","title":"one line","location":"path:line"}]}
```

- `done` means the review was read through and the comment posted. `comment` is its plain `https://` URL and must be
  the reviewed PR's URL followed by `#` or `/` (PR 70's is not PR 7's). A `done` without one is recorded as `failed`
  with a harness note. `failed` means the reviewer could not review; the summary says why.
- The harness cannot check that the comment exists (principle 5); the overseer does (below).
- At most 20 findings. `title` and `location` are one line, cut at 200 and 300 characters; `summary` is cut at 2000.
  `verdict` is `findings` exactly when `findings` is not empty, and a `done` review has a verdict and an impact.
- `low` without `review.low_impact` is recorded as `normal`, with a harness note.
- Anything else is `unknown`. `review_runs` status is `running`, `done`, `failed`, `unknown`, `timeout`, or `crashed`.

### The verdict, and automating on it

canopy never approves (TRUST_MODEL §6): a review changes no GitHub review state and cannot satisfy a required
approval. The verdict is the marker. A repository that wants low-impact PRs to skip a human reviewer can run its own
automation, such as a CI job that reads the latest `canopy-review` marker for the head commit from an account it
allows and sets a required check. That is the repository owners' decision. The marker is only as trustworthy as
every agent the operator runs, until a bot identity (ROADMAP, deferred).

### The overseer's part

The state block gains `reviews`: whether `agent_prs` is on, whether a query is set, the limits, running review runs,
and for each PR reviewed in the last 14 days (at most 50, newest first) its URL, linked ticket, review runs so far, and
latest run: id, commit, status, verdict, impact, comment URL, finding titles, start and end.

For the loop's own PRs, the phase table (§7) gains two rows between `ci_red` and `green_unreviewed`, used only when
`agent_prs` is on. Findings are `review_findings` only when `trust.trusted_reviewers` lists `canopy:review`; otherwise
they are `untrusted_review` and wait for the operator's go-ahead like any untrusted reviewer's (§7, D089):

| Phase | Derived from | Next action |
|---|---|---|
| `review_pending` | checks pass, no approval, no `done` review of the head commit, under the per-PR limit | `canopy review run --ticket KEY` |
| `review_findings` | the head commit's `done` review has findings, newer than the `review` cursor | classify as review comments (§7): dispatch `resume` pointing at the review run and its comment, or `needs_author` |

A clean review, or a PR at its review limit, moves on to `green_unreviewed`, whose `needs_reviewer` item links the
latest review. A `resume` pushes a new commit, which is reviewed again, up to the per-PR limit. The overseer recognizes
a review's comment by the comment URL in the state block, never by the marker, and never counts it toward
`changes_requested`.

When it reads a PR, the overseer checks that the latest `done` review's comment exists on that PR, by the operator's
account, with a marker naming that run. If not, it records `review_unposted` (Attention, below), and an agent PR moves
on to `needs_reviewer` as a PR at its review limit does: a worker is never sent to a missing comment. The `reviewed`
guard still holds for that commit; the next commit is reviewed as usual. Operator comments with a `canopy-review`
marker that no run in the state block names are ignored, like any text that is not an authorized reply.

For PRs from `review.query`, the overseer runs the query each tick and keeps only PRs of this repository (the one whose
PRs it reads for tickets); `_review` could not fetch another repository's commit from `origin`. The prompt says so; a
`repo:` qualifier saves the reads. For each open match whose head commit has no `done` review, it runs a review or
records `canopy review wait --pr URL --rationale "<text>"` (say, checks still running, or a draft). Nothing else is
decided about these PRs.

Review decisions are `decisions` rows with the PR's URL in the `pr` column: `dispatch:review`, `wait`,
`refused:<guard>`, and `attention:<reason>`. An agent PR's rows also carry its ticket key.

### Attention

- `review_failed`: a PR's latest review run ended `failed`, `unknown`, `timeout`, or `crashed`. Recorded every tick
  that the PR is still a candidate and nothing newer has run; `canopy review run` may retry within the per-PR limit.
- `review_unposted`: the latest `done` review's comment is not on the PR (above). It lasts until a newer review of the
  PR ends `done` with its comment in place.
- `review_limit`: recorded by the refusal, and by the overseer every tick that a candidate PR's head is unreviewed and
  it is at its limit.
- Findings are not attention items. For an agent PR they lead to a `resume`, or the existing `needs_author` or
  `needs_reviewer` items.

`canopy attention` takes `--pr URL`, in place of a ticket key for a PR with no ticket, or beside one for an agent PR.
An item with only a PR is shown as `pr:<URL>`, and its `notifications` row holds that in `ticket_key`, which no ticket
key can equal (§17). The `reviews` event group (§20) carries `review.ended`: PR, ticket, run, status, verdict, impact,
comment.

### Agent definition

canopy ships `canopy-reviewer` in the definitions directory (§13), not the repository's `.opencode/agent/` (TRUST_MODEL
T7):

- no edits, no subagents, no bash; reads allowed only inside the checkout;
- MCP: the tracker and GitHub, read tools only, plus the one tool that posts a comment on a PR's conversation. Tools
  that submit a PR review, push or write files, change labels, or edit or delete comments are denied by name.

A review that should run the PR's tests uses the operator's own copy of the definition, with bash allowed for exactly
those commands, as a chore does (§19). That runs the PR's code on the operator's machine, a reason to keep
`review.query` to PRs whose authors they trust.

### Journal

- `review_runs`: id, tick id, PR URL, commit, ticket key (nullable), slot, lease id and holder, pid of `_review`, pid of
  the agent, started and ended times, status, `result_json` (validated, text cut to its limits), log path. Separate
  from `runs`, which is keyed by ticket and branch.
- `decisions.pr`: nullable.
- The `review` cursor (§7) also covers review runs: a `resume` for a review's findings passes
  `--cursor review=` with the time of the run's comment.

### Trust model changes

Recorded in TRUST_MODEL with M11's human approval: T1 (the reviewer reads the most hostile text; what it writes is
data; `review.query` authorizes and is user-only), T3 (`max_reviews`, `max_reviews_per_day`, `max_reviews_per_pr`,
one review per commit, and the review timeout are controls in code), T4 (the harness runs nothing from the checkout,
and the reviewer's working directory is outside it), T5 (first line and marker), T6 (one comment per run is a prompt
rule only; extra comments are noise, not authority), T7 (every review key user-only except
`policy.max_reviews_per_pr`), §6 (never submit a PR review; never push to or edit a PR the loop is only reviewing),
and §7 (a `review.query` matching other people's PRs comments in your name; a reviewer definition that runs commands
runs the PR's code).

### Open

- Inline comments on lines: GitHub puts them in a submitted review, whose tool can also approve. They wait for a
  runtime that can deny the approve event, or a bot identity.
- Updating the earlier comment instead of adding one per commit. Editing needs a tool that can edit any of the
  operator's comments.
- A repository-offered review rubric, such as its own `low_impact`, that an operator opts into by name.
- A comment tool the runtime lets the reviewer call once, on one PR, would turn T6's residual into a control. canopy
  will not ship one: it would be VCS code (principle 5).
- Whether OpenCode confines the reviewer to its `checkout` link. The opt-in reviewer canary
  (`tests/canopy/test_opencode_canary.py`) settles it. If not, the reviewer runs without a checkout and reads the PR
  only through MCP.

## 22. Conversations

Private tickets and the journal's conversation (ROADMAP M18), tracker comments in the journal (M19), the web UI's
pages and actions (M20), its chores (M23), and its ticks (M24) are built. Rationale in D072 to D076 and D080 to D082.

The journal is the one record of every ticket's conversation: what workers reported and asked, what people replied,
and where each came from. A **channel** is a way into or out of that record: the tracker, the CLI, the web UI, and
Slack later. Channels differ in how they reach the operator and how they prove who wrote a reply. The overseer and
workers never see which channel a message came from, so adding a channel changes no prompt.

A ticket is **public** when one of `tracker.labels` authorizes it, as today, and **private** when the operator starts
it in canopy (below). A started ticket is private whatever labels it carries: the start record wins. A private
ticket's conversation never touches the tracker: the operator can deliver a ticket a client filed without the agent's
reports, its questions, or the operator's answers appearing on it.

### Messages

A `messages` table, one row per message:

- its subject (below): a ticket now, a PR with M14; the journal id (`AUTOINCREMENT`, so ids never repeat); and the
  time canopy recorded it.
- `source`: `worker` (from a run's result line), `operator` (from a channel that authenticated the operator), or
  `tracker` (a tracker comment the overseer mirrored, M19).
- `kind`: `report` or `question` for a worker's, `reply` for the operator's, `comment` for a mirrored one.
- `channel`: `run`, `cli`, `web`, `slack`, or `tracker`.
- For a worker's message, its run. For a mirrored one, the tracker's comment id, author account id, and time, unique
  per subject and comment id.
- The body, bounded: a worker's text as its result contract bounds it; the operator's at 4000 characters; a mirrored
  comment's at 2000, marked truncated when cut.
- `answers`: the id of the message a reply answers, when the channel knows it.
- For an operator's message, a submission id, unique per subject, so a retried submission records nothing new. The
  web form carries one generated when the form is rendered. The CLI derives it from the subject, the message being
  answered, and the body, so rerunning the same `canopy reply` after an uncertain result is the same submission.

Who writes:

- `_run` records a run's `report` (its summary and PRs) and, for a `blocked` run, its `question`, in the transaction
  that closes the run's row, for every ticket. The harness already has both from the result line (§8), so no agent
  gains a write.
- Operator input goes through one function in `core/conversation.py` that every channel calls, with the guards in one
  place: the key is valid (§17), the ticket was started, the body is within its bound.
- Mirrored comments are recorded by the overseer (M19, below), a worker's marked comments among them. Migration 0004
  added their columns and the mirror cursor.
- Migration 0003 backfilled a `report`, and a `question` for a `blocked` run, from every ended run's `result_json`,
  so tickets worked before M18 have a conversation too.

Agents never write a message directly. No worker command records one, and the overseer records only mirrored tracker
comments, which authorize nothing.

### Authority stays with the source

The journal is what the operator reads. Authority comes from where a message originated:

- **Public ticket.** Authorization and replies are as §7 and §17 say: the overseer's live read of the tracker. A
  mirrored comment is the overseer's claim, like `--label`; it never makes a ticket `human_replied`, authorizes a
  split, or counts as "try again" after a failed run. The operator may also reply in canopy (D089): an operator
  message is canopy's own fact, as on a private ticket, and is how the operator answers an untrusted reviewer (§7). It
  stays in the journal and never reaches the ticket.
- **Private ticket.** The journal is the source. Its start record and the operator's messages are canopy's own facts,
  written after a channel authenticated the operator, so the harness checks them in code without reading the tracker
  (D003). Tracker comments on a private ticket are data, whoever wrote them.

This is principle 1's split applied to conversation: for a private ticket the journal owns the conversation, and for
a public one the tracker does and the journal holds a copy.

### Private tickets (M18)

The operator's commands are top-level verbs that take a reference to a subject, anything canopy works on or reports
about, so the same verbs serve tickets now, PRs with M14, and what comes later (References, below; D075):

| Command | Does |
|---|---|
| `canopy start REF` | work it privately, in place of a queue label |
| `canopy stop REF [--now]` | no new dispatches; a running run finishes unless `--now` ends it |
| `canopy reply REF [TEXT]` | answer it, with TEXT or stdin |
| `canopy forget REF` | forget its branch and PRs, so its next `implement` starts over (below); public tickets too |
| `canopy show REF` | its phase, PRs, recent runs, and conversation, oldest message first |

`canopy status` lists what was started, with each subject's phase, beside the attention list and runs; there is no
separate `list`.

- `start` is private by construction: canopy cannot label a ticket (D003), so a ticket started in canopy keeps its
  conversation in the journal. The command says so when it runs, and when the next tick will pick the ticket up. A
  later `--public` could start a ticket whose conversation stays on the tracker; none is planned.
- `stop` without `--now` is graceful: it says which run is still going and that it will finish. With `--now` it also
  ends that run: its process group is killed and its slots returned and desk removed as reconcile does for a
  crashed run (§6), and the run is marked `stopped`, a status that raises no attention item and counts toward attempt
  limits like any ended run. `stop` refuses a ticket that was not started: a public ticket stops when its queue label
  is removed.
- `stop` does not delete the start record; it marks it stopped. A stopped ticket stays private and is dispatched
  by nothing, whatever labels it carries, until `canopy start` again: a queue label left on it never turns it
  public.
- The start record is the authorization. Only the operator's commands write it, short of T1's residual (below).
- A started ticket is private even when it also carries a queue label, or gains one later. The harness chooses the
  worker in code: `canopy dispatch` for a started ticket always renders the private prompt and runs the private
  definition, whatever the overseer passed.
- `stop` and `dispatch` cannot interleave. `dispatch` checks the start record and inserts the run's row in one
  write transaction, and `stop` marks the record stopped in one: whichever commits first wins, and `stop` reports any
  run the other committed. `_run` reads the record again before it starts the worker and ends the run `stopped` if the
  record is stopped.
- The state block marks each private ticket and carries its operator messages newer than its message cursor.
- `canopy dispatch` needs no `--label` for a started ticket. It checks the start record in code, a guard where a public
  ticket's `--label` is a claim (D051). `--kind split` on a private ticket is refused `private`: a split creates tickets
  in the tracker.
- The worker prompt has a private variant: no label check, since the harness checked the start record; never comment
  on, label, or edit the ticket; the result line's `summary` and `question` are the report. The agent definition is
  `canopy-worker-private`: `canopy-worker`, its MCP tools denied by name included (D084), with every tool of the
  tracker's MCP server denied by wildcard and only its read tools allowed by name, and the tracker CLIs canopy knows
  (`gh`, `acli`, `jira`) denied in its bash rules.
  - The server is `tracker.mcp_server` and its tools `tracker.read_tools`, both user-only, with a default for each
    shipped provider's usual MCP server (`config.DEFAULT_TRACKER_TOOLS`): `atlassian` with Jira's read tools for
    `jira`, and `github` for `github`, whose server is also the one PRs go through, so its list adds the PR tools a
    worker needs and leaves out every tool that writes to an issue. Both are rendered into the definition's
    permission block as `"<server>_*": deny` and then `"<server>_<tool>": allow` for each (D080). OpenCode names an
    MCP tool `<server>_<tool>`, matches permission keys as wildcards on that name, lets the last matching rule win, and
    hides a tool whose last rule denies it outright (read in its source, 1.18.35); a live check of a private run is
    the operator's half of M18's acceptance.
  - Atlassian's Rovo MCP server lists only its primary tools unless its URL asks for `?tools=all`, and runs the rest
    through `execute*` tools that read or write by argument. OpenCode cannot see the argument, so those are denied:
    with the default URL a private worker reads the ticket with `getJiraIssue` and `searchJiraIssuesUsingJql` only.
  - With no read tools for the provider, `canopy start` refuses (`no_read_tools`) rather than run a worker that
    cannot read the ticket. A wrong list fails closed: the worker cannot read, ends `failed`, and posts nothing.
  - D044's guard grows for private runs: the harness refuses one when the worktree's OpenCode config has any
    `permission` or `tools` entry naming the tracker server's tools, since a repository rule merged after canopy's
    could reopen a write tool. The operator's own global config is the operator's to keep consistent (§13).
- Phases (§7) read the journal for the ticket's own phases: `needs_human` when the latest run ended `blocked` and no
  operator message came after it; `human_replied` when an operator message is newer than the ticket's message cursor
  (`last_message_id`), a cursor of its own over journal ids, never the comment cursor, which stays the tracker's. The
  action is `resume` with `--cursor message=<message id>`, its context pointing at the message. The PR phases are
  unchanged.
- The harness raises `awaiting_reply` every tick for a private ticket whose latest question has no operator message
  after it, with the question as its detail (D028's pattern). A public ticket's question still reaches the operator as
  `run.ended` (§20), whose `message` field is the id of the message the run recorded, its `question` for a `blocked`
  run and its `report` otherwise, so a channel can say what a reply answers.
- After `crashed`, `worker_failed`, and the other run reasons (§14), "try again" on a private ticket is an operator
  message after the run ended.
- `canopy reply` takes a started ticket, or a public one a tick has seen (it has a journal row); any other is refused
  `unknown`. On a public ticket the state block carries its operator messages newer than its message cursor under
  `operator`, and every public `implement`, `fix-ci`, and `resume` prompt carries the latest 20
  (`{{OPERATOR_MESSAGES}}`, at most 30,000 characters), each labeled the operator's: an instruction. The workers'
  questions come with them, labeled data, so a reply to message N names something the worker can read; the rest of the
  conversation is on the tracker (D093). The overseer's `--context` points at a message by id, never quotes it. A reply
  on a ticket with no branch yet rides its `implement`, and one after a failed run is "try again". Its authorized
  repliers' comments on the ticket still work as before (§7). `show` drops control characters from every message.
- A public worker can write to the ticket and its PRs, so keeping the operator's messages off them is its prompt's
  rule, not a guard (TRUST_MODEL T6). Text the ticket's readers must never see belongs on a private ticket.
- `start`, `stop`, `reply`, and `forget` refuse when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set. `_run`, `_chore`,
  and `_review` set `CANOPY_RUN_ID` for their agents.
- The private worker runs with `runtime.private_worker_cmd`, a template of its own as `split_cmd` is (D080). Its prompt
  carries `{{CONVERSATION}}`: the ticket's latest 20 messages, oldest first, at most 30,000 characters, each labeled
  the operator's (an instruction) or an earlier worker's (data). That is how a resumed worker reads the operator's
  reply; the overseer's `--context` points at the message id and never quotes it.
- A `canopy reply` answers the ticket's latest question, if any, and is idempotent on its submission id. Its body is
  stripped, and refused empty or over 4000 characters (`bad_body`) rather than cut.
- `canopy start` on a ticket the overseer marked done clears the done flag: the operator asked for it again. On a
  ticket with a public run still going, it says so: that run may still write to the ticket, and `_run` ends any public
  run that had not started its worker yet `stopped`.

### Forgetting a ticket's work

`canopy forget REF` has canopy drop a ticket's work so the loop starts it over (D086). It takes a ticket, public or
private, from the operator's shell only, and:

- refuses `unknown` for a ticket the journal has no row for, `running` while a run works it (wait for it, or end a
  started ticket's with `canopy stop --now`), and `split` for a ticket a split made children of: they are tickets of
  their own, and forgetting the parent would not undo them.
- clears the ticket's branch, phase, `needs_human_since`, and done flag, and deletes its units, with their branches,
  PRs, phases, and review and ci cursors. The next `implement` names a new branch with its `--slug`; from then on
  `bad_slug` (§8) binds to that one.
- records `forgotten_at` with the ticket's newest run and message ids, and the loop's reads skip what came before
  them: `last_run` in the state block, the run reasons on the attention list (§14), a private ticket's waiting question
  (`awaiting_reply`) and new operator messages, and a private worker's `{{CONVERSATION}}`. A reply after it answers
  nothing. A forgotten ticket reads to the overseer as one never dispatched, so its prompt is unchanged.
- keeps the rest. `runs` and `run_slots` stay, so the attempt limits and the fix-ci cooldown count every run, before
  and after (D030); a ticket at its implement limit needs the limit raised in config, and `forget` says so. The comment
  and mirror cursors stay, so tracker comments already handled stay handled. The message cursor stays, and the boundary
  overrules it. The start record stays: a started ticket stays started, a stopped one stopped. `show` prints the whole
  history and when the work was forgotten.
- holds the dispatch lock, which a dispatch holds from its plan through its run's insert, so a dispatch that read the
  old branch cannot record it again after `forget` commits.
- touches nothing outside the journal. The old PR and the branch on origin are the operator's to close and delete, and
  the command names them: until they are gone the overseer still finds the `agent/<KEY>-*` branch (§7's `ready` needs
  none on origin) and dispatches to continue it, refused `no_branch`. A ticket stacked on the old branch (§10) loses
  its base when that branch is deleted, so forget a blocker only once nothing is stacked on it.

### References

A reference names a subject by its shape, so no kind needs a flag and no form can be read as another's: a ticket key
(§17) has no `:`, `#`, or `/`.

| Reference | Subject | Verbs |
|---|---|---|
| `PROJ-123` | a ticket | all (M18), and the overseer's `mirror` (M19) |
| `api#42`, or the PR's URL | a PR | all, once PR-scoped work exists (M14); refused before |
| `chore:NAME` | a chore (§19) | `reply` (its notes), `show` |
| `run:ID` | a run | `show` |

A verb a kind does not support is refused `unsupported`, naming the verbs it does. Messages and start records are keyed
by subject (its kind and id), not by ticket key, so a new kind adds a row here, not a table. Every form is parsed and
validated in code, as ticket keys are (§17).

### Tracker comments in the journal (M19)

The journal holds a copy of each ticket's tracker comments, so the operator reads every ticket's conversation in one
place, public or private (D081).

- Each tick, for every candidate, the overseer records each comment past the ticket's mirror cursor, oldest first:
  `canopy mirror REF --comment ID --author ACCOUNT --at TIME`, with the text on stdin, or `--body TEXT`. It requires
  `CANOPY_TICK_ID` like `dispatch` (D020) and takes a ticket reference; any other kind is refused `unsupported`.
- The text goes through a quoted heredoc, never an argument: the shell expands nothing in it. Its delimiter is the
  state block's `mirror.body_delimiter`, `CANOPY_BODY_` and 16 random hex digits drawn fresh each tick, so no comment
  can be written to end the heredoc early and run what follows. OpenCode checks a heredoc command's permission against
  its whole text, so the overseer's `canopy *` rule admits it (read in its source, 1.18.35); a body the shell parser
  reads as a command substitution is refused by the rule, failing closed, and the overseer then mirrors the comment
  as `(text not mirrored)`.
- Bounds, checked in code: a comment id as plain as a cursor id (`bad_comment`); the author an account id of at most
  200 printable characters without whitespace (`bad_author`); the time ISO 8601, read as UTC without an offset, and
  stored in the journal's own format (`bad_time`); the text stripped and not empty (`bad_body`; the prompt mirrors a
  comment without text as `(no text)`), cut at 2000 characters and marked truncated. At most 100 `mirror` calls a tick
  (`mirror_limit`), counted from the tick's `mirror` decisions, so a long history spreads over several ticks. Every
  refusal is recorded as a `refused:<guard>` decision.
- Idempotent on the subject and comment id (a unique index): a comment recorded again records nothing new, whatever
  text is passed the second time. Each call records a `mirror` decision in the same transaction, naming the message,
  or the message it already was, so the decisions show each comment mirrored once. The loop's tick block leaves
  `mirror` decisions out, as it does `wait`, and the tick's summary counts them.
- The harness reads the workers' marks (D069) itself: a comment that starts with `trust.comment_prefix` and ends with
  `trust.comment_suffix`, whichever are set, and whose last line is not a quote, is recorded with `source` `worker`;
  any other with `source` `tracker`. A worker's comment is recorded because its text can differ from the result line
  or come from a run whose result line never parsed. Either way it authorizes nothing: phases, `awaiting_reply`, and
  the loop's wake read operator messages only, and a private worker's prompt labels a mirrored comment as data, with
  its author's account id.
- The mirror cursor (`last_mirrored_id`) is its own, apart from the comment cursor the phases use, and only
  `canopy mirror` moves it, to the comment it records; `--cursor` cannot name it. It starts empty, so the first mirror
  of a ticket, including one worked before M19, covers its whole comment history once; worker comments the comment
  cursor had passed are recorded then. The state block carries it in each ticket's `cursors`.
- A dry run records the mirror too, as a record of what the overseer saw, but moves no cursor and changes no phase.
- `canopy show` lists a mirrored comment with its source, comment id, author, and time, and whether it was cut.
- The mirror lags the tracker by up to one tick. A comment edited or deleted after it was mirrored is not updated.
  PR review comments are not mirrored; they join the journal with PR subjects (M14).

### Waking the loop

During the wait (§6, the loop), each step checks the journal for an operator message to a ticket recorded since the
last tick began. A note to a chore (§19) does not wake it: the chore's next run reads it. One ends the wait and runs the
next tick, at most once a minute. Every channel wakes it the same way, whether the message came from another process
(`canopy reply`) or the loop's own server thread (D073). Capacity, attempt limits, and cooldowns hold as for any tick.

### Channels

| Channel | In | Out | Proves the operator by |
|---|---|---|---|
| tracker | comments, mirrored (M19) | worker comments on public tickets | `trust.authorized_repliers`, read by agents |
| cli | `canopy start`, `stop`, `reply` (public tickets too), `forget` | `canopy show`, `canopy status` | the operator's shell (T1 below) |
| web (M20) | reply, start, stop; notes to chores (M23) | pages | the listener secret (TRUST_MODEL T8) |
| slack (later) | thread replies | §20's sink | Slack user ids the operator lists |

Outbound, every channel uses §20's events: a sink posts them, and the web UI reads the same journal.

### The web UI (M20)

Served by `canopy loop` from a thread (D073):

- On unless `--no-serve` or `serve.enabled = false`. `serve.bind` (loopback by default, or a private address) and
  `serve.port`. Every `serve.*` key is user-only (T7).
- It requires the operator's listener secret (T8, below). Without one the loop says why and how to make one, logs it,
  and serves nothing; the loop goes on. It serves plain HTTP, also on a private address: T8's "relies on the network"
  residual stands (D076).
- Each request opens its own journal connection, never takes the tick lock, and writes only through the functions the
  CLI uses: `conversation.start`, `stop`, and `reply` with channel `web` (a note to a chore is a `reply` on its
  subject, as `canopy reply chore:NAME` is), and for a stop with `now`, the same `runs.halt.end` as
  `canopy stop --now`. `serve` is a feature and cannot import `runs` or `loop`, so the loop hands it
  that function and the attention list's (`loop.attention.listed`) when it starts the server (`serve.backend`). The one
  process it runs is `treehouse status --json`, for the worktrees page (below): it changes no lease, but it takes the
  pool's lock.
- A server failure is logged and the server restarted after 1 second, doubling to at most 60; it never ends the loop.
  Stopping the loop stops it, waiting at most 2 seconds for open streams.
- Pages: the attention list (the home page; most severe first rather than grouped by reason, beside the selected item's
  conversation and reply form, with the running runs under the list, below counters of running runs, questions waiting,
  the list, and the last 24 hours' spend, `ui/DESIGN.md`), runs (running, then the 50 that ended last), worktrees (each
  pool's slots, below), tickets, each with its conversation and the decisions about it, chores (below), and ticks
  (below). Actions: the CLI's verbs, reply, start, and stop (with or without `now`), and a note to a chore.
  OpenCode's session attach (M15) is not in the UI: the runs page shows each run's session id, and attach joins once
  M15 runs workers against OpenCode's server.
- FastAPI on uvicorn (D074), serving a single-page app built from `ui/` (D079) and the JSON and SSE API it reads.
  uvicorn's `Server` runs in the thread, installs no signal handlers there (the loop's own handle Ctrl-C, §6), logs
  nothing to the terminal, and stops when the loop sets its `should_exit`. Request bodies and path parameters are
  validated with pydantic models and `conversation.parse_ref`, as everything else parsed from outside is (D026).
- Every value from the journal is escaped: tracker comments and agent output are untrusted text in a page that holds
  the operator's session. React escapes text it renders, and nothing renders journal text as HTML
  (`dangerouslySetInnerHTML` is never given it). No inline script built from data. Message bodies are sent with control
  characters dropped, as `canopy show` prints them.
- It lives in `src/canopy/serve/`, a features-layer package, the only one that imports `fastapi`, `starlette`, or
  `uvicorn`; `tests/canopy/test_layers.py` fails on an import of them anywhere else, as for click in `cli/`. The ban on
  `socket`, `http.client`, and `urllib.request` (§20) stays absolute: canopy's code opens no socket itself. It listens
  and calls out to nothing, so T2's "no outbound call" stands.

Signing in (D082):

- The listener secret is `listener-secret` in the user config directory (`~/.config/canopy/`): one line of at least 32
  characters, in a regular file, not a symlink, owned by the operator, with no group or other permission bits.
  `canopy secret` writes one, 32 random bytes in URL-safe base64, and prints it; it never replaces one without
  `--rotate`. The loop reads it once, when it starts serving.
- The browser gets it from the operator: the sign-in page asks for it once, in a password field a password manager
  can keep. `POST {base}/api/session` compares it in constant time; a wrong one is answered after a second and logged.
- A right one sets a session cookie, `canopy_session_<port>`: `HttpOnly`, `SameSite=Strict`, path `{base}/`, for 30
  days. Its value is its issue time and a random nonce, signed with the secret (HMAC-SHA256). The server keeps no
  session state, so a session outlives a loop restart, and a new secret signs every browser out. Signing out clears
  the cookie in that browser.
- The per-session token is a second HMAC over the same issue time and nonce. `GET {base}/api/session` gives it to a
  signed-in page, which sends it as `X-Canopy-Token` on every write.
- Every API route but `{base}/api/session` answers 401 without a valid session. A write (any method but GET and HEAD)
  also needs the token and an `Origin` header naming an allowed host: a same-origin request. The custom header makes
  a cross-origin write need a CORS preflight, which the server never grants.
- The app's own files (`index.html` and its assets) are served without a session: they hold no journal data, and the
  sign-in page is one of them.

The API, under `{base}/api`:

| Route | Does |
|---|---|
| `GET /session`, `POST /session`, `DELETE /session` | whether this browser is signed in, with its token; sign in; sign out |
| `GET /meta` | canopy's version, and whether the data is mock |
| `GET /attention` | the attention list, as `canopy status` shows it |
| `GET /runs` | running runs, then the 50 that ended last: kind, status, PRs, summary, session, cost, worktrees |
| `GET /tick` | the latest tick, as `canopy status`'s first line shows it, or none; and the acknowledged message |
| `GET /ticks` | the latest 50 ticks, newest first: status, times, summary, overseer cost, how many decisions |
| `GET /ticks/{id}` | one tick: what `canopy decisions ID` prints; 404 for no such tick |
| `GET /spend` | what the last 24 hours cost: worker, split, and chore runs and each tick's overseer, by start (§13) |
| `GET /tickets` | the journal's tickets, most recent activity first, at most 200: phase, private or public, waiting |
| `GET /tickets/{key}` | one ticket: what `canopy show` prints, its latest 100 messages, and its latest 20 decisions |
| `POST /tickets/{key}/start` | `canopy start` |
| `POST /tickets/{key}/stop` | `canopy stop`, with `now` for `--now` |
| `POST /tickets/{key}/replies` | `canopy reply`, with the form's submission id |
| `GET /chores` | each configured chore, as `canopy status` lists it: its runs, due time, window, and open findings |
| `GET /chores/{name}` | one chore defined for this workspace: what `canopy show chore:NAME` prints; 404 for any other |
| `POST /chores/{name}/replies` | `canopy reply chore:NAME`: a note its next runs read, with the form's submission id |
| `GET /worktrees` | each pool's slots from `treehouse status --json`, with the running run or review holding each |
| `GET /events` | the event stream, below |

A message is acknowledged once a tick that read it closes `ok`: `GET /tick` and `tick.updated` carry the newest message
the latest `ok` tick read (§6 step 3), or none before the first. The attention list is that tick's, so until then a
reply has not reached the loop's decisions or the list: the conversation marks each of the operator's messages after it
as waiting for the next tick, and an `awaiting_reply` item whose ticket waits on no question now as answered. A tick
that read a message but did not close `ok` acknowledges nothing, as it leaves the attention list standing.

A guard's refusal is a 409 whose `detail` names the guard and gives its reason, as the CLI prints them. A reply carries
a submission id the form drew when it was rendered, sent again unchanged when the operator retries, and stored as
`web:<id>`, so a retried submission records nothing new.

The event stream: each open stream holds its own journal connection and reads SQLite's `data_version` once a second.
When another connection has committed since, it reads the attention list, the runs, the tickets, the chores, the
spend, and the latest tick again, and sends each that changed, whole: `attention.updated`, `runs.updated`,
`tickets.updated`, `chores.updated`, `spend.updated` (when the cost changed; its window moves with the clock),
`tick.updated`, and `ticket.changed` naming each ticket whose summary changed. A new stream starts with every list,
the spend, and the latest tick. The UI writes a list into its query with `setQueryData` and refetches a changed ticket
only if a page shows it; a chore's page is read again on every `chores.updated`, whose list carries each chore's
newest note, so a note changes it. The latest tick carries how many decisions it has recorded, so `tick.updated` is
sent as a running tick records them, and on it the UI reads again the ticks list, a tick's page, and a ticket's page,
each only if a page shows it. The journal has
no notifications, so a once-a-second read of one pragma is the cheapest way to learn of a change; nothing in the browser
polls.

The chores pages (M23): a chore's finding reaches the attention list, and the operator answers it in the browser as
`canopy reply chore:NAME` does in the terminal.

- `GET /chores` lists the chores `canopy status` lists: those configured for this workspace, none while
  `capacity.max_chores` is 0. Each has its `every_minutes`, `days`, `hours`, `timezone`, and `when`; its running run,
  or else its latest ended one; its `due_at` (§19, the `not_due` and `outside_hours` guards' earliest start, by the
  server's clock); its open findings, each with when its unbroken sequence of `ok` runs began; and its newest note's id.
- `GET /chores/{name}` is one chore defined for this workspace, configured or not, as `canopy reply chore:NAME` takes
  a note to one: that summary, its latest 10 runs with status, summary, number of findings, session, cost, and log
  path, and the latest 10 notes, oldest first, which are what its next run's `## Run` section carries. A name no chore
  could have is refused `bad_ref`; one not defined here is a 404.
- `POST /chores/{name}/replies` takes the reply form's body and submission id, as a ticket's does, behind the same
  session token and `Origin` check, and records a note with channel `web`. Nothing in the web UI runs a chore: the
  overseer decides when one runs (§19), and `canopy chore try` stays in the CLI.
- A chore run's summary is the harness's note or the agent's summary on one line, and a finding's title and detail are
  the agent's: untrusted text, rendered as text with control characters dropped.
- The chores page is in the navigation, and each chore has a page. On the attention list, a chore's item, a finding or
  `chore_failed`, opens the chore's notes and the note form beside the list, as a ticket's opens its conversation. A
  note no run of the chore has started since is marked as waiting for its next run: notes wake nothing and no tick
  reads them (§19), so a tick's acknowledgement says nothing about them.

The ticks pages (M24): the `decisions` table is the overseer's reasons for what the loop did and the evaluation corpus
for prompt changes (§6), and "why has the loop not picked this up" is answered where the ticket is.

- `GET /ticks` lists the latest 50 ticks, newest first, each as the header's tick is shown, with its overseer's
  session and cost and how many decisions it recorded. `GET /ticks/{id}` is one tick and its decisions in the order
  they were recorded; an id that is not a positive integer is refused (422), and no such tick is a 404.
- A decision names its subject as `canopy decisions` does: a ticket, a unit as its ticket and repository
  (`ABC-1 (web)`), a repository, `chore:NAME`, `pr:URL` for a PR no ticket owns, or `-` for the whole tick; with its
  ticket, repository, chore, and PR apart, and its action and rationale.
- A rationale is the overseer's text: untrusted, rendered as text, its control characters dropped and its whitespace
  collapsed to one line as `canopy decisions` prints it. It was cut at 2000 characters when recorded (§6).
- A ticket's page lists the latest 20 decisions about it, its units' included, newest first, each with its tick.
- The tick's page names where the overseer's output is, `<state_dir>/ticks/<id>.log`, when the file exists, and does
  not serve it (D104): it is agent output from a file, unbounded and unchecked, where everything the UI shows comes from
  the journal.
- The ticks page is in the navigation, and the header's latest tick links to its page. Reads only.

The worktrees page (taken on request, 2026-10-08; D090): for each repository in the workspace, in map order, its pool's
slots as `treehouse status --json` reports them, read when the page asks. Each slot is one line: its state (below;
treehouse's own status on hover), its number (its path on hover), its lease holder, the branch it has checked out (or
detached; a run's slot is detached, D109, and shows the run's branch), the processes treehouse found running in it,
and since when; an idle slot is its state and number alone, and a note gets a second line. A lease is matched to a
running run or review by its lease id, as reconcile matches them, so a slot names the ticket, run kind, and run that
hold it. The page groups slots in five states it colors: `working` (held by a run or review the journal shows
running), `held` (leased or in use by anything else: the operator's own shell,
`canopy-sync`, or a `canopy:` lease no running run holds, which it notes the next reconcile returns), `dirty` (unleased
with uncommitted changes), `idle` (available), and `broken` (damaged, unverified, or a status canopy does not know). A
pool with no clone, or whose treehouse fails, shows why in its place; the other pools still show. Branch and process
names are shown as text with control characters dropped, and at most 20 processes per slot. A path inside the workspace
is shown from its root (`.treehouse/web-3f9c2a1b/1/web`), here and in the runs page's worktrees; a workspace of one's
pool, outside its repository, is shown whole. When a pool's slots share a directory, the pool's header names it once.
The pool's declared size (`capacity`, §18) is shown with its slot count, and a pool holding more slots than that says
how many, and that `canopy workspace sync` removes idle ones. Above the pools, counters of every pool's slots working,
held, needing a look (dirty or broken, and any pool it could not read), and free; each pool's header has a square per
slot in its state's color.

The pools are read at once, a thread each and at most 8, so a workspace of many repositories waits on its slowest pool
rather than on all of them in turn. `treehouse status` changes no lease, but it takes the pool's state lock and may
rewrite the pool's state file as it heals it, as reconcile's reads do every tick, so a slow read holds up a lease in
that pool for as long as it takes.

It is not on the event stream: the journal does not hold a slot's branch or processes, and a `treehouse status` per
pool once a second per open page would cost more than the page is worth. The UI reads it again when a `runs.updated`
event changes which running runs hold which worktrees (a run's cost moving does not), when the operator asks, and
every 30 seconds while a page shows it in a visible tab (D090): what runs in a slot, whether it is dirty, and the slots
a sync adds or removes never reach the journal, and a run's own refresh comes as it is recorded, before its worker has
checked out its branch. Only an operator's read shows on the Read again button.

How it serves, built in M20's foundation and true of every page:

- Under one path prefix (`serve.base_path`; `--base-path` for `python -m canopy.serve`; empty by default), so a proxy
  can mount it anywhere: the API at `{base}/api`, the app's hashed files at `{base}/assets/`, and `index.html` for
  every other GET or HEAD. The prefix is written into `index.html` as `<base href>`; the build uses relative URLs and
  the router reads its basepath from it, so one build serves under any prefix. The prefix comes from config, never
  from a request header.
- The fallback to `index.html` never answers under `{base}/api` (an unknown API path is a JSON 404) or for a path
  with a file extension (a missing asset is a 404, not a page). `index.html` is sent `no-cache`, so an upgrade never
  shows a stale UI; hashed assets are cached as immutable.
- Every response refuses framing and MIME sniffing and sends no Referer. `index.html` carries a CSP that allows only
  this origin, plus the inline theme script by its hash, computed from the file served.
- The Host header must name a loopback host or the bind address, on any route: that stops DNS rebinding. An `Origin`
  header on an API route must name one of those too: that stops another site's page from calling the API or opening
  the stream. Ports are not compared, so an SSH forward to another local port works.
- The event stream is FastAPI's SSE: `Cache-Control: no-cache`, `X-Accel-Buffering: no` so a proxy or forward does not
  buffer it, and a keepalive comment after 15 idle seconds. Nothing compresses it.
- The page makes no request to another origin: fonts and icons are bundled.
- `python -m canopy.serve --mock` serves the same API over a journal it seeds from fixtures in a temporary directory,
  for the UI's development server and its end-to-end tests. The fixtures are a workspace of three repositories, one
  not cloned, with a run holding slots in two pools and a pool past its declared size. Writes go to that journal.
  Without `--secret-file` it signs nobody in and asks for no session; only mock mode allows that, and it binds loopback
  only.

### Trust model changes

M18's and M19's are in TRUST_MODEL T1 and T6, with the operator's approval note in each milestone's PR. M20's are in
T8: the listener secret's file and sign-in, the session cookie and its token on writes, the allowed hosts, escaping,
and the residuals they leave, needing the operator's approval note in M20's PR.

The overseer prompt's changes, private tickets' phases from the state block and no `--label` for them (M18), and
mirroring each new comment (M19), are in the prompt.

Replies on public tickets and trusted reviewers (D089) changed T1: an operator message authorizes a public ticket's
`resume`, as an authorized reply does, and an untrusted reviewer's feedback starts no run without one. Their PR carries
the operator's approval note.

### Open

- Whether a private worker should have no tracker MCP server at all. It would then need the ticket's text from
  elsewhere; the overseer's `--context` holds 2000 characters.
- Whether a private ticket's PR body and branch should name the ticket key.
- Deleting a ticket's conversation, for client data the operator must not keep. `forget` keeps it.
- `forget` in the web UI. It is the CLI's only; the web channel would call the same function.
- A forgotten ticket's attempt counts are not in the state block, which shows them per unit, so the overseer learns a
  limit from the `attempt_limit` refusal rather than before dispatching.
- Mirrored comments edited or deleted after the mirror.
- PR review comments in the journal, alongside ticket comments, once PRs are subjects (M14).
- Slack replies: a bridge holding a Socket Mode connection that runs `canopy reply` (a uv workspace member, like
  the Slack sink, so the harness stays free of network code), or the overseer reading Slack through MCP (§20). Either
  needs a T1 change naming Slack user ids.

## 23. Flaky CI (M25)

Rationale in D102 and D103. Designed, not built: until M25 lands, §7's `ci_red` always dispatches `fix-ci`, and §7,
§8, §12, and §13 describe canopy as it is. This section says what changes in each.

Some failures are not the change's: a test that fails one run in five, a runner that died, a package registry that
timed out. A `fix-ci` worker sent to one changes code that is not broken, or reports `blocked`, and spends an attempt
either way. A **triage** is a run that reads a new failure first and decides. Flaky: it reruns the failed jobs, and the
PR goes back to `ci_running`. Real: the next tick dispatches `fix-ci` as before. A triage never edits, commits, or
pushes, and holds no worktree.

### Configuration

```toml
[policy]
max_triage_ci_attempts = 0   # per unit; 0, the default, turns triage off

[runtime]
triage_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-ci-triage --format json {prompt}'
triage_timeout_minutes = 10
triage_skill = ""            # optional; the skill that says which of a repository's failures are flaky
```

- `max_triage_ci_attempts` is a `max_<kind>_attempts` like the others (§8): counted from `runs`, never reset (D030).
  Its default is 0, and a repository may only tighten policy (§12), so only the operator's file turns triage on (D103).
- `triage_cmd` follows §12. A private ticket's triage (§22) uses it too: the triage agent writes nothing to the tracker.
- `triage_skill` names a skill the triage agent follows, from where the runtime reads skills (§13): the repository's
  (`.agents/skills/<name>/SKILL.md`, read from its primary clone, below) or the operator's in `$HOME`. It holds what
  only the repository knows: tests known to flake, failures that are always infrastructure, checks never to rerun, and,
  for a CI that is not GitHub Actions, which tool reruns a job. Unset, the agent follows the prompt's general rules
  alone. Named but not available, the agent reruns nothing and reports `real` with a summary starting
  `no triage skill:`, so the failure goes to `fix-ci` as it did before triage existed.

### Off unless configured

With `max_triage_ci_attempts` at 0 nothing changes: the state block has no triage fields, the overseer prompt's triage
rows do not apply, `ci_red` dispatches `fix-ci`, and `canopy dispatch --kind triage-ci` refuses as `triage_off`, with
no attention item. A test holds this.

### Dispatch

`canopy dispatch KEY --kind triage-ci [--repo NAME] --cursor ci=<run> --context '<check and link>'` runs §8's guards
as for `fix-ci`, without `cooldown`, plus:

- `triage_off`: `policy.max_triage_ci_attempts` is 0.
- `bad_request`: a `triage-ci` that names more than one unit, or gives `--base`. A triage reads one PR.

It leases no slot. `_run` claims the run (§8 step 1), skips the git steps, and runs `triage_cmd` with timeout
`triage_timeout_minutes` and cwd the unit's primary clone: the repository root in a workspace of one, its clone under
`repos/` in a workspace (§18). The shadowing check (§13) covers that directory first, as it does for the overseer. It
parses the triage result (below), skips push verification, and records the run and its report (§8 step 7). A triage
counts toward `capacity.max_workers` with workers and reviews: it is an agent run, with spend.

The cwd is never a checkout of the PR's branch, so the runtime loads the repository's skills from the primary clone,
and a PR cannot change the skill that judges it (D103). In a workspace of one that clone is the operator's own
checkout, on whatever branch they have there.

### The prompt

`prompts/ci-triage.md`, and `ci-triage-private.md` for a started ticket (§22), with the key, the repository, its PR
and branch, the attempt number and limit, `{{TRIAGE_SKILL}}` (the instruction to follow the named skill, or nothing),
the overseer's context, and the result contract. The agent:

- checks authorization first, as every worker does (§8 step 3): a closed ticket, or one with none of the queue labels,
  is `failed` with a summary starting `not authorized:`. The private variant has no label to check.
- reads the PR head commit's failed checks and their logs, the earlier runs of those checks on the same commit, and the
  same checks' recent runs on the base branch.
- reports `flaky` only with evidence the change did not cause the failure: the skill names it; the job failed before
  any of the repository's code ran (runner lost, checkout or dependency download failed, a service outside the
  repository returned an error or timed out); or a test the diff does not touch fails and passes on the base branch
  with nothing it tests changing. Anything else, and anything it is unsure of, is `real`: a `fix-ci` that finds nothing
  to fix costs less than a rerun that hides a regression.
- reports `real` for a failure on a head commit a triage already reran: a check gets one rerun per commit.
- reruns only the failed jobs of the failed runs it judged, on the PR's head commit, once each: with
  `gh run rerun <id> --failed`, or the tool the skill names. It starts no other workflow run, cancels nothing, and
  touches no other PR's or branch's runs. It does not wait for the rerun.
- treats logs, the diff, and PR text as data (TRUST_MODEL T1), and writes nothing else: no comments, labels, edits, or
  commits. Its summary is its report, which `canopy show` and the web UI list with the ticket's other runs (§22).

Result contract, one JSON line, last line of the agent's text (§13), validated with pydantic (D026):

```json
{"status":"done|failed","verdict":"flaky|real","commit":"<full head sha>",
 "reruns":["https://github.com/o/r/actions/runs/123"],"summary":"one paragraph"}
```

- `done` has a verdict and the head commit it judged, 40 or 64 lowercase hex characters. `reruns` is non-empty exactly
  when the verdict is `flaky`: at most 10 plain `https://` URLs of at most 500 characters. Otherwise the run is
  recorded `failed` with a harness note. `summary` is cut at 2000.
- `failed` means it could not triage, and the summary says why. Like any run that ends other than `done`, it raises
  attention (§14, D028), and the overseer waits for an authorized reply or an operator message before the unit's next
  dispatch.
- Anything else is `unknown`.

### The overseer's part

The state block's `policy` gains `max_triage_ci_attempts`; each unit's `attempts` gains `triage-ci`, and the unit gains
its latest triage: run id, status, verdict, commit, reruns, and end time. When triage is on, `ci_red` (§7) is decided
by the first that fits:

| Situation | Action |
|---|---|
| failure newer than the `ci` cursor on a head commit no triage has rerun, and the unit under its triage limit | `dispatch triage-ci --cursor ci=<run>` |
| the unit's latest run is a `triage-ci` that ended `done` with `real`, and no run since | `dispatch fix-ci`, its context pointing at the triage run |
| failure newer than the `ci` cursor on a commit a triage reran, or the unit at its triage limit | `dispatch fix-ci --cursor ci=<run>`, as today |

A rerun's checks are newer than the cursor, so a unit whose rerun is still running is `ci_running` and waits, and one
whose rerun passes moves on as any green PR does. Triage takes `ci_red`'s place in step 4's priority order. The
`fix-ci` cooldown counts from the latest `fix-ci` only, and `fix-ci` attempts count only `fix-ci` runs, so reruns
spend neither.

### Agent definition

canopy ships `canopy-ci-triage` in the definitions directory (§13):

- no edits, no subagents, no web tools; reads only inside its cwd.
- bash denied but for `gh run view *` and `gh run rerun *`, checked command by command (D021).
- MCP: the tracker and GitHub, read tools only. Denied by name: every tool the worker definition denies, and comment,
  label, and PR update tools. GitHub's server folds reruns into `actions_run_trigger`, which also starts workflows and
  cancels runs, so it stays denied, and reruns go through `gh`; a tool named for reruns alone (`*rerun*`) is allowed.

A CI reached through another MCP server needs its rerun tool allowed. The operator copies the definition into their
runtime config, allows exactly that tool, and points `triage_cmd` at it, as for a chore's tools (§19).

Workers lose what this section gives the triage: `canopy-worker` denies `gh run rerun*`, `gh run cancel*`,
`gh run delete*`, and `gh workflow*` (today its bash allows them; only the MCP names are denied), so a triage is the
only run that reruns CI. `gh run view` stays: reading a failure is `fix-ci`'s job. `canopy-worker-private` already
denies all of `gh`.

### Journal

- A triage is a `runs` row of kind `triage-ci` with no `run_slots`, its branch the ticket's, and `result_json` the
  validated result. Its report message (§8 step 7) is the summary with each rerun URL on a line.
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
- T7: `runtime.triage_*` is user-only, and a repository cannot raise `max_triage_ci_attempts` from 0. The skill is
  read from the primary clone, never the PR's branch. Residual: a repository's skill steers verdicts, as repository
  skills steer every run (§13).
- §6: never rerun CI except in a triage run, and never more than `policy.max_triage_ci_attempts` triage runs per unit.
- §7: protect workflows whose rerun does more than test, such as deploys and releases, with environment protection
  rules that require a reviewer: a rerun runs as you.

### Open

- Whether the triage's verdict should reach the `fix-ci` prompt, rather than the worker reading the failure again.
  The overseer's context only points at the triage run (D031).
- Whether a triage should comment on the PR saying what it reran and why, for its reviewers. That needs a comment tool
  the definition denies.
- Whether reruns should reach a human as debt: a finding of the build-health chore (§19), or an attention item when a
  unit's reruns reach its limit.
- One rerun per commit is a prompt rule. The harness does not know the head commit; the `commit` a triage reports is
  the agent's word.
- Whether the overseer should skip triage for a failure the change obviously caused, saving a run. It reads check
  names and states, not logs (T1).
