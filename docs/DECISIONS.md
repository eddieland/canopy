# Decisions

Append-only: a changed choice gets a new entry that supersedes the old one. An entry is a few lines: the decision, the
reason when it is not obvious, and at most a line each for alternatives worth not reconsidering and what would make us
revisit. How a thing works belongs in `DESIGN.md`; the story of a change belongs in its PR.

The log was condensed once, on 2026-10-08, with every number kept. The longer entries are in git history.

## D001. Do not build on Azimuth

New repository, no shared code. Azimuth encoded the workflow in code and never shipped as something a second person
could run; treehouse covers its worktree problems. Salvage ideas, not code.

## D002. treehouse is the worktree pool

Hard dependency on treehouse (pooled worktrees, durable leases, dirty detection, JSON, no daemon), with lease holder
`canopy:<TICKET>`. Worktrees are ephemeral; the pushed branch is the checkpoint.
Revisit: if treehouse's lease semantics change incompatibly.

## D003. Connectivity through the agent runtime's MCP, not harness code

The harness imports no tracker or VCS client and never sees a token; agents reach trackers and GitHub through the
runtime's MCP servers. So the harness cannot verify anything the tracker says, such as who wrote a comment.
Revisit: if the overseer's token cost for reading state dominates; then move polling into Python.

## D004. SQLite journal plus flock, not a stateless overseer

SQLite in WAL mode with numbered migrations, and `flock` around the tick. The journal holds loop facts only; world facts
are re-read every tick. Cursors, attempts, cooldowns, crash detection, and the audit log are queries.
Rejected: state in ticket comments and labels (slow, noisy for teammates, unqueryable).

## D005. Aggressive release of worktrees

A slot is held only while a worker process runs; waiting on CI, review, or a human holds nothing. Workers always push
before release, so build caches must be slot-independent.

## D006. OpenCode as the agent runtime, not Pi

OpenCode has built-in MCP with OAuth (D003), per-agent permissions, and `opencode run --agent`, and the team uses it. Pi
would need an extension for MCP, putting connectivity code back in our hands. The commands are templates (D009), so
another runtime is a config change.

## D007. Python with uv, not Go

Python 3.12+, uv, ruff, pytest, stdlib first: an isolated `uv tool install`, faster iteration, stdlib `sqlite3` and
`tomllib`, and the team's tooling. Type checker: D017.

## D008. Policy in prompts, guards in code

What to do about a ticket lives in `prompts/overseer.md`; what the loop may never do lives in dispatch guards and agent
permissions. The prompt cannot relax a guard, and the `decisions` table is the prompt eval corpus.
Revisit: if prompt behavior proves unstable, move specific rules into code one at a time, each with an entry.

## D009. Runtime abstraction is a command template

No adapter interface: `runtime.*_cmd` are command templates with `{prompt}`, rendered per D023.
Revisit: when a second runtime needs a different invocation or result parsing; then the smallest interface for both.

## D010. Operator identity for the MVP

Everything runs as the operator; no bot account. Agent work is marked by branch prefix, PR label, and commit trailer.
Revisit: when audit or compliance requires a distinct identity.

## D011. `ty` for type checking

Superseded by D017.

## D012. Milestone status lives in ROADMAP.md

Each milestone ends with a `Status:` line; a done one gets a date, `Learned`, and `Next`. No separate status file.

## D013. 120-character line length everywhere

120 columns for every file type; `.editorconfig` is the source of truth and ruff matches it. Narrower text is left
alone rather than reflowed.

## D014. Tracker-agnostic: MCP plus a contract, with optional provider skills

Config names a free-form `tracker.provider` and `tracker.query`; DESIGN §17 is the provider-neutral contract; provider
knowledge goes in optional `tracker-<provider>` skills. The label, not the query, authorizes work, so a vague query
cannot widen scope. Ticket keys are regex-guarded because they reach branch names, paths, and argv.
Revisit: a tracker that needs code gets an entry before the code.

## D015. The subprocess boundary is enforced by lint

ruff's `TID251` bans `subprocess`, `os.system`, and `os.popen` outside `src/canopy/infra/procs.py`, tests included (one
exception, D024). `os.exec*`, `os.spawn*`, and `pty` are not banned yet; widen the list if anything reaches for them.

## D016. Layered config: shared repository file, personal user file

Defaults, then the repository's `canopy.toml` (shared keys only), then `$XDG_CONFIG_HOME/canopy/config.toml`, merged per
key. Keys that run commands, choose prompts, spend, or authorize are user-only, since anyone who can push controls the
committed file; repository `policy.*` may only tighten. `tracker.labels` is user-only because two operators sharing a
label would work the same tickets.
Rejected: a gitignored `canopy.local.toml` (easy to commit by accident).

## D017. `pyrefly` in strict mode is the only type checker

`pyrefly` with `preset = "strict"` over `src`, `tests`, and the extensionless fakes. Supersedes D011: two checkers meant
satisfying both for little extra coverage.
Revisit: if strict mode costs more than it catches; then relax error kinds, not the project.

## D018. ruff selects every stable rule

`select = ["ALL"]` with a commented `ignore` list. Google-style docstrings in `src/`, no relative imports, no preview
rules. Opt out with a commented `ignore` or a `noqa` with a code, never by narrowing `select`; a ruff bump fixes or
ignores what it flags.

## D019. Every test directory is a package

Every directory under `tests/`, the root included, has an `__init__.py` (`INP001`). Without the root one, pytest names
`tests/canopy/` `canopy` and shadows `src/canopy`.
Rejected: `--import-mode=importlib`, which changes how `conftest.py` is imported for no gain.

## D020. The overseer reaches the journal through the CLI, keyed by `CANOPY_TICK_ID`

The tick sets `CANOPY_TICK_ID`, and `dispatch`, `decide`, and `attention` refuse without a running tick, so the journal
holds only what the loop did; `ticket set` uses it only to detect a dry run. Attention items are decisions with action
`attention:<reason>`; the current list is the latest `ok` tick's, so there is no attention table. Dry-run behavior:
D036.

## D021. OpenCode permissions under `opencode run` (the M1 canary)

From OpenCode 1.18.32's source: `opencode run` auto-rejects every `ask`, which ends the turn; `deny` is enforced and the
model continues; the last matching rule wins; bash compound commands are checked per command. So every catch-all `"*"`
comes before its exceptions, and the overseer denies `task`, since subagents run with wider permissions. The opt-in
live canary has a positive control. Permissions are defense in depth, not the boundary.
Revisit: on any OpenCode major version.

## D022. Runtime files are bundled into the wheel

hatch's `force-include` copies `migrations/` and `.agents/` into the wheel under `canopy/_data/`; `resources.py` looks
there, then at the repository root. A new top-level runtime directory needs a `force-include` line.

## D023. Command templates are split into argv; no shell runs

`shlex.split` the template, substitute `{prompt}` (exactly once) inside each word, run the argv. The prompt carries
agent- and ticket-written text, so a shell would be a code execution risk. Templates cannot pipe or redirect; a wrapper
such as a sandbox is a prefix or a script.
Revisit: if a runtime needs the prompt on stdin or in a file, or the prompt nears Linux's 128 KiB argument limit.

## D024. The fake agent may start processes

`tests/fakes/agent` imports `subprocess` with `noqa: TID251`, so a fake overseer runs the real CLI as an agent's bash
tool does. It stands in for an external runtime, not canopy code.

## D025. click for the CLI

`click` over `argparse`: the CLI is the operator's and overseer's surface and grows every milestone. Exit codes: usage
and config errors 2, refusals 1. `decide [KEY] ACTION` parses its positionals by hand, since click has no optional
positional before a required one.

## D026. pydantic for validating config and other programs' output

pydantic v2 for config and for JSON from other programs. Scope and tighten checks stay plain code run per file before
the merge (TRUST_MODEL T7); pydantic validates the merged result.
Rejected: pydantic-settings, whose environment and dotenv sources are the back door T7 closes.

## D027. hypothesis for property tests of validators (dev only)

Dev dependency for property tests of the validators between agent-written text and paths, argv, and prompts, generating
near-valid inputs where anchoring bugs live. Its first run found `$` accepting a trailing newline in keys.

## D028. The harness raises attention for runs; retrying is an authorized reply

Every tick, the harness raises attention for a ticket whose latest run ended crashed, unpushed, unknown, timed out, or
failed. It clears when a newer run starts or the ticket is done; there is no dismiss command. The prompt forbids a
redispatch until an authorized replier comments (TRUST_MODEL T1), and the attempt limit (D030) bounds an overseer that
ignores it.

## D029. `canopy _run` and dispatch details: detached via `python -m canopy`, claimed by pid, serialized by flock

Dispatch spawns `sys.executable -m canopy _run <id>` in a new session; the run is claimed by that pid. Dispatches hold a
`flock` on `dispatch.lock` from guards through spawn, because the SQLite write lock would block every `_run` closing its
row. The worker leads its own process group, which reconcile kills before returning the slot.
Revisit: if pid reuse is ever observed; then compare process start times.

## D030. Attempt limits and the fix-ci cooldown are derived from `runs`; cursors ride on the dispatch

An attempt is a `runs` row of that kind, however it ended. Counts never reset and there is no reset command: the
overseer can run any `canopy` command, and a guard it can reset is not a guard. A human raises a limit in their config.
`--cursor` advances only once the worker starts, so a refused dispatch leaves its trigger for the next tick.
Revisit: if limits routinely hit healthy tickets; then count per PR.

## D031. `--context` is text that points at what to read, not a file and not a quote

`--context TEXT`, at most 2000 characters, points at what the worker should read and never quotes it. A file path could
pull any operator-readable file into a prompt (T6), and quoting invites injection and forged authorization headers.
Every worker prompt names the authorized repliers, and the worker checks authorship itself.

## D032. Attention notifications: an item is its ticket and reason, and is notified once while it stays open

An item is identified by ticket, reason, and repository, so the overseer's rewording does not re-notify. Each sink
tracks what it was sent (D035). A notification goes out when items are new or resolved; only a zero exit within 60
seconds counts as sent, so a failed command is retried.
Revisit: if operators want reminders for long-open items, or routing finer than groups.

## D033. Workspaces: one directory, a repository map, pools inside it

A workspace is a directory with a map, clones, treehouse pools, and state: one queue, one capacity, one journal. A
repository without a map is a workspace of one; the map replaces the repository config layer with the same controls.
Splitting is D061.
Rejected: one loop per repository (two journals would have to agree on one ticket); one pool for every repository (a
pool is how treehouse proves a slot belongs to a clone).

## D034. Chores: recurring agent runs the operator defines and the overseer delegates, reporting to attention

A chore is recurring non-ticket work (such as checking CI health), defined only in the user config. The overseer
decides when; the harness refuses one not due, running, or over `max_chores`. Runs hold no lease and push nothing, the
shipped definition has no write tools, and findings go to attention without informing ticket decisions. Named "chore"
because "task" is OpenCode's subagent tool.
Rejected: cron (no guards, journal, or judgment about when); the overseer checking inline (bash on the agent that
dispatches).

## D035. Notifications: sinks are commands fed by the journal; Slack ships as one sink

A sink is a command that gets one message on stdin at the end of a tick, JSON by default; `notify.cmd` and text sinks
get text. Events and digests are derived from the journal with no model; an outbox with a cursor per sink lets a failing
sink retry alone. The harness makes no network call and holds no secret; the Slack sink is a separate process with its
own webhook file.
Rejected: HTTP or an SDK in the harness (T2); the overseer posting through Slack MCP (an LLM in every delivery);
interactive Slack features (each needs a listener).

## D036. A dry run checks the dispatch guards and changes no loop state the next live tick reads

A dry-run `dispatch` runs the same guards in the same order, counting this tick's dry dispatches as running, but tries
no lease or spawn; a dry-run `ticket set` records phases only. Otherwise a dry tick is a tick, attention included, so
the `decisions` table is a faithful eval corpus.

## D037. A tick-wide skip closes the tick as `skipped`, which leaves the attention list standing

When the overseer records a tick-wide `skip` (tracker or GitHub unreachable), the tick closes `skipped` and exits 1.
The list is the latest `ok` tick's, so an outage does not resolve and re-raise every item.

## D038. Recommend HTTPS remotes; `canopy init` warns about SSH ones and refuses nothing

A sandboxed worker (HOST_ISOLATION) cannot reach the SSH agent socket, so HTTPS is the supported path. `canopy init`
warns about SSH push URLs, rewrites included; nothing else checks the remote.
Revisit: when the sandbox ships.

## D039. Reviews: a fresh reviewer per PR commit that comments as itself, never approves, and needs no ticket

A reviewer run per PR commit posts one comment that identifies itself and ends in a machine-readable verdict marker.
It never submits a PR review, and its definition denies the tools that approve, push, label, or edit; whether low-impact
PRs skip a human is the repository's own automation. The loop knows its reviews from the journal, not the marker.
Rejected: a GitHub review (the tool that comments on lines can approve); a status or label for the verdict (a tool that
sets one can set any).

## D040. Agent runs load canopy's definitions from a directory canopy owns, never from the repository

canopy snapshots its bundled agents and skills into an immutable `<state_dir>/runtime/<digest>/`, and every template
that runs a canopy agent passes it as `OPENCODE_CONFIG_DIR={definitions_dir}`. A missing agent makes OpenCode silently
run its allow-everything default, and repository copies are repository-controlled (T7). The runtime's own skill paths
stay on, so operators and repositories customize with new skill names.
Rejected: `OPENCODE_DISABLE_PROJECT_CONFIG` (blocks the repository's skills and MCP servers).

## D041. Layered subpackages now; a uv workspace when the first separate program lands

`src/canopy` is layered subpackages (`cli`, `loop`, features, `core`, `infra`); imports go down, never between features,
and only `cli` imports click, checked by `tests/canopy/test_layers.py`. Code that runs as its own process and must not
share the harness's imports is a uv workspace member under `packages/`.
Rejected: ruff `TID251` for layers (exemptions are per file, so allowing click would also allow `subprocess`).

## D042. The loop is `canopy loop` in the foreground, not cron or launchd

`canopy loop` runs ticks one after another and waits after each. It is not a daemon: no detaching, pid file, or
self-restart. A scheduler outside canopy cannot read the journal, so it cannot pace ticks by what they cost.
`canopy tick` stays for one tick by hand.

## D043. rich for terminal output

`rich` for the loop's live output (spinner, countdown, color, truncating columns), plain when piped. `curses` loses
scrollback, which is the loop's record, and hand-written ANSI would reimplement terminal detection and redraw.

## D044. Refuse to start an agent where the repository's OpenCode config defines one of canopy's agents

OpenCode deep-merges agent definitions across config directories, keeping the first-loaded key order, so a repository
definition can place a bash `allow` before canopy's rules and loosen them; D040's snapshot alone does not prevent it.
The harness refuses to start an agent whose start directory has a file or JSON config naming one of canopy's agents. It
does not parse JSONC or substitutions, a residual T7 records.

## D045. Stacking checks the base's shape in code; the overseer chooses it from live state every dispatch

`--base` must be `trust.branch_prefix` plus one ref component, so an injected overseer cannot aim a PR at a release
branch. The base is not stored on the ticket: each dispatch chooses it from the live PR state. A retargeted PR merges
the base in; workers never force-push.

## D046. Proprietary for now, installed from git, never from PyPI under this name

Proprietary license; install with `uv tool install git+https://github.com/eddieland/canopy`. `canopy` on PyPI is an
unrelated project, and the `Private :: Do Not Upload` classifier makes PyPI refuse an upload. `make install-check` is
the clean-machine check.
Revisit: before any public release, together with the name.

## D047. The operator's canopy skill is printed by `canopy skill`, and agent runs do not load it

The operator skill lives outside the definitions snapshot and is printed by `canopy skill` for the operator to save.
In the snapshot it would help no run, and a `$HOME` copy would collide with it by name.

## D048. treehouse is pinned to a commit until a release has `base_branch`

`make treehouse` and the README pin treehouse commit `1185dc6`: canopy requires the lease's `base_branch`, which no
release had, so every lease from a release was refused.
Revisit: when a treehouse release includes `base_branch`.

## D049. A second stop signal within one second of the first is the same Ctrl-C

uv forwards the terminal's SIGINT to canopy about 200 ms after canopy got its own, which read as a second Ctrl-C and
aborted the tick. The loop ignores a stop signal less than one second after the first.

## D050. Build canopy rather than adopt Symphony, agent-orchestrator, or Hermes Kanban

None offers what canopy is for: any tracker through MCP with no tracker code, never merging, no daemon, worktrees
released while waiting, and a fresh overseer per tick (survey in `PRIOR_ART.md`). Take their lessons, not their code.

## D051. A dispatch names the queue label it relies on, and the worker checks it again

A live overseer dispatched an unlabeled ticket, so `canopy dispatch` requires `--label`, one of `tracker.labels`, and
every worker prompt starts by checking the ticket's labels and failing without changes if none match. `--label` is a
claim the harness cannot verify (D003); the worker's read is the independent check, and human review is the backstop.

## D052. Until joint runs, a ticket has one repository: the one its first dispatch named

Superseded by D058.

## D053. A workspace's state directory, and any definitions snapshot, must be private to the operator

A workspace's `.canopy/` may sit in a shared checkout, where anyone who can push could plant a journal or a permissive
definitions snapshot. canopy refuses a state directory or snapshot that is a symlink, owned by someone else, or group-
or world-accessible. It checks permissions, not provenance.

## D054. Stacking stays, and the operator controls it through the overseer's policy

`policy.stacking` is `"auto"` (default) or `"never"`, followed by the overseer prompt with no harness guard, at the
operator's choice (REQUIREMENTS C1). Under `"never"`, a blocker has landed only when closed and its PR, if it had one,
merged (D057).
Revisit: if the overseer stacks under `"never"`; then add the guard.

## D055. Listeners are allowed on loopback or a private network, behind the operator's secret

A listener binds to loopback by default or to a private address the operator sets, never a wildcard or public one, and
checks a listener secret from an operator-only file. Whoever holds it acts as the operator; listeners lift no guard.
Revisit: more than one person per machine or listener, or a network the operator does not control.

## D056. A worker may push to the head branch of a PR the operator wrote and labeled

A PR's head branch may be pushed to if the PR is open, not from a fork, authored by the operator, and carries a queue
label. Agents check author and label, as the harness cannot (D003); pushes are never forced.
Rejected: any labeled PR (a label would put commits on a coworker's branch).

## D057. Under `policy.stacking = "never"`, a blocker has landed only when its PR merged

Amends D054's definition: a blocker has landed when it is closed and its PR, if it had one, merged. One whose PR closed
unmerged never landed, and the dependent ticket gets `needs_author`.

## D058. A ticket's work is units, one per repository; a unit may start after another unit's PR merged

A unit is a repository a ticket was dispatched to, with its own PR, phase, cursors, and attempts. Any `implement` may
add one, before or after another unit's PR merged, so a sequenced change is one ticket. At most one unit per repository,
so a follow-up PR is a new ticket.

## D059. One branch per ticket; a desk only for a joint run; `run_slots` holds every run's slots

The first `implement` names the ticket's branch and every later dispatch continues it, so a run has one branch. Only a
joint run gets a desk of worktrees. Every run's slots live in `run_slots`, so code reads one shape.

## D060. Pending migrations wait for runs an earlier canopy started

A detached run from before an upgrade writes the old schema. Migrations apply only when no running run, chore run, or
review run has a live process; until then every command fails naming them. So a migration may drop what an earlier
canopy wrote.

## D061. A ticket over several repositories stays one ticket; the loop splits it only when an authorized replier asks

Supersedes D033's preference for splitting. A multi-repository ticket stays one ticket with a unit per repository. A
split requires `--request <comment id>`, a claim the splitter verifies by reading the comment, and children are created
without the queue label, so a human authorizes each.
Rejected: a split label (another label every tracker needs, which anyone who can label could add).

## D062. A split runs in a desk at the base branches, with its own command, and records only children new to the journal

A split leases a desk like a joint run but checks out base branches, makes no branch, and pushes nothing. It has its own
`runtime.split_cmd` and attempt limit. `_run` records a child only if it is new to the journal and not the parent, so a
steered splitter cannot claim an existing ticket.

## D063. A chore names the workspaces it runs in; by default it runs in every one

Chores come from the user file, which every workspace reads, so a chore may list `workspaces`; with none it runs in
every one.
Rejected: a chore table per workspace (every chore written once per workspace).

## D064. The desktop sink ships inside canopy as a script; the Slack sink stays its own distribution

`canopy-notify-desktop` is a canopy module with its own console script. It holds no secret and needs no network, which
are the reasons the Slack sink is separate.

## D065. The reviewer reads its checkout through a link in a directory of its own; reviews name their repository

The reviewer runs in `<state_dir>/reviews/<id>/`, holding one link to the slot, with `external_directory: deny`, so the
PR supplies no runtime config and the reviewer reads no other files; it still reads the PR and tickets through MCP. A
review leases from its `--repo` pool and counts toward `max_workers`.

## D066. Pool sizes are declared in the user file; `workspace sync` converges on them and on the map

Pool sizes are user-only (`capacity.slots_per_repo`, `repo_slots`), and canopy enforces them itself, since treehouse's
`max_trees` lives only in committed or global files. `workspace sync` converges pools and clones on the map, removing a
clone only when nothing in it would be lost.

## D067. Releases ship one executable per platform, built by CI and copied to the machine that runs canopy

A release is a pex in venv mode inside a scie per platform, with an interpreter and `uv.lock`'s pinned dependencies, so
the machine that runs canopy needs no credential, Python, uv, or network to install it. Built and attached by the tag
workflow.
Rejected: PyInstaller, Nuitka, shiv, zipapp (`sys.executable -m canopy` breaks); PyApp, uvbox (install from the
network).

## D068. The migrations are squashed into one for v0.1, and older journals are not upgraded

`0001_init.sql` creates the v0.1 schema directly. A journal from the old series is not upgraded; the operator moves it
aside. A one-time exception; never edit a shipped migration.

## D069. Workers mark their comments with a configurable prefix and suffix that only take authority away

Everything posts as the operator, so a worker's comment could read back as an authorized reply or review feedback.
Workers mark every comment with `trust.comment_prefix` and `comment_suffix` (user-only); a comment carrying every mark,
outside any quote, is a worker's and is never authority. Forging the marks only silences the forger.
Rejected: an HTML comment marker (trackers such as Jira drop or escape it).

## D070. A merge conflict is a unit's phase, `conflicted`, handled by `resume`

GitHub runs no checks on a conflicting PR, so it read as running or green. `conflicted` is derived before CI and
review, and handled by a `resume` that merges the base in, spending resume attempts.
Rejected: a separate dispatch kind (`resume` already merges the base); rebasing (needs force).

## D071. A run's session and cost are read from OpenCode's JSON events on stdout

The default worker and split templates use `--format json`; `core/agent_output.py` takes the result text, session id,
and summed `step_finish` cost from the events, and reads plain stdout otherwise. One invalid cost drops the whole cost
rather than understating it.
Revisit: when OpenCode changes the event shape, or a second runtime reports these differently.

## D072. The journal holds every ticket's conversation; authority stays with its source

A `messages` table records every ticket's conversation, from workers' results, the operator's channels, and the
overseer's mirror of tracker comments. A private ticket, started with `canopy start`, never writes to the tracker, and
only operator messages authorize it. On a public ticket the mirror authorizes nothing; replies are read live.
Rejected: a shadow ticket in a private tracker (manual copying); the journal as source for public tickets (a steered
overseer could forge a reply).

## D073. The web UI is served by `canopy loop`, from a thread, behind an off switch

`canopy loop` serves the UI from a thread with its own journal connection, writing only through the CLI's functions,
and never ending the loop on failure. Only `src/canopy/serve/` imports the web stack; canopy's own socket ban stays.
Rejected: a separate `canopy serve` (two commands to keep running; the seam keeps it a small change later).

## D074. FastAPI on uvicorn, with Jinja2 templates, for the web UI

`fastapi` (validates with pydantic, D026), pure-Python `uvicorn` in a thread, `jinja2` with autoescaping,
`python-multipart`; `httpx` dev only. stdlib `http.server` would leave routing, form parsing, and escaping to canopy, in
the one package that faces a browser. Added in M20.

## D075. The operator's commands are top-level verbs that take a reference to any subject

`canopy start`, `stop`, `reply`, and `show` take a `REF` whose shape names its kind (ticket key, PR, `chore:NAME`,
`run:ID`); a kind refuses a verb it does not support. Messages and start records are keyed by subject.
Rejected: verbs under a noun per kind (one verb learned per kind, a command group per new kind).

## D076. Private tickets and the web UI ship without sandboxing or TLS

The operator judged the residuals low (2026-10-08): an unsandboxed worker can forge `canopy reply` or reach the tracker
through the operator's own tools, and the UI on a private address serves plain HTTP. Guards cannot contain a capable
agent running as the operator; what matters is limiting the untrusted text agents act on (T1). M18 does not wait for
sandboxing.
Revisit: with D055's revisit, or after an incident where a run wrote outside its run or posted to a private ticket.

## D077. No agent has web tools

Every canopy definition (overseer, worker, reviewer, splitter, chore) denies `webfetch`, `websearch`, and
`codesearch`, as scalars a repository's config cannot loosen (D044); `tests/canopy/test_definitions.py` checks each.
Web pages and search results are untrusted text an agent picks up on its own, and keeping that text out is the defense
that matters (D076). A worker's bash still reaches the network, a residual T1 names.
Rejected: denying them for the overseer only (workers read the same client-written tickets and look things up most).
Revisit: when workers are sandboxed with egress controls (HOST_ISOLATION), or if missing lookups measurably hurt runs.

## D078. Workers open PRs with the operator's skill when `runtime.pr_skill` names one

Some operators must open PRs with their employer's tooling, and a skill alone cannot override the prompt's "through
the GitHub MCP". `runtime.pr_skill` (user-only) names a skill that `implement` and `resume` workers open PRs with and
nothing else; a missing skill fails the run rather than falling back to the MCP. With it set, an override without
`{{OPEN_PR}}` is `bad_prompt`, as D051 does for `{{LABELS}}`.
Rejected: a skill alone (prompt and skill disagree); a harness command that opens PRs (VCS knowledge in code, D014).
Revisit: if other single steps need the operator's own tooling; then generalize rather than add keys one by one.

## D079. The web UI is a single-page app built from `ui/`; FastAPI serves it and its API

Supersedes D074's templates: a richer surface (live SSE updates without polling, route transitions, two themes) built
by agents one feature at a time needs a client framework and a base that keeps them consistent. `ui/` is Vite, React
with the React Compiler, TypeScript, Tailwind, shadcn/ui, TanStack Router and Query, pinned exactly; its types are
generated from FastAPI's OpenAPI schema. FastAPI and uvicorn stay; `jinja2` and `python-multipart` are not added, and
`httpx2` replaces the deprecated `httpx` for tests. The wheel's build hook builds the app when npm is on PATH, so
operators never need Node; contributors do (`make check` runs the UI's checks). Rules: `ui/AGENTS.md`, `ui/DESIGN.md`.
Rejected: Jinja2 with htmx (per-page script is where agent-built features drift); committing the build (minified
diffs); building at install (Node for every operator); server rendering (a second runtime).
Revisit: if the UI shrinks to pages a template would serve, or Node costs the toolchain more than it saves.

## D080. The private worker is a template and a definition of its own, rendered with the tracker's server and tools

`runtime.private_worker_cmd` runs `canopy-worker-private`, as `split_cmd` runs the splitter: no new placeholder, and an
operator can point it at a different runtime. The definition is rendered into the snapshot from `tracker.mcp_server`
and `tracker.read_tools` (user-only, with defaults per shipped provider): `"<server>_*": deny`, then each tool allowed
by name, so an unlisted write tool fails closed. The server name is a key of its own because OpenCode prefixes tools
with the name the operator's config gives the server, which canopy cannot read.
Rejected: an `{agent}` placeholder in `worker_cmd` (every existing template would need it); denying write tools by
name pattern, as the splitter does (a write tool with an unexpected name stays open); no tracker server at all (the
worker could not read the ticket, and `--context` holds 2000 characters).
Revisit: if a tracker's server multiplexes reads and writes through one tool, as Atlassian's `execute` does, and its
read-only tools stop covering what workers need.

## D081. The overseer mirrors tracker comments through a quoted heredoc with a per-tick random delimiter

`canopy mirror` is the first command that carries untrusted text, so the overseer passes a comment's body on stdin in
a quoted heredoc, which the shell does not expand, and the state block gives a delimiter drawn fresh each tick, so no
comment can be written to end the heredoc and run the lines after it. The harness reads the workers' marks (D069) in
code to record a comment's source, and bounds a tick to 100 mirrors, counted from its `mirror` decisions.
Rejected: the body as a quoted argument (one missed escape runs the text); a fixed delimiter (a comment can contain
it); the overseer saying which comments are workers' (a judgment code can make).
Revisit: if the agent runtime gains a way to pass a tool's text to a command without a shell.

## D082. The browser signs in once with the listener secret and keeps a cookie signed with it

The web UI's sign-in page takes the listener secret from the operator, who pastes it or lets a password manager fill
it, and sets an `HttpOnly`, `SameSite=Strict` cookie: an issue time and a nonce, HMAC-signed with the secret, good for
30 days. Writes add a per-session token derived the same way. The server keeps no sessions, so a loop restart signs
no one out, and `canopy secret --rotate` signs everyone out.
Rejected: a one-time link the loop prints (good once, for one browser, and only while that loop runs); the secret
kept by the page and sent on every request (any script on the page could read it, and `EventSource` sends no
headers); server-side sessions (lost on every restart, with nothing gained over a signed cookie for one operator).
Revisit: with D055's revisit, when more than one person signs in, or if sessions must be ended one at a time.

## D083. The loop paces idle ticks from the journal, not by checking the world for changes first

A tick whose overseer run finds nothing new is waste however little it cost, so `canopy loop` doubles its wait after
each idle tick in a row, up to `loop.idle_max_minutes`, and wakes early on the events it can see itself: an operator
message, or a run, chore run, or review run ending (DESIGN §6). Idleness is read from what the tick recorded: its
status, decisions, attention list, tickets and units, and runs. The harness still cannot see the world between ticks
(D003), so a teammate's comment waits for the next tick, up to the cap.
Rejected: polling GitHub or the tracker in Python to skip unchanged ticks (a VCS client in the harness, D003); a
cheaper pre-check agent each tick (still an LLM call per tick, and a second prompt's judgment gating the first's);
quiet hours in config (a guess at when teammates work, wrong across time zones, where backoff learns it); pacing by
cost alone (M13; a cheap tick that finds nothing is still not worth running); webhooks (deferred; a listener, T8).
Revisit: if the cap's latency on teammates' comments or CI is felt; then quiet hours, or D003's own revisit.

## D084. Workers set labels through the tracker's MCP edit tool, and deny dangerous MCP tools by name

Labels landed only when a worker reached for `gh`, which is GitHub-only and not on every machine. Ticket labels are set
with the tracker's issue edit tool, passing only labels; the PR label only where a GitHub tool sets labels, since
GitHub's one such tool, `issue_write`, also creates and closes issues, and granting it is the operator's call.
`canopy-worker` and `canopy-worker-private` deny merging, review submission, closing, transitions, ticket creation, API
file and branch writes, deletes, forks, Copilot agents, and workflow runs by tool name; `test_definitions.py` checks.
Label writes replace the whole set, so skills read it right before writing. Names differ by server: defense in depth.
Rejected: `gh ... --add-label` (GitHub-only, a credential the runtime does not hold); allowing `issue_write` by default
(permissions match names, not arguments); the harness setting labels (no tracker code, D003, D014).
Revisit: when GitHub's server gains a label-only tool, or a deny is found not to apply to MCP tools.

## D085. canopy's version is built from the latest `v*` tag with uv-dynamic-versioning

Pushing a `v*` tag is the whole release step (D067): no commit bumps a version first, so the tag and the version
cannot disagree. Between tags a build names its distance and commit (`0.2.1.dev3+1a2b3c4`), so `canopy --version` says
which build is running. `uv-dynamic-versioning` is a build-time dependency only, pinned in `build-system.requires`;
stdlib cannot supply a hatchling version source. canopy-notify-slack keeps its static version for now.
Rejected: a static version with a CI check that the tag matches it (a release takes a commit and a tag that must
agree); hatch-vcs (pulls in setuptools-scm and setuptools for the same result).
Revisit: if a build that matters runs without the repository's tags, as a shallow clone does.

## D086. `canopy forget` clears a ticket's branch and units and marks a boundary; it keeps every run

The operator can have canopy forget a ticket's work so its next implement starts over (DESIGN §22). It clears the
branch, units, and phases, and records the ticket's newest run and message, which the loop's reads then skip; it deletes
no run and no message. Runs stay because the attempt limits and the cooldown are derived from them (D030): a forget that
reset them would be the reset command D030 rules out. It is the operator's only, like `start` (T1), and it closes no PR
and deletes no branch: canopy reaches GitHub only through agents (D003), and never closes a PR.
Rejected: deleting the ticket's rows (loses the history `show` and the decisions corpus read, and resets attempts);
clearing the comment cursor too (handled comments would read as new); a forget the overseer can call.
Revisit: if operators routinely raise a limit just to start a forgotten ticket over; then count attempts per branch.

## D087. `canopy init` writes only keys whose default does not serve

A default written into a config file is pinned there: when canopy changes it (as the agent templates did for
`{definitions_dir}`, D040, and for the overseer's `--format json`), every file init wrote keeps the old value. So the
user file gets the queue label and an empty `trust.authorized_repliers` to fill in; `canopy.toml` and
`canopy-workspace.toml` get the provider and a query. `examples/config.toml` documents every key.
Rejected: writing every key the operator might tune, commented or not (they go stale, and read as choices to make).
Revisit: if operators routinely miss a key they needed to change; then print it from init instead of writing it.

## D088. A key at the loop's countdown ticks now, with no one-minute floor

An operator who wants a tick sooner can press `t` during the wait rather than open a second terminal for `canopy tick`.
It skips `repeat.WAKE_MIN_SECONDS`, which exists so messages arriving in a burst cannot make the loop spin; a keypress
is a deliberate request for exactly one tick, as `canopy tick` by hand already is, and every hard guard still holds.
Keys come from the terminal in cbreak mode through stdlib `termios`; keys typed during a tick are dropped.
Rejected: a full-screen TUI library (a new dependency for one key); a key that also aborts or skips a running tick.

## D089. Untrusted reviewers wait for the operator's go-ahead, given with `canopy reply` on any ticket

A review bot's comment resumed a ticket as `changes_requested` (M3's live check), and the operator wants only reviewers
they trust to start a fixup. `trust.trusted_reviewers` (user-only, empty by default) lists them by VCS host login, with
`canopy:review` for canopy's own reviewer, which posts as the operator. Anyone else's feedback is `untrusted_review` on
the attention list until the operator answers in canopy, with `canopy reply` or the web UI, which now take a public
ticket the journal has. The answer is the worker's instruction ("use your best judgement on the bot's review"); the
review stays data. The overseer gates it and the resume worker checks again, both by prompt: the harness cannot read a
comment's author (D003). The operator chose the empty default, the reply channel, and the configurable entry for
canopy's reviewer.
Rejected: a list of untrusted reviewers (a new bot would be trusted until noticed); defaulting to everyone (today's
behavior, but a bot's comments steer workers until the operator acts); the go-ahead as a ticket comment by an authorized
replier (public on the ticket, a Jira account where the reviewer is a GitHub login, and no web UI path); a harness
guard on resume (it cannot see whose comments a run addresses).
Revisit: if the overseer is found dispatching for untrusted feedback without a go-ahead; then a `--review-from` claim
on `canopy dispatch` checked against the list, as `--label` is (D051).

## D090. The worktrees page reads treehouse when asked, not from the journal or the event stream

The web UI's worktrees page shows each pool's slots: what holds each, its branch, and the processes in it. The server
runs `treehouse status --json` once per pool on each `GET /api/worktrees`, through `procs` like every other process,
and matches leases to running runs and reviews by lease id (DESIGN §22). The UI reads it again when a `runs.updated`
event changes which running runs hold which worktrees, and when the operator asks; nothing polls. The pools are read
at once, a thread each. A read takes the pool's state lock, as reconcile's do, so a slow one briefly holds up a lease.
Rejected: a snapshot the tick writes to the journal (a new table and migration, and as stale as the last tick, which
idle pacing stretches to two hours, D083); `treehouse status` on the event stream (once a second per pool per open
page, and a slow pool would stall every stream); only the journal's `run_slots` (no branch, no processes, nothing about
slots canopy does not hold).
Revisit: if `treehouse status` turns out slow enough on a large pool that opening the page is felt, or if treehouse
gains a way to be told of changes.

## D091. The worktrees page also reads the pools every 30 seconds while it is open

D090's triggers miss what never reaches the journal: processes starting and stopping in a slot, a slot going dirty, a
shell opened in one, a review starting or ending, and the slots `canopy workspace sync` adds or removes. They also fire
too early for a new run, whose refresh comes as it is recorded, before its worker has checked out its branch. So the
worktrees query refetches every 30 seconds while a page shows it and its tab is visible; it is the UI's one
`refetchInterval`. Each refetch is one `treehouse status` per pool, which takes each pool's lock (D090).
Rejected: the event stream reading treehouse on a slower cadence (every open stream, any page, pays for it, and a slow
pool stalls the stream); a shorter interval (more lock time for a page that is read, not watched); manual reads only
(the operator asked for it).
Revisit: if the lock time shows up in leases, or if treehouse gains a way to be told of changes.

## D092. `make test` runs the suite in parallel with pytest-xdist

The suite took about 200s serially on four cores, most of it waiting on fake agent and treehouse processes rather than
on the CPU; `-n auto` brings it to about 60s with the same results. The fixtures were already hermetic (every state
file, HOME and git config under `tmp_path`, the one live server on port 0), so no test changed. stdlib has nothing
that distributes pytest tests; a hand-rolled split by file would balance worse and need its own reporting. `-n auto`
is in `make test`, not `addopts`, so `uv run pytest` on one test stays serial and works under a debugger.
Rejected: `--dist worksteal` (no faster here); `addopts = "-n auto"` (pays worker startup on every single-test run).
Revisit: if a test needs shared state across processes; then give it an xdist group, never a serial-only suite.
