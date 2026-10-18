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
back. The schema is in `migrations/`: `0001_init.sql` is the whole schema as of v0.1, and a journal that applied the
pre-squash migrations is not upgraded (D068). Each later change is a new migration.

What it records, and why:

- **Ticks**: each tick's status (`running`, `ok`, `skipped`, `canopy_unavailable`, `overseer_failed`,
  `reconcile_failed`, or `abandoned`), summary, and what it read up to (§6 step 3). Its cost is its overseer's alone;
  each run it dispatched records its own. On a tick `canopy loop` ran, whether it was idle and what ended the wait
  before it (§6, Idle pacing), so spend can be split by what it bought. A tick that cannot take the lock writes no row.
- **Tickets and units**: each ticket seen, with its last derived phase, its branch (named by its first implement),
  whether it is done or forgotten (§22), and the cursors that make ticks incremental; each unit, a ticket's work in one
  repository (§18), with its branch, PR, phase, and cursors (§7).
- **Runs**: each worker, split, and plan run, and each review and chore run (§21, §19), with its processes, status, and
  a summary of its result, and each slot it leased with the base it started from. A worker run's status is `running`,
  one the worker reports (`done`, `blocked`, `failed`), or one the harness sets (`unknown`, `timeout`, `unpushed`,
  `crashed`, `stopped`). Runs are the source for capacity, crash detection, attempt counts, and the CI cooldown,
  which are derived from them, never stored (D030); a unit's limit adds the operator's grants.
- **Cost**: for a tick's overseer and every run, what the runtime reported (§13), nothing when it reported nothing.
- **Grants** of attempts, plan runs, and review runs (§21, §22, §25), and the tickets a split created, written only
  from a validated split result (§18). Grants are only added to.
- **`decisions`**: each overseer decision and its rationale. The audit log, the attention list's source (§14), and the
  prompt-evaluation corpus.
- **`notifications`** and the sinks' outbox: what each sink was told, so an open item is notified once per sink (§14),
  and the events, cursors, and failures of each sink (§20).
- **`messages`**: each subject's conversation (§22), mirrored tracker comments among them. Ids never repeat.
- **`starts`**: each subject the operator started privately (§22). Never deleted: a stopped ticket stays private.
- **`pause`**: present while the operator has paused the loop (§6); a resume deletes it.
- **`notices`**: each notice to workers (§8). At most one is in force; rows are never deleted.
- **Plan threads**: the operator's comments on a plan, written only by the web channel (§25).
- **Agent memory**: each ticket note, proposal, and lesson, and for each run rendered while a tier was on, the modes it
  was rendered under and what was rendered into it (§28). Empty while memory is off.

Rules: the journal never stores credentials or raw CI logs (token counts are usage, not credentials). A run's result
is a summary.

`canopy decisions [TICK]` prints a tick, the latest by default, with its overseer's cost and its decisions: the way to
read a dry run's plan. The web UI shows the same (§22).

`canopy spend` weighs what agent runs cost against what they got done, by UTC day over a window (7 days by default,
today's so far included), so that comparing two windows tells whether spending more bought more: each kind's cost, the
ticks by what they bought and what woke them, the tickets done and the spend per ticket done, each ticket's and PR's
own cost, and which tools put the most into context. The web UI's spend page shows it (§22). What it counts:

- Every figure is by start: a run counts on the day it started, within the window, all read at one moment.
- A ticket is done in the window by its newest `done` decision there (§7), if still done and not forgotten. That is
  `merged` and `closed` alike: a tracker that closes a ticket when its PR merges closes most that landed before the loop
  sees the merge, so leaving `closed` out would undercount. A ticket closed unworked counts too, marked as such.
- Spend per ticket done divides the window's whole spend, overseer, chores, and open tickets included, since that is
  what getting those tickets done cost.
- A ticket's or PR's own cost is its worker, split, and review runs in the window; the overseer's is no ticket's. A
  PR's runs are those whose result names it, so a joint run counts on each of its PRs, and one still running on none.
- Tools: most of a run's context after the fixed prefix is tool results, which each later call reads again
  (MEASUREMENTS 2026-10-13 F6, F14). A tool is measured by the characters it returned, since the runtime does not say
  which tokens were its result; four to a token is a rule of thumb, labeled an estimate wherever it is shown.
- First calls: a run's fixed overhead is all in its first call (§13), so what it was sent, less canopy's prompt, is the
  kind's overhead, and a change of snapshot (D040) shows as a step; an OpenCode upgrade does not change the snapshot,
  so a re-measurement splits by start for one. A first call that wrote more than half of what it was sent to the cache
  started cold, a heuristic; the journal keeps both counts.
- The overseer's tools and first calls include dry runs'.

`canopy health` reads the same window for how the runs in it ended: each kind's runs by sort and status, with what they
cost, the newest that failed with a note on each, and the overseer's asks a guard refused, by guard. A failure is a run
that did not do what it was started for: a tick that did not close `ok`, or a worker, chore, or review run that ended
`failed`, `unknown`, `unpushed`, `crashed`, or `timeout`; a worker that asked a question or that the operator stopped
did. Beside `canopy spend --json`, it is what a chore that looks at canopy itself reads (`examples/chores/`).

## 12. Configuration

Configuration is layered. Each layer overrides the one before it, key by key:

1. Built-in defaults.
2. **Workspace file**, `canopy-workspace.toml` at the workspace root (§18). Shared by everyone who runs canopy on the
   workspace, and committed when the workspace is itself a repository. canopy reads no config from a code repository:
   there is no `canopy.toml` (D016).
3. **User file**, `$XDG_CONFIG_HOME/canopy/config.toml` (default `~/.config/canopy/config.toml`). Personal, never
   committed, and optional. It serves every workspace, so it holds what is the same in all of them: the runtime
   templates, the comment marks, the commit trailer, notification sinks.
4. **Private file**, `<state_dir>/config.toml`, the workspace's own file for the operator alone, never committed. It
   holds what belongs to one workspace: its queue labels, its authorized repliers and trusted reviewers (each in its
   tracker's identity format), `review.query`, `runtime.setup_cmd` and `runtime.pr_skill`, `tracker.mcp_server`, its
   chores, its loop's pacing, its capacity (each workspace's journal counts its own), and its web UI's port, so that
   two workspaces' loops do not collide.

At least one of the user file and the private file must exist; with neither, the error names the private file and
`canopy init`.

Every key has a scope. A **shared** key may be set in any file. A **private** key may be set in the user file or the
private file, never in the workspace file; a workspace file that sets one is a config error that names the key and the
private file, and canopy refuses to run. No key is held to the user file: a workspace whose team marks agent work its
own way sets its own comment marks and trailer. Unknown keys are errors in every file. A removed key, such as
`paths.state_dir`, is an error that says what to do instead. A validation error names the file the bad value came from,
or, for a missing key, every file it may be set in. `[chores]` comes whole from the last file that sets it.

The private file is under the workspace root, which may be a checkout of a shared repository, and its keys run
commands. The state directory being private to the operator (§18, D053) says nothing of where it came from: a
`.canopy/` checked out under umask 077 passes that check. So whenever config is loaded, canopy runs one
`git ls-files` at the workspace root and refuses a state directory any of whose files git tracks, the journal
included; when the root is in no repository, nothing is tracked and git does not run, and when git fails otherwise,
canopy refuses too. The private file itself is opened without following a symlink, and must be a regular file of the
operator's that no one else can write. A sandboxed run can neither read nor write it (§24); an unsandboxed one can, as
it can the user file.

What is not a key stays in the user config directory, as files: the secrets (`listener-secret`, `slack-webhook`,
`slack-token`) and the sandbox templates (`sandbox/<role>.json`), which every workspace's runs share. The prompt
overrides default to `prompts/` there too.

| Key | Scope | Why |
|---|---|---|
| `tracker.provider` | shared | a property of the repository's tracker |
| `tracker.query` | shared | the repository scopes it to a project; a user may narrow it |
| `tracker.needs_human_label` | shared | a signal to people; queues are already disjoint |
| `tracker.ticket_url` | shared | the tracker's address is the team's; a link runs nothing |
| `tracker.labels` | private | defines this operator's queue |
| `tracker.mcp_server`, `tracker.read_tools` | private | what a private ticket's worker may call (§22) |
| `tracker.private` | private | turns a queue label into a start record (§22) |
| `tracker.query_every_minutes` | private | how often the overseer pays to run the query (§7): the operator's spend |
| `policy.*` | shared; the repository may only tighten | limits spend, retries, and stacking |
| `trust.branch_prefix` | shared | team conventions for spotting agent work |
| `trust.authorized_repliers` | private | who may steer this operator's workers |
| `trust.trusted_reviewers` | private | whose review feedback reaches a worker without the operator's go-ahead (§7) |
| `trust.comment_prefix`, `trust.comment_suffix` | private | they silence the comments that carry them (§8) |
| `trust.commit_trailer`, `trust.commit_trailer_name`, `trust.commit_trailer_email` | private | whether and whom the operator's commits credit (§8) |
| `trust.rebase` | private | lets workers replace a branch's history (§8, TRUST_MODEL T1) |
| `capacity.*` | private | the operator's machine and spend |
| `pools.backend` | private | which program makes worktrees on the operator's machine (§18) |
| `loop.*` | private | how often the overseer runs: the operator's spend |
| `runtime.*` | private | commands run on the operator's machine |
| `notify.*` | private | a command run on the operator's machine |
| `paths.*` | private | where prompts and state are read from |
| `chores.*` | private | a chore runs a command and a prompt, and spends money (§19) |
| `review.*` | private | `review.query` authorizes reading other people's PRs, and runs an agent on them (§21) |
| `serve.*` | private | a listener on the operator's machine, and where (§22, TRUST_MODEL T8) |
| `memory.*` | private | what workers may write into later runs' prompts (§28, TRUST_MODEL T7) |

Whoever controls a shared workspace file (anyone who can push to the repository holding it) must not run commands,
choose prompts, spend money, or authorize anyone; those keys are private (TRUST_MODEL T7).

Workspace file, beside the map (§18):

```toml
[tracker]
provider = "jira"            # jira | github | linear | any name; selects tracker-<provider> skill
needs_human_label = "needs-human"
query = 'project = PROJ AND statusCategory != Done'
ticket_url = ""              # optional; a ticket's page, with {key} for its key, for the web UI to link (§17)

[policy]
max_implement_attempts = 2
max_resume_attempts = 6      # every resume of a unit, whatever its reasons, an old fix-ci run among them (§8)
ci_cooldown_minutes = 30     # how long a resume for CI alone waits after the unit's last run that worked on CI (§8)
max_split_attempts = 1       # per ticket (§18)
max_plan_attempts = 3        # per ticket (§25)
plan = "off"                 # off | approve (§25); "approve" is stricter
stacking = "auto"            # auto | never (§10); "never" is stricter

[trust]
branch_prefix = "agent/"
```

Private keys, in the user file or the private file; any of them may be in either, and the private file wins:

```toml
[tracker]
labels = ["agent-ready-yourname"]
mcp_server = ""         # optional; the tracker's MCP server as OpenCode names it; default by provider (§22)
# read_tools = [...]    # optional; the only tools of it a private ticket's worker may call; default by provider
private = false         # optional; true starts a labeled ticket privately on its first dispatch (§22)
query_every_minutes = 0 # the least time between ticks that run the query; 0 runs it every tick (§7)

[capacity]
max_workers = 2

[pools]
backend = "treehouse"   # or "canopy": canopy's own pool makes the worktrees (§18, ROADMAP M45)

[runtime]
overseer_cmd = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer --format json
    --title={title} {prompt}'''
worker_cmd   = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --format json
    --title={title} {prompt}'''
split_cmd    = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-splitter --format json
    --title={title} {prompt}'''
plan_cmd     = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-planner --format json
    --title={title} {prompt}'''
overseer_timeout_minutes = 15
worker_timeout_minutes = 45
pr_skill = ""           # optional; the skill workers open PRs with instead of the GitHub MCP (§8)
setup_cmd = ""          # optional; runs in each slot at the run's branch, before the worker (§9)
setup_timeout_minutes = 30
# private_worker_cmd: worker_cmd with `--agent canopy-worker-private`, for a ticket started with `canopy start` (§22)

[loop]
interval_minutes = 15   # `canopy loop` waits this long after each tick ends
idle_max_minutes = 120  # and up to this long after idle ticks in a row (§6, Idle pacing)
min_gap_minutes = 1     # and no tick starts sooner than this after the last one began (§6)

[trust]
authorized_repliers = ["tracker-account-id"]   # Jira accountId, GitHub login, ...
trusted_reviewers = ["github-login", "canopy:review"]   # whose PR feedback a worker addresses unasked (§7)
comment_prefix = "CANOPY:"   # every worker comment starts with it (§8)
comment_suffix = ""          # and ends with this, if set
commit_trailer = true                            # a worker adds this trailer when the runtime adds none (§8)
commit_trailer_name = "canopy worker"            # a worker's commits are co-authored by this (§8)
commit_trailer_email = "noreply@canopy.invalid"  # at this address
rebase = false               # true: workers rebase and push with a lease, never merge a base in (§8)

[paths]
prompt_overrides = "~/.config/canopy/prompts"
# worktree_include = "~/.config/canopy/worktreeinclude"   # optional; replaces the committed .worktreeinclude (§9)
# worker_instructions = "~/.config/canopy/worker-instructions.md"   # optional; in every worker's prompt (below)

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

[memory]                # agent memory (§28); each tier off, record, or use
ticket_notes = "off"    # notes a ticket's runs write for its later runs
proposals = "off"       # lessons workers propose, which reach runs once you promote them

[retention]             # how long canopy keeps its own history (§26); 0 keeps a kind forever
run_files_days = 30     # a run's, chore run's, or review's files, once it ended this long ago
tick_files_days = 7     # a tick's files; a tick not `ok` keeps them for run_files_days
journal_days = 90       # harness attention rows, past the window the attention list reads
log_max_mib = 50        # canopy.log is rotated past this
log_keep = 3            # and this many rotated files are kept
memory_days = 30        # the text of a note or proposal no longer in force (§28)
```

Built-in defaults are the values shown, except: `tracker.provider`, `tracker.query`, and `tracker.labels` have no
default and must be set; `trust.authorized_repliers` defaults to empty (nobody can resume blocked work), and so does
`trust.trusted_reviewers` (every review waits for the operator).

Validation:

- A trusted reviewer is `canopy:review` or a login of at most 100 characters with no whitespace, colon, or backtick.
- `trust.comment_prefix` and `trust.comment_suffix` are each empty or one line of at most 80 characters, with a letter
  or digit, no backtick, and no surrounding spaces, and at least one is set.
- `trust.commit_trailer_name` is one line of at most 80 characters, with a letter or digit, no backtick or angle
  bracket, and no surrounding spaces; `trust.commit_trailer_email` is at most 254 characters, with one `@` and no
  whitespace, backtick, or angle bracket.
- `trust.branch_prefix` must be non-empty, end in `/`, and consist of plain ref components (letters, digits, `_`, `-`,
  each starting with a letter or digit) joined by `/`. Branch names reach git's argv.
- `tracker.ticket_url` is empty (no links) or a plain `https://` URL of at most 500 characters with `{key}` exactly
  once and no other braces, such as `https://acme.atlassian.net/browse/{key}`. The web UI puts it in an `href`.

The commit trailer keys make the `Co-authored-by` trailer a worker adds when the agent runtime adds no attribution of
its own (§8, TRUST_MODEL T5). Name agent work the way the team's tooling expects, such as a team's bot address, never a
person: the trailer is how a reader tells the work is an agent's. Turned off, a worker keeps the runtime's trailer and
adds none, so with a runtime that adds none only the branch prefix and the PR mark the work. The keys are private
because the commits are the operator's: a shared file must not credit agent work to a person.

`trust.rebase` is for repositories whose host or CI refuses merge commits: a worker rebases onto a base branch instead
of merging it, and pushes with `git push --force-with-lease`, the one force its definition allows, while `canopy
_run`'s own push takes a lease on the commit the run started from (§8, TRUST_MODEL T1). It applies to every repository
the operator works on, and is private because it lets a worker replace a branch's history.

Rules:

- **Queues are per operator.** `tracker.labels` is a non-empty list; a ticket carrying any of them is in this
  operator's queue. Two operators must never share a label: the guards (one worker per ticket, attempt limits,
  cooldowns) see only the local journal. canopy cannot detect sharing; it is the operator's responsibility
  (TRUST_MODEL §7).
- **The repository may only tighten policy.** A repository `policy.*` value is used only if stricter than the built-in
  default: a lower attempt limit, a longer cooldown, or `stacking = "never"`. Otherwise the default stands. The user
  file may set any value, including a looser one; the rule only stops a commit from loosening limits for operators who
  never set them (TRUST_MODEL §3). Scope and tighten checks run per file, so an error names the file that caused it.
- `canopy init` sets up a workspace in the current directory, or fills in the one it is inside (§18). A new workspace
  is never the home directory, where every later init below it would land, and never a directory that already has a
  `.canopy/`, which may be an earlier canopy's journal. In a git checkout it refuses unless given `--workspace`:
  canopy writes nothing into a code repository (a repository at the home directory is the operator's dotfiles, and
  needs no flag). The refusal names a `canopy.toml` at the checkout's root as not read.
- `canopy init` writes the private file if missing, readable only by the operator, with a queue label of
  `agent-ready-<$USER>` and empty repliers and reviewers to fill in, where the user file does not set them, and the
  workspace file if there is none. It never writes the user file, never overwrites a file, and installs nothing else
  (§13). No file gets a key whose default serves: a default written into a file is pinned there, and a later canopy's
  never reaches it. It warns about copies of canopy's agent definitions in the OpenCode config, which stop runs (§13),
  and, unless `worker_cmd` is already sandboxed, prints a sandboxed one to add: the sandbox is opt-in (§24).
- `canopy sandbox setup` needs no workspace. It copies the sandbox's policy templates to `<user config dir>/sandbox/`
  (0700), never over one that is there; installs the `srt` version the wrapper's lockfile pins, with npm's install
  scripts off; and checks what it cannot install because it needs root: on Linux bubblewrap (0.5.0 or later, able to
  make a user namespace), socat, ripgrep, and a machine `srt` ships its seccomp filter for, without which a sandboxed
  command can connect to any Unix socket it sees; on macOS ripgrep; and that canopy is not root. Anything missing
  would leave a sandbox weaker than §24 says, so it exits 1 while a thing is left to do. It writes no config (D117).
- `capacity.slots_per_repo` and `[capacity.repo_slots]` declare each repository's pool size in a workspace (§18).
  Unset (the default) leaves pools unmanaged. Private, so a team's map cannot grow the operator's disk use.
- `pools.backend` names the pool that makes the workspace's worktrees: treehouse or canopy's own (§18). Switching is
  safe with runs in flight; `canopy workspace sync` carries the idle slots over.
- Remotes should be HTTPS with a credential helper, not SSH: a sandboxed worker cannot reach the SSH agent socket.
  `canopy workspace sync`, which `canopy init` runs for the URLs it is given, warns naming every push URL git would
  reach over SSH, after git's URL rewrites. Only a warning: nothing else checks the remote.

A command template is split into words with `shlex`, then `{prompt}` and `{definitions_dir}` are replaced inside each
word in one pass. No shell runs, so the prompt is always exactly one argument (D023). Every agent template must contain
`{prompt}` exactly once and `{definitions_dir}` (the definitions directory, §13) at least once; a template without it
is a config error that prints the line to write instead. The check cannot tell where the runtime reads the value: a
custom template, such as a sandbox wrapper's, must still set `OPENCODE_CONFIG_DIR` to it, or OpenCode runs its default
agent, which allows everything (D040). `env` in the default templates is the ordinary program, not a shell.
`notify.cmd` is split the same way, gets its input on stdin, and must not contain `{prompt}`.

Overrides in `prompt_overrides` replace files of the same name in `prompts/`. An overseer override goes into the
overseer's definition in a snapshot of its own (§13), so a change to it reaches the next tick, and one canopy cannot
read as UTF-8 refuses the snapshot. An override must keep what the guards rely on: an overseer override must pass
`--label` on every `canopy dispatch`, and a worker override must include `{{LABELS}}` and the authorization check that
uses it (§8, D051); a worker override without it is refused as `bad_prompt`. An empty value means the default. In the
user file, `paths.*` values must be absolute or start with `~`, since canopy runs from the workspace root and a
relative path would let a shared workspace supply them (TRUST_MODEL T7). In the private file a relative value resolves
against the state directory, never the workspace root, so it stays private and under the provenance check above. There
is no key for the state directory: it is always `<workspace>/.canopy/` (§18), written `<state_dir>` in this document.

`paths.worker_instructions` names a file of the operator's standing instructions, habits every worker should keep,
rendered into every worker prompt but a split's, after the obligations (§8). Prefer it to an override for anything a
few lines can say, and a skill for know-how a worker loads when it needs it (§13). It is at most 4 KiB of UTF-8; a
file canopy cannot use refuses the dispatch as `bad_prompt` rather than running a worker without it. A passing
condition, such as a CI outage, belongs in a notice to workers (§8): it lapses, and the overseer and reviews hear it.

`tracker.provider` is a free-form name the harness never branches on; prompts use it to name the `tracker-<provider>`
skill, and the one use canopy makes of it is to give that skill, when it ships one, to the overseer in its definition,
so it need not be loaded on every tick (§13). `tracker.query` is how the overseer finds candidates: in the tracker's
search syntax where it has one (JQL, GitHub issue search), otherwise plain language. It finds tickets; it does not
authorize them (§17). The repository's query usually omits the label; an operator can override it in the private file
to include their labels and save the overseer reads. It is shared though the overseer reads every ticket it returns
before it checks labels, an exposure stated in TRUST_MODEL T7's residual.

## 13. Agent runtime

OpenCode. The harness depends on one capability: run a named agent non-interactively in a given cwd with a prompt and
read its stdout, `opencode run --agent <name>`. MCP connectivity, OAuth, and tool permissions are the runtime's job.

Agent definitions ship in `agents/`; agent runs load them from a directory canopy owns (below):

- `canopy-overseer`: read-only tools plus bash restricted to `canopy *` and `treehouse status*`, nothing outside the
  workspace (`external_directory: deny`), and one command per bash call: an `ask`, such as a `cd` out of the
  workspace, ends the run under `opencode run` (D021) and loses every decision it had not recorded, where a `deny`
  costs only the call. MCP: the tracker, GitHub.
- `canopy-worker`: edit and bash within the worktree. MCP: the tracker (ticket comments, and labels through its issue
  edit tool), GitHub (open/update PR, read reviews and checks); merge, review submission, closing, transition, ticket
  creation, delete, fork, API file and branch writes, and other agents or workflow runs denied by name (D084).
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

Every agent's output is read the same way. A template either prints the agent's text on stdout, or asks OpenCode for
`--format json`, which prints one JSON event per line; then the agent's text is that of its `text` events. Every result
contract (the overseer's done token, §8, §18, §19, §21) is read from that text, so a template may switch formats
without changing a prompt. The agent's final message is the last `text` event's text; plain stdout does not say where
a message ends, so all of it is the final message.

A JSON contract (§8, §18, §19, §21) is the last line of the text that starts with `{`, and lines after it that do not
are passed over: a runtime, or a plugin the operator must load, may print a notice after the agent's last word. A last
object that does not validate is no result; canopy never falls back to an earlier one, which may be an example the
agent quoted or a result it took back. The overseer's done token is plain text, a line anywhere in its final message
(§6).

From events the harness also reads, each validated (D026):

- the session id, with which the operator opens the transcript in OpenCode's own tools (`opencode export <id>`, or
  `opencode --session <id>` in the run's directory).
- the cost: dollars and tokens by kind (input, output, reasoning, cache read, cache write), summed over the model
  calls. If one call's figures do not validate, the run reports no cost rather than too little. A run killed mid-call
  (a timeout) reports what its finished calls cost, a lower bound. A subagent's calls are its own session's, and not
  counted.
- the peak context: the most one call was sent, so how large the run's context grew.
- the first call: what it was sent, and what it wrote to the cache. All of a run's fixed overhead (the system prompt,
  the agent's body, the tool schemas) is in its first call, and the cache write says whether the provider had that
  prefix cached (MEASUREMENTS 2026-10-13 F11, F12).
- the tool calls, rolled up by tool: how many, how many ended in an error, and the characters they returned. A run
  keeps a bounded number of tools, the rest counted together, so output no runtime printed cannot fill the journal.

The harness records these on the tick or run (§11), with the digest of the definitions snapshot the run loaded, so a
change to a prompt, an override, or a definition splits the runs into before and after; the digest only when the
runtime reported something, since a template that prints plain text may not load the snapshot at all. Every default
template asks for events, so every agent run canopy starts records what it cost, a running worker's so far, and the
web UI's spend (§22) sums them all. A template of the operator's that asks for no events records nothing, and its runs
are missing from the spend. A tick's output file and a run log hold the events as printed, and the web UI reads one
session's back from them as its transcript (§22).

Wherever canopy prints what a run or a tick cost, the CLI and the web UI alike, it says it as
`$0.25, 3.5k tokens, 5.5k peak context`. The tokens are every kind but cache reads. Each call reads again what the
calls before it were sent, so cache reads summed grow with the square of a session's length and dwarf the rest,
saying nothing about what the run did; the peak context says what the sum hid, how large the context got. Each kind is
still kept apart in the journal, and a transcript shows each call's (§22).

### Session titles

Every runtime template may name `{title}`, the run's session title, and the defaults pass it as
`opencode run --title={title}`, so OpenCode's session list names each session as canopy does:

- a worker or split run: `<KEY> <kind>: <the ticket's title>` (§7), or `<KEY> <kind>` before the overseer names it;
- a tick's overseer: `tick <id>`; a chore: `chore:<name>`; a review: `review <PR URL>`.

The title is read when the run starts, so a rename shows in canopy at once and in the runtime from the ticket's next
run. canopy names sessions rather than reading OpenCode's own titles because those are not in the events: reading one
back would take an OpenCode-only command after every run, where the runtime is otherwise only a command template (§12),
and its model writes it from canopy's prompt, which is mostly the same for every run of a kind.
Like `{prompt}`, `{title}` is replaced inside a word after the template is split. The defaults keep `--title=` and the
title in one word, and every title starts with a letter or digit, so a title is never read as an option.

### Where the runtime finds canopy's definitions

Rationale in D040 and D044.

canopy snapshots its bundled `agents/` and `skills/` into `<state_dir>/runtime/<digest>/`, named for a digest of their
contents. Two definitions are rendered from config first, so a change to what they are rendered from makes a new
snapshot rather than changing one:

- `canopy-worker-private` gets the tracker's MCP server and the tools of it a private worker may call (§22).
- `canopy-overseer` gets the overseer's prompt, the operator's override if there is one (§12), as its body, followed by
  the shipped `tracker-<provider>` skill when canopy ships one. OpenCode sends an agent's body as its system prompt,
  which the provider caches across ticks with the tool schemas; a tick's message is its state block alone (§6). The
  skill stays in `skills/` too, for the workers. An override canopy cannot read refuses the snapshot, which fails the
  tick and every run started from it: a run without its definitions would run without the prompt. A definition canopy
  did not render, such as the shipped file loaded by hand, tells the overseer to print `no prompt supplied` and exit.

A snapshot is written to a temporary directory, renamed into place, and never changed, so overlapping runs never load a
partial set. The overseer run and each `_run` use the installed canopy's snapshot, creating it if missing. A snapshot
canopy made is readable only by the operator; one that is a symlink, someone else's, or open to others (for example
from a checkout of a shared workspace, §18) is refused: the overseer's refusal fails the tick, a worker's is a
`crashed` run. When no run is live, reconcile removes other snapshots and temporary directories over an hour old;
a live run may be an earlier canopy's, still loading its snapshot. OpenCode writes a `.gitignore` and `node_modules/`
into each config directory it loads, the snapshot included.

Command templates name the current snapshot with `{definitions_dir}` (§12), required in every template that runs a
canopy-shipped agent (`overseer_cmd`, `worker_cmd`, `private_worker_cmd`, `split_cmd`, §25's `plan_cmd`, §19's
`chore_cmd`, §21's `review_cmd`), as the defaults in §12 show.

Nothing is installed into repositories, and a leased worktree always has the definitions its run names. OpenCode merges
`OPENCODE_CONFIG_DIR` after the repository's config, so a repository's definition of a canopy agent is merged into
canopy's and could loosen its bash rules (D044). Before starting an agent, the harness checks the OpenCode config in the
agent's start directory (the workspace root for the overseer, the worktree on the run's branch for a worker) and
refuses if it defines one of canopy's agents: a file named for one under `.opencode/{agent,agents,mode,modes}/`, or an
`opencode.json` or `opencode.jsonc` at the root or in `.opencode/` whose text names one. The overseer's refusal fails
the tick (`overseer_failed`, summary naming the files); a worker's is a `crashed` run whose note names them, and its
slot is returned. `canopy init` warns about the same files. A private run (§22) is also refused where that config
names any tool of the tracker's MCP server, since a rule merged after canopy's could reopen a write tool.

Customizing canopy is adding skills where the runtime already looks: the repository (`.agents/skills/`,
`.claude/skills/`, `.opencode/skill/`) or the operator's home (`~/.agents/skills/`, `~/.claude/skills/`,
`~/.config/opencode/skill/`). canopy turns none of these off. Give a custom skill its own name; same-named skills do not
reliably override each other. A `$HOME` skill that workers use must be a single `SKILL.md`: the worker's
`external_directory: deny` lets it load the skill but not read files next to it outside the worktree. A repository can
also define its own agents under other names, MCP servers, and permissions (TRUST_MODEL T7). A skill only adds to what
a prompt says; when the operator needs workers to open PRs differently from what the prompt says, `runtime.pr_skill`
names the skill and the prompt then says to use it (§8). Prefer that to a prompt override.

### The operator's skill

`canopy skill` prints a skill named `canopy` that teaches an agent in the operator's own session the canopy CLI and the
state directory, how to read the journal read-only, and how to look into what canopy did and found. canopy installs it
only when asked: `canopy skill --install [DIR]` saves it as `canopy/SKILL.md` in `DIR`, `~/.agents/skills` unless
given, and the operator runs it again after upgrading. It is not in the definitions snapshot, where it would help no
run. It tells an agent started by canopy to follow its prompt instead, and grants nothing: the overseer's and worker's
bash rules apply either way.

### Shell completion

`canopy completion SHELL` prints the script that completes canopy in bash, zsh, or fish, for the operator's shell
startup file. It completes commands, options, choices, and the workspace's repository and chore names, but not ticket
keys, which would open the journal on every Tab, and not the commands only the overseer runs inside a tick, which
would refuse the operator anyway.

## 14. Attention list

After every tick the list is rendered to `<state_dir>/attention.md`, readable only by the operator: grouped by reason,
one line per item with ticket key, age, and detail (usually a link). Items disappear when their cause is gone; there is
no manual dismissal. `canopy status` prints it too, with the last tick, a pause or notice in force (§6, §8), the tickets
the operator started (§22), the running workers, and the runs that ended most recently.

Reasons are exactly the attention rows in the phase table plus `crashed`, `unpushed`, `unknown_result`, `worker_failed`,
`attempt_limit`, `fix_ci_override` (§8: every `resume` is refused while an override of a retired fix-ci prompt
exists), a private ticket's `awaiting_reply` (§22) and a planner's (§25), the overseer's `plan_review` and
`plan_changed` (§25), `canopy_unavailable` (§6 step 5), and in a workspace
`repo_missing` and the overseer's `multi_repo`, `split_unlabeled`, and `split_self_labeled` (§18). Chores add
`chore_failed` and their findings, listed by chore after the ticket items (§19). Reviews add `review_failed` and
`review_limit`, about a PR (§21). A notice to workers adds the overseer's `notice_rerun`: a check failed while a notice
was in force, the notice has ended, and no newer run of the check exists, so the operator reruns it (§8). Agent memory
adds the harness's `memory_proposal`, about a done ticket whose runs' proposals wait on the operator, and
`lesson_review` and `lesson_wrong`, about the workspace, each one item naming every lesson it is about; none while
`memory.proposals` is off, and the last two only at `use` (§28). An item about one unit of a ticket names its
repository and is shown as `KEY (repo)`.

The harness raises the run reasons itself, every tick, after reconcile. For a ticket not marked done, its latest
run's status maps to a reason: `crashed` to `crashed`, `unpushed` to `unpushed`, `unknown` or `timeout` to
`unknown_result`, `failed` to `worker_failed`. The detail names the run, the harness note or the worker's summary, and
the run log. The cause is gone when a newer run starts for the ticket or the ticket is marked done. The overseer does
not dispatch such a ticket again until an authorized replier comments after the run ended; that is how a human says
"try again". An operator message after the run ended says it too (§22, D093), the only way on a private ticket.
`blocked` and `stopped` raise nothing here. Nor does a ticket the operator stopped (§22), whatever its latest run: nothing
dispatches it, so no reply could answer the item, and stopping it says they have seen to it. An `unpushed` run's commits
stay where `canopy show` names them. Started again, the ticket raises its item again.

The harness raises `awaiting_reply` every tick for each started ticket, not done, whose latest question has no operator
message after it (§22), and for each public ticket, not done, whose latest plan run ended `blocked` with its question
unanswered: the planner writes nothing to the ticket, so its question is canopy's to raise (§25). Its detail is the
question and how to answer it. Its cause is gone once the operator replies, and the item with it at the next `ok` tick;
until then the web UI marks it answered.

The harness also raises `repo_missing` every tick for each repository in the workspace map with no clone at
`repos/<name>`. It has no ticket key and is shown under the repository's name. Its cause is gone once
`canopy workspace sync` (or anything else) puts the clone there.

A tick raises `canopy_unavailable` when `canopy --version` fails from the overseer's environment, and runs no overseer
(§6 step 5). It is about neither a ticket nor a repository, and is shown as `-`. Its detail says why, and its cause is
gone at the first tick that ends otherwise.

The overseer records an item with `canopy attention <KEY> <reason> --detail "<link or text>"`, naming the unit's
repository when it is about one, every tick the cause holds. The item is stored as a decision, not in a separate table
(D020). The current list is the attention decisions of the latest `ok` tick: an item disappears the first tick that
does not record it, and a failed or `skipped` tick leaves the previous list standing. A `canopy_unavailable` tick adds
its one item to that list while it is the latest tick to have ended. The overseer's state block lists its own open
items (§6 step 4), so it records each again until it sees the cause gone. Dry-run ticks count like live ones. An item's
age runs from the first tick of its unbroken run. Reasons must match `[a-z][a-z0-9_]*`.

`attempt_limit` is raised two ways: the overseer records it when the state block shows a ticket at its limit for the
work it needs, and `canopy dispatch` records it with an `attempt_limit` refusal. Either way it lasts as long as the
overseer keeps asking for that work. The refusal's item names the unit at its limit.

Notification. An item is identified by its ticket, reason, and repository if it has one, so two units at their
resume limit are two items; rewording its detail does not make it new. Each notification sink (§20), `notify.cmd`
among them, keeps its own record of what it was told. When `notify.cmd` is set, each tick compares the list with that
record: unrecorded items are new, and recorded ones no longer listed are resolved. If either exists, the command gets
one message on stdin: a summary line, a `+ KEY reason: detail` line per new item, a `- KEY reason` line per resolved
one, and the path of `attention.md`. Only when it exits 0 within 60 seconds is the record updated. So a failed
notification is retried next tick, an open item is never notified twice, and an item that returns after going away is
new again.

## 15. Failure handling

- Worker crash: detected in reconcile; what is left of the worker is killed; every slot tidied as `_run`'s step 6
  tidies it (§8) and returned; the run's object directory and a joint run's desk removed; ticket goes to attention with
  `crashed`. Not auto-redispatched: the harness never restarts a run, and the overseer prompt waits for an authorized
  reply (§14). Every kind has an attempt limit in code, so an overseer that redispatches anyway stops at
  `policy.max_<kind>_attempts` (D030).
- Worker exits without a result, times out, reports `failed`, or leaves commits unpushed: `_run` returns the slot and
  records the status; the ticket goes to attention (§14).
- Stale lease without a run: returned in reconcile.
- treehouse unavailable or failing in reconcile: tick closes with `reconcile_failed`; the overseer does not run.
- `canopy --version` fails from the overseer's environment: tick closes with `canopy_unavailable`, the overseer does
  not run, and the item of that name is on the attention list until a tick ends otherwise (§6 step 5).
- Overseer timeout or bad output: tick closes with `overseer_failed`; nothing is dispatched; next tick retries. Three
  consecutive ticks that end other than `ok` produce a `loop.failing` notification for sinks that take `loop`, once per
  streak, and `loop.recovered` at the next `ok` tick (§20). There is no attention item for this: the attention list is
  the latest `ok` tick's, so a failing loop cannot add to it; `canopy_unavailable`, above, is the one exception.
- Overseer left a duty undone (the query when due, a ticket's decision, a due chore's): the tick closes with
  `overseer_failed`, its summary naming each one (§6 step 5). What it dispatched stands; the attention list stays as it
  was, and the next tick owes the same duties.
- MCP unavailable: the overseer reports it with a tick-wide `skip`; the tick closes as `skipped` and `canopy tick`
  exits 1; no decisions are made on partial data, and the attention list stays as it was.
- Overseer asks for something the guards refuse: the refusal is recorded as a decision with the guard's reason.
- An error the tick code does not handle, in a tick `canopy loop` runs: the tick ends as `error` in the loop's output,
  the traceback is logged, and the loop goes on. The next tick closes the row as `abandoned` (§6).

## 16. Open questions

- Whether `ask` permissions in OpenCode agent definitions block or auto-deny under `opencode run`. Answered from
  OpenCode's source: `ask` is auto-rejected and `deny` is enforced (D021). The live canary is opt-in; its first real
  run confirms or overturns this.
- Whether a Slack notification path should use a sink command or the overseer posting via MCP. Answered (§20, D035): a
  sink command, with a Slack sink shipped in canopy. The overseer does not post.
- Whether `merged` should trigger a tracker transition. Default no; humans own ticket state.
- One operator on several repositories. Answered by the workspace (§18): one queue, and state per workspace under its
  root. Repositories that are not one queue go in separate workspaces, each with its own journal and locks.
