# canopy design

Normative. Code follows the design; a change to something the design states changes it in the same PR. The rationale
for a behavior lives in the design, next to it. `DECISIONS.md` holds only the decisions every developer must know:
cross-cutting constraints, trust-boundary rules, and runtime dependencies.

## What belongs here

The design says what canopy does and why, at the level someone needs to rely on it or to change it safely. It is not
the implementation written out in prose, a changelog, or a measurement report: every detail it fixes is one more thing
every later change must keep in step, and one more thing to read before making it.

It holds:

- behavior seen from outside the code: what the operator, the overseer, workers, and the tracker see and may do; the
  commands and config keys and what they mean; what a tick, a run, or a sink is promised;
- the guards and invariants the harness enforces, and the contracts between parts: a result line, what the state block
  carries, what a pool guarantees, what a channel may write;
- why each is so, in a sentence or two, and the alternatives rejected for it, a line each, where they would otherwise
  be proposed again.

The rest goes where the next person to change it will look:

- how the code does it (modules, functions, columns, field order, algorithms, which test enforces what): the code, its
  docstrings and comments, and `migrations/` for the schema. §5 maps packages, not modules;
- every flag and output line of a command: its `--help` and its tests;
- what a measurement found: `MEASUREMENTS.md`, cited here by date and finding, without its figures;
- how a behavior came to be, who asked for it, and which milestone built it: the PR, and the milestone's lines in
  `ROADMAP.md`;
- what a prompt tells an agent beyond the contract the harness checks: the prompt;
- the web UI's pages and how they look: `ui/DESIGN.md`.

A behavior change edits the design only where the design says something about it, and a refactor usually edits none.
Prefer the shorter statement: a detail that turns out to matter can be added later, and one that does not costs every
reader.

The design is the files in this directory, read in the order below. Sections are numbered across all of them, so the
numbers run on from one file to the next, and §N, or DESIGN §N from code and other documents, names one section wherever
it lives. A new section takes the next number and goes at the end of the last file, or starts a new file there; it does
not go in the middle of the sequence.

- This file: what belongs in the design, the problem, goals, principles, and components.
  - [What belongs here](#what-belongs-here)
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
- [Flaky CI](FLAKY_CI.md): triage of a CI failure before a `resume` is sent to fix it.
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
- [Review replies](REVIEW_REPLIES.md): replies to coworkers' review comments that workers draft and the operator
  sends.
  - [29. Review replies the operator sends (M53)](REVIEW_REPLIES.md#29-review-replies-the-operator-sends-m53)

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
- A hosted service, a service installed with the OS, or a workflow DSL. `canopy loop` (§6) runs where the operator
  started it, in the foreground or detached by `canopy daemon`, and nothing restarts it. A listener is allowed only on
  loopback or the operator's private network, behind the operator's secret (TRUST_MODEL T8, D055); none is built yet.
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
  __main__.py  python -m canopy, how dispatch starts _run from the same installation
  cli/         the command line; only cli imports click, and only __main__ imports cli
  loop/        the tick (§6) and canopy loop, which drive the features below; the state block; the attention list
  runs/        worker runs on tickets (§8): guards, leases, the detached _run, reconcile
  chores/      the operator's recurring chores (§19)
  notify/      notification sinks (§20)
  reviews/     adversarial reviews of PRs (§21)
  memory/      agent memory's feature (§28): proposals' expiry, its attention items, and search
  serve/       the web UI's server (§22, D079); the only package that imports fastapi, starlette, uvicorn, or anyio
  setup/       canopy init, the sandbox's setup, and workspace sync (§18, §24)
  core/        what every feature shares: config, the Context, the journal and its typed rows, vocabularies, contracts,
               conversations, pools
  infra/       plumbing that knows nothing about tickets or agents; procs.py is the only module that runs subprocesses
```

```text
prompts/         the overseer's, workers', and the reviewer's prompts
agents/          OpenCode agent definitions, one per kind of run
skills/          tracker-<provider>/: optional per-tracker guides (§17)
operator-skill/  SKILL.md: the canopy skill, for the operator's own agent sessions (§13); agent runs never load it
migrations/      NNNN_name.sql
packages/        uv workspace members: separate programs canopy ships, run only as commands, such as the Slack sink
                 (§20) and the sandbox wrapper (§24)
ui/              the web UI (D079): a Vite and React app, its own rules in ui/AGENTS.md and ui/DESIGN.md
```

`prompts/`, `agents/`, `skills/`, and `operator-skill/` live under `.agents/` in this repository. The wheel bundles
them, with `migrations/` and the built UI, so a new runtime directory needs a line in `pyproject.toml`.

canopy installs from git with `uv tool install` (D046), which builds the wheel and so the web UI, and puts `canopy`,
both sinks, the GitHub reader and poster (§29), and the sandbox wrapper on `PATH`. Dispatch, chores, and reviews start
`_run`, `_chore`, and `_review` via `sys.executable -m canopy`, so whatever runs canopy must be an interpreter that
imports it. The version is the tag's
(D085). A tag's GitHub Release carries notes, not a build: the install is still from git.

Where later work goes:

- A feature is a features-layer package plus a `cli/` command module: `chores` (§19), `notify` (§20), `reviews`
  (§21). `loop` calls its reconcile and publish steps and its state block part. Deleting a feature deletes those three.
- A command's module is imported only when that command runs, and `cli/common.py`, which every command imports,
  imports nothing from `loop`. The overseer and workers run `canopy` many times a tick, and each process pays for every
  module it imports.
- A pydantic model defers building its schema until it first validates, for the same reason. The web server's models
  stay eager, since FastAPI builds them all when it creates the app.
- A feature others write to keeps its writing half in `core`: dispatch, `_run`, `_chore`, and reconcile record §20's
  events through `core.outbox`; `notify` delivers them.
- Code that runs in its own process and must not share the harness's imports or dependencies is a uv workspace member
  under `packages/`, such as §20's Slack sink and the sandbox wrapper. `canopy`, the workspace root, lists each one's
  script among its own, so one install puts them all on `PATH`. canopy reads the wrapper's bundled templates and
  lockfile, and never runs it: only a command template does.
- A module that takes on a second concern splits into a same-named package in the same layer.

Roles:

- **Harness**: schedules, locks, guards, journals, renders. Runs the overseer once per tick and workers on demand.
- **Overseer**: an agent run with `overseer_cmd`. Reads the world through MCP and the state summary, decides one next
  action per ticket, and acts only through `canopy dispatch`, `canopy decide`, `canopy queried`, `canopy attention`,
  `canopy chore run`, `canopy chore wait` (§19), `canopy review run`, `canopy review wait` (§21), and `canopy mirror`
  (§22). Read-only everywhere else. What it owes every tick is checked when it ends (§6 step 5).
- **Worker**: an agent run with `worker_cmd` in a leased worktree with a task prompt. Writes code, pushes a branch,
  opens or updates a PR, comments on the ticket, prints a result line, exits. Never merges, approves, or moves a ticket
  to Done. A private ticket's worker runs with `private_worker_cmd` and writes nothing to the ticket (§22).
