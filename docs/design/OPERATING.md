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

- **Ticks**: each tick's status, summary, what it read up to (§6 step 3), whether it ran the overseer (§39), and, for
  a tick `canopy loop` ran, what woke it (§6), so spend can be split by what it bought. A tick that cannot take the
  lock writes nothing.
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

`spend.monthly_budget_usd` is what the operator means a local calendar month of runs to cost. `canopy spend` and the
spend page track the month so far against it, with the pace it is on once its first day is over, and a sink that takes
`loop` hears once when the month reaches it, again only for a budget raised past it. `spend.budget_alerts` adds other
percentages of the budget, each told once a month: one message for the highest reached, and only for more dollars than
the sink was last told, so a raised budget or an added alert is news when the month reaches it and a lowered one is not.
It is a number to watch, never a brake: nothing pauses or refuses a run over it (ROADMAP's deferred spend-paced loop
would be that).

`canopy health` reads the same window for how runs ended: each kind's runs by status and cost, the newest failures,
and the overseer's asks a guard refused. A failure is a run that did not do what it was started for: a tick not closed
`ok`, or a run ended `failed`, `unknown`, `unpushed`, `crashed`, or `timeout`. With `canopy spend --json`, it is what a
chore that looks at canopy itself reads (`examples/chores/`).

Two more read-only commands serve those chores. `canopy config show` lists each number, switch, and choice in the
merged config with its default, bounds, and the file that set it; text, commands, and paths are left out, since they
may carry a host or a token and an agent reports what it reads. `canopy config commands` shows those commands,
rendered as a run would start them, to the operator alone: it is refused inside a tick or a run. `canopy agents` asks
the runtime what each of canopy's agents is offered, MCP servers, skills, and its own tools, once it has merged the
operator's own runtime config into canopy's definitions, so a recommendation to deny one rests on the merge the
runtime makes, not on canopy's files alone.

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
reviewers, the comment marks and commit trailer, and `trust.rebase`. Unknown keys are errors in every
file, and a removed key is an error that says what to do instead.

**The private file's provenance.** The private file is under the workspace root, which may be a checkout of a shared
repository, and its keys run commands. So whenever config is loaded, canopy refuses a state directory any of whose
files git tracks, and refuses when git cannot say; the private file must be a regular file of the operator's, not a
symlink, that no one else can write (§18, D053). A sandboxed run can neither read nor write it (§24).

Secrets (the listener secret, Slack credentials) and the sandbox templates are files in the user config directory, not
keys, shared by every workspace's runs.

**From the web UI.** The Limits and trust page under Settings (§22) edits a few keys of the workspace's private file
in place, and no others (D128, TRUST_MODEL T8). They are named one by one in `canopy/serve/config_edit.py`, never by
section, so a key added to a section later is not editable until it is named there. A limit may be raised or
lowered, but the page cannot loosen it past its bound; the file can set any value, and the page may still tighten a
value the file set past the bound. A trust key moves only toward stricter: a config write outlives the listener
secret, and a replier added through a stolen session would go on steering workers after a new secret ended it.

| Key | From the page |
|---|---|
| `capacity.max_workers`, `capacity.slots_per_repo`, each `capacity.repo_slots` entry | at most 32; an unmanaged pool's first count is bounded too |
| `capacity.max_chores`, `capacity.max_reviews` | at most 16 |
| `capacity.max_reviews_per_day` | at most 500 |
| `policy.max_implement_attempts`, `policy.max_resume_attempts` | at most 10 |
| `policy.max_reviews_per_pr` | at most 25 |
| `policy.ci_cooldown_minutes` | at least 5 |
| `loop.interval_minutes`, `loop.idle_max_minutes` | at least 2 |
| `spend.monthly_budget_usd` | at most 10000; raising it keeps a sink from hearing the month reached it |
| `spend.budget_alerts` | any list the loader takes; the 100% alert is sent whatever it holds |
| `policy.stacking` | to `"never"` only |
| `trust.authorized_repliers`, `trust.trusted_reviewers` | entries removed, never added |
| `trust.rebase` | to `false` only |
| `trust.commit_trailer` | to `true` only |

The bounds sit well above what one machine runs today, so the page serves the operator's real changes; what they stop
is a stolen session turning spend up without limit. A raise within them outlives a new secret, and that residual is
spend, which the page and the log show. `capacity.repo_slots` is edited as its entries: the page lists the
repositories with a count of their own and takes a name to give another one, so a workspace of many repositories
shows the few that differ from `capacity.slots_per_repo`. A save:

- writes the private file only, never the workspace file (T7), a shared `policy.*` key included, nor the user file,
  which serves every workspace. A key whose value comes from the user file is written to the private file whole, where
  it shadows the user file's for this workspace alone: a list keeps the entries the page did not drop, and
  `capacity.repo_slots` the repositories it did not change. The page names a key's file and says so before the save. A
  private file not there yet is made, the operator's alone (`0600`);
- is edited in place with tomlkit (D129), so the operator's comments, order, and layout stay; a list loses its removed
  entries where they stand, keeping the rest and their comments. A file tomlkit would not write back byte for byte, as
  read, is refused `not_roundtrip` before anything changes, so a save differs from the file only in the values set;
- keeps the file as it was beside it, `config.toml.bak` with the file's mode, replacing the previous save's: the way
  back from a save is to move it over the file and Reload. A save that made the file keeps no backup;
- carries the hash of the private file as the page read it, an empty file's when there is none, and holds a lock
  beside the file (`config.toml.lock`) from reading the file to replacing it, so two saves made on one read cannot
  both pass; a file whose hash differs is refused `stale`, checked again just before the replace, so a hand edit is
  lost only if it lands in that last moment;
- applies the change to a copy beside the file, which `config.load` validates as any `canopy` command would read it,
  and checks every bound on the values the copy loads to, so the rules hold whatever the request's shape; a refusal
  writes nothing and gives the loader's message, naming the private file;
- replaces the file atomically, keeping its mode, and refuses one that is a symlink or not the operator's (D053's
  check, `unsafe_file`), and inside a tick or run (`inside_run`), as the CLI's verbs do;
- logs each change with channel `web`, the key, and its old and new values, then asks the loop to read its config
  again through the same path as Reload (§6). A save whose reload is refused, or never asked for because the server
  stopped between the two, takes effect at the next reload.

There is no CLI verb for it: the operator's editor is the CLI's way, and a `canopy config set` would be in reach of
the overseer's `canopy *` bash rule. Pools: a changed `capacity.slots_per_repo` or `capacity.repo_slots` bounds leases
from the next tick; making or removing slots is still `canopy workspace sync`, which the page does not run.

Rejected: a file of canopy's own layered after the private file (a hand edit to the private file would be silently
overridden), writing the file anew with the stdlib (its comments lost), and writing the user file, whose change would
reach every workspace.

Rules:

- **Queues are per operator.** A ticket carrying any of `tracker.labels` is in this operator's queue. Two operators
  must never share a label: the guards (one worker per ticket, attempt limits, cooldowns) see only the local journal.
  canopy cannot detect sharing; it is the operator's responsibility (TRUST_MODEL §7).
- **The repository may only tighten policy.** A workspace file's `policy.*` value is used only if stricter than the
  built-in default; the user and private files may set any value. This stops a commit from loosening limits for
  operators who never set them (TRUST_MODEL §3). Scope and tighten checks run per file, so an error names its file.
- Values that reach git's argv, a prompt, or the web UI's links (`trust.branch_prefix`, the comment marks, the commit
  trailer, `tracker.ticket_url`) are validated at load.
- The commit trailer keys set the `Co-authored-by` trailer git adds to a worker's commits, through canopy's hooks (§8,
  TRUST_MODEL T5). It names agent work, never a person: it is how a reader tells the work is an agent's.
  Left as the default, its name credits the model canopy chose for the worker (§13, Each agent's model), and a
  second trailer that of the planner whose approved plan it follows (§25). `trust.commit_prefix`, private too, is
  text git puts before each subject, `{key}` naming the ticket.
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
`{title}` are replaced inside each word. No shell runs, so the prompt is always exactly one argument, or, in a
template that places no `{prompt}`, as the defaults do, the command's stdin, where no argument limit applies (D023).
Every agent template contains `{prompt}` at most once and `{definitions_dir}` (§13) at least once. canopy cannot tell
where the runtime reads it: a custom template, such as a sandbox wrapper's, must still set `OPENCODE_CONFIG_DIR` to it,
or OpenCode runs its default agent, which allows everything (D040). `notify.cmd` is split the same way and takes no
`{prompt}`. `runtime.worker_cmd_prefix` and `worker_cmd_suffix` wrap every command a worker run starts (worker, private
worker, and plan) from one key, so a sandbox wrapper (§24) cannot miss one; they may not hold `{prompt}`. The
overseer's, a chore's, and a review's templates are not wrapped: each takes a different sandbox role, or none.

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
starts. `paths.reviewer_instructions` and `paths.chore_instructions` are the same for every review and every chore run,
which a file canopy cannot use refuses as `bad_prompt`; a chore's follow its own prompt, which comes first. Each file
reaches only its own role's prompts, and a role without one has no section for them.

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

- `canopy-overseer`: read-only tools plus canopy's own tools, each allowed by name (§27); no shell but the commands the
  operator names in `runtime.allow_bash` (private, T7), nothing outside the workspace, one command per bash call.
  canopy renders those last of its bash rules, after the deny of every other command, since the last match wins and
  its definition is merged after the operator's runtime config, and refuses one that runs a command it is given or is
  the loop's own (TRUST_MODEL T1). Rules `deny`, never `ask`: an `ask` ends the run under `opencode run` (D021) and
  loses every decision not yet recorded. MCP: the tracker's read tools only (T6); of GitHub, its reads of PRs and
  branches, and of issues only when they are the tickets.
- `canopy-worker`: edit and bash within the worktree; `runtime.allow_bash` names commands that beat its bash denies,
  rendered last, with the overseer's checks, and the private worker's the same. MCP: the tracker (comments, labels,
  follow-ups), GitHub (open and update a PR, read reviews and checks, and its issue tools only when they are the
  tickets); merge, review submission, closing, transition, delete, fork, API file and branch writes, and other agents
  or workflow runs denied by name (D084).
- `canopy-reviewer`: no edits, shell, or subagents; MCP read tools only (§21): of the tracker's server, its read tools
  by name, and of GitHub, issue reads only when they are the tickets.
- `canopy-chore`: no edits or subagents, and no shell but its own history; MCP write tools denied by name, and of the
  tracker's server, its read tools only, by name (§19).

Every definition but the overseer's denies canopy's own tools, `canopy_*`; a chore's then allows its history, and the
reviewer's and the planner's canopy's read-only git tools, each by exact name (§27).

None has web tools: every definition denies `webfetch`, `websearch`, and `codesearch`, and code mode's `execute`,
whose code can fetch, so an MCP server an agent needs is set to `codemode: false` (TRUST_MODEL T1, D077).
A tool an agent never calls is denied whole, since the runtime sends every schema it allows on every call and none it
denies: GitHub's tools no prompt asks for, by name, as the server's own name is the operator's, and its issue tools,
from both workers and the planner too, off a GitHub tracker. A pattern that would take one of the tracker's own tools
canopy knows is left out.

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

What the run was offered is recorded beside them: MCP servers, with the rules that leave it only some of one's tools,
skills, and the runtime's own tools. The runtime is asked as `canopy agents` asks it, while the agent starts, by the
run's own command with its agent's run swapped for the runtime's debug commands, so it is asked where the agent starts
and inside any sandbox that wraps it. A run whose command canopy cannot read so, or that the runtime could not answer
for, records why instead, and the run goes on either way.

The default templates title each session as canopy names it: a worker run by ticket, kind, and title; a tick by its id,
what woke it, and what it faces; a chore or review by its name or PR. A title never starts like an option.

### Where the runtime finds canopy's definitions

canopy snapshots its bundled agents, skills, and plugin into the state directory, named for a digest of their contents,
and the templates point the runtime at it (§12). The snapshot is written whole, never changed, unwritable once written
(§33), and readable only by the operator, so overlapping runs never load a partial set; one that is a symlink, someone
else's, or open to others is refused, failing the tick or making the run `crashed` (D040). Definitions are rendered
from config, so a change to their inputs makes a new snapshot. Among them:

- `canopy-worker-private` gets the tracker's MCP server and only the tools of it a private worker may call (§22).
- `canopy-overseer` gets the tracker's MCP server and only its read tools, and the overseer's prompt, or the
  operator's override (§12), as its body, then the shipped `tracker-<provider>` skill if any, and then no skill tool,
  having nothing left to load. The body is the system prompt the provider caches across ticks; a tick's message is its
  state block alone (§6). An override canopy cannot read fails the tick and every run started from it, rather than
  running without the prompt.
- Every definition gets the artifact store's MCP server denied whole, and an agent `artifacts.publish_roles` names its
  tools by exact name and its skill (§38).

Nothing is installed into repositories. OpenCode merges canopy's definitions after the repository's config, so a
repository's definition of a canopy agent could loosen its rules (D044). The harness refuses to start an agent where
the config in its start directory defines one of canopy's agents: the overseer's refusal fails the tick, and a
worker's is a `crashed` run whose slot is returned. A private run (§22) is also refused where that config names any
tool of the tracker's MCP server, since a rule merged after canopy's could reopen a write tool.

Customizing canopy is adding skills where the runtime already looks, in the repository or the operator's home; canopy
turns none off, but for the overseer whose body holds the tracker's skill, and the operator's skill below. A
repository can also define its own agents under other names, MCP servers, and permissions (TRUST_MODEL T7).
`runtime.pr_skill` names a skill workers open PRs with (§8); prefer that to a prompt override.

canopy ships one plugin, `canopy.js`, whose jobs are a clock that tells a running agent the minutes left and a split
that lets an unsandboxed run's first call read its agent's tools and body from the provider's cache; they, and what
OpenCode does with a plugin, are §33.

### Each agent's model

Built as far as each agent's default in `[runtime.models]`, a chore's own model, variants, the ticket's override
from `canopy model` or the ticket's page, the check of a model and its variant before a worker or plan run, and
recording what served (REQUIREMENTS R23). The check before a review, a chore, or a tick's overseer is still to come;
until then such a run on an unlisted model fails as it starts, and one at an unlisted variant runs at the model's
default.

The operator wants to canary a model, running one ticket's workers on another and comparing what they did and cost,
and to choose each agent's model on its own, such as a reviewer on another model than the worker's (§21). The design
promises:

- **The operator alone chooses.** A run's model is its ticket's override for its agent, else that agent's default in
  `[runtime.models]`, else the runtime's default, fixed when the run starts; a chore's own `model` comes before the
  chore's default (§19). A model may name the variant it runs at, such as a reasoning effort, as
  `provider/model@variant`. `runtime.models` is private (T7): a model
  is what the operator's spend buys, and its provider is sent the ticket and the code. The override is set only by the
  operator's `canopy model` or the ticket's page, through one function refused inside an agent run (T1); the
  overseer, a dispatch, and ticket text choose none.
- **What is recorded is what served.** No event names the model a call went to, so canopy reads each run's session
  from the runtime's own record once the run ends: the process that ran it reads it as it closes the run, and the wait
  after a live tick reads the rest, one at a time, never-read runs the newest first, past ones among them. A read
  records each model that wrote a run's replies, a variant other than its default named with it, and what they cost;
  for a run more than one model served, also which wrote each reply, keyed as the log's events key each call.
  `canopy spend` breaks each kind's cost down by model, and the web UI names each run's models on its page, and a
  split run's on its transcript, at each call where the model changed. A read never fails a run or a tick; a session
  the runtime no longer keeps leaves its run unattributed, or as a read before found it, and a failed read is tried
  again later, a few times at most.
- **canopy's choice is the one made.** canopy writes the model, and its variant, into the agent's rendered
  definition, so each set of models gets its own snapshot (D040); a chore with a model of its own runs a copy of the
  chore's definition made for it. A template's model or variant option would override it unseen, so any `runtime`
  template, prefix, or suffix that passes one is a config error, as is a chore's own command that does while it runs
  canopy's chore agent. A chore that runs an agent of the operator's own takes its model there, not from canopy.
- **No silent fallback.** Before a run starts, canopy checks its model against the list OpenCode would look it up in,
  and its variant against the model's, since OpenCode drops an unlisted variant without a word. An unlisted model or
  variant, or a list that cannot be read, refuses the run with an attention item, spending no attempt and leasing no
  slot, so the work resumes once the model is back. It never falls back to the default, since a canary's run
  on a model nobody chose would read as the canary's.

The PR that builds the choosing proposes T1, T5, T7, and T8 to match. Rejected: a model chosen by the overseer or
ticket labels (T1); a list of models shipped with canopy; one override for all of a ticket's agents; recording only the
model asked for, which leaves every run on the default unattributed and splits no run's cost between models.

### The operator's skill

`canopy skill` prints a skill that teaches an agent in the operator's own session the canopy CLI and how to read the
journal read-only. canopy installs it only when asked; it is not in the snapshot and grants nothing, and every agent
canopy ships denies it by name, wherever it is installed. Shell completion leaves out ticket keys, which would open
the journal on every Tab, and the commands only the overseer runs.

## 14. Attention list

After every tick the list is rendered to `<state_dir>/attention.md`, readable only by the operator, one line per item
grouped by reason. Items disappear when their cause is gone; there is no manual dismissal. `canopy status` prints it
too, with the loop's state and the running and recent runs.

Reasons are the phase table's attention rows (§7), the run reasons below, `attempt_limit`, and those the sections that
raise them define: `canopy_unavailable` and `disk_low` (§6), `fix_ci_override` and `notice_rerun` (§8), `repo_missing`,
`auto_maintenance_on`, `multi_repo`, and `follow_up_unrecorded` (§18), `chore_failed` and chore findings (§19),
`review_failed`, `review_limit`, and `review_rebuttal` (§21), `awaiting_reply` (§22, §25), `flaky_rerun` (§23), `plan_review`,
`plan_changed`, and `archive_unpushed` (§25), `memory_proposal`, `lesson_review`, and `lesson_wrong` (§28),
`drafts_waiting` (§29), `connector_failed` (§30), `persona_missing` and `bad_persona` (§31), `model_missing` and
`model_list_failed` (§13), `git_too_old` (§8), `review_waiting` and `review_unsettled` (§34), and
`task_ticket_unrecorded` (§36). An item
about one unit names its repository, shown as `KEY (repo)`. An item about a PR whose latest reviewed commit has a
`high` review (§21), or about its ticket, comes first: within its reason on the list, and in a notification.

**Raised by the harness.** Every tick, after reconcile, for a ticket not done, its latest run's status maps to a
reason: `crashed`, `unpushed`, `unknown_result` (for `unknown` or `timeout`), or `worker_failed` (for `failed`). The
cause is gone when a newer run starts or the ticket is done. The overseer does not dispatch such a ticket again until
an authorized replier comments, or the operator sends a message, after the run ended (§22, D093): that is how a human
says "try again". `blocked` and `stopped` raise nothing, nor does a ticket the operator stopped (§22). The harness also
raises `awaiting_reply` for a started ticket's, a planner's, or a task's unanswered question (§22, §25, §36),
`repo_missing` for a mapped repository with no clone and `auto_maintenance_on` for a clone whose config leaves git's
automatic maintenance on (§18), `git_too_old` while the git on `PATH` is too old for canopy's commit hooks (§8),
`connector_failed` about the workspace, one item naming
every source whose run that tick read less than it was asked (§30), and `canopy_unavailable` or `disk_low` for a tick
whose check of the overseer's tools or free disk failed (§6 step 5). Follow-ups a run filed are an event, not an item:
the sinks hear of them once, as `follow_ups.filed` (§20), since nothing canopy watches tells when the operator has
decided on one. It raises `follow_up_unrecorded` about a ticket whose runs reported tickets the journal did not
record, until the ticket is done or forgotten (§18).

**Recorded by the overseer.** The overseer records an item with its `attention` tool (§27), with a reason and a detail,
every tick its cause holds. Items are stored as decisions, not a table of their own (D020). The current list is the attention
decisions of the latest `ok` tick, so an item disappears the first tick that does not record it, and a failed or
`skipped` tick leaves the previous list standing; `canopy_unavailable` or `disk_low` is added to it while it is the
latest tick's. The harness holds the overseer's item through a tick that did not give the overseer its subject, such as
a ticket the harness decided (§37), since the overseer cannot record again what it was not shown; the item goes the
first tick that gives the overseer its subject and leaves it out, or once its ticket is done or stopped. The state
block lists the overseer's open items on what it is given (§6 step 4), so it records each again until it sees the
cause gone. An item's age runs from the first tick of its unbroken run. `attempt_limit` is recorded by the overseer when
the state block shows a ticket at its limit, and by `canopy dispatch` with an `attempt_limit` refusal, and lasts while
the overseer keeps asking.

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
- The server of the overseer's tools does not answer `initialize`: the tick closes `canopy_unavailable`, the overseer
  does not run, and the item of that name stays until a tick ends otherwise (§6 step 5).
- Too little free disk: the tick closes `disk_low` the same way. Runs already going keep going; none starts until a
  tick finds the space.
- Overseer timeout or bad output: the tick closes `overseer_failed`; nothing is dispatched; the next tick retries.
  Three consecutive ticks not `ok` send a `loop.failing` notification once per streak, and `loop.recovered` at the next
  `ok` (§20); no attention item, since a failing loop cannot add to the latest `ok` tick's list.
- Overseer left a duty undone (the query when due, a ticket's decision, a due chore's): the tick closes
  `overseer_failed`, naming each (§6 step 5). What it dispatched stands, and the next tick owes the same duties.
- Tick code raises an unexpected exception: the tick closes `error`, its summary the exception's type and message, so
  the journal keeps the cause when the logs cannot; the traceback goes to `canopy.log`, and the loop goes on.
- MCP unavailable: the overseer first does what needs nothing from the server that failed (due chores; with GitHub,
  reviews and a private ticket's `resume`; with the tracker, closed tickets marked done), then records a tick-wide
  `skip`. The tick closes `skipped`: what it started stands, nothing is decided on partial data, and the attention list
  stays as it was.
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
