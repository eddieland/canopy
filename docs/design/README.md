# canopy design

Normative. Code follows the design; changes to behavior change it in the same PR. The rationale for a behavior lives in
the design, next to it. `DECISIONS.md` holds only the decisions every developer must know: cross-cutting constraints,
trust-boundary rules, and runtime dependencies.

The design is the files in this directory, read in the order below. Sections are numbered across all of them, so the
numbers run on from one file to the next, and §N, or DESIGN §N from code and other documents, names one section wherever
it lives. A new section takes the next number and goes at the end of the last file, or starts a new file there; it does
not go in the middle of the sequence.

- This file: the problem, goals, principles, and components.
  - [1. Problem](#1-problem)
  - [2. Goals](#2-goals)
  - [3. Non-goals](#3-non-goals)
  - [4. Principles](#4-principles)
  - [5. Components](#5-components)
- [The loop](LOOP.md): the tick, ticket phases, dispatch and the worker contract, slot release, and stacking.
  - [6. Tick](LOOP.md#6-tick)
  - [7. Ticket phases and next actions](LOOP.md#7-ticket-phases-and-next-actions)
  - [8. Dispatch and the worker contract](LOOP.md#8-dispatch-and-the-worker-contract)
  - [9. Aggressive release](LOOP.md#9-aggressive-release)
  - [10. Dependencies and stacking](LOOP.md#10-dependencies-and-stacking)
- [Operating canopy](OPERATING.md): the state model, configuration, the agent runtime, the attention list, failure
  handling, and open questions.
  - [11. State model](OPERATING.md#11-state-model)
  - [12. Configuration](OPERATING.md#12-configuration)
  - [13. Agent runtime](OPERATING.md#13-agent-runtime)
  - [14. Attention list](OPERATING.md#14-attention-list)
  - [15. Failure handling](OPERATING.md#15-failure-handling)
  - [16. Open questions](OPERATING.md#16-open-questions)
- [Trackers and workspaces](WORKSPACES.md): where tickets come from, and one queue over several repositories.
  - [17. Trackers](WORKSPACES.md#17-trackers)
  - [18. Workspaces and multi-repo tickets](WORKSPACES.md#18-workspaces-and-multi-repo-tickets)
- [Chores, notifications, and reviews](CHORES_NOTIFICATIONS_REVIEWS.md): recurring chores, notifications away from the
  terminal, and adversarial reviews of PRs.
  - [19. Chores](CHORES_NOTIFICATIONS_REVIEWS.md#19-chores)
  - [20. Notifications](CHORES_NOTIFICATIONS_REVIEWS.md#20-notifications)
  - [21. Reviews](CHORES_NOTIFICATIONS_REVIEWS.md#21-reviews)
- [Conversations](CONVERSATIONS.md): the journal's conversation, private tickets, its channels, and the web UI.
  - [22. Conversations](CONVERSATIONS.md#22-conversations)
- [Flaky CI](FLAKY_CI.md): triage of a CI failure before a fix-ci worker is sent.
  - [23. Flaky CI (M25)](FLAKY_CI.md#23-flaky-ci-m25)
- [Sandboxed runs](SANDBOXING.md): the opt-in OS sandbox around every agent run but the overseer's.
  - [24. Sandboxed runs (M26)](SANDBOXING.md#24-sandboxed-runs-m26)
- [Plans](PLANNING.md): a plan for a ticket, approved by the operator before any `implement`.
  - [25. Plans before implementing (M44)](PLANNING.md#25-plans-before-implementing-m44)
- [Garbage collection](GARBAGE_COLLECTION.md): what canopy removes of its own history and caches, and what it keeps.
  - [26. Garbage collection (M47)](GARBAGE_COLLECTION.md#26-garbage-collection-m47)
- [The overseer's tools](OVERSEER_TOOLS.md): the MCP tools canopy serves the overseer, in place of the CLI.
  - [27. The overseer's tools (M48)](OVERSEER_TOOLS.md#27-the-overseers-tools-m48)
- [Agent memory](MEMORY.md): what workers record of what they learn, who reads it, and who decides.
  - [28. Agent memory (M50)](MEMORY.md#28-agent-memory-m50)

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
- A sandbox the harness knows about. Sandboxing is an opt-in prefix on the command templates (§24), and the harness
  never learns whether a run is sandboxed (D118).

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
the features, `runs`, `setup`, `chores`, `notify`, `reviews`, `memory`, and `serve`; `core`; `infra`. A module imports
from its own package and lower layers only. Features never import each other; what two share moves down a layer.
`tests/canopy/test_layers.py` enforces this and fails on a module outside the packages it lists.

```text
canopy (harness, Python)
  __main__.py      python -m canopy, how dispatch starts _run from the same installation

  cli/             the command line; only cli imports click, and only __main__ imports cli
    launcher.py    the console script and python -m canopy: `--version` alone without importing the CLI (§6)
    main.py        main(), exit codes, the root group, which imports a command's module only when it runs
    common.py      opening the Context, refusals, the tick named by CANOPY_TICK_ID
    params.py      validated parameter types: ticket keys, reasons, slugs, cursors, bounded text
    render.py      how status, show, and the other read-back commands name tickets, runs, costs, and chores
    setup.py       init, skill, secret (the web UI's listener secret, §22)
    loop.py        loop (serving the web UI unless --no-serve), tick, tick --dry-run, status, decisions
    spend.py       spend: each day's cost by kind, and the ticks by what they bought (§11)
    runs.py        dispatch, _run
    conversation.py start, stop, reply, forget, grant, show: the operator's verbs on a subject (§22), a PR's review
                   request among them (§21); pause and resume, on the loop (§6); notice, to every later run (§8)
    journal.py     decide, attention, ticket set
    workspace.py   workspace sync
    chores.py      chore run, chore wait, chore try, _chore
    notify.py      notify test
    reviews.py     review run, review wait, review end, review show, _review
    memory.py      memory list, forget, purge: agent memory's tiers and what they hold (§28)

  loop/            the tick (§6), which drives the features below
    tick.py        lock, migrate, reconcile, run the overseer, close the tick, publish
    repeat.py      canopy loop: ticks one after another with a wait between them, its own lock, rich output
    reread.py      reading the config again while the loop runs, on SIGHUP or from the web UI (§6)
    pacing.py      how long the loop waits: idle ticks, gates, and what wakes it early (§6, Idle pacing)
    web.py         the web UI for canopy loop: the listener secret checked, the server's backend wired, started
    state.py       the overseer's state block
    attention.py   the attention list from the journal; render attention.md, diff, notify

  runs/            worker runs on tickets (§8)
    dispatch.py    guards, leases (all or nothing), render the worker prompt, spawn detached _run
    policy.py      attempt limits and the fix-ci cooldown per unit, derived from runs, run_slots, and grants
    worker.py      canopy _run: branch setup and the operator's setup command in each slot, the worker, result
                   parsing, push verification, slot return; a split's run, its children validated into split_children
    desks.py       a joint run's desk: one link per worktree it leased (§18)
    tidy.py        a run's object directory, and each slot put back before it is returned: its `.git` link and
                   `commondir`, and no ref or reflog naming the run's own objects (§8)
    reconcile.py   dead runs marked crashed, their slots and desks cleaned up, stale leases returned, the capacity
                   left; the shadow of canopy's pool over treehouse's slots (§18)
    halt.py        canopy stop --now: a stopped ticket's run killed and closed as reconcile closes a dead one (§22)

  chores/          the operator's recurring chores (§19); what the web UI reads of them is in core (chore_*.py)
    start.py       canopy chore run: guards, the prompt with its `## Run` section, spawn detached _chore
    execute.py     canopy _chore: the chore's command in its cwd, result parsing, closing its row
    trial.py       canopy chore try: a run outside any tick, in the foreground; recorded unless --no-record
    reconcile.py   chore runs whose _chore is gone marked crashed

  notify/          notification sinks (§20)
    deliver.py     each sink in turn: its attention diff, events, digest; one message; the loop's own events
    message.py     the message in text or json, its bounds, the digest
    journal.py     sinks' cursors and failures, what each was told, the outbox's reads and pruning
    desktop.py     canopy-notify-desktop: the desktop sink, a separate command

  reviews/         adversarial reviews of PRs (§21)
    start.py       canopy review run: guards, the slot, the reviewer's prompt, spawn detached _review
    grants.py      a PR's review limit, and canopy grant URL review raising it
    execute.py     canopy _review: checkout at the commit, its diff kept for the web UI, the reviewer outside it,
                   result checks, slot return
    view.py        the state block's reviews
    findings.py    a review as a resumed worker and canopy review show read it, from the journal
    reconcile.py   review runs whose _review is gone: reviewer killed, slot returned, marked crashed

  memory/          agent memory's feature (§28)
    manage.py      the operator's verbs: forget one memory, purge many, each a secure delete leaving a tombstone

  serve/           the web UI's server (§22, D079); the only package that imports fastapi, starlette, uvicorn, or anyio
    app.py         create_app(): the guard, the API under {base}/api, the single-page app under {base}/
    api/           the JSON and SSE routes, a router per resource: session, tickets and the operator's verbs on
                   them, runs, ticks, chores, the loop, worktrees, events, search, reviews, pull requests; deps.py the backend
                   and sessions each app binds for its routes, refs.py what the routes share, docs.py the schema and
                   a Swagger UI page over it
    auth.py        sign-in with the listener secret, the signed session cookie, the per-session token on writes
    secret.py      the listener secret's file: read with its checks, written by `canopy secret`
    backend.py     what the loop hands the server: config, journal, the attention list, ending a run, a reload; a
                   Context per request
    views.py       journal rows as the API's models: attention items, runs, tickets, messages, search hits
    reviews.py     review runs as the API's models: each one's findings anchored on its diff (§21)
    pull_requests.py the PRs the journal knows, each with the runs that pushed to it, its reviews, and its decisions
    live.py        the event stream: data_version read 4 times a second, changed lists sent whole
    sse.py         an event stream whose client left ends without FastAPI's teardown error in the log
    schema.py      the API's pydantic models, the source of the UI's generated TypeScript types
    spa.py         the built app: hashed assets, index.html for routes with a <base href> and a CSP, never for /api
    guard.py       Host, Origin, and body size checks, and security headers on every response
    options.py     ServeOptions: loopback or private host, port, base path, mock data
    server.py      the server's thread for canopy loop: uvicorn without signal handlers, restarted with a backoff
    mock.py        a journal seeded from fixtures, and the changes its stream shows
    mock_reviews.py the mock journal's review runs and the diffs beside their logs, and a review request
    __main__.py    python -m canopy.serve --mock: serve for development and tests, or print the OpenAPI schema

  setup/
    init.py        canopy init: the private config, branch protection text, the SSH push URL check, the sandbox hint
    sandbox.py     canopy sandbox setup: the wrapper's templates, the pinned srt, and what needs root
    workspace.py   canopy init: the skeleton; canopy workspace sync: converge clones and pools (§18)

  core/            what every feature shares
    agent_output.py an agent's stdout: its text, and OpenCode's JSON events' session id and cost (§13)
    chore_view.py  each configured chore: due time, runs, open findings; chore_failed items; its state block part
                   (§19), read by the loop, the CLI, chores, and the web UI
    chore_window.py a chore's days and hours: whether a run may start now, and when it next may
    chore_result.py a chore's result contract, validated with pydantic
    review_result.py a review's result contract, validated with pydantic (§21), read by reviews and the web UI
    review_diff.py a review run's diff beside its log: read bounded, parsed, and each finding anchored on it (§21)
    review_requests.py the operator's requests to review a PR the loop does not own, with their guards (§21), which
                   the CLI and the web UI share
    search.py      the web UI's search over the journal: tickets, messages, chore runs, decisions, ticks (§22)
    spend.py       what agent runs cost by day, kind, and what the ticks bought, for canopy spend and the web UI (§11)
    config.py      layered config: canopy-workspace.toml, the user config.toml, the private .canopy/config.toml; scopes
    context.py     the Context every command passes around: config, workspace, db connection, runner
    contract.py    what every agent result contract is built from: bounded text, plain URLs, the last stdout line
    conversation.py references, start records, the operator's messages, runs' reports and questions, with the guards
                   every channel shares (§22)
    db.py          SQLite journal, migrations; the one lifecycle of every table of detached runs (§6)
    dead_runs.py   what each kind's reconcile shares: runs whose process is gone, their agents killed, closed crashed
    records.py     typed journal rows: a frozen dataclass per table, built by a query and held to its schema
    vocab.py       the closed vocabularies: a run's status and kind, a ticket's phase (§7, §8), as StrEnums
    items.py       the attention item: its subject, fingerprint, and age
    outbox.py      the events notification sinks receive, recorded with the fact they report (§20)
    pause.py       the loop's pause, which every channel writes: whether `canopy loop` starts another tick (§6)
    notice.py      the operator's notice to workers, which every channel writes: what every later run hears (§8)
    memory.py      agent memory (§28): each tier's mode in words, a run's part of the prompt and what it was rendered
                   under, writing what a run sent in the transaction that closes it, and the digests
    memory_text.py what a memory's text may hold (§28, Bounds): a slug key, one line without hidden characters or
                   secrets; and its text with every hidden character named, as every surface shows it
    plans.py       each plan's file, written once and read bounded, and its row: current, superseded, approved
                   by its file's hash (§25)
    definitions.py the snapshot of agents/ and skills/ that agent runs load (§13), the private worker's rendered from
                   config; the guards against shadowing them and against naming the tracker's tools (§22)
    prompts.py     prompt files and overrides; rendering worker prompts
    pools.py       what a worktree pool is to every caller: slots, leases, returns, and the Pool protocol (§18)
    treehouse.py   status, get --lease, return, destroy; a Pool per repository, with its declared size (§18)
    pool.py        canopy's own pool: worktrees it makes, leases in the journal's slots table (§18, ROADMAP M45)
    hostgit.py     git as the harness runs it: hooks, the filesystem monitor, and submodule fetches off; a slot's
                   `.git` link and `commondir`, read and put back (§8)
    workspace.py   the workspace: its map, repositories, their pools, the private state directory (§18)

  infra/           plumbing that knows nothing about tickets or agents
    procs.py       the only module that runs subprocesses (lint-enforced); a timeout kills the whole process group;
                   a child's PWD names its cwd (OpenCode runs tools in PWD); detached spawns and pid liveness
    cwds.py        the processes working in a directory, from /proc or lsof, and ending them: what keeps a slot busy
    lock.py        flock on <state_dir>/lock; a tick that cannot lock exits 0 with a log line
    stopping.py    SIGTERM, SIGHUP, and SIGINT become an exception the cleanup of _run and _chore catches
    hangup.py      whether the controlling terminal hung up, to tell that SIGHUP from a reload's
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
  canopy-sandbox/  the sandbox wrapper, its policy templates, and srt's lockfile (§24, D117)
ui/              the web UI (D079): a Vite and React app, its own rules in ui/AGENTS.md and ui/DESIGN.md
hatch_build.py   the wheel's build hook: builds ui/ with npm and bundles ui/dist as canopy/_data/ui
```

`prompts/`, `agents/`, `skills/`, and `operator-skill/` live under `.agents/` in this repository. The wheel bundles
them, with `migrations/`, under `canopy/_data/` through hatch's `force-include`, so a new runtime directory needs a
line there.

canopy installs from git with `uv tool install` (D046), which builds the wheel and so the web UI, and puts `canopy`,
both sinks, and the sandbox wrapper on `PATH`. Dispatch, chores, and reviews start `_run`, `_chore`, and `_review` via
`sys.executable -m canopy`, so whatever runs canopy must be an interpreter that imports it. The version is the tag's
(D085): a build at `v0.2.0` is 0.2.0, and a build between tags names its distance from the last one and its commit.
Pushing the tag runs `.github/workflows/release.yml`, which makes the tag's GitHub Release with notes Claude writes,
through the operator's subscription, from the commits since the previous tag; GitHub's generated notes stand in if it
fails. The release carries no build: the install is still from git.

Where later work goes:

- A feature is a features-layer package plus a `cli/` command module: `chores` (§19), `notify` (§20), `reviews`
  (§21). `loop` calls its reconcile and publish steps and its state block part. Deleting a feature deletes those three.
- A top-level command is listed in `COMMANDS` in `cli/main.py`, by its module and attribute, and its module is
  imported only when that command runs. The overseer and workers run `canopy` many times a tick, and each process pays
  for every module it imports, so `canopy decide` loads `cli/journal.py` and not the tick, the worker, or chores. For
  the same reason `cli/common.py`, which every command imports, imports nothing from `loop`.
  `tests/canopy/test_cli.py` fails on a command missing from `COMMANDS` and on one that imports another's module.
- A feature others write to keeps its writing half in `core`: dispatch, `_run`, `_chore`, and reconcile record §20's
  events through `core.outbox`; `notify` delivers them.
- Code that runs in its own process and must not share the harness's imports or dependencies is a uv workspace member
  under `packages/`, such as §20's Slack sink and the sandbox wrapper. `canopy`, the workspace root, lists each one's
  script among its own, so one install puts them all on `PATH`. canopy reads the wrapper's bundled templates and
  lockfile, and never runs it: only a command template does.
- A module that takes on a second concern splits into a same-named package in the same layer, as `cli.py` did.
- A pydantic model sets `defer_build=True`, so its schema is built where it first validates, not where it is imported.
  The overseer and workers run `canopy` many times a tick, and each process would otherwise build every model it
  imports, though a command validates few of them. A field whose default is a model takes it through
  `default_factory`; a default instance builds the model at import. The web server's models in `serve/` stay eager,
  since FastAPI builds them all when it creates the app. `tests/canopy/test_models.py` fails on a model that does not
  defer, does not build, or is built when `canopy` starts.

Roles:

- **Harness**: schedules, locks, guards, journals, renders. Runs the overseer once per tick and workers on demand.
- **Overseer**: an agent run with `overseer_cmd`. Reads the world through MCP and the state summary, decides one next
  action per ticket, and acts only through `canopy dispatch`, `canopy decide`, `canopy queried`, `canopy attention`,
  `canopy chore run`, `canopy chore wait` (§19), `canopy review run`, `canopy review wait` (§21), and `canopy mirror`
  (§22). Read-only everywhere else. What it owes every tick is checked when it ends (§6 step 5).
- **Worker**: an agent run with `worker_cmd` in a leased worktree with a task prompt. Writes code, pushes a branch,
  opens or updates a PR, comments on the ticket, prints a result line, exits. Never merges, approves, or moves a ticket
  to Done. A private ticket's worker runs with `private_worker_cmd` and writes nothing to the ticket (§22).
