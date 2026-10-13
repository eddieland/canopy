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
  pids, times, status, the validated result (§21), and what the runtime reported (§13), as `runs` has it.
  `decisions.pr` names the PR of a decision about a review.
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
- `pause`: at most one row, present while the operator has paused the loop (§6), with when and through which channel.
  A resume deletes it.

Rules: the DB never stores credentials or raw CI logs (token counts are usage, not credentials). `result_json` is a
summary.

`repo` in `ticket_units` and `run_slots` is nullable, a remnant of pre-workspace journals; canopy never writes null
there.

## 12. Configuration

Configuration is layered. Each layer overrides the one before it, key by key:

1. Built-in defaults in `config.py`.
2. **Workspace file**, `canopy-workspace.toml` at the workspace root (§18). Shared by everyone who runs canopy on the
   workspace, and committed when the workspace is itself a repository. canopy reads no config from a code repository:
   there is no `canopy.toml` (D016).
3. **User file**, `$XDG_CONFIG_HOME/canopy/config.toml` (default `~/.config/canopy/config.toml`). Personal, never
   committed. Required.

Every key has a scope. A **shared** key may be set in either file; the user file wins. A **user-only** key may be set
only in the user file; a workspace file that sets one is a config error that names the key, and canopy refuses to
run. Unknown keys are errors in both files. A removed key, such as `paths.state_dir`, is an error that says what
to do instead.

| Key | Scope | Why |
|---|---|---|
| `tracker.provider` | shared | a property of the repository's tracker |
| `tracker.query` | shared | the repository scopes it to a project; a user may narrow it |
| `tracker.needs_human_label` | shared | a signal to people; queues are already disjoint |
| `tracker.ticket_url` | shared | the tracker's address is the team's; a link runs nothing |
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
| `review.*` | user-only | `review.query` authorizes reading other people's PRs, and runs an agent on them (§21) |
| `serve.*` | user-only | a listener on the operator's machine, and where (§22, TRUST_MODEL T8) |

Whoever controls a shared workspace file (anyone who can push to the repository holding it) must not run commands,
choose prompts, spend money, or authorize anyone; those keys are user-only (TRUST_MODEL T7).

Workspace file, beside the map (§18):

```toml
[tracker]
provider = "jira"            # jira | github | linear | any name; selects tracker-<provider> skill
needs_human_label = "needs-human"
query = 'project = PROJ AND statusCategory != Done'
ticket_url = ""              # optional; a ticket's page, with {key} for its key, for the web UI to link (§17)

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
- `tracker.ticket_url` is empty (no links) or a plain `https://` URL of at most 500 characters with `{key}` exactly
  once and no other braces, such as `https://acme.atlassian.net/browse/{key}`. The web UI puts it in an `href`.
- `canopy init` sets up a workspace in the current directory, or fills in the one it is inside (§18). A new workspace
  is never the home directory, where every later init below it would land, and never a directory that already has a
  `.canopy/`, which may be an earlier canopy's journal. In a git checkout it refuses, unless given `--workspace`:
  canopy writes nothing into a code repository. A repository at the home directory is the operator's dotfiles, not a
  code repository, and needs no flag. The refusal names a `canopy.toml` at the checkout's root as not read.
- `canopy init` writes the user file if missing, with `tracker.labels = ["agent-ready-<$USER>"]` and an empty
  `trust.authorized_repliers` and `trust.trusted_reviewers` to fill in, and prints the label. It writes the workspace
  file only if there is none, with `tracker.provider` and an example `tracker.query`. Neither file gets a key whose
  default serves: a default written into a file is pinned there, and a later canopy's never reaches it. It never
  overwrites either file and installs nothing else (§13). If the config does not load (for example, templates lacking
  `{definitions_dir}`), it prints the error. It warns about copies of canopy's agent definitions in the OpenCode config
  of the workspace root and of each cloned repository, which stop runs (§13).
- `capacity.slots_per_repo` and `[capacity.repo_slots]` declare each repository's pool size in a workspace (§18).
  Unset (the default) leaves pools unmanaged. User-only, so a team's map cannot grow the operator's disk use.
- Remotes should be HTTPS with a credential helper, not SSH: a sandboxed worker cannot reach the SSH agent socket.
  `canopy workspace sync`, which `canopy init` runs
  for the URLs it is given, runs `git remote get-url --push --all origin` in each primary clone, which applies
  `insteadOf` and `pushInsteadOf` rewrites, and warns naming every URL git would reach over SSH: `ssh://`,
  `git+ssh://`, or scp-like `[user@]host:path`. Only a warning: sync still succeeds, and nothing else checks the
  remote.
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
runs from the workspace root and a relative path would let a shared workspace supply them (TRUST_MODEL T7). There is
no key for the state directory: it is always `<workspace>/.canopy/` (§18), written `<state_dir>` in this document.

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
  tools only; commenting anywhere, submitting a review, pushing, writing files, labels, and edits denied by name
  (§21).
- `canopy-chore`: no edits, shell, or subagents; MCP write tools denied by name (§19). A chore that runs the operator's
  own tools uses the operator's own copy of it.
- `canopy-splitter`: read-only file tools in its desk; no edit, shell, or subagents. MCP: the tracker
  (create and link tickets, comment), with tools for labels, assignees, edits, PRs, branches, and files denied by name
  (§18).

None has web tools: every definition denies `webfetch`, `websearch`, and `codesearch` (TRUST_MODEL T1, D077).

When the tracker is GitHub Issues, the tracker and GitHub are the same MCP server. The runtime is swappable by editing
the command templates. No interface.

### What a run prints

Every agent's output is read the same way (`core/agent_output.py`). A template either prints the agent's text on
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

The default `overseer_cmd`, `worker_cmd`, `split_cmd`, `chore_cmd`, and `review_cmd` ask for events. A tick records
what its overseer reports on the tick (§6), `_run` what a worker or split reports on the run (§8, §11), `_chore` what a
chore reports on its chore run (§19), and `_review` what a reviewer reports on its review run (§21). So every agent run
canopy starts records what it cost, and the web UI's spend (§22) sums them all. A template of the operator's that asks
for no events records nothing, and its runs are missing from the spend. A tick's output file and a run log hold the
events as printed, and the web UI reads one session's back from them as its transcript (§22).

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
agent's start directory (the workspace root for the overseer, the worktree on the run's branch for a worker) and
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
names the skill and the prompt then says to use it (§8). Prefer that to a prompt override.

### The operator's skill

`canopy skill` prints a skill named `canopy` that teaches an agent in the operator's own session the canopy CLI, where
the state directory's files are, how to read the journal read-only, and how to answer "why was KEY not picked up".
canopy installs it nowhere: the operator saves it where their runtime reads skills, such as
`~/.agents/skills/canopy/SKILL.md`, and again after upgrading. It is not in the definitions snapshot, where it would
help no run, so a `$HOME` copy,
which canopy's own runs also load, never meets a same-named skill. It opens by telling an agent started by canopy
(`CANOPY_TICK_ID` set, or a canopy prompt) to follow its prompt instead. It grants nothing: the overseer's and worker's
bash rules apply either way.

## 14. Attention list

After every tick the list is rendered to `<state_dir>/attention.md` (`.canopy/attention.md` in the workspace), readable
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
chore after the ticket items (§19). Reviews add `review_failed` and `review_limit`, about a PR
(§21). An item about one unit of a ticket names its repository and is shown as `KEY (repo)`.

The harness raises the run reasons itself, every tick, after reconcile. For a ticket not marked done, its latest
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
the cause holds. `--repo` names the unit it is about, such as the PR waiting on a reviewer. The item is stored as a
decision with action `attention:<reason>`, not in a separate table (D020). The current list is the attention decisions
of the latest `ok` tick: an item disappears the first tick that does not record it, and a failed or `skipped` tick
leaves the previous list standing. Dry-run ticks count like live ones. An item's age runs from the first tick of its
unbroken run. Reasons must match `[a-z][a-z0-9_]*`.

`attempt_limit` is raised two ways: the overseer records it when the state block shows a ticket at its limit for the
work it needs, and `canopy dispatch` records it with an `attempt_limit` refusal. Either way it lasts as long as the
overseer keeps asking for that work. The refusal's item names the unit at its limit.

Notification. An item is identified by its ticket, reason, and repository if it has one, so two units at their
fix-ci limit are two items; rewording its detail does not make it new. Each notification sink (§20), `notify.cmd`
among them, keeps its own record of what it was told. When `notify.cmd` is set, each tick compares the list with its
rows in the `notifications` table: unrecorded items are new, and rows whose item is no longer listed are resolved. If
either exists, the command gets one message on stdin: a summary line, a `+ KEY reason: detail` line per new item, a
`- KEY reason` line per resolved one, and the path of `attention.md`. Only when it exits 0 within 60 seconds are new
items added to the table and resolved ones removed. So a failed notification is retried next tick, an open item is
never notified twice, and an item that returns after going away is new again.

## 15. Failure handling

- Worker crash: detected by pid liveness in reconcile; what is left of the worker is killed; every slot tidied as
  `_run`'s step 6 tidies it (§8), from the `.git` link `_run` recorded, and returned; the run's object directory and a
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
  exits 1; no decisions are made on partial data, and the attention list stays as it was. The overseer prompt
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
  per workspace under its root. Repositories that are not one queue go in separate workspaces, each with its own
  journal and locks.
