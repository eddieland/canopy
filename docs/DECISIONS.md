# Decisions

Append-only: a changed choice gets a new entry that supersedes the old one. Keep entries short: the decision, the
reason when it is not obvious, alternatives worth not reconsidering, and what would make us revisit. How a thing works
belongs in `DESIGN.md`.

## D001. Do not build on Azimuth

Decision: new repository, no shared code. Azimuth encoded the workflow in code and never shipped as something a second
person could run; treehouse covers its worktree problems.
Revisit: never; salvage ideas, not code.

## D002. treehouse is the worktree pool

Decision: hard dependency on treehouse (pooled worktrees, durable leases, dirty detection, JSON output, no daemon).
canopy uses `status --json`, `get --lease --json`, and `return --force --if-lease-id --if-lease-holder`, with lease
holder `canopy:<TICKET>`.
Consequences: worktrees are ephemeral; the pushed branch is the checkpoint.
Revisit: if treehouse's lease semantics change incompatibly.

## D003. Connectivity through the agent runtime's MCP, not harness code

Decision: the harness imports no tracker or VCS client and never sees a token. Trackers and GitHub are reached through
the runtime's MCP servers; tracker specifics are prompt and config.
Consequences: only agents read tracker and PR state; the overseer does it each tick, guided by journal cursors. The
harness cannot verify anything the tracker says, such as who wrote a comment or when a label was added.
Revisit: if the overseer's token cost for reading state dominates, or MCP auth from a script becomes trivial. Then move
polling into Python.

## D004. SQLite journal plus flock, not a stateless overseer

Decision: SQLite in WAL mode with numbered migrations, and `flock` around the tick. The journal holds loop facts only;
world facts are re-read every tick.
Consequences: cursors, attempts, cooldowns, crash detection, and the audit log are queries.
Rejected: a stateless overseer keeping state in ticket comments and labels (slow, noisy for teammates, unqueryable).
Revisit: multi-machine operation (not planned).

## D005. Aggressive release of worktrees

Decision: a slot is held only while a worker process runs. Waiting on CI, review, or a human holds nothing. Workers push
before release, always.
Consequences: reacquisition lands on any slot, so build caches must be slot-independent (the repository's concern).
Revisit: if reacquisition cost is measured to exceed the capacity gained.

## D006. OpenCode as the agent runtime, not Pi

Decision: OpenCode. It has built-in MCP with OAuth (which D003 relies on), per-agent tool permissions, and
`opencode run --agent`, which is all the pluggability canopy needs. The team already uses it. Pi would need an
extension for MCP, putting connectivity code back in our hands, and its richer extension API is for changing the agent
from inside, which canopy does not do.
Consequences: `overseer_cmd` and `worker_cmd` default to OpenCode, but they are templates (D009), so another runtime is
a config change. Agent permissions are defense in depth, not the boundary (D021).
Revisit: if we want the loop inside the agent process (firstmate's shape, rejected in favor of orchestrating from
outside).

## D007. Python with uv, not Go

Decision: Python 3.12+, uv, ruff, pytest, stdlib first. Go would match treehouse's single binary, but Python gives an
isolated `uv tool install`, faster iteration, stdlib `sqlite3` and `tomllib`, and matches team tooling. Type checker:
D017.
Revisit: if installation friction on coworker machines shows up in M5.

## D008. Policy in prompts, guards in code

Decision: what to do about a ticket lives in `prompts/overseer.md`. What the loop may never do lives in `dispatch.py`
guards and agent permissions. The `decisions` table is the prompt eval corpus.
Consequences: a new capability is a tool plus a paragraph. The prompt cannot relax a guard.
Revisit: if prompt behavior proves too unstable, move specific phase rules into code one at a time, each with an entry
here.

## D009. Runtime abstraction is a command template

Decision: no adapter interface. `runtime.overseer_cmd` and `runtime.worker_cmd` are command templates with `{prompt}`,
rendered per D023.
Revisit: when a second runtime needs a different invocation or result parsing. Then introduce the smallest interface
that covers both.

## D010. Operator identity for the MVP

Decision: everything runs as the operator; no bot account. Agent work is marked by branch prefix, PR label, and commit
trailer.
Consequences: no org approval needed; audit is the local journal plus those markers.
Revisit: when audit or compliance requires a distinct identity.

## D011. `ty` for type checking

Superseded by D017.

## D012. Milestone status lives in ROADMAP.md

Decision: each milestone in `ROADMAP.md` ends with a `Status:` line; a done milestone gets a date, `Learned`, and
`Next`. No separate status file.
Revisit: if status notes grow long enough to crowd out the plan.

## D013. 120-character line length everywhere

Decision: 120 columns for every file type. `.editorconfig` is the source of truth; ruff's `line-length` matches. Text
wrapped narrower is left alone rather than reflowed.
Revisit: if a tool we adopt cannot be configured to 120.

## D014. Tracker-agnostic: MCP plus a contract, with optional provider skills

Decision: the harness stays tracker-blind. Config names a free-form `tracker.provider` and a `tracker.query` in the
tracker's own syntax or plain language. DESIGN §17 is the provider-neutral contract. Per-provider knowledge goes in
optional `tracker-<provider>` skills (shipped for `jira` and `github`). No adapter interface.
Consequences: a new tracker is config, plus a skill if agents misread it. The label, not the query, authorizes work, so
a vague query cannot widen scope. Ticket keys are regex-guarded in the CLI because they reach branch names, paths, and
argv.
Revisit: if the `decisions` table shows agents ignoring skills (then inline the skill into the rendered prompt). A
tracker that needs code gets an entry here before the code.

## D015. The subprocess boundary is enforced by lint

Decision: ruff's banned-api rule (`TID251`) bans `subprocess`, `os.system`, and `os.popen` outside
`src/canopy/procs.py`, tests included (one exception, D024). The fakes are linted through `extend-include`.
Consequences: `os.exec*`, `os.spawn*`, and `pty` are not banned yet.
Revisit: widen the banned list if anything reaches for another way to start processes.

## D016. Layered config: shared repository file, personal user file

Context: the queue label must be personal, since guards see only the local journal and two operators sharing a label
would work the same tickets. A committed file can be changed by anyone who can push.
Decision: built-in defaults, then the repository's `canopy.toml` (committed, shared keys only), then
`$XDG_CONFIG_HOME/canopy/config.toml`, merged per key. Every key is shared or user-only (DESIGN §12); a user-only key
in the repository file is an error. Keys that run commands, choose prompts, spend, or authorize are user-only.
Repository `policy.*` may only tighten. `tracker.labels` is a required, user-only list.
Consequences: operators must choose distinct labels; canopy cannot check that.
Rejected: a gitignored `canopy.local.toml` (easy to commit by accident); a shared label with an assignee filter in the
query (the query does not authorize, D014).
Revisit: when one operator needs different labels or state per repository (D033), or a team wants a shared
authorized-replier list.

## D017. `pyrefly` in strict mode is the only type checker

Decision: `pyrefly` with `preset = "strict"`, covering `src`, `tests`, and the extensionless fakes
(`project-includes`). Supersedes D011 and the `ty` in D007: two checkers meant satisfying both for little extra
coverage.
Revisit: if strict mode forces suppressions on correct code often enough to cost more than it catches; then relax the
offending error kinds, not the whole project.

## D018. ruff selects every stable rule

Decision: `select = ["ALL"]` with a commented `ignore` list and per-file ignores for tests and fakes. Google-style
docstrings in `src/`; tests need none. No relative imports. Preview rules off. ruff floor 0.16.
Consequences: a ruff bump can add rules; `uv.lock` pins the version, so the bump PR fixes or ignores (with a reason)
what it flags. Opt out with a commented `ignore` entry or a `noqa` with a code, never by narrowing `select`.
Revisit: if the ignore list outgrows one screen, or ruff bumps routinely cost more than they catch.

## D019. Every test directory is a package

Decision: every directory under `tests/`, the root included, has an `__init__.py`; `INP001` enforces it. Without the
root one, pytest's default import mode names `tests/canopy/` `canopy` and shadows `src/canopy`.
Rejected: `--import-mode=importlib`, which changes how `conftest.py` and helpers are imported for no gain.
Revisit: if pytest's default import mode changes.

## D020. The overseer reaches the journal through the CLI, keyed by `CANOPY_TICK_ID`

Decision: the tick sets `CANOPY_TICK_ID` in the overseer's environment. `dispatch`, `decide`, and `attention` refuse
without it or when it names a tick that is not `running`; `ticket set` uses it only to detect a dry run. Attention items
are decisions with action `attention:<reason>`; the current list is the latest `ok` tick's. In a dry run, `dispatch`
records `dispatch:<kind>` and starts nothing, and `ticket set` records phases but not cursors.
Consequences: no attention table. Commands run by hand outside a tick are refused, so the journal holds only what the
loop did.
Revisit: if the runtime stops passing the environment to its bash tool (then a `--tick` flag), or attention items need
state that survives a failed overseer run (then a table).

## D021. OpenCode permissions under `opencode run` (the M1 canary)

Finding, from OpenCode 1.18.32's source: `opencode run` auto-rejects every `ask` (unless `--auto` or
`--dangerously-skip-permissions`), and the rejection ends the turn. `deny` is enforced; the model sees an error and
continues. The last matching rule wins. Bash compound commands are checked per command. `permission:` replaces the
deprecated `tools:` frontmatter. Project agents load from `.opencode/agent/`, skills from `.opencode/skill/<name>/`.
Decision: every catch-all `"*"` comes before its exceptions. The overseer denies `task`, since subagents run with wider
permissions. `canopy init` installs to `.opencode/agent/` and `.opencode/skill/`. The live canary
(`tests/canopy/test_opencode_canary.py`, opt-in with `CANOPY_OPENCODE_CANARY=1`) has a positive control, so a model
that does nothing cannot pass.
Consequences: `ask` never hangs a tick; it is a deny that also stops the turn. Permissions stay defense in depth.
Revisit: after the first live canary run (record the result in a new entry), and on any OpenCode major version.

## D022. Runtime files are bundled into the wheel

Decision: hatch's `force-include` copies `migrations/` and `.agents/` into the wheel under `canopy/_data/`.
`resources.py` looks there first, then at the repository root.
Consequences: a new top-level runtime directory needs a `force-include` line.
Revisit: if moving the directories under `src/canopy/` becomes simpler than the two lookups.

## D023. Command templates are split into argv; no shell runs

Decision: `shlex.split` the template, replace `{prompt}` inside each word, and run the argv directly. `{prompt}` must
appear exactly once. The prompt carries agent- and ticket-written text, so shell quoting would be a code execution
risk.
Consequences: the prompt is always one argument. Templates cannot use pipes, redirection, or `$VAR`; a wrapper such as a
sandbox is a prefix or a script. Linux caps one argument at 128 KiB.
Revisit: if a runtime needs the prompt on stdin or in a file, or the prompt nears the argument limit.

## D024. The fake agent may start processes

Decision: `tests/fakes/agent` imports `subprocess` with `noqa: TID251`, so a fake overseer runs the real CLI in
separate processes, as an agent's bash tool does. It stands in for an external runtime, not canopy code.
Revisit: if a second fake needs the same, move the exception to `per-file-ignores` for `tests/fakes/`.

## D025. click for the CLI

Decision: `click` instead of `argparse`; the CLI is the operator's and overseer's surface and grows every milestone.
`cli.main` runs the group non-standalone and returns an exit code: usage errors 2, refusals (`CliError`) 1, config and
migration errors 2. Keys, reasons, cursors, and journal text are click parameter types. `decide [KEY] ACTION` parses
its positionals by hand, because the overseer prompt uses that syntax and click has no optional positional before a
required one.
Revisit: if click's typing forces suppressions under pyrefly strict.

## D026. pydantic for validating config and other programs' output

Decision: pydantic v2 for config and for JSON from other programs (treehouse, worker results). Config fields carry
scope and tighten direction as `Annotated` metadata; `Strict*` types reject coercion. Scope and tighten checks stay
plain code run per file before the merge (TRUST_MODEL T7); pydantic validates the merged result, and errors map back to
their file. treehouse models ignore unknown fields. Supersedes "stdlib only" in D016.
Consequences: pydantic-core is a compiled wheel; M5's clean-machine install must cover it.
Rejected: pydantic-settings, whose environment and dotenv sources are the back door T7 closes.
Revisit: if the compiled dependency causes install friction on a coworker machine.

## D027. hypothesis for property tests of validators (dev only)

Decision: `hypothesis` as a dev dependency, for property tests in `tests/canopy/test_properties.py` of the validators
between agent-written text and paths, argv, and prompts. Strategies generate near-valid inputs (a valid value with junk
around it), where anchoring bugs live. The first run found `$` accepting a trailing newline in keys; fixed with
`fullmatch`.
Revisit: if suite runtime becomes a problem; lower `max_examples` before dropping tests.

## D028. The harness raises attention for runs; retrying is an authorized reply

Decision: after reconcile, every tick, the harness records `attention:<reason>` for each ticket not marked done whose
latest run ended `crashed`, `unpushed`, `unknown` or `timeout` (`unknown_result`), or `failed` (`worker_failed`). The
item clears when a newer run starts or the ticket is marked done. The overseer prompt forbids redispatching such a
ticket until an authorized replier comments after the run ended (TRUST_MODEL T1). There is no `canopy clear`.
Consequences: no attention table and no dismissal command. Since M3, `max_implement_attempts` (D030) bounds an overseer
that ignores the prompt.
Revisit: if the `decisions` table shows the overseer redispatching after a failed run; then a dispatch guard.

## D029. `canopy _run` and dispatch details: detached via `python -m canopy`, claimed by pid, serialized by flock

Decision:
- Dispatch spawns `sys.executable -m canopy _run <id>` (the same installation) in a new session, stdin from
  `/dev/null`, output to the run log, so the overseer's captured stdout is not held open.
- A run is claimed by the pid dispatch spawned; any other `_run` for it is refused.
- Dispatches hold a blocking `flock` on `<state_dir>/dispatch.lock` from the guards through the spawn. The SQLite write
  lock would instead block every running `_run` closing its row.
- The worker leads its own process group. `_run` records `runs.worker_pid`, and reconcile kills that group before
  returning the slot. SIGTERM, SIGHUP, and SIGINT to `_run` become cleanup.
- The overseer supplies the branch `--slug` (default `work`), since the harness cannot read titles (D003).
  `trust.branch_prefix` must be plain ref components (T7).
Consequences: pid reuse between a crash and the next tick could read a dead run as alive or kill an unrelated group.
`--base` stays `not_implemented` until M4.
Revisit: if pid reuse is ever observed (then compare process start times), or the rendered prompt should move from a
file into the journal.

## D030. Attempt limits and the fix-ci cooldown are derived from `runs`; cursors ride on the dispatch

Decision:
- An attempt is a `runs` row of that kind, whatever it ended as, crashed and failed spawns included. Counts never
  reset, and there is no reset command: the overseer can run any `canopy` command, and a guard it can reset is not a
  guard. A human raises the limit in their user config.
- `policy.max_implement_attempts` defaults to 2: the first try and one retry after an authorized reply (D028). The
  repository may only lower it, like the other limits.
- The fix-ci cooldown runs from the `ended_at` of the ticket's latest fix-ci run. Only fix-ci has one.
- Guard order: `running`, `attempt_limit`, `cooldown`, `capacity`. An `attempt_limit` refusal also records that
  attention item.
- `fix-ci` and `resume` continue `tickets.branch` and refuse `--slug`; a ticket without one is `no_branch`.
- `dispatch --cursor NAME=ID` advances cursors only once the worker starts, so a refused dispatch leaves its trigger
  unhandled for the next tick.
Consequences: the overseer cannot alter limits. A long review cycle can exhaust `max_resume_attempts` (default 3) on a
healthy ticket.
Revisit: if limits hit healthy tickets routinely (then count per PR, or reset on a merged PR), or an operator needs to
retry past a limit without editing config (then an operator-only command that refuses inside a tick).

## D031. `--context` is text that points at what to read, not a file and not a quote

Context: the overseer cannot write files. A path it chose could pull any file the operator can read into a worker
prompt (T6). Quoting ticket text into a shell command line invites injection and forged "AUTHORIZED REPLY" headers.
Decision: `--context TEXT`, at most 2000 characters, pointing at what the worker should read (links, comment ids, check
names, account ids), never quoting it. Every worker prompt names the authorized repliers from the user config, and the
worker checks a reply's author itself.
Consequences: an author check the overseer cannot influence. The harness still cannot verify authorship (D003), so
there is no author flag. An overseer ignoring the prompt can still write 2000 characters the worker is told are not
instructions.
Revisit: if workers routinely fail to find what the context points at, or the runtime can pass a file or stdin to the
overseer's commands safely.

## D032. Attention notifications: an item is its ticket and reason, and is notified once while it stays open

Decision: `attention.md` is rewritten after every tick, once the tick is closed. An item is identified by ticket and
reason; the overseer rewords details. `notifications` holds notified items still open. A notification goes out when
items are new or resolved, and only a zero exit within 60 seconds updates the table. The fingerprint is sha256 of key
and reason; the migration's comment saying otherwise is stale.
Consequences: no re-notification for a reworded or long-lived item; a failed command is retried; an item that comes
back notifies again. A hung notify command holds the tick lock for up to 60 seconds.
Revisit: if operators want reminders for long-open items, or per-reason routing (then say so in the message, not in
more commands).

## D033. Workspaces: one directory, a repository map, pools inside it; split tickets in the tracker, unlabeled

Context: real tickets touch several repositories. Some need one coordinated change; some are really several pieces of
work. One loop per repository gives each its own queue, capacity, and state, so a cross-repository ticket belongs to
none of them.
Decision (DESIGN §18, planned for M6 to M8):
- A workspace is a directory with a map (`canopy-workspace.toml`, plus prose in `MAP.md`), clones under `repos/`,
  treehouse pools under `.treehouse/` via `TREEHOUSE_ROOT` (apart from the operator's own pools), and state under
  `.canopy/`. One queue, one capacity, one journal. A repository with no workspace file is a workspace of one.
- The workspace file replaces the repository file layer with the same scopes and T7 controls. Clone URLs are read only
  by an operator command, never by a tick.
- A ticket's work is units, one per repository, each with its own branch, PR, cursors, and attempts. A coordinated
  change is one joint run: one worker, one desk of worktrees, linked PRs. One worker per ticket stays a guard.
- A ticket that is several pieces of work is split in the tracker by a `split` worker into children with no queue
  label. A human labels each child, and only a label added after the split run ended counts. Children are ordered by
  the tracker's blocker relation (M4).
Consequences: no new dependency. Creating tickets and links is a new tracker write, confined to a splitter agent with
no label tools. Splitting needs label history from the tracker. The desk needs an OpenCode permission canary.
`run_slots` replaces the slot columns on `runs`, `split_children` records children and their repositories, and
attention items gain a repository.
Rejected:
- One loop per repository with cross-loop coordination: two journals would have to agree on one ticket.
- One treehouse pool for every repository: a pool is how treehouse proves a slot belongs to a clone.
- Splitting inside the journal: no human sees or approves the pieces, and canopy would reimplement blockers.
- Children created with the queue label: work the loop authorized for itself (T1).
- Parallel units of one ticket: a TRUST_MODEL §6 change for a speedup nobody has measured.
Revisit: if labeling each child is measured as friction (then an authorized reply approving the split on the parent);
if the overseer is measured choosing repositories wrongly; if OpenCode's permissions cannot follow the desk's links
(then the worker's cwd is the first unit's worktree and the others are allowed as external directories).
