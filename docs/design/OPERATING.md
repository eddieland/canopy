# Operating canopy

Part of the canopy design, normative like all of it: the state model, configuration, the agent runtime, the attention
list, failure handling, and open questions. Sections are numbered across the whole design; the [README](README.md) has
the map. Previous: [The loop](LOOP.md). Next: [Trackers and workspaces](WORKSPACES.md).

- [11. State model](#11-state-model)
- [12. Configuration](#12-configuration)
- [13. Agent runtime](#13-agent-runtime)
- [14. Attention list](#14-attention-list)
- [15. Failure handling](#15-failure-handling)
- [16. Open questions](#16-open-questions)

## 11. State model

The journal records the loop's own facts (§4 principle 1): what each tick saw, decided, and dispatched, and what came
back. The schema is in `migrations/`, squashed once for v0.1; a journal from before the squash is not upgraded (D068).

What it records, and why:

- **Ticks**: each tick's status, summary, what it read up to (§6 step 3), and, for a tick `canopy loop` ran, what woke
  it (§6), so spend can be split by what it bought. A tick that cannot take the lock writes nothing.
- **Tickets and units**: each ticket seen, with its derived phase, its branch, whether it is done or forgotten (§22),
  and its cursors; each unit, a ticket's work in one repository (§18), with its branch, PR, phase, and cursors (§7).
- **Runs**: every worker, plan, review, and chore run (§19, §21), with its status, a summary of its result, and
  each slot it leased. Capacity, crash detection, attempt counts, and the CI cooldown are derived from runs, never
  stored (D030); a unit's limit adds the operator's grants.
- **Cost**: what the runtime reported for each tick's overseer and each run (§13), nothing when it reported nothing.
- **Grants** of attempts, plan runs, and review runs (§21, §22, §25), only ever added to; and the follow-ups a run
  filed, written only from its validated result (§18).
- **Decisions**: each overseer decision and its rationale. The audit log, the attention list's source (§14), and the
  prompt-evaluation corpus.
- **Notifications**: what each sink was told, so an open item is notified once per sink (§14, §20).
- **Messages** (§22), **starts** (§22, never deleted: a stopped ticket stays private), the **pause** (§6), **notices**
  (§8, at most one in force), **plan threads** (§25), and **agent memory** (§28, empty while memory is off).

The journal never stores credentials or raw CI logs, and a run's result is kept only as a summary.

`canopy decisions [TICK]` prints a tick's overseer cost and decisions: the way to read a dry run's plan.

`canopy spend` weighs what agent runs cost against what they got done, by day over a window, so that comparing two
windows tells whether spending more bought more. Every figure counts a run on the day it started, in the local time of
the machine canopy runs on, as the operator's own day is. A ticket counts as done by its newest `done` decision in the
window, `merged` and `closed` alike, since a tracker that closes a ticket when its PR merges closes most before the loop
sees the merge. Spend per ticket done divides the window's whole spend, overseer and chores included. A tool's share of
context is measured in characters it returned, since the runtime does not attribute tokens to tool results, and is
labeled an estimate wherever shown (MEASUREMENTS 2026-10-13).

`canopy health` reads the same window for how runs ended: each kind's runs by status and cost, the newest failures,
and the overseer's asks a guard refused. A failure is a run that did not do what it was started for: a tick not closed
`ok`, or a run ended `failed`, `unknown`, `unpushed`, `crashed`, or `timeout`. With `canopy spend --json`, it is what a
chore that looks at canopy itself reads (`examples/chores/`).

Two more read-only commands serve those chores. `canopy config show` lists each number, switch, and choice in the
merged config with its default, bounds, and the file that set it; text, commands, and paths are left out, since they
may carry a host or a token and an agent reports what it reads. `canopy agents` asks the runtime what each of canopy's
agents is offered, MCP servers and skills, once it has merged the operator's own runtime config into canopy's
definitions, so a recommendation to deny one rests on the merge the runtime makes, not on canopy's files alone.

## 12. Configuration

Configuration is layered. Each layer overrides the one before it, key by key:

1. Built-in defaults.
2. **Workspace file**, `canopy-workspace.toml` at the workspace root (§18): shared by everyone who runs canopy on the
   workspace, and committed when the workspace is itself a repository. canopy reads no config from a code repository:
   there is no `canopy.toml` (D016).
3. **User file**, `$XDG_CONFIG_HOME/canopy/config.toml`: personal, never committed, optional. It serves every
   workspace, so it holds what is the same in all of them.
4. **Private file**, `<state_dir>/config.toml`: the workspace's own file for the operator alone, never committed. It
   holds what belongs to one workspace, such as its queue labels, its repliers and reviewers, and its capacity.

At least one of the user file and the private file must exist. `examples/config.toml` lists every key.

**Scope.** Every key is shared or private. A shared key may be set in any file; a private key only in the user file or
the private file, and a workspace file that sets one is a config error naming the key, so canopy refuses to run.
Whoever controls a shared workspace file (anyone who can push to the repository holding it) must not run commands,
choose prompts or models, spend money, authorize anyone, decide what is said in the operator's name, or loosen a
guard; every key that does is private (TRUST_MODEL T7). Among them are every `runtime`, `notify`, `connect`,
`chores`, `review`, `serve`, `memory`, `paths`, `capacity`, and `loop` key, the queue labels, the repliers and trusted
reviewers, the comment marks and commit trailer, `trust.rebase`, and the plan triage. Unknown keys are errors in every
file, and a removed key is an error that says what to do instead.

**The private file's provenance.** The private file is under the workspace root, which may be a checkout of a shared
repository, and its keys run commands. So whenever config is loaded, canopy refuses a state directory any of whose
files git tracks, and refuses when git cannot say; the private file must be a regular file of the operator's, not a
symlink, that no one else can write (§18, D053). A sandboxed run can neither read nor write it (§24).

Secrets (the listener secret, Slack credentials) and the sandbox templates are files in the user config directory, not
keys, shared by every workspace's runs.

Rules:

- **Queues are per operator.** A ticket carrying any of `tracker.labels` is in this operator's queue. Two operators
  must never share a label: the guards (one worker per ticket, attempt limits, cooldowns) see only the local journal.
  canopy cannot detect sharing; it is the operator's responsibility (TRUST_MODEL §7).
- **The repository may only tighten policy.** A workspace file's `policy.*` value is used only if stricter than the
  built-in default; the user and private files may set any value. This stops a commit from loosening limits for
  operators who never set them (TRUST_MODEL §3). Scope and tighten checks run per file, so an error names its file.
- Values that reach git's argv, a prompt, or the web UI's links (`trust.branch_prefix`, the comment marks, the commit
  trailer, `tracker.ticket_url`) are validated at load.
- The commit trailer keys set the `Co-authored-by` trailer a worker adds when the runtime adds no attribution of its
  own (§8, TRUST_MODEL T5). It names agent work, never a person: it is how a reader tells the work is an agent's.
- `trust.rebase` lets workers rebase and push with `--force-with-lease` instead of merging a base in, for hosts that
  refuse merge commits; `_run`'s own push leases the commit the run started from (§8, TRUST_MODEL T1).
- `canopy init` sets up a workspace in the current directory or fills in the one it is inside (§18). Never in the home
  directory or one that already has a `.canopy/`, and in a git checkout only with `--workspace`: canopy writes nothing
  into a code repository. It writes the private file, readable only by the operator, and a workspace file where
  missing, never the user file, never over a file, and no key whose default serves, since a written default is pinned
  and a later canopy's never reaches it. It warns about copies of canopy's agent definitions in the OpenCode config
  (§13) and, unless `worker_cmd` is sandboxed, prints the prefix to add: the sandbox is opt-in (§24).
- `canopy sandbox setup` copies the sandbox templates to the user config directory, never over one there, installs the
  pinned `srt`, and checks what needs root to install; it exits 1 while anything left would make the sandbox weaker
  than §24 says. It writes no config (D117).
- Pool sizes (`capacity.slots_per_repo`, `[capacity.repo_slots]`) are private, so a team's map cannot grow the
  operator's disk use; unset leaves pools unmanaged (§18). `pools.backend` may be switched with runs in flight.
- Remotes should be HTTPS with a credential helper: a sandboxed worker cannot reach the SSH agent socket. `canopy
  workspace sync` warns about push URLs over SSH; nothing else checks the remote.

**Command templates.** A template is split into words with `shlex`, and `{prompt}`, `{definitions_dir}`, and
`{title}` are replaced inside each word. No shell runs, so the prompt is always exactly one argument (D023). Every
agent template contains `{prompt}` exactly once and `{definitions_dir}` (§13) at least once. canopy cannot tell where
the runtime reads it: a custom template, such as a sandbox wrapper's, must still set `OPENCODE_CONFIG_DIR` to it, or
OpenCode runs its default agent, which allows everything (D040). `notify.cmd` is split the same way and takes no
`{prompt}`. `runtime.worker_cmd_prefix` and `worker_cmd_suffix` wrap every command a worker run starts (worker, private
worker, and plan) from one key, so a sandbox wrapper (§24) cannot miss one; they may not hold `{prompt}`. The
overseer's, a chore's, a review's, and a triage's templates are not wrapped: each takes a different sandbox role, or
none.

**Prompt overrides** in `paths.prompt_overrides` replace files of the same name in `prompts/`. An override must keep
what the guards rely on: an overseer override passes `--label` on every `canopy dispatch`, and a worker override
includes `{{LABELS}}` and the authorization check that uses it, or the dispatch is refused as `bad_prompt` (§8, D051).
In the user file, `paths.*` values must be absolute or start with `~`, since a relative path would let a shared
workspace supply them; in the private file a relative value resolves against the state directory, never the workspace
root (TRUST_MODEL T7). The state directory is always `<workspace>/.canopy/` (§18), written `<state_dir>` here.

`paths.worker_instructions` names a short file of the operator's standing instructions, rendered into every worker
prompt, after the obligations (§8). Prefer it to an override, and a skill for know-how (§13). A file
canopy cannot use refuses the dispatch as `bad_prompt` rather than running a worker without it. A passing condition,
such as a CI outage, belongs in a notice to workers (§8). `paths.overseer_instructions` is the same for the overseer:
rendered at the end of its prompt, which comes first, and a file canopy cannot use fails the tick before the overseer
starts. Neither reaches the other's prompt.

`tracker.provider` is a free-form name the harness never branches on; prompts use it to name the `tracker-<provider>`
skill, which canopy puts in the overseer's definition when it ships one (§13). `tracker.query` finds candidates; it
does not authorize them (§17). It is shared though the overseer reads every ticket it returns before checking labels,
an exposure stated in TRUST_MODEL T7's residual.

## 13. Agent runtime

OpenCode. The harness depends on one capability: run a named agent non-interactively in a given cwd with a prompt and
read its stdout. MCP connectivity, OAuth, and tool permissions are the runtime's job. The runtime is swappable by
editing the command templates (§12) and the `runtime` package (§5). Its surface, which the rest of canopy calls, names
no runtime, and holds what any runtime's output is bounded by; its implementation alone knows OpenCode: its events, the
format of canopy's definitions, and the config files the shadowing check reads (D009). A new runtime is a new
implementation bound in its place. No interface: one runtime at a time.

Agent definitions ship in `agents/`:

- `canopy-overseer`: read-only tools plus bash restricted to `canopy *` and `treehouse status*`, nothing outside the
  workspace, one command per bash call. Rules `deny`, never `ask`: an `ask` ends the run under `opencode run` (D021)
  and loses every decision not yet recorded. MCP: the tracker's read tools only (T6); of GitHub, its reads of PRs and
  branches, and of issues only when they are the tickets.
- `canopy-worker`: edit and bash within the worktree. MCP: the tracker (comments, labels, follow-ups), GitHub (open and
  update a PR, read reviews and checks); merge, review submission, closing, transition, delete, fork, API file and
  branch writes, and other agents or workflow runs denied by name (D084).
- `canopy-reviewer`: no edits, shell, or subagents; MCP read tools only (§21): of the tracker's server, its read tools
  by name, and of GitHub, issue reads only when they are the tickets.
- `canopy-chore`: no edits, shell, or subagents; MCP write tools denied by name (§19).

None has web tools: every definition denies `webfetch`, `websearch`, and `codesearch` (TRUST_MODEL T1, D077).
A tool an agent never calls is denied whole, since the runtime sends every schema it allows on every call and none it
denies: GitHub's tools no prompt asks for, by name, as the server's own name is the operator's.

### What a run prints

Every agent's output is read the same way, whether the template asks for plain text or JSON events. A JSON result
contract (§8, §18, §19, §21) is the last line of the text that starts with `{`; lines after it that do not are passed
over, since a runtime or plugin may print after the agent's last word. A last object that does not validate is no
result: canopy never falls back to an earlier one, which may be an example the agent quoted or a result it took back.
The overseer's done token is a plain line anywhere in its final message (§6).

From the events the harness also reads, each validated (D026), the session id, the cost, the context used, and the
tool calls by tool, a skill's by the skill it loaded, and records them on the tick or run (§11) with the digest of the
definitions it loaded, so a prompt or definition change splits runs into before and after. Figures that do not
validate make the run report no cost rather than too little, and a template that asks for no events records no cost.

The default templates title each session as canopy names it: a worker run by ticket, kind, and title; a tick by its id,
what woke it, and what it faces; a chore or review by its name or PR. A title never starts like an option.

### Where the runtime finds canopy's definitions

canopy snapshots its bundled agents and skills into the state directory, named for a digest of their contents, and the
templates point the runtime at it (§12). The snapshot is written whole, never changed, and readable only by the
operator, so overlapping runs never load a partial set; one that is a symlink, someone else's, or open to others is
refused, failing the tick or making the run `crashed` (D040). Two definitions are rendered from config, so a change to
their inputs makes a new snapshot:

- `canopy-worker-private` gets the tracker's MCP server and only the tools of it a private worker may call (§22).
- `canopy-overseer` gets the tracker's MCP server and only its read tools, and the overseer's prompt, or the
  operator's override (§12), as its body, then the shipped `tracker-<provider>` skill if any, and then no skill tool,
  having nothing left to load. The body is the system prompt the provider caches across ticks; a tick's message is its
  state block alone (§6). An override canopy cannot read fails the tick and every run started from it, rather than
  running without the prompt.

Nothing is installed into repositories. OpenCode merges canopy's definitions after the repository's config, so a
repository's definition of a canopy agent could loosen its rules (D044). The harness refuses to start an agent where
the config in its start directory defines one of canopy's agents: the overseer's refusal fails the tick, and a
worker's is a `crashed` run whose slot is returned. A private run (§22) is also refused where that config names any
tool of the tracker's MCP server, since a rule merged after canopy's could reopen a write tool.

Customizing canopy is adding skills where the runtime already looks, in the repository or the operator's home; canopy
turns none off, but for the overseer whose body holds the tracker's skill. A repository can also define its own
agents under other names, MCP servers, and permissions (TRUST_MODEL T7). `runtime.pr_skill` names a skill workers
open PRs with (§8); prefer that to a prompt override.

### What OpenCode does with a plugin

canopy ships no plugin. One in the snapshot would rest on this, read from OpenCode's source at 1.19.3 (2026-10-19) and
read again before one is built: OpenCode loads plugins from every config directory, the snapshot's last, so a
repository's run first; a hook that throws fails the tool call after the tool has run; an MCP tool's result is
truncated after the hook, keeping the head. With any plugin configured, OpenCode waits on an npm install into every
writable config directory it loads, so a snapshot that ships a plugin must be unwritable. A variable canopy sets for a
run reaches a sandboxed agent unchanged.

### Each agent's model

Designed, not built (REQUIREMENTS R23). Until it lands, an agent runs on OpenCode's default unless its template passes a
model, and the journal cannot say which.

The operator wants to canary a model, running one ticket's workers on another and comparing what they did and cost,
and to choose each agent's model on its own, such as a reviewer on another model than the worker's (§21). The design
promises:

- **The operator alone chooses.** A run's model is its ticket's override for its agent, else that agent's default in
  `[runtime.models]`, else the runtime's default, fixed when the run starts. `runtime.models` is private (T7): a model
  is what the operator's spend buys, and its provider is sent the ticket and the code. The override is set only by the
  operator's `canopy model`, refused inside an agent run (T1); the overseer, a dispatch, and ticket text choose none.
- **What is recorded is what runs.** canopy writes the model into the agent's rendered definition, so each set of
  models gets its own snapshot (D040). A template's model option would override it unseen, so any `runtime` template,
  prefix, or suffix that passes one is a config error. Each run, review, chore run, and tick records the model asked
  for, and `canopy spend` breaks cost down by it.
- **No silent fallback.** Before a run starts, canopy checks its model against the list OpenCode would look it up in.
  An unlisted model, or a list that cannot be read, refuses the run with an attention item, spending no attempt and
  leasing no slot, so the work resumes once the model is back. It never falls back to the default, since a canary's run
  on a model nobody chose would read as the canary's.

The PR that builds it proposes T1, T5, T7, and T8 to match. Rejected: a model chosen by the overseer or ticket labels
(T1); a list of models shipped with canopy; one override for all of a ticket's agents.

### The operator's skill

`canopy skill` prints a skill that teaches an agent in the operator's own session the canopy CLI and how to read the
journal read-only. canopy installs it only when asked; it is not in the snapshot and grants nothing. Shell completion
leaves out ticket keys, which would open the journal on every Tab, and the commands only the overseer runs.

## 14. Attention list

After every tick the list is rendered to `<state_dir>/attention.md`, readable only by the operator, one line per item
grouped by reason. Items disappear when their cause is gone; there is no manual dismissal. `canopy status` prints it
too, with the loop's state and the running and recent runs.

Reasons are the phase table's attention rows (§7), the run reasons below, `attempt_limit`, and those the sections that
raise them define: `canopy_unavailable` (§6), `fix_ci_override` and `notice_rerun` (§8), `repo_missing`, `multi_repo`,
`follow_up_filed`, and `follow_up_unrecorded` (§18), `chore_failed` and chore findings (§19), `review_failed` and
`review_limit` (§21), `awaiting_reply` (§22, §25), `plan_review`, `plan_changed`, and `not_trivial` (§25),
`memory_proposal`, `lesson_review`, and `lesson_wrong` (§28), and `drafts_waiting` (§29). An item about one unit names
its repository, shown as `KEY (repo)`.

**Raised by the harness.** Every tick, after reconcile, for a ticket not done, its latest run's status maps to a
reason: `crashed`, `unpushed`, `unknown_result` (for `unknown` or `timeout`), or `worker_failed` (for `failed`). The
cause is gone when a newer run starts or the ticket is done. The overseer does not dispatch such a ticket again until
an authorized replier comments, or the operator sends a message, after the run ended (§22, D093): that is how a human
says "try again". `blocked` and `stopped` raise nothing, nor does a ticket the operator stopped (§22). The harness also
raises `awaiting_reply` for a started ticket's or a planner's unanswered question (§22, §25), `repo_missing` for a
mapped repository with no clone (§18), and `canopy_unavailable` for a tick whose `canopy --version` check failed (§6
step 5). It raises `follow_up_filed` about a ticket not done whose runs filed follow-ups since its latest forget, naming
each with its repository while canopy has no run of it, no start record, and no mark that it is done: a queue label,
which the overseer then dispatches on, or the operator's start ends its wait. Items have no dismissal, so a follow-up
the operator leaves stops being asked about when its parent is done or forgotten. It raises `follow_up_unrecorded`
about a ticket whose runs reported tickets the journal did not record, until the ticket is done or forgotten (§18).

**Recorded by the overseer.** The overseer records an item with `canopy attention <KEY> <reason> --detail ...`, every
tick its cause holds. Items are stored as decisions, not a table of their own (D020). The current list is the attention
decisions of the latest `ok` tick, so an item disappears the first tick that does not record it, and a failed or
`skipped` tick leaves the previous list standing; `canopy_unavailable` is added to it while it is the latest tick's.
The state block lists the overseer's open items (§6 step 4), so it records each again until it sees the cause gone. An
item's age runs from the first tick of its unbroken run. `attempt_limit` is recorded by the overseer when the state
block shows a ticket at its limit, and by `canopy dispatch` with an `attempt_limit` refusal, and lasts while the
overseer keeps asking.

**Notification.** An item is identified by its ticket, reason, and repository; rewording its detail does not make it
new. Each sink (§20), `notify.cmd` among them, keeps its own record of what it was told, and each tick sends it the new
and resolved items, updating the record only when the sink succeeds. So a failed notification is retried next tick, an
open item is never notified twice, and an item that returns after going away is new again.

## 15. Failure handling

- Worker crash: detected in reconcile; what is left of the worker is killed, every slot tidied (§8 step 6) and
  returned, and the ticket goes to attention with `crashed`. The harness never restarts a run; the overseer waits for an
  authorized reply (§14), and every kind's attempt limit in code stops an overseer that redispatches anyway (D030).
- Worker exits without a result, times out, reports `failed`, or leaves commits unpushed: `_run` returns the slot and
  records the status; the ticket goes to attention (§14).
- Stale lease without a run: returned in reconcile.
- treehouse unavailable or failing in reconcile: the tick closes `reconcile_failed`; the overseer does not run.
- `canopy --version` fails from the overseer's environment: the tick closes `canopy_unavailable`, the overseer does not
  run, and the item of that name stays until a tick ends otherwise (§6 step 5).
- Overseer timeout or bad output: the tick closes `overseer_failed`; nothing is dispatched; the next tick retries.
  Three consecutive ticks not `ok` send a `loop.failing` notification once per streak, and `loop.recovered` at the next
  `ok` (§20); no attention item, since a failing loop cannot add to the latest `ok` tick's list.
- Overseer left a duty undone (the query when due, a ticket's decision, a due chore's): the tick closes
  `overseer_failed`, naming each (§6 step 5). What it dispatched stands, and the next tick owes the same duties.
- Tick code raises an unexpected exception: the tick closes `error`, its summary the exception's type and message, so
  the journal keeps the cause when the logs cannot; the traceback goes to `canopy.log`, and the loop goes on.
- MCP unavailable: the overseer records a tick-wide `skip`; the tick closes `skipped`, no decisions are made on partial
  data, and the attention list stays as it was.
- Overseer asks for something the guards refuse: the refusal is recorded as a decision with the guard's reason.
- An unhandled error in a tick `canopy loop` runs: the traceback is logged and the loop goes on; the next tick closes
  the row as `abandoned` (§6).

## 16. Open questions

- Whether `ask` permissions in OpenCode agent definitions block or auto-deny under `opencode run`. Answered from
  OpenCode's source: `ask` is auto-rejected and `deny` is enforced (D021). The live canary is opt-in; its first real
  run confirms or overturns this.
- Whether a Slack notification path should use a sink command or the overseer posting via MCP. Answered (§20, D035): a
  sink command, with a Slack sink shipped in canopy. The overseer does not post.
- Whether `merged` should trigger a tracker transition. Default no; humans own ticket state.
- One operator on several repositories. Answered by the workspace (§18): one queue, and state per workspace under its
  root. Repositories that are not one queue go in separate workspaces, each with its own journal and locks.
