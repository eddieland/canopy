# canopy design

Normative. Code follows the design; a change to something the design states changes it in the same PR. The rationale
for a behavior lives in the design, next to it. `DECISIONS.md` holds only the decisions every developer must know:
cross-cutting constraints, trust-boundary rules, and runtime dependencies.

## What belongs here

The design is a map of canopy, not a specification of every behavior. It says what each part does, what it promises,
and why, so that someone can rely on it or change it without breaking a promise. The code is the specification of how.

A statement belongs here only if it is one of:

- a promise someone outside the code relies on: what the operator, the overseer, a worker, or a coworker sees and may
  do;
- a guard or invariant the harness enforces, or a contract between parts: a result line, the state block, a pool, a
  channel;
- the reason for one of those, in a sentence, and an alternative rejected for it, in a line, only where it would
  otherwise be proposed again.

Everything else is cut on sight, by the author or the reviewer:

- how the code does it: procedures step by step, modules, functions, tables and columns, field order, algorithms,
  error messages, timeouts and limits the operator never sets, which test enforces what. The code and its comments
  hold it; §5 maps packages, not modules;
- every command flag, config key, and output line. `--help`, `examples/config.toml`, and the tests hold them; the design
  names a key only where a behavior turns on it;
- edge cases, unless one is itself a promise;
- measurements: `MEASUREMENTS.md`, cited here by date only where a finding is the reason for a behavior;
- history: how a behavior came to be, the bug that prompted it, the milestone that built it. The PR and `roadmap/` hold
  it, and headings carry no milestone numbers;
- what a prompt tells an agent beyond what the harness checks: the prompt;
- what a third-party tool does: a comment where canopy depends on it, or a measurement;
- the web UI's pages: `ui/DESIGN.md` and the guide.

The default for a PR is no design change. A new feature gets a few sentences in the section it belongs to, or a short
new section; a fix or a refactor edits the design only when it changes a promise. Prefer changing a sentence to adding
one, and delete what the change makes stale. A numbered section past about 100 lines is due a prune: the PR that would
grow it prunes it instead. A detail that turns out to matter can be added later; one that does not costs every reader,
and every later change has to keep it in step.

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
  - [23. Flaky CI](FLAKY_CI.md#23-flaky-ci)
- [Sandboxed runs](SANDBOXING.md): the opt-in OS sandbox around every agent run but the overseer's.
  - [24. Sandboxed runs](SANDBOXING.md#24-sandboxed-runs)
- [Plans](PLANNING.md): a plan for a ticket, approved by the operator before any `implement`.
  - [25. Plans before implementing](PLANNING.md#25-plans-before-implementing)
- [Garbage collection](GARBAGE_COLLECTION.md): what canopy removes of its own history and caches, and what it keeps.
  - [26. Garbage collection](GARBAGE_COLLECTION.md#26-garbage-collection)
- [The overseer's tools](OVERSEER_TOOLS.md): the MCP tools canopy serves the overseer, in place of the CLI.
  - [27. The overseer's tools](OVERSEER_TOOLS.md#27-the-overseers-tools)
- [Agent memory](MEMORY.md): what workers record of what they learn, who reads it, and who decides.
  - [28. Agent memory](MEMORY.md#28-agent-memory)
- [Review replies](REVIEW_REPLIES.md): replies to coworkers' review comments that workers draft and the operator
  sends.
  - [29. Review replies the operator sends](REVIEW_REPLIES.md#29-review-replies-the-operator-sends)
- [Connectors](CONNECTORS.md): the programs that read the tracker and GitHub into the journal, and the phases canopy
  derives from them beside the overseer's.
  - [30. Connectors](CONNECTORS.md#30-connectors)
- [Personas](PERSONAS.md): the voice a planner, a reviewer, or a worker writes in, and who chooses it.
  - [31. Personas](PERSONAS.md#31-personas)
- [Feedback plans](FEEDBACK_PLANS.md): a plan for what comes back to a PR, approved by the operator before the
  `resume` that acts on it.
  - [32. Plans before feedback runs](FEEDBACK_PLANS.md#32-plans-before-feedback-runs)
- [A clock for running agents](CLOCK.md): the minutes left, told to a running agent near its timeout.
  - [33. A clock for running agents](CLOCK.md#33-a-clock-for-running-agents)
- [Published reviews](PUBLISHED_REVIEWS.md): a review of a PR the loop does not own, revised in canopy and published
  as the operator's comment review.
  - [34. Publishing a review](PUBLISHED_REVIEWS.md#34-publishing-a-review)
- [The overseer reads the journal](READING_THE_JOURNAL.md): the overseer deciding from what the connectors observed,
  and the harness checking in code what was its word.
  - [35. The overseer reads the journal](READING_THE_JOURNAL.md#35-the-overseer-reads-the-journal)
- [One-off tasks](TASKS.md): work the operator hands canopy in their own words, about no ticket.
  - [36. One-off tasks](TASKS.md#36-one-off-tasks)
- [The harness decides](HARNESS_DECIDES.md): the decisions the harness records in code before the overseer runs, and
  what it leaves to judgment.
  - [37. The harness decides what needs no judgment](HARNESS_DECIDES.md#37-the-harness-decides-what-needs-no-judgment)
- [Artifacts](ARTIFACTS.md): pages workers publish, the comments people leave on them, and how those come back.
  - [38. Artifacts and Louvre](ARTIFACTS.md#38-artifacts-and-louvre)

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
the features, `runs`, `setup`, `chores`, `notify`, `reviews`, `memory`, and `serve`; `core`; `runtime`; `infra`. A
module imports from its own package and lower layers only. Features never import each other; what two share moves down
a layer. `tests/canopy/test_layers.py` enforces this and fails on a module outside the packages it lists.

```text
canopy (harness, Python)
  __main__.py  python -m canopy, how dispatch starts _run from the same installation
  cli/         the command line; only cli imports click, and only __main__ imports cli
  loop/        the tick (§6) and canopy loop, which drive the features below; the state block; the attention list;
               the overseer's verbs, which its commands and its MCP server share (§27)
  runs/        worker runs on tickets (§8) and the operator's tasks (§36): guards, leases, the detached _run and
               _task, reconcile
  chores/      the operator's recurring chores (§19)
  notify/      notification sinks (§20)
  reviews/     adversarial reviews of PRs (§21)
  memory/      agent memory's feature (§28): proposals' expiry and its attention items
  serve/       the web UI's server (§22, D079); the only package that imports fastapi, starlette, uvicorn, or anyio
  setup/       canopy init, the sandbox's setup, and workspace sync (§18, §24)
  core/        what every feature shares: config, the Context, the journal and its typed rows, vocabularies, contracts,
               conversations, pools
  runtime/     all canopy knows of the agent runtime (§13, D009): a surface that names no runtime, and behind it,
               bound in one module, OpenCode's events, definitions' format, and config files; nothing about tickets
  infra/       plumbing that knows nothing about tickets or agents; procs.py is the only module that runs subprocesses
```

```text
prompts/         the overseer's, workers', and the reviewer's prompts
personas/        the voices a planner, a reviewer, or a worker writes in (§31), `canopy.md` among them
agents/          agent definitions in the runtime's format, one per kind of run
skills/          tracker-<provider>/: optional per-tracker guides (§17)
operator-skill/  SKILL.md: the canopy skill, for the operator's own agent sessions (§13); agent runs never load it
migrations/      NNNN_name.sql
packages/        uv workspace members: separate programs canopy ships, run only as commands, such as the Slack sink
                 (§20) and the sandbox wrapper (§24)
ui/              the web UI (D079): a Vite and React app, its own rules in ui/AGENTS.md and ui/DESIGN.md
```

`prompts/`, `personas/`, `agents/`, `skills/`, and `operator-skill/` live under `.agents/` in this repository; the
wheel bundles them with `migrations/` and the built UI. canopy installs from git with `uv tool install` (D046), which
puts `canopy` and every workspace member's script on `PATH`. Dispatch, chores, and reviews start their detached
processes via `sys.executable -m canopy`, so whatever runs canopy must be an interpreter that imports it.

Where later work goes:

- A feature is a features-layer package plus a `cli/` command module; `loop` calls its reconcile and publish steps and
  its state block part. Deleting a feature deletes those three.
- A feature others write to keeps its writing half in `core`, as §20's events go through `core.outbox`.
- A command imports only what it needs, and `cli/common.py` imports nothing from `loop`: the overseer and workers run
  `canopy` many times a tick, and each process pays for every module it imports.
- Code that runs in its own process and must not share the harness's dependencies is a uv workspace member under
  `packages/`, run only as a command.
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
