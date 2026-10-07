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

## D034. Chores: recurring agent runs the operator defines and the overseer delegates, reporting to attention

Context: some recurring work is not a ticket, such as spot-checking the CI build queue and recent builds, other people's
PRs included, for flaky jobs and stuck PRs. It needs judgment, sometimes over the operator's own deterministic tools.
Everything canopy runs today holds a worktree and pushes a branch for a queue ticket.
Decision (DESIGN §19, planned for M9):
- A chore is defined only in the user config: prompt, command template, `every_minutes` (a guard), and a
  plain-language `when` the overseer applies. The overseer runs a due chore or records a wait; the harness refuses one
  that is not due, already running, or over `capacity.max_chores`.
- A chore run is a detached `_chore` process in its own `chore_runs` table, with no lease, branch, or push. Its result
  is a summary and up to 20 findings with stable ids, which go to the attention list and `notify.cmd`.
- Read-only: the shipped `canopy-chore` definition has no write tools. A chore's own tooling is allowed in an agent
  definition in the operator's runtime config, not the repository.
- Opt-in and isolated: with no chores, or `max_chores = 0`, the overseer sees and decides exactly what it did before;
  deleting a chore clears its attention items. Findings do not inform ticket decisions.
- Named "chore" because "task" is OpenCode's subagent tool.
Consequences: a second spawn and reconcile path beside dispatch, and a second source for the attention list. Spend is
bounded in code to one run per `every_minutes` per chore. A broken overseer also stops chores. The feature is one
table, one column, one CLI group, one agent definition, and one prompt paragraph, so it can change or go without
touching ticket handling.
Rejected:
- The overseer doing the check inline: bash for arbitrary tools on the one agent that dispatches, every tick.
- Cron running the agent: no guards, journal, crash detection, attention list, or judgment about when. It is the
  fallback if M9 is not worth building.
- A fixed interval with no overseer: timing conditions such as "after a merge to main" need judgment (D008).
- Chore runs as `runs` rows: rebuilds the table the core loop depends on for a feature that may not survive M9.
- Findings informing ticket decisions from the start: a wrong chore would degrade the core loop, and opting out of that
  would mean dropping the chore.
- Recurring tickets through `dispatch`, chores the overseer defines (T1, T3), and chores in the repository file (T7).
Revisit: if chores routinely need to write (then unlabeled tickets first); if the overseer ignores `when` (then a
machine-readable window checked by a guard); if overseer failures starve chores (then the harness runs one overdue by
twice its interval); in M7, whether `chore_runs` folds into `runs` with no slots; once findings have a track record,
whether they may hold back ticket work, opt-in per chore.

## D035. Notifications: sinks are commands fed by the journal; Slack ships as one sink

Context: `notify.cmd` gets attention diffs as text. The operator wants issues and periodic progress in Slack, and
perhaps replies from Slack later.
Decision (DESIGN §20, planned for M10):
- A sink is a command that gets one message on stdin at the end of a tick, JSON by default. There can be several, each
  choosing event groups and an optional digest interval. `notify.cmd` becomes shorthand for a text sink of attention
  only, and its messages do not change.
- Events are a closed set the harness derives from the journal: attention opened and resolved, runs started and ended,
  and the loop failing and recovering. Attention stays D032's diff, now per sink. Point events go through an outbox
  with a cursor per sink, so a failing sink retries without resending to the others.
- The harness writes the digest from the journal, with no model, and sends it even when quiet, so a missing digest
  shows a dead scheduler.
- canopy ships `canopy-notify-slack`, a stdlib incoming-webhook sink run as a separate process. It reads its webhook
  from a file of its own and escapes Slack markup. Lint keeps network modules and the sink out of the harness.
Consequences: amends D032, whose table gains a sink column. The harness still makes no network call and holds no
secret. Alerts arrive up to one tick interval late. Each sink can hold the tick lock for 60 seconds. Two new tables.
Rejected:
- HTTP or a Slack SDK in the harness: the process that enforces the guards would hold a credential and make outbound
  calls (T2), and each destination would become code, which D003 and D014 keep trackers from being.
- A Python plugin interface: third-party code loaded into the harness process. A command is already the plug (D009).
- The overseer posting through a Slack MCP server (DESIGN §16's alternative): model spend and an LLM in every
  delivery, no retry, and a new write tool on the agent that dispatches. It stays the likely way to read replies.
- A chore for the periodic report: a model run to restate what the journal already holds. Chores are for judgment;
  their summaries reach sinks as events.
- Delivering from `dispatch` or `_run` when the event happens: concurrent sends outside the lock and a second retry
  path, to save at most one tick interval.
- Slack's interactive features (buttons, slash commands, Events API, Socket Mode): each needs a listener or a daemon.
Revisit: when two-way is wanted (then per-ticket threads, replies read through MCP, and a T1 change); if one tick
interval is measured as too slow for an alert; if operators want routing finer than groups.

## D036. A dry run checks the dispatch guards and changes no loop state the next live tick reads

Context: interactive dry runs showed plans a live tick would never carry out. `dispatch` in a dry run recorded every
request as `dispatch:<kind>`: an overseer asking for eight dispatches got eight, where a live tick would have started
one and refused seven (attempt limit, cooldown, running, no branch, capacity). `ticket set --done` also marked tickets
done, which drops them from every later state block, live ticks included.
Decision (DESIGN §6, §8), superseding D020's dry-run sentence:
- A dry-run `dispatch` checks the same guards, in the same order, and records a refusal as `refused:<guard>` like a
  live one, `attempt_limit` attention included. Each dry-run dispatch already recorded this tick counts as a running
  run, so `running` and `capacity` refuse what the live tick would. An allowed dispatch records the branch it would
  work on. The lease, prompt, and spawn are not tried, so `no_slot`, `bad_prompt`, and `spawn_failed` never appear.
- A dry-run `ticket set` records phases only: no cursors, no done flag.
- A dry-run tick is otherwise a tick: its attention items are the attention list and are notified. They describe the
  world as the overseer read it, and the guards now make a dry run's `attempt_limit` items the ones a live tick records.
Consequences: the `decisions` table is a faithful evaluation corpus for prompt changes. A dry run takes the dispatch
lock.
Rejected: simulating the lease with `treehouse status` (a real `get` may create a slot, so status cannot say whether it
would succeed); keeping dry-run attention off the list and out of notifications (an operator running only dry runs, as
M1 asks, would have no list at all).
Revisit: if dry-run notifications turn out to be noise for operators who alternate dry and live ticks.

## D037. A tick-wide skip closes the tick as `skipped`, which leaves the attention list standing

Context: when the overseer cannot reach the tracker or GitHub it records one tick-wide `skip` (`mcp_unavailable`,
`tracker_unsupported`) and exits cleanly. The tick closed `ok`, so its empty attention list became the current one:
every open item was notified as resolved, then as new on the next good tick, and item ages restarted.
Decision: after a successful overseer run, a tick-wide `skip` among the tick's decisions closes the tick as `skipped`,
and `canopy tick` exits 1. The attention list is the latest `ok` tick's, so a skipped tick leaves it as it was, like a
failed one. Any other decisions the overseer recorded in that tick stay in the journal.
Consequences: a run item the harness raises during an outage (a crashed worker) reaches the list at the next `ok` tick,
as it already did during an overseer failure. Schedulers see the outage as a failed run.
Rejected: carrying the previous list forward into the skipped tick (copies decisions the overseer never made).
Revisit: with DESIGN §15's attention item after consecutive overseer failures, which should count skipped ticks too.

## D038. Recommend HTTPS remotes; `canopy init` warns about SSH ones and refuses nothing

Context: HOST_ISOLATION proposes running workers under `srt`, and the worker pushes from inside the run. On Linux
`srt` blocks creating Unix sockets, which includes the SSH agent socket, so an SSH remote cannot push from a sandboxed
worker without extra policy. HTTPS with a credential helper works through the sandbox's proxy.
Decision: HTTPS remotes are the supported path, and the docs use them everywhere. `canopy init` resolves `origin`'s
push URLs through git, so `insteadOf` and `pushInsteadOf` rewrites count, and prints a warning naming any that go over
SSH, with the two ways to fix it. It is a warning, not a guard: init succeeds, and tick, dispatch, and `_run` never
look at the remote.
Consequences: an operator who runs unsandboxed can keep SSH remotes. An operator who wants to keep SSH for their own
fetches can push over HTTPS with `pushInsteadOf`, which silences the warning.
Rejected: refusing SSH remotes in init or at dispatch (the sandbox is opt-in and not built, and the operator is fully
trusted, TRUST_MODEL §3); checking the remote on every tick (noise for a choice the operator already made).
Revisit: when the sandbox ships. If it finds a way to support SSH (allowing the agent socket, or pushing from the host),
drop the warning; if sandboxing becomes the default, consider making SSH remotes an attention item.

## D039. Reviews: a fresh reviewer per PR commit that comments as itself, never approves, and needs no ticket

Context: the operator wants an adversarial review of PRs, the loop's own and their hand-written ones, by an agent run
that did not write the change. It should say what it is in a comment on the PR. Some teams want PRs judged low-impact
to need no human reviewer. Tracking each review as a ticket in the tracker is unwanted.
Decision (DESIGN §21, planned for M11):
- `canopy review run --pr URL --sha SHA` starts a detached `_review` in a leased slot checked out at that commit,
  with the reviewer's working directory outside the checkout. Guards in code: one `done` review per commit, a per-PR
  limit, a daily limit, `max_reviews` within `max_workers`.
- A review of the loop's own PR comes before `needs_reviewer`, when `review.agent_prs` is on, and its findings go back
  to a worker through `resume`. PRs matched by the user-only `review.query` are reviewed and nothing else. The PR is
  the unit: no ticket, no tracker writes.
- The reviewer posts one comment on the PR's conversation, whose first line identifies it and whose last line is a
  machine-readable marker with the commit, verdict, and impact. It never submits a PR review. Its definition denies
  the tools that could approve, push, label, or edit.
- The verdict is only that comment. Letting low-impact PRs skip a human reviewer is the repository's decision, made in
  its own automation. canopy still never approves (TRUST_MODEL §6).
- The loop recognizes its reviews by the journal, never by the marker, so a review's comment never counts as a
  human's review comment.
Consequences: the overseer handles PRs that are not tickets, and `decisions` gains a `pr` column. A third detached-run
path beside `_run` and `_chore`. Every review comment is posted as the operator (D010), including on other people's
PRs when the query matches them. Findings sent to `resume` make `max_resume_attempts` (D030) easier to reach. A
repository that gates merges on the marker trusts every agent the operator runs.
Rejected:
- Submitting a GitHub review: the tool that can comment on lines can also approve, and as the operator an approval
  counts on other people's PRs.
- An approval opt-in for low-impact PRs: breaks TRUST_MODEL §6, and under D010 it would be the operator's approval,
  given by an agent that read untrusted text.
- A commit status or a label for the verdict: a tool that sets them can set any status, such as a required CI check,
  or any label, such as one that triggers automation. A label also outlives the commit it judged.
- A ticket per reviewed PR: tracker noise, and the tracker adds nothing a PR does not already have.
- A chore that reviews: runs on a timer, not per commit; has no checkout; and its findings never reach a worker.
- The reviewer working in the checkout: the runtime would load its configuration and agent definitions from files
  the PR controls.
- Review runs as `runs` rows: those are keyed by ticket and branch, which a review of a hand-written PR has neither of.
- The harness checking the reviewer's comment, or allowing it one comment, through the VCS API: VCS code in the
  harness (principle 5, D003). The overseer checks the comment; one comment per run stays a prompt rule.
Revisit: when a runtime can deny approving or a bot identity exists (then inline comments); if the per-commit review
is measured as too costly on busy PRs (then the overseer waits for a quiet period, under a guard); if OpenCode cannot
confine reads to the checkout (then no checkout, MCP reads only); if repositories want to share a rubric.

## D040. Agent runs load canopy's definitions from a directory canopy owns, never from the repository

Context: `canopy init` copies `canopy-overseer`, `canopy-worker`, and the tracker skill into the repository's
`.opencode/`. A leased worktree only has them if they are committed, and when `opencode run --agent NAME` cannot find
NAME it prints a warning and runs OpenCode's default agent, which allows everything: a worker with none of its denies.
Nothing in canopy notices. Copies in every repository also do not scale to M6's workspaces, and T7 already names them as
repository-controlled config the user-only keys do not cover.
Decision (DESIGN §13):
- canopy snapshots its bundled `agents/` and `skills/` into `<state_dir>/runtime/<digest>/`, named for a digest of
  their contents: written to a temporary directory, renamed into place, and never modified afterwards, so concurrent
  runs never see a partial set. A run uses the snapshot for the installed canopy, creating it if missing. Reconcile
  removes other snapshots when no run is live. OpenCode scans `{agent,agents}/` and `{skill,skills}/` in a config
  directory, so the bundled names need no renaming.
- Command templates get a `{definitions_dir}` placeholder for the snapshot; the default templates are `env
  OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker {prompt}` and the same for the overseer.
  Every template that runs a canopy-shipped agent must contain it: `overseer_cmd`, `worker_cmd`, and D039's
  `review_cmd`. Without it the config error prints the replacement line; canopy does not rewrite the user file.
- The runtime's own skill paths stay on, and adding skills there is how an operator or a repository customizes canopy:
  OpenCode reads `OPENCODE_CONFIG_DIR` in addition to `~/.agents/skills`, `~/.claude/skills`, `~/.config/opencode/`,
  the repository's `.agents/skills`, `.claude/skills`, and `.opencode/`, and `skills.paths`. Customizations use new
  names: OpenCode loads skills concurrently, so which of two same-named skills wins is not deterministic.
- `canopy init` stops installing agent definitions and skills, including D039's `canopy-reviewer` into the
  operator's runtime config.
- The live canary gains a precedence check: a repository-level definition of the canary agent that allows a denied
  command must not make it run.
Consequences: the definitions an agent runs with always exist and always match the installed canopy; upgrading canopy
updates them at the next run. A repository can still add skills, MCP servers, plugins, and permission rules for keys
canopy's definitions do not set; it cannot override a key they do set, since `OPENCODE_CONFIG_DIR` merges after
project config and the last matching rule wins (from OpenCode 1.18.32's source; the canary confirms it live). The
worker's `external_directory: deny` means it gets a skill's `SKILL.md` from anywhere but cannot read files next to it
outside the worktree, so skills in `$HOME` that workers use, and canopy's own, are single files. OpenCode installs its
plugin package into every config directory, so each snapshot gets a `node_modules/` once. Operators upgrading from
an earlier canopy edit their templates once, guided by the config error. The placeholder is a path,
not a shell variable, so D023 holds; `env` is an ordinary program.
Rejected:
- Pointing `OPENCODE_CONFIG_DIR` at the installed package: OpenCode writes `.gitignore`, `package.json`, and
  `node_modules/` into it, inside site-packages or, in a source checkout, inside `.agents/`.
- Committing `.opencode/` in every repository: a copy per repository to keep current, and one that anyone who can push
  controls (T7).
- `OPENCODE_DISABLE_PROJECT_CONFIG`: it blocks the repository's skills and MCP servers, which operators should be able
  to use to customize canopy.
- A guard that refuses when the worktree defines a `canopy-*` agent: it cannot see agents defined in `opencode.json`
  without parsing JSONC, and merge order already makes canopy's keys win.
- One mutable `<state_dir>/runtime/` rewritten before each run: overlapping runs could load a half-written set.
- Rewriting the old default templates during config loading: the operator's file would no longer say what runs.
- `skills.paths` in the operator's `opencode.json`: covers skills only, not agent definitions, and changes every
  OpenCode session the operator runs.
Revisit: when M6 needs workspace-level skills above the repositories (`OPENCODE_CONFIG_CONTENT` with `skills.paths` can
list several directories); when a second runtime needs its definitions somewhere else (D009); if the canary shows a
repository can loosen a key canopy sets.

## D041. Layered subpackages now; a uv workspace when the first separate program lands

Context: 18 modules in one directory at M3, and M6 to M11 each add a feature of similar size (workspaces, joint runs,
chores, notifications, reviews): 40 or more modules on that path. Nothing said which module may import which, so only
review kept chores removable (D034) and the network out of the harness (D035).
Decision (DESIGN §5):
- `src/canopy` is layered subpackages: `cli`; `loop`; the features (`runs` and `setup`, later `chores`, `notify`,
  `reviews`); `core`; `infra`. Imports go down, never between features. `tests/canopy/test_layers.py` checks every
  import, `TYPE_CHECKING` ones included, fails on a module in no listed package, and keeps click inside `cli`.
- `cli/` has one command module per feature, so the command surface stays in one place and nothing else needs click.
- The repository becomes a uv workspace when M10 builds the Slack sink. `canopy` stays the root project; members go
  under `packages/`. A member is code that runs as its own process and must not share the harness's imports or
  dependencies. Anything that reads or writes the journal stays in `canopy`. This amends D035: the sink is the member
  `canopy-notify-slack`, not `canopy.sinks.slack`. `canopy` depends on it and lists its script in its own
  `[project.scripts]`, so one `uv tool install` still installs both, and the ban on importing `canopy.sinks` becomes
  the layer test refusing `canopy_notify_slack`.
Consequences: imports name their layer (`from canopy.core import db`). D015's exemption is now
`src/canopy/infra/procs.py`. A new package needs a line in the layer test and in DESIGN §5. `migrations/`, `.agents/`,
D022's lookup, and the install command stay where they are, because the root project does not move. M10 must check that
`uv tool install` resolves the member from git and from an index on a clean machine.
Rejected:
- A workspace now, with `canopy` moved to `packages/canopy/`: every path moves (resources, force-include, CI, pyrefly)
  for one member and no second distribution.
- A virtual workspace root with every project under `packages/`, now or later: the same moves, for symmetry only.
- Splitting the harness into distributions (core, features, CLI): they share one journal, one lock, and one release.
- Features owning their click commands: click in every layer, and D025's parameter types shared upward out of `cli`.
- ruff's `TID251` for layers: exemptions are per rule and file, so letting `cli/` import `canopy.cli` or click would
  also let it import `subprocess`.
- import-linter: a dependency for what a short stdlib test does. Reconsider if the contracts outgrow one layer list.
Revisit: if shared code piles up in `core` until it is the new flat directory (then split it by concern); when a second
separate program ships, which becomes a workspace member by the rule above.

## D042. The loop is `canopy loop` in the foreground, not cron or launchd

Context: the README told operators to schedule `canopy tick` with cron or launchd once they trusted it. Every tick runs
the overseer, which reads the queue through MCP, so the tick rate sets the loop's largest recurring spend (TRUST_MODEL
§2), and pacing ticks by what they cost is the planned cost control (ROADMAP M13). A scheduler outside canopy cannot
read the journal, so it cannot pace by anything.
Decision (DESIGN §6):
- `canopy loop` runs ticks one after another in the foreground and waits after each one ends: `--every`, else
  `loop.interval_minutes` (user-only, default 15). One function, `repeat.pace` in `canopy.loop`, decides the wait,
  so pacing by spend replaces a function, not the scheduler.
- Each iteration is an unchanged tick. The loop adds its own lock, so a state dir has at most one loop. `canopy tick`
  stays, for one tick by hand, a dry run, or an operator who still prefers a scheduler.
- SIGINT or SIGTERM stops the loop after the current tick; a second one aborts the tick. A tick that raises ends as
  `error` and the loop goes on.
- It is not a daemon: it does not detach, write a pid file, restart itself, or listen on anything. Keeping it running,
  in a terminal, tmux, or a service manager, is the operator's choice.
Consequences: AGENTS.md's do-not-build list and DESIGN §3 no longer say the loop is a scheduled tick. One process lives
for days with one journal connection and the config it read at start. A loop that dies stops ticks until it is
restarted, as a broken crontab did; M10's digest is how the operator would notice.
Rejected:
- Recommending cron or launchd: no pacing from the journal, no output a person reads, and set up differently on each
  platform.
- A background daemon with start and stop commands: pid files, log rotation, and supervision to write, for what a
  terminal or the platform's service manager already does.
- Holding the tick lock through the wait: `canopy tick` by hand could never run while a loop is up.
- A start-to-start cadence: a tick longer than the interval would lead straight into the next one.
- Ending the loop on a failed tick: DESIGN §15 already has the next tick retry.
Revisit: with M13, when the wait depends on spend; when M6 puts several repositories in one queue.

## D043. rich for terminal output

Context: `canopy loop` runs for hours in front of a person. It needs a spinner during a tick, a countdown during the
wait, color by status, and aligned columns that truncate long text, redrawn in place on a terminal and plain when
piped to a file.
Decision: adopt `rich` for the loop's output. Other commands keep `click.echo` until their output is reworked; moving
them is not required. rich writes to stdout only; the log stays JSON lines through `logging`.
Why stdlib was insufficient: `curses` takes over the whole screen and loses scrollback, which is the loop's record of
what happened. Hand-written ANSI would reimplement terminal detection, width, truncation, `NO_COLOR`, and in-place
redraw. click's `style` covers color only.
Consequences: one runtime dependency, pure Python and typed, bringing `markdown-it-py` and `pygments`. Tests render to a
`Console` over a `StringIO`, which draws no color and none of the in-place output.
Rejected: `textual` (a full-screen application framework, where the loop is a log with a status line); `tqdm`
(progress bars only).
Revisit: if a command's output needs something rich cannot draw plainly off a terminal.

## D044. Refuse to start an agent where the repository's OpenCode config defines one of canopy's agents

Context: D040 rejected a guard against repository definitions of `canopy-*` agents because merge order makes canopy's
keys win. OpenCode 1.18.32's source says otherwise for bash rules. Agent definitions from every config directory are
merged with a deep object merge, and a permission map becomes rules in key order, the last matching rule winning. A key
both definitions set keeps the position of the definition loaded first, the repository's, and takes canopy's value; keys
only the repository sets stay where the repository put them; canopy's other keys are appended. So a repository
definition with `"*": deny` followed by `"rm *": allow` gives the overseer `"*": deny`, `"rm *": allow`, then canopy's
own allows: `rm` runs (`opencode agent list` shows exactly that order). A scalar value such as `external_directory:
deny` replaces whatever the repository set, so only map-valued keys, in practice bash, can be loosened this way.
Decision (DESIGN §13, TRUST_MODEL T7):
- Before starting the overseer or a worker, the harness looks at the OpenCode config in the directory the agent starts
  in: files under `.opencode/{agent,agents,mode,modes}/` named for one of canopy's agents, and `opencode.json` or
  `opencode.jsonc` at the root or in `.opencode/` whose text contains one's name. If any is found the agent does not
  start: the tick fails with `overseer_failed`, or the run ends `crashed` and its slot is returned, naming the files.
- A worker's check runs after its branch is checked out, on the files the worker would load.
- `canopy init` warns about the same files, which earlier versions of init installed.
Consequences: repositories that committed `.opencode/agent/canopy-*.md` from an earlier `canopy init` stop working until
the files are removed. A JSON config that mentions a canopy agent's name for any reason, such as a comment, is refused
too. The check does not parse JSONC or apply OpenCode's `{env:...}` and `{file:...}` substitutions, so a config that
builds the name through JSON escapes or a `{file:...}` reference gets past it; TRUST_MODEL T7 records that residual.
Rejected:
- Parsing `opencode.json` as JSONC with substitutions: reimplements OpenCode's loader, and would still trail it.
- Refusing any repository OpenCode config: blocks the skills and MCP servers operators should be able to add (D040).
- Agent names unique to each installation: templates name the agent, so every operator would edit them on each
  upgrade, and a repository targeting one canopy version can compute a name derived from its contents.
- Relying on the canary alone: it checks how the runtime merges definitions, not what a given repository commits.
Revisit: if OpenCode gives a config directory's agent definitions precedence over the project's, or lets a command
disable project agent definitions without disabling project skills; when a second runtime is supported (D009).

## D045. Stacking checks the base's shape in code; the overseer chooses it from live state every dispatch

Decision:
- `canopy dispatch --base BRANCH` is accepted for every kind. The base must be `trust.branch_prefix` followed by one
  plain ref component, and not the run's own branch; anything else is `bad_base`. Only agent branches can be stacked
  on, so an overseer steered by injected text cannot aim a worker's PR at a release or other long-lived branch.
- The harness does not require the base to be a branch in its own journal. A blocker in another operator's queue,
  under the same shared prefix, is a legitimate base.
- The base is not stored on the ticket or inherited by later runs. Each dispatch passes it or not, from what the
  overseer reads that tick (the blocker's PR open or merged), and the run records it in `runs.base_branch`. The state
  block shows the latest run's base so the overseer can see a ticket was stacked.
- `treehouse get` is not given the base. `_run` already creates the branch from `origin/<base>` after a fetch, and a
  base missing from origin is a `crashed` run with a note, before the worker starts.
- A stacked ticket whose blocker merged is retargeted by a `resume` without `--base`: the worker points the PR at the
  repository's base branch and merges that branch in if it conflicts. Workers push without force, so no rebase.
Alternatives: a `tickets.base_branch` column that later runs inherit (a journal fact standing in for the PR's live
base, DESIGN §4, and one that goes stale when the blocker merges); checking the base against the journal (refuses
cross-operator stacks); passing `--base` to treehouse (its handling of a branch that exists only on origin is not
canopy's to rely on).
Consequences: an overseer that forgets `--base` on a stacked ticket's `resume` before its PR exists opens that PR
against the base branch, with the blocker's commits in it; a reviewer sees that. The harness cannot tell a base is
green or is the ticket's blocker; that stays the overseer's judgment, like every other reading of the tracker.
Revisit: if the `decisions` table shows stacks on red or unrelated branches, or stacked tickets' later runs dropping
their base; then record the base per ticket and check it in dispatch.

## D046. Proprietary for now, installed from git, never from PyPI under this name

Context: M5 makes canopy something a coworker installs. The repository is private, and `canopy` on PyPI is an unrelated
project: `uv tool install canopy`, which README's install step said, installs it and fails with no `canopy` executable.
Decision:
- License: proprietary, all rights reserved (`LICENSE`, `license = "LicenseRef-Proprietary"`). Coworkers use it under
  the owner's permission, as with any private repository.
- Install: `uv tool install git+https://github.com/eddieland/canopy`, with the HTTPS credential any private clone
  needs; `--reinstall` upgrades. The `Private :: Do Not Upload` classifier makes PyPI refuse an upload, so a mistaken
  publish cannot take a name that is not ours.
- `tests/install-check.sh` (`make install-check`) is the clean-machine check: `uv tool install` from the checkout
  into an empty HOME, then `canopy init` and a dry tick against the fakes, asserting the bundled files come from the
  installed tool. CI runs it on Linux and macOS for every change. It is not in `make check` because it downloads the
  dependencies.
Rejected: a permissive license now (the owner chose to decide that with a public release); publishing to PyPI under
another name (a rename is open, README's first line, and a release process is more than M5 needs).
Revisit: before any public release or index publish, together with the name; if a coworker cannot use git credentials
for the install.

## D047. The operator's canopy skill is printed by `canopy skill`, and agent runs do not load it

Context: the `canopy` skill reserved in `.agents/skills/` was for an agent in the operator's own session, answering
"why was KEY not picked up". Since D040 it would ship only in the definitions snapshot, which only canopy's overseer and
workers load: the overseer has its prompt and the worker may not run `canopy` at all. An operator's copy in `$HOME`
would then be a second skill with the same name in every run, and which one OpenCode loads is not deterministic.
Decision (DESIGN §13): the skill moves to `.agents/operator-skill/SKILL.md`, bundled but outside the snapshot.
`canopy skill` prints it; the operator saves it where their runtime reads skills and again after upgrading. It tells an
agent started by canopy to follow its prompt instead, since canopy's runs also read `$HOME`'s skills. It describes only
read-only use: ticks and the overseer's commands are the operator's and the overseer's.
Rejected:
- `canopy init` writing it into `~/.agents/skills/`: D040 took init out of the operator's runtime config, and a file
  written behind the operator's back goes stale unnoticed on upgrade.
- Keeping it in the snapshot: runs gain nothing from it, and a `$HOME` copy collides with it by name.
Revisit: when a second runtime reads skills from somewhere `canopy skill`'s output does not fit; if operators ask for
an install command.

## D048. treehouse is pinned to a commit until a release has `base_branch`

Context: canopy's lease model requires `base_branch` from `treehouse get --lease --json`; dispatch uses it as the
worker's base when there is no `--base`. treehouse added the field after v2.3.0, its newest release, so `make treehouse`
(which installed the newest release) and `treehouse update` both give a treehouse whose every lease canopy refuses. A
live tick on 2026-09-25 refused all three dispatches as `no_slot` this way, and `treehouse update` also left a binary
that needs glibc 2.34+.
Decision: `make treehouse` and README's install step pin commit `1185dc6`, the one canopy's treehouse shapes were read
from (ROADMAP M0). `TREEHOUSE_VERSION` takes a tag, commit, or branch.
Rejected:
- Making `base_branch` optional and falling back to `main`: a wrong base is a silent wrong PR target, worse than a
  refused dispatch.
- Tracking treehouse's `main`: unreviewed upstream changes to the JSON canopy parses would land on the next install.
Revisit: when a treehouse release includes `base_branch`; switch the default back to a release tag.

## D049. A second stop signal within one second of the first is the same Ctrl-C

Context: D042 has the loop's first SIGINT or SIGTERM stop after the tick and a second abort it. Run as `uv run canopy
loop` (a checkout, a developer), one Ctrl-C aborted the tick: the terminal sends SIGINT to the foreground process
group, which holds both uv and canopy, and uv 0.11 forwards the SIGINT it got to its child about 200 ms later. canopy
cannot tell the forwarded copy from a second keypress by its content.
Decision (DESIGN §6): `repeat.signals` ignores a stop signal that arrives less than `SAME_SIGNAL_SECONDS` (1.0) after
the first, measured on a monotonic clock, for SIGINT and SIGTERM alike. The clock is injected, so tests need no sleeps.
Rejected:
- Detecting uv (its env vars or parent process) and ignoring one extra signal: couples canopy to one launcher's
  behavior and version, and misfires if uv stops forwarding.
- Moving canopy into its own process group: the terminal's Ctrl-C would then reach only uv, so canopy would depend on
  uv forwarding it, and a `canopy loop` run directly would lose Ctrl-C altogether.
- A shorter window, such as 300 ms: close to uv's 200 ms delay on a loaded machine, for no gain; a person reads the
  "stopping after this tick" line before pressing Ctrl-C again.
Revisit: if a launcher forwards signals later than a second, or operators find a deliberate double Ctrl-C ignored.

## D050. Build canopy rather than adopt Symphony, agent-orchestrator, or Hermes Kanban

Context: three open-source projects overlap with canopy's loop (surveyed 2026-09-29 in `PRIOR_ART.md`). Polling,
dispatch, a worktree per ticket, and sending CI and review back to an agent are common to all of them.
Decision: keep building canopy; take their lessons, not their code, as with Azimuth (D001). What none of them offers,
and canopy is for: any tracker through MCP with no tracker code (D003, D014); never merging (TRUST_MODEL §6), held by
the prompts, a `gh pr merge` deny in canopy's agent permissions as defense in depth (TRUST_MODEL T4, T7), and branch
protection, which is the boundary; no daemon or listener (D042); worktrees released while waiting (D005); a fresh
overseer each tick (DESIGN §6).
Rejected:
- Implementing Symphony's spec: it targets the Codex app-server protocol and a tracker adapter per provider, keeps
  state in memory, and lets a repository file set the agent command and shell hooks (TRUST_MODEL T7).
- Configuring agent-orchestrator: its tracker intake is GitHub and GitLab only, its sessions are long-lived and fed
  messages, and it runs listeners.
- Hermes Kanban: its tasks live on its own board, not the team's tracker, and it has no CI or review follow-up.
Revisit: if agent-orchestrator ships tracker intake through MCP or Jira and a fresh session per run; if Symphony's spec
drops the Codex requirement and moves CI and review follow-up into scope; if Hermes lands tracker-driven issue
resolution ([#404](https://github.com/NousResearch/hermes-agent/issues/404)).

## D051. A dispatch names the queue label it relies on, and the worker checks it again

Context: labels are canopy's only authorization to start work (TRUST_MODEL T1), and until now only the overseer's
prompt checked them. In the live acceptance run on 2026-09-25 the overseer (OpenCode with `gpt-6-luna`) dispatched an
unlabeled ticket twice, dry and live: the ticket was in the state block from an earlier dry run, the prompt says to
union the state block with the query, and the overseer skipped the label read for it. Other ticks skipped the same
tickets correctly, so the check is unreliable rather than absent. canopy has no tracker code (D009), so it cannot read
labels itself.
Decision: `canopy dispatch` requires `--label LABEL`, one of `tracker.labels` compared case-insensitively (GitHub
labels are), and refuses otherwise as `unauthorized`, the first guard. The refusal does not list the configured labels,
so the overseer cannot copy one from it. The decision's rationale records the configured spelling. Every worker prompt
starts by reading the ticket and reporting `failed` (`not authorized: ...`) without changes if it is closed or carries
none of the queue labels, which the harness renders into the prompt; a worker prompt without `{{LABELS}}`, such as an
override written before this decision, fails to render and the dispatch is refused as `bad_prompt`. The overseer
prompt says the state block authorizes nothing and that `[bot]` approvals do not count as approval.
Rejected:
- Prompt wording alone: it already said labels authorize; the failure was a skipped step, which a required argument
  turns into an explicit claim.
- Reading labels in the harness: that is a tracker client (D009), per provider.
- Narrowing `tracker.query` to the operator's label: the state-block union still brings old tickets back, and the
  query is shared across operators.
Residual: `--label` is a recorded claim, not a check: the harness knows only that the label is configured, not that it
is on the ticket, so an overseer that names a label it did not read passes the guard. The independent check is the
worker's own read of the ticket's labels, a separate agent run with its own tracker access; it is a prompt instruction,
so it too can be skipped. Human review of every PR is the backstop.
Revisit: if a tracker-neutral way to read labels appears (for example a runtime command canopy can call without
provider code), move the check into code.

## D052. Until joint runs, a ticket has one repository: the one its first dispatch named

Context: M6 makes several repositories one queue, but units, joint runs, and per-unit attempts are M7 (DESIGN §18).
The journal still has one branch, PR, and set of attempt counts per ticket, so a second repository for a ticket would
overwrite its branch, count its attempts against the first repository's, and leave `fix-ci` and `resume` without a way
to tell which branch they continue.
Decision: in a workspace, every `canopy dispatch` names exactly one repository with `--repo`. Each run records it
(`runs.repo`), and a ticket's repository is its latest run's. A dispatch naming any other repository for a ticket that
has runs is refused as `unknown_repo`, the guard §18 already defines for "not the one recorded". The overseer prompt
records attention `multi_repo` for a ticket that needs several repositories, so a human splits it. In a workspace of
one, `--repo` is optional and the check is skipped, so renaming the checkout's directory never strands a ticket.
Rejected:
- Letting a later implement move the ticket: the branch and PR of the first repository would be forgotten, and its
  attempts would count against the second.
- Building units now: M7's schema (`ticket_units`, `run_slots`) and its canary belong together; M6 would ship half.
Revisit: M7 replaces the check with units: `implement` may add a repository to a ticket, and `fix-ci` and `resume` name
the unit whose PR needs work. Units added one after another, such as a follow-up PR after the first merged, are an
open question (DESIGN §18, Open): the check here is what blocks them now.

## D053. A workspace's state directory, and any definitions snapshot, must be private to the operator

Context: a workspace keeps its state under its root (`.canopy/`, D033), and the root may be a checkout of a shared
workspace repository. Before M6 the state directory was the operator's own (`~/.canopy`). Inside a checkout, anyone who
can push to the workspace repository could commit a `.canopy/` holding a journal, or a definitions snapshot named for a
released canopy's digest whose agents allow everything; canopy would load it, breaking TRUST_MODEL T7's rule that
canopy's agent definitions never come from the repository (D040).
Decision: every command in a workspace that opens the journal refuses a `.canopy/` that is a symlink, belongs to someone
else, or has group or other permission bits, as a config error naming the fix (remove it; canopy recreates it). canopy
creates it 0700, and git creates directories from the umask, typically 0755. Separately, and in every workspace, a
definitions snapshot is used only if it passes the same test: canopy's own are made with `mkdtemp`, so they are 0700. A
refused snapshot fails the tick as `overseer_failed` or a run as `crashed`, with the message.
Rejected:
- Asking git whether `.canopy/` is tracked: a process per command, and the workspace root need not be a repository.
- Verifying a snapshot's contents against the bundled files: OpenCode writes its own files into the snapshot, and
  extra files (an `opencode.json` at its root) would need their own rules.
- State outside the workspace: D033 keeps each workspace's journal with it, so deleting the workspace removes it.
Residual: the check reads permissions, not provenance. A checkout made under a umask of 077 creates private
directories, and files git adds inside a `.canopy/` canopy already made are the operator's own. `.gitignore` covers
`.canopy/`, and review of the workspace repository is the backstop, as for the map itself.

## D054. Stacking stays, and the operator controls it through the overseer's policy

Context: the operator's requirements say ticket B is not started until A lands (REQUIREMENTS R8); the overseer stacks B
on A's open, green PR (D045), which starts B sooner. The operator, asked, chose to keep stacking but to control it, and
preferred the control to be the overseer's judgment rather than a harness guard (REQUIREMENTS C1).
Decision: a shared key `policy.stacking`, `"auto"` (default: the overseer stacks when DESIGN §10's conditions hold) or
`"never"` (a blocked ticket waits until its blocker is closed and has no open PR, so a blocker closed before its PR
merges has not landed). It is rendered into the state block with the other
policy, and the overseer prompt follows it. The repository may only tighten it (`"never"` is stricter), as for every
`policy.*` key. The harness adds no guard: whether to stack is policy, which lives in prompts (D008); `bad_base` still
checks the base's shape.
Rejected:
- A `bad_base` refusal under `"never"`: a second place for a preference the operator asked to keep in the overseer.
- A boolean: leaves no room for a later per-ticket or per-relation mode without renaming the key.
Revisit: if the overseer stacks under `"never"` in the decisions corpus (then add the guard); if the operator wants
per-ticket control, such as a label that forbids or allows stacking for one ticket.

## D055. Listeners are allowed on loopback or a private network, behind the operator's secret

Context: TRUST_MODEL §4 said nothing listens on the network, which ruled out prompting a running session (OpenCode's
server), interactive notifications, and a local UI (REQUIREMENTS C2, C3). The operator wants two-way communication and
runs on a private VPC, and asked for simple protection.
Decision (TRUST_MODEL §4, T8, §6): a listener canopy runs or starts binds to loopback by default, or to a private
address the operator sets in the user config; never a wildcard or public address. Every listener checks the operator's
listener secret, read from an operator-only file. Whoever holds it acts as the operator. Listeners lift no guard.
The first listener is OpenCode's own server, so the operator can attach to a worker's session and prompt it (ROADMAP
M15); a local UI and interactive notifications may follow under the same rules.
Consequences: DESIGN §3 no longer lists a network listener or a web UI as non-goals. `canopy loop` is still not a
daemon and listens on nothing itself (D042) until a milestone gives it a listener.
Rejected:
- Loopback only: the operator asked for the VPC; loopback stays the default.
- mTLS or per-user accounts: more than a single-operator tool on a private network needs now.
- No secret on loopback: any local user could steer the operator's workers.
Revisit: if canopy is run by more than one person per machine or listener, or on a network the operator does not
control (then per-user authentication).

## D056. A worker may push to the head branch of a PR the operator wrote and labeled

Context: the operator wants canopy to fix CI and address review on their own hand-written PRs (REQUIREMENTS R9). Those
PRs' branches are not under `trust.branch_prefix`, where workers are limited to pushing (TRUST_MODEL T1, §6). The
operator chose direct pushes over a fix branch with a PR into theirs (REQUIREMENTS C4).
Decision (TRUST_MODEL T1, §6; built in ROADMAP M14): a PR's head branch may be pushed to if the PR is open, not from a
fork, authored by the operator, and labeled with one of `tracker.labels`. The label is the authorization, as on a ticket
(D051): the overseer reads it and the author, and the worker reads both again before changing anything. Pushes are
never forced. The harness refuses the repository's base branch; it cannot read PRs (D003), so authorship is the agents'
check.
Rejected:
- A prefixed fix branch with a PR into the operator's: keeps T1 unchanged but adds a merge per fix, which the operator
  declined.
- Any PR with the label, whoever wrote it: lets a label put a worker's commits on a coworker's branch.
Revisit: if the decisions corpus shows a dispatch for a PR the operator did not write.

## D057. Under `policy.stacking = "never"`, a blocker has landed only when its PR merged

Context: D054 defined `"never"` as waiting until the blocker is closed and has no open PR. A blocker whose PR was closed
without merging also has no open PR, so that definition would start B on a prerequisite that never landed.
Decision: supersedes D054's definition only. A blocker has landed when it is closed and its PR, if it had one, merged.
One whose PR closed unmerged never landed: the overseer records `needs_author` for B, as it already does for a stacked
ticket whose blocker's PR closed unmerged (DESIGN §10). `"never"` governs starting a ticket; one already stacked when
the setting changes keeps its stacked PR and its follow-up runs, since that PR cannot merge before its blocker's.
The rest of D054 stands, including no harness guard.
Revisit: with D054's triggers.

## D058. A ticket's work is units, one per repository; a unit may start after another unit's PR merged

Context: D052 kept a ticket in the repository of its first dispatch until M7. M7 builds units (DESIGN §18), and the
open question was whether a unit can start once the ticket's first PR has merged: the next repository once the first
lands, or a follow-up PR after late review feedback.
Decision: a ticket's units are the repositories it has been dispatched to, each with its own PR, phase, review and ci
cursors, and attempt counts. Any `implement` may add a unit for a repository the ticket has none in, before or after
another unit's PR merged: that is how a sequenced change (web consuming the api's release) is worked inside one ticket.
The queue label authorizes it, as it authorized the first. A repository has at most one unit per ticket, so a
follow-up PR in a repository whose unit has merged is a new ticket a human files. The overseer marks the ticket done
only when every unit's PR has merged and no other repository is left to change. Attention items about a unit name its
repository. D052's check is gone.
Consequences: attempt limits and the fix-ci cooldown are per unit, so a new unit starts with none used; one worker per
ticket still holds. The harness cannot tell a sequenced unit from a joint one or check that the first PR merged (D003):
the overseer prompt carries that judgment, and `multi_repo` still asks a human to split a ticket that is several
independent pieces until M8.
Rejected:
- No unit after a merge: the common cross-repository ticket, a contract change then its consumer, would need a second
  ticket for work the first already describes and authorizes.
- A follow-up in the same repository, authorized by a reply after the merge: two units per repository, a second branch,
  and a new authorization path (TRUST_MODEL T1) for a need nobody has measured. Revisit: if filing follow-up tickets for
  late review feedback is measured as friction; if the overseer is measured adding units a ticket did not need.

## D059. One branch per ticket; a desk only for a joint run; `run_slots` holds every run's slots

Context: M7's units share a run's branch, and a joint run leases a slot per repository (DESIGN §18). Before units, a
retry `implement` could name a new slug, and every run held one slot, in columns of `runs`.
Decision:
- The ticket's first `implement` names its branch, and every later dispatch continues it in every unit. A later
  `implement` whose `--slug` names another branch is refused as `bad_slug`. A run therefore has one branch, and a joint
  `fix-ci` or `resume` never covers units on different branches.
- A run in one repository runs its worker in the worktree, as before; only a joint run gets a desk. Joint runs depend on
  the desk canary; runs in one repository do not. canopy marks each desk it makes and removes only those: anything
  else under `desks/` is the operator's, and one in a desk's place refuses the run.
- Migration 0005 moves every run's slot into `run_slots` and every ticket's PR, its phase about that PR, and its review
  and ci cursors into a unit, and drops the old columns, so code reads one shape. Rows from before workspaces have no
  repository name; a workspace of one ignores it and renames the unit on its next write.
- A joint run's prompt must have `{{REPOSITORIES}}` and `{{PRS}}`; an override without them still serves a run in one
  repository.
Consequences: a retry after a failed `implement` continues whatever that run pushed rather than starting a fresh branch.
Result lines with the old single `pr` are still read for a run in one repository.
Rejected:
- A branch per unit: a joint run with several branches, and `--slug` per repository.
- A desk for every run in a workspace: every run would depend on the canary, for no gain in one repository.
- Keeping the slot columns for old runs: two code paths for reconcile, attempt counts, and the state block.
Revisit: if the desk canary fails (then, per D033, the worker's cwd is the first unit's worktree and the others are
allowed as external directories); if operators need a fresh branch after a failed implement.

## D060. Pending migrations wait for runs an earlier canopy started

Context: `canopy _run` is detached and outlives the command that dispatched it. After an upgrade, the first canopy
command migrates the journal while a `_run` of the old version may still be working; when its worker finishes it writes
the old schema, and a migration that dropped a column (0005) makes that write fail, losing the run's result.
Decision: `db.migrate` applies pending migrations only when no `running` run has a live `_run`. Otherwise it fails
with a `MigrationError` naming the runs, and every command that opens the journal fails the same way until they finish.
A run whose `_run` is gone does not hold migrations back; the next tick's reconcile closes it.
Consequences: an operator who upgrades with workers running waits, at most the worker timeout, before canopy runs
again. A migration may change or drop what an earlier canopy writes without keeping it compatible.
Rejected:
- Keeping dropped columns and old writes working until old runs drain: every migration would carry two shapes for a
  window nobody can see the end of from the journal.
- Draining from inside canopy (stop dispatching, wait, then migrate): the old version is the one dispatching.
Revisit: if waiting out the worker timeout after upgrades is measured as friction.

## D061. A ticket over several repositories stays one ticket; the loop splits it only when an authorized replier asks

Context: D033 had the overseer prefer splitting a multi-repository ticket into tracker tickets, implementing jointly
only when the halves could not stand alone. The operator's own work does not fit that: a change that sets up a database
edits the Terraform repository and then the Kubernetes repository, under one ticket, and the loop should watch both PRs.
M7's units (D058) work such a ticket jointly or in sequence. Creating real tickets is something a person decides to do,
not a default of the loop. First proposed in the draft PR #54, written before M7 landed.
Decision (supersedes D033's preference for splitting):
- A ticket that needs several repositories stays one ticket, with a unit per repository, joint or sequenced as the
  overseer judges. One that is several independent pieces, with no request to split it, gets `multi_repo` attention.
- The overseer splits a ticket only when an authorized replier's comment on it asks for a split. `canopy dispatch
  --kind split` requires `--request <comment id>` and refuses without it as `unauthorized`; `--request` on another kind
  is `bad_request`. The splitter reads that comment and creates nothing unless an authorized replier wrote it and it
  asks for a split, and a split prompt without `{{REQUEST}}` does not render (D051's pattern).
Rejected:
- A dedicated split label: another label every tracker must be set up with, and one anyone who can label could add.
- An operator command that starts a split outside a tick: a second path into dispatch's guards and journal for one
  kind of run.
Consequences: the harness cannot read the comment, so `--request` is a recorded claim; the splitter's own read is the
independent check, as with labels. ROADMAP M8's acceptance starts from such a comment.
Revisit: if operators ask for splits often enough that a comment per ticket is friction; if the overseer is measured
choosing joint or sequenced wrongly.

## D062. A split runs in a desk at the base branches, with its own command, and records only children new to the journal

Context: DESIGN §18 planned the splitter in a desk of the named repositories' worktrees. With M7's desks and
`run_slots` in place, a split can use the joint run's machinery; what differs is that it reads and never pushes.
Decision (DESIGN §8, §18):
- A split leases a slot per repository and runs in a desk like a joint run. `_run` checks each worktree out at its base,
  detached, makes no branch, skips push verification, and records no branch or unit for the ticket (`runs.branch` is
  empty). Its slots are returned and its desk removed as for any run.
- The splitter has its own template, `runtime.split_cmd`, defaulting to `--agent canopy-splitter`, rather than a
  rewrite of `worker_cmd`. It shares `worker_timeout_minutes`.
- Split attempts are counted per ticket (`policy.max_split_attempts`, default 1), never in a unit's counts.
- `_run` records a child only if it is new to the journal (not already a child, never dispatched) and not the parent,
  besides the checks DESIGN planned. A steered splitter could otherwise claim an existing ticket and pin it to a
  repository. A `failed` split's valid children are recorded too: they exist in the tracker.
- `bad_split` refuses a split of a ticket that has a branch, of a split's child, in a workspace of one, or over fewer
  than two repositories.
- A tracker without label history gets `multi_repo` attention, not the planned tick-wide `skip`: a skip leaves the
  ticket stuck with nobody told, and a human can still split it by hand.
Rejected:
- Running the splitter at the workspace root on the primary clones (PR #54, written before desks): they may be stale or
  on another branch, and the root holds the journal.
- A split per unit: a split is the ticket's and makes the units' work into other tickets.
Revisit: if splits are judged on code the splitter could not read; when a runtime can restrict a create tool's
arguments (then forbid labels on create in the definition).

## D063. A chore names the workspaces it runs in; by default it runs in every one

Context: chores come from the user file, which every loop the operator runs reads, and each workspace has its own
journal (D033). A chore therefore ran in every workspace, each with its own `every_minutes` guard, so a build-health
chore for one CI system would run once per workspace. DESIGN §19 left open whether to scope chores by a list per chore
or a table per workspace.
Decision: a chore may set `workspaces`, a list of workspace names (a map's `[workspace] name`, or a workspace of one's
repository name). It runs only in those; with none it runs in every workspace, as before. A chore not configured for a
workspace is invisible there: no state block entry, `unknown_chore` on `canopy chore run`, nothing on the attention list.
Rejected:
- A `[workspaces.<name>.chores.<chore>]` table per workspace: every chore written once per workspace, and the user file
  learns a second layout for one key.
- A global journal of chore runs shared by workspaces: the journal is per workspace (D053), and a second one would need
  its own locks and migrations.
Revisit: if operators keep many chores that differ by workspace (then a table per workspace).

## D064. The desktop sink ships inside canopy as a script; the Slack sink stays its own distribution

Context: the operator wants desktop notifications before Slack (REQUIREMENTS N2), and a wrapper script of their own
is a custom layer H2 rules out. D035 and D041 made the Slack sink a separate distribution so that the harness never
holds a secret or opens a connection.
Decision (DESIGN §20): `canopy-notify-desktop` is a module of canopy (`canopy.notify.desktop`) with a console script in
canopy's own install. It runs only as a configured sink command, like any other, and passes the title and body to
`notify-send` or `osascript` as arguments. The Slack sink stays a uv workspace member, `canopy-notify-slack`, whose
script canopy's install also provides.
Rejected:
- A second workspace member for the desktop sink: it holds no secret and needs no network, which are the reasons the
  Slack sink is separate; a distribution of its own would add packaging for nothing.
- `notify.cmd` pointed at `notify-send`: it takes arguments, not stdin, so it needs a wrapper of the operator's.
Consequences: one `uv tool install` puts `canopy`, `canopy-notify-desktop`, and `canopy-notify-slack` on `PATH`.
Revisit: if a desktop sink needs a dependency the harness should not carry (then a workspace member like Slack's).

## D065. The reviewer reads its checkout through a link in a directory of its own; reviews name their repository

Context: DESIGN §21 put the reviewer's working directory outside the checkout, so that a PR cannot supply the
runtime's configuration, and left open how the reviewer then reads the checkout and how reviews work in a workspace of
several repositories. The worker's `external_directory: deny` refuses paths outside the working directory, and the
desk canary (D059) showed OpenCode lets edits through a link inside it.
Decision (DESIGN §21):
- `_review` makes `<state_dir>/reviews/<id>/` holding one link, `checkout`, to the slot, and runs the reviewer there
  with `external_directory: deny`. The prompt names the link. The directory is removed, never following the link,
  when the run ends or reconcile closes it.
- `canopy review run` takes `--repo`, required in a workspace of several (`unknown_repo` otherwise), and leases from
  that repository's pool. A PR of a repository outside the workspace still fails at the fetch.
- A running review counts toward `max_workers` in dispatch's `capacity` guard and the state block's capacity, since it
  holds a slot.
Rejected:
- `external_directory: allow`: the reviewer could read anything on the machine, such as the operator's home.
- No checkout, MCP reads only: kept as the fallback if the reviewer canary fails.
Revisit: if the reviewer canary fails (then MCP reads only); if reviewers need to run the PR's tests (then the
operator's own definition, as DESIGN §21 says).

## D066. Pool sizes are declared in the user file; `workspace sync` converges on them and on the map

Context: the operator wants the workspace's repositories and treehouse slots managed declaratively. The map already
declared the repositories, but sync only added clones, and a pool's size was treehouse's `max_trees`, which treehouse
reads only from a repository's committed `treehouse.toml` or the operator's treehouse config, with no flag or variable
to set it per command.
Decision (DESIGN §18):
- `capacity.slots_per_repo` and `[capacity.repo_slots]`, user-only, declare each workspace pool's size. Unset, the
  default, leaves a pool unmanaged. A workspace of one's pool is never sized: it may be the operator's interactive one.
- canopy enforces the size itself: a lease that would grow a pool past it is `no_slot`, and a slot treehouse makes
  anyway is returned and destroyed. `max_trees` stays treehouse's; sync reports when it is below the declared size.
- `canopy workspace sync` converges: it fills pools by leasing as `canopy-sync` and returning, trims them with
  treehouse's unforced `destroy`, and removes clones the map dropped. Removal needs the clone clean, with no stash and
  no commit missing from its remote-tracking refs, and every slot destroyed unforced; anything else is kept, and sync
  exits 1. It holds the tick lock.
- Repositories can be added by clone URL, `canopy workspace add` or `canopy init --workspace URL...`, which write the
  map and sync, so a workspace goes from an empty directory to sized pools in one command. The map stays the record:
  the command appends tables to it, rather than keeping a list of its own.
Rejected:
- Sizes in the map: a commit to a shared map would set how much of the operator's disk and machine canopy uses, which
  TRUST_MODEL T7 keeps user-only, like the rest of `capacity`.
- Writing `max_trees` into a `treehouse.toml`: the repository's file is committed and shared, and the user-level file
  is every pool's, the interactive ones included.
- Removing on request only (`sync --prune`): the operator chose convergence; the safety checks replace the flag.
- A treehouse command to create slots: there is none; leasing and returning is how a slot is made ahead of a run.
Revisit: if treehouse gains a per-command `max_trees` or a way to create slots, use it; if removal keeps a clone the
operator considers disposable often enough to be friction, add a flag that skips the stash or unpushed check.

## D067. Releases ship one executable per platform, built by CI and copied to the machine that runs canopy

Context: D046's install is `uv tool install git+https://...` from a private repository, so the machine that runs canopy
needs a git credential for canopy's own repository, and uv and the package index besides. The operator wants a machine
that holds no credential for this repository, which is D046's revisit condition.
Decision (DESIGN §5):
- A release is a single executable per platform: linux-x86_64, linux-aarch64, macos-aarch64. It is a pex
  (`pex-tool/pex`) in venv mode inside a scie, holding a python-build-standalone interpreter, canopy,
  canopy-notify-slack, and the dependencies `uv.lock` pins, with their hashes. `scripts/build-binary.sh` builds it
  from `uv build` and `uv export`; pex runs through `uvx` at a pinned version, so it is a build tool, not a dependency.
- Pushing a tag `vX.Y.Z` that matches `pyproject.toml`'s version runs `.github/workflows/release.yml`: it builds on
  each platform's runner, runs the install check against each executable, and attaches them with their checksums to a
  GitHub Release. It uses only the job's own token.
- The operator downloads a release where they are signed in to GitHub and copies the file to the machine that runs
  canopy. That machine needs no credential, no Python, no uv, and no network for the install.
- The git install stays for anyone who has the credential.
Rejected:
- PyInstaller, Nuitka onefile: `sys.executable` is the frozen program, so `sys.executable -m canopy`, how dispatch,
  chores, and reviews start their runs, does not work.
- shiv, a plain zipapp, a pex without venv mode: `sys.executable` is a bare interpreter that cannot import canopy.
- PyApp, uvbox: they install on first run from the network.
- Wheels attached to the release, installed with `uv tool install ./canopy-*.whl`: still needs uv and the index on the
  machine, resolves afresh rather than from `uv.lock`, and resolves `canopy-notify-slack` from PyPI, where anyone can
  register the name, whenever its wheel is left out.
- Public release assets: the executable holds the source.
Revisit: if a platform needs an older glibc than its wheels allow (pin pex's target with `--complete-platform`); if
the machine that runs canopy should fetch releases itself (then a read-only credential, or a store it already uses);
with D046, before any public release.

## D068. The migrations are squashed into one for v0.1, and older journals are not upgraded

Context: nine migrations had built the schema, two of them (0005, 0008) moving data between shapes the code no longer
reads. Every fresh journal replayed all nine, and the docs explained columns by the migration that added them. No
journal outside development needs to survive the upgrade.
Decision: `migrations/0001_init.sql` creates the schema as of v0.1 directly; 0002 to 0009 are gone. The schema is the
same as the nine produced, column for column and index for index, so the code is unchanged. A journal that applied the
old series fails to open with the `MigrationError` for migrations this canopy does not know, and the operator moves
`<state_dir>/canopy.db` aside to start a fresh one. While a run the old canopy started is alive, the error is D060's
instead, naming the run, so the journal is never moved aside under a worker that a fresh journal would not know about.
After this, the rule holds again: never edit a shipped migration.
Rejected:
- Adopting a journal at exactly the old 1 to 9 by rewriting its `schema_migrations`: code kept only to carry
  development journals across one release.
- Refusing old journals with an error of their own: the generic one already names the cause.
Consequences: a journal from before v0.1 loses its attempts, cursors, and notified items when moved aside; the world
facts are re-read from their sources. `repo` in `ticket_units` and `run_slots` stays nullable, as the old series left
it, though canopy never writes null there; tightening it is a migration of its own. A journal that applied only the
old 0001, from M0 and never opened since, is taken as current and fails at its first query instead.
Revisit: never for v0.1; a later squash needs its own decision and a plan for the journals then in use.

## D069. A merge conflict is a unit's phase, `conflicted`, handled by `resume`

Context: the phase table had no row for a PR that conflicts with its base. GitHub runs no `pull_request` checks on a
PR it cannot merge, so such a PR derived as `ci_running` with nothing running, or as green from an earlier head's
results, which raised `needs_reviewer` or `ready_to_merge` for a PR nobody could merge. agent-orchestrator tracks
mergeability for the same reason (PRIOR_ART "In prompts").
Decision (DESIGN §7):
- `conflicted` is a unit's phase, between `pushed_no_pr` and `ci_running`. The overseer derives it when GitHub reports
  the PR conflicting (`mergeable` false, `mergeable_state` `dirty`), before reading checks or reviews, so it wins over
  every CI and review phase. A mergeability GitHub has not computed yet is not a conflict.
- The action is `resume`, with context naming the conflict and the base, and the same `--base` for a stacked PR. The
  worker merges the base in and pushes without force, as it already does when a stacked PR is retargeted (D045). New
  review comments or findings ride the same run with their cursor.
- A conflict has no cursor. It is a state of the PR, not an item with an id, so it is new for as long as it lasts.
  The `resume` attempt limit bounds a base that keeps moving (D030).
- The harness adds only the phase name. It cannot read mergeability (D003), so there is no guard; the phase is the
  overseer's reading, like every other.
Rejected:
- A `merge-base` dispatch kind with its own prompt and limit: `resume` already merges the base in, and a kind is a
  guard, an attempt count, and a prompt to keep for the same work.
- Rebasing: the push would need force, which workers never use.
- Attention only: merging the base in is a change the author makes without a decision. A conflict that does need one
  ends the run `blocked`, which raises attention already.
- Folding it into `ci_red`: it would spend `fix-ci` attempts, and key newness on a check run that never ran.
Consequences: conflicts spend `resume` attempts, shared with review comments and replies, so a long-lived PR on a busy
base reaches `max_resume_attempts` sooner.
Revisit: if the decisions corpus shows conflicts using up `resume` attempts that review comments needed; then a limit
of their own.
