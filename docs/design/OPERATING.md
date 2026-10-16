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
  §6 step 3). Status is `running`, `ok`, `skipped`, `canopy_unavailable`, `overseer_failed`, `reconcile_failed`, or
  `abandoned`. What the runtime reported about its overseer run (§13), in the same columns as `runs`: `session_id`,
  `cost_usd`, and tokens by kind, all NULL when it reported nothing. A tick's cost is its overseer's alone; each run it
  dispatched records its own. On a tick `canopy loop` ran, whether it was idle and what ended the wait before it
  (`idle`, `woken_by`, §6 Idle pacing), so spend can be split by what it bought; NULL on a hand-run tick.
  `canopy spend [--days N] [--json]` reads that split (`core/spend.py`): for each of the last N UTC days, 7 by
  default and at most 366, today's so far included, what the live ticks' overseers, idle ticks' among them, dry runs'
  overseers, worker and split runs, chore runs, and review runs cost, each run on the day it started; the ticks that
  ended in the window in five groups, each tick in one (a dry run, whatever the loop said of it; a live tick that did
  not close `ok`; an `ok` one the loop called idle; one it called not idle; one no loop ran, which a tick from before
  the loop recorded it also reads as), with the count and cost of each and idle ticks' share of what the live ticks
  that ended cost; the live ticks the loop ran by `woken_by`; and how many ended runs of each kind reported no cost.
  Beside what the window cost, what it got done (asked for by the operator, 2026-10-15, to weigh cost against value):
  the tickets marked done in it, each day's and in all, and the window's whole spend over them; each ticket with a
  run or review run in the window, or marked done in it, with what its own runs cost and when and how it was marked
  done; and each PR a run in the window pushed to, or a review run of it, with what those cost. Every figure is by
  start, within the window's days and none after, read in one transaction. The text lists the ten costliest
  tickets; `--json` prints all of it as one object, for a re-measurement (`docs/MEASUREMENTS.md`) to start from. The
  web UI's spend page shows it (§22).

  `--json` also has `first_calls`: for each kind and each definitions snapshot its runs loaded in the window, how many
  reported a first call, the median of what it was sent (the lower middle one of an even count), the share that started
  cold, and when the first and last of them started. A run's fixed overhead, the system prompt, the agent's body, and
  the tool schemas, is all in its first call (§13), so the median less the prompt canopy sent is that kind's overhead,
  and a change of snapshot (a prompt, an override, or a definition, D040) shows as a step between two rows; an OpenCode
  upgrade does not change the snapshot, so a re-measurement splits by start for one. A first call started cold when it
  wrote more than half of what it was sent to the cache: a warm one reads the fixed prefix from it and writes only what
  is new, the prompt, while a cold one writes the prefix too. The rule is a heuristic; the two counts are in the journal
  for a finer one. The overseer's include dry runs, whose first call is a live tick's; a run recorded before migration
  0027, or that made no model call, is in none. Neither the text nor the web UI shows them: they are for a
  re-measurement, as S33 reads them.

  Then which tools put the most into context (asked for by the operator, 2026-10-15, issue 434): after the fixed
  prefix, most of a run's context is tool results, which each later model call reads again, and the first
  measurements took an analysis session over the tick logs to find that PR reads and tracker searches were most of the
  overseer's (MEASUREMENTS 2026-10-13 F6, F14). For each kind and tool, from `run_tools` over the runs that started in
  the window, the runs that called it, its calls, the calls that ended in an error, the characters they returned, and
  those over four as an estimate of the tokens, the most characters first. Characters, because `step_finish` does not
  say which of a call's tokens a tool's result was; four to a token is a rule of thumb, labeled an estimate wherever it
  is shown. The overseer's include dry runs, as its first calls do. The text lists the ten that returned the most,
  `--json` every one (`tools`), and the web UI's spend page all of them.

  Done is a ticket's newest `done` decision (§7) in the window, on a ticket still marked done and not forgotten since:
  `merged`, and `closed` too, since a tracker that closes a ticket when its PR merges closes most tickets that landed
  before the loop sees the merge, so leaving them out would undercount what landed. A ticket closed unworked is
  counted as well; the per-ticket row says which it was. Spend per ticket done divides the window's whole spend, the
  overseer's, chores', and the runs of tickets still open included, since that is what getting those tickets done
  cost; comparing two windows' figures is what tells whether spending more bought more. A ticket's and a PR's own
  cost is its worker, split, and review runs, as on its page, but within the window: the overseer's is no ticket's. A
  PR's runs are those whose result names it, so a joint run counts on each of its PRs, and a run still running, with
  no result yet, counts on its ticket and on none of its PRs.
  `canopy decisions [TICK]` prints a tick (the latest by default), its overseer's session and cost, and its decisions;
  `--ticket KEY` filters decisions by exact ticket key and reports when none match. This is the way to read a dry run's
  plan. The web UI shows the same: its ticks page lists the latest 50, a tick's page its decisions, and a ticket's page
  the latest decisions about it across ticks (§22). A tick that cannot take the lock writes no row.
- `tickets`: one row per ticket key seen; the workspace root (`repo`), the ticket's own last derived phase, its
  branch (named by its first implement), the comment cursor (`last_comment_id`), a private ticket's message cursor
  (`last_message_id`, §22), the mirror cursor (`last_mirrored_id`, §22), done flag, and, once the operator forgot its
  work, when, with its newest run and message then (`forgotten_at`, `forgotten_run_id`, `forgotten_message_id`, §22).
  Cursors make ticks incremental. Attempt counts and the fix-ci cooldown are derived from `runs` and `run_slots`, not
  stored (D030); a unit's limit adds its `attempt_grants`.
- `ticket_units`: one row per unit, a ticket's work in one repository (§18); ticket, repository, branch, PR URL, the
  unit's phase, and its cursors (`last_review_id`, which holds a time despite its name (§7), and `last_ci_run_id`).
- `runs`: one row per worker execution; ticket, kind, branch (empty for a split, which works on none), pid of `canopy
  _run`, pid of the worker agent (`worker_pid`), status, result_json. Status is `running`, `done`, `blocked`,
  `failed` (the three the worker reports), `unknown`, `timeout`, `unpushed`, `crashed`, or `stopped` (§22); `private`
  marks a run on a started ticket. Source for capacity, crash
  detection, attempt counts, and the fix-ci cooldown. What the runtime reported (§13): the session id (`session_id`),
  the dollar cost (`cost_usd`), tokens by kind (`tokens_input`, `tokens_output`, `tokens_reasoning`,
  `tokens_cache_read`, `tokens_cache_write`), the peak context (`tokens_peak_context`, §13), the first model call's
  context and cache write (`tokens_first_call`, `tokens_first_cache_write`, §13), and the digest of the definitions
  snapshot it loaded (`definitions_digest`, §13), all NULL when it reported nothing; the peak is NULL too on a run
  recorded before migration 0025, and the first call and digest on one before migration 0027.
- `run_slots`: one row per slot a run leased; the repository whose pool it came from, slot path, lease id and holder,
  and the base branch the run started from there. A joint run has one per repository.
- `review_runs`: one row per review run; the PR's URL, the commit, the ticket of an agent PR, the repository and slot,
  pids, times, status, the validated result (§21), and what the runtime reported (§13), as `runs` has it.
  `decisions.pr` names the PR of a decision about a review.
- `run_tools`: one row per agent run and tool it called (§13), the run by its table (`ticks` for an overseer, `runs`,
  `chore_runs`, or `review_runs`) and id; the tool's name, its calls, the calls that ended in an error, and the
  characters they returned. Written with the run's cost, in place of what was there; no row for a run whose template
  prints no events, nor for one recorded before migration 0032.
- `attempt_grants`: one row per `canopy grant`; the ticket, repository, kind, runs granted, and when (§22).
  Only added to.
- `review_grants`: one row per `canopy grant URL review`; the PR's URL, review runs granted, and when (§21, §22).
  Only added to.
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
- `notices`: one row per notice to workers the operator set (§8): its text, when and through which channel it was set,
  when it lapses, and when and through which channel it was cleared or replaced, if it was. At most one is in force;
  rows are never deleted.

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
   committed, and optional. It serves every workspace, so it holds what is the same in all of them: the runtime
   templates, the comment marks, the commit trailer, notification sinks.
4. **Private file**, `<state_dir>/config.toml`, the workspace's own file for the operator alone, never committed. It
   holds what belongs to one workspace: its queue labels, its authorized repliers and trusted reviewers (each in its
   tracker's identity format), `review.query`, `runtime.setup_cmd` and `runtime.pr_skill`, `tracker.mcp_server`, its
   chores, its loop's pacing, its capacity (each workspace's journal counts its own), and its web UI's port, so that
   two workspaces' loops do not collide.

At least one of the user file and the private file must exist; with neither, the error names the private file and
`canopy init`. A user file from before the private file keeps working unchanged: nothing migrates.

Every key has a scope. A **shared** key may be set in any file. A **private** key may be set in the user file or the
private file, never in the workspace file; a workspace file that sets one is a config error that names the key and the
private file, and canopy refuses to run. No key is held to the user file, the comment marks and the commit trailer
included: a workspace whose team marks agent work its own way sets its own. Unknown keys are errors in every file. A
removed key, such as `paths.state_dir`, is an error that says what to do instead. A validation error names the file
the bad value came from, or, for a missing key, every file it may be set in.

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
max_fix_ci_attempts = 2
fix_ci_cooldown_minutes = 30
max_resume_attempts = 3
max_split_attempts = 1       # per ticket (§18)
max_plan_attempts = 3        # per ticket (§25)
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
```

Built-in defaults are the values shown, except: `tracker.provider`, `tracker.query`, and `tracker.labels` have no
default and must be set; `trust.authorized_repliers` defaults to empty (nobody can resume blocked work), and so does
`trust.trusted_reviewers` (every review waits for the operator). A trusted reviewer is `canopy:review` or a login of at
most 100 characters with no whitespace, colon, or backtick.

`trust.comment_prefix` and `trust.comment_suffix` are each empty or one line of at most 80 characters, with a letter or
digit, no backtick, and no surrounding spaces, and at least one is set.

`trust.commit_trailer_name` and `trust.commit_trailer_email` make the `Co-authored-by` trailer a worker adds to its
commits when the agent runtime adds no attribution of its own (§8, TRUST_MODEL T5). The name is one line of at most 80
characters, with a letter or digit, no backtick or angle bracket, and no surrounding spaces; the address is at most 254
characters, with one `@` and no whitespace, backtick, or angle bracket. They are private because the commits are the
operator's: a shared file must not credit agent work to a person. Set them to name agent work the way the team's
tooling expects, such as a team's bot address, and never to a person: the trailer is how a reader tells the work is
an agent's. `trust.commit_trailer = false` turns the trailer off, for a runtime whose own attribution suffices or a
team whose tooling rejects it: a worker still keeps the runtime's trailer, but adds none of its own, so with a runtime
that adds none the commits carry no trailer, and only the branch prefix and the PR mark the work. It is private for
the same reason.

`trust.rebase` is for repositories whose host or CI refuses merge commits. Set, a worker that brings a base branch into
its branch rebases onto it instead of merging it, and pushes the result with `git push --force-with-lease`; the
worker's definition allows that one force and no other, and `canopy _run`'s own push takes a lease on the commit the
run started from (§8, TRUST_MODEL T1). It applies to every repository the operator works on. It is private because
it lets a worker replace a branch's history: a shared file must not decide that.

**From the web UI.** The Limits and trust page under Settings (§22) edits a few keys of the user file in place, and no
others (D121, TRUST_MODEL T8). They are named one by one in `canopy/serve/config_edit.py`, never by section, so a key
added to a section later is not editable until it is named there. A limit may be raised or lowered, but the page cannot
loosen it past its bound; the file can set any value, and the page may still tighten a value the file set past the
bound. A trust key moves only toward stricter: a config write outlives the listener secret, and a replier added through
a stolen session would go on steering workers after a new secret ended it.

| Key | From the page |
|---|---|
| `capacity.max_workers`, `capacity.slots_per_repo`, each `capacity.repo_slots` entry | at most 32; an unmanaged pool's first count is bounded too |
| `capacity.max_chores`, `capacity.max_reviews` | at most 16 |
| `capacity.max_reviews_per_day` | at most 500 |
| `policy.max_implement_attempts`, `policy.max_fix_ci_attempts`, `policy.max_resume_attempts` | at most 10 |
| `policy.max_split_attempts` | at most 5 |
| `policy.max_reviews_per_pr` | at most 25 |
| `policy.fix_ci_cooldown_minutes` | at least 5 |
| `loop.interval_minutes`, `loop.idle_max_minutes` | at least 2 |
| `policy.stacking` | to `"never"` only |
| `trust.authorized_repliers`, `trust.trusted_reviewers` | entries removed, never added |
| `trust.rebase` | to `false` only |
| `trust.commit_trailer` | to `true` only |

The bounds sit well above what one machine runs today, so the page serves the operator's real changes; what they stop
is a stolen session turning spend up without limit. A raise within them outlives a new secret, and that residual is
spend, which the page and the log show. `capacity.repo_slots` is edited as its entries: the page lists the
repositories with a count of their own and takes a name to give another one, so a workspace of many repositories
shows the few that differ from `capacity.slots_per_repo`. A save:

- writes the user file only, never the workspace file (T7), a shared `policy.*` key included: the user file wins;
- is edited in place with tomlkit (D122), so the operator's comments, order, and layout stay; a list loses its removed
  entries where they stand, keeping the rest and their comments. A file tomlkit would not write back byte for byte, as
  read, is refused `not_roundtrip` before anything changes, so a save differs from the file only in the values set;
- keeps the file as it was beside it, `config.toml.bak` with the file's mode, replacing the previous save's: the way
  back from a save is to move it over the file and Reload;
- carries the hash of the user file as the page read it, and holds a lock beside the file (`config.toml.lock`) from
  reading the file to replacing it, so two saves made on one read cannot both pass; a file whose hash differs is
  refused `stale`, checked again just before the replace, so a hand edit is lost only if it lands in that last moment;
- applies the change to a copy beside the file, which `config.load` validates as any `canopy` command would read it,
  and checks every bound on the values the copy loads to, so the rules hold whatever the request's shape; a refusal
  writes nothing and gives the loader's message, naming the user file;
- replaces the file atomically, keeping its mode, and refuses one that is a symlink or not the operator's (D053's
  check, `unsafe_file`), and inside a tick or run (`inside_run`), as the CLI's verbs do;
- logs each change with channel `web`, the key, and its old and new values, then asks the loop to read its config
  again through the same path as Reload (§6). A save whose reload is refused, or never asked for because the server
  stopped between the two, takes effect at the next reload.

There is no CLI verb for it: the operator's editor is the CLI's way, and a `canopy config set` would be in reach of
the overseer's `canopy *` bash rule. Pools: a changed `capacity.slots_per_repo` or `capacity.repo_slots` bounds leases
from the next tick; making or removing slots is still `canopy workspace sync`, which the page does not run.

Rejected: a file of canopy's own layered after the user file (a hand edit to the user file would be silently
overridden), and writing the user file anew with the stdlib (its comments lost).

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
- `canopy init` writes the private file if missing, readable only by the operator, with
  `tracker.labels = ["agent-ready-<$USER>"]` and an empty `trust.authorized_repliers` and `trust.trusted_reviewers` to
  fill in, each only where the user file does not set it, and prints the label when it writes one. It never writes the
  user file. It writes the workspace file only if there is none, with `tracker.provider` and an example
  `tracker.query`. No file gets a key whose default serves: a default written into a file is pinned there, and a later
  canopy's never reaches it. It never overwrites a file and installs nothing else (§13). If the config does not load
  (for example, templates lacking `{definitions_dir}`), it prints the error. It warns about copies of canopy's agent
  definitions in the OpenCode config of the workspace root and of each cloned repository, which stop runs (§13). Unless
  `worker_cmd` already starts with `canopy-sandbox`, it prints that template behind the wrapper's prefix as a line for
  the user file, pointing to `docs/SANDBOX.md`, and writes nothing: the sandbox is opt-in and needs `canopy sandbox
  setup` first (§24).
- `canopy sandbox setup` needs no workspace. It copies `canopy-sandbox`'s policy templates to
  `<user config dir>/sandbox/` (0700), never over one that is there; installs `srt` with
  `npm ci --ignore-scripts --engine-strict` from the lockfile the wrapper ships, into
  `$XDG_DATA_HOME/canopy/sandbox-runtime/`, unless an earlier install of that lockfile finished and its `srt` answers
  the pinned version (a copy of the lockfile, written only once an install has, records which did); and checks what it
  never runs because it needs root: on Linux bubblewrap, socat, and ripgrep, and that bubblewrap can make a user
  namespace (naming the AppArmor sysctl when that is why not), on macOS ripgrep, and that canopy is not root. On Linux
  it also checks what `srt` only warns about, with `--debug`, and runs without: bubblewrap 0.5.0 or later, and a
  machine `srt` ships its seccomp filter for (x86_64, aarch64), without which a sandboxed command can connect to any
  Unix socket it sees. Either missing would leave a sandbox weaker than §24 says, so each is a thing to do.
  It prints each thing left to do and exits 1 while there is one; it writes no config, and prints the `worker_cmd`
  line `canopy init` does (D117).
- `capacity.slots_per_repo` and `[capacity.repo_slots]` declare each repository's pool size in a workspace (§18).
  Unset (the default) leaves pools unmanaged. Private, so a team's map cannot grow the operator's disk use.
- `pools.backend` names the pool that makes the workspace's worktrees: `"treehouse"` (the default) or `"canopy"`,
  canopy's own (§18). Switching is safe with runs in flight; `canopy workspace sync` carries the idle slots over.
- Remotes should be HTTPS with a credential helper, not SSH: a sandboxed worker cannot reach the SSH agent socket.
  `canopy workspace sync`, which `canopy init` runs
  for the URLs it is given, runs `git remote get-url --push --all origin` in each primary clone, which applies
  `insteadOf` and `pushInsteadOf` rewrites, and warns naming every URL git would reach over SSH: `ssh://`,
  `git+ssh://`, or scp-like `[user@]host:path`. Only a warning: sync still succeeds, and nothing else checks the
  remote.
- Reading is `tomllib`, merging is a key-by-key dict merge, and validation is pydantic models carrying each key's type,
  default, scope, and tighten direction (D026). Scope and tighten checks run per file before the merge, so errors name
  the file that caused them. `[chores]` comes whole from the last file that sets it.

A command template is split into words with `shlex`, then `{prompt}` and `{definitions_dir}` are replaced inside each
word in one pass. No shell runs, so the prompt is always exactly one argument (D023). Every agent template must contain
`{prompt}` exactly once and `{definitions_dir}` (the definitions directory, §13) at least once; a template without it
is a config error that prints the line to write instead. The check cannot tell where the runtime reads the value: a
custom template, such as a sandbox wrapper's, must still set `OPENCODE_CONFIG_DIR` to it, or OpenCode runs its default
agent, which allows everything (D040). `env` in the default templates is the ordinary program, not a shell.
`notify.cmd` is split the same way, gets its input on stdin, and must not contain `{prompt}`.

Overrides in `prompt_overrides` replace files of the same name in `prompts/`. An overseer override goes where the
shipped prompt goes, into the overseer's definition in a snapshot of its own (§13), so a change to it reaches the next
tick, and one canopy cannot read as UTF-8 refuses the snapshot. An override must keep what the guards rely on: an
overseer override must pass `--label` on every `canopy dispatch`, and a worker override must include `{{LABELS}}` and
the authorization check that uses it (§8, D051); a worker override without it is refused as `bad_prompt`. The default is
`prompts/` next to the user file, `~/.config/canopy/prompts` unless `XDG_CONFIG_HOME` says otherwise; an empty value
means the default. In the user file, `paths.*` values must be absolute or start with `~`, since canopy runs from the
workspace root and a relative path would let a shared workspace supply them (TRUST_MODEL T7). In the private file a
relative value resolves against the state directory, never the workspace root:
`worker_instructions = "worker-instructions.md"` names `<state_dir>/worker-instructions.md`, private and under the
provenance check above. There is no key for the state directory: it is always `<workspace>/.canopy/` (§18), written
`<state_dir>` in this document.

`paths.worker_instructions` names a file of the operator's standing instructions, a few habits every worker should
keep, such as how to commit review fixes. canopy renders it into every worker prompt but a split's, as
`{{STANDING_INSTRUCTIONS}}` under its own heading, before the obligations, which come first (§8). It adds to the shipped
prompts without copying them, so prefer it to an override for anything a few lines can say; a skill is still the place
for know-how a worker loads when it needs it (§13). It is at most 4 KiB of UTF-8, and a file canopy cannot use refuses
the dispatch as `bad_prompt` rather than running a worker without it. Like every `paths.*` key it is private: set in
the user file, it serves every workspace; set in the private file, one. A passing condition, such as a CI outage,
belongs in a notice to workers (§8) instead: it lapses on its own, the overseer and reviews hear it too, and the web UI
shows it while it lasts.

`tracker.provider` is a free-form name the harness never branches on; prompts use it to name the `tracker-<provider>`
skill, and every shipped skill is in the definitions directory (§13). The one use canopy makes of it is to look up that
skill by name and give it to the overseer in its definition, so it need not be loaded on every tick (§13).
`tracker.query` is how the overseer finds candidates: in the tracker's search syntax where it has one (JQL, GitHub issue
search), otherwise plain language. It finds tickets; it does not authorize them (§17). The repository's query usually
omits the label; an operator can override it in the private file to include their labels and save the overseer reads.
It is shared though the overseer reads every ticket it returns before it checks labels: the operator's choice
(2026-10-15), with that exposure stated in TRUST_MODEL T7's residual.

## 13. Agent runtime

OpenCode. The harness depends on one capability: run a named agent non-interactively in a given cwd with a prompt and
read its stdout, `opencode run --agent <name>`. MCP connectivity, OAuth, and tool permissions are the runtime's job.

Agent definitions ship in `agents/`; agent runs load them from a directory canopy owns (below):

- `canopy-overseer`: read-only tools plus bash restricted to `canopy *` and `treehouse status*`, nothing outside the
  workspace (`external_directory: deny`), and one command per bash call, as its prompt says: an `ask`, such as a `cd`
  out of the workspace, ends the run under `opencode run` (D021) and loses every decision it had not recorded, where a
  `deny` costs only the call. MCP: the tracker, GitHub.
- `canopy-worker`: edit and bash within the worktree. MCP: the tracker (ticket comments, and labels through its issue
  edit tool), GitHub (open/update PR, read reviews and checks); merge, review
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
per line; otherwise it is stdout itself. Every result contract (the overseer's done token, §8, §18, §19, §21) is read
from that text, so a template may switch formats without changing a prompt. The agent's final message is the last
`text` event's text; plain stdout does not say where a message ends, so all of it is the final message.

A JSON contract (§8, §18, §19, §21) is the last line of the text that starts with `{`, and lines after it that do not
are passed over: a runtime, or a plugin the operator must load, may print a notice after the agent's last word, and a
plain template, or one that sends stderr to stdout, puts it in the text. A last object that does not validate is no
result; canopy never falls back to an earlier one, which may be an example the agent quoted or a result it took back.
The overseer's done token is plain text, a line anywhere in its final message (§6).

From events the harness also reads, each validated (D026):

- the session id: the first `sessionID` of at most 100 letters, digits, `_`, and `-`. The operator opens the
  transcript with OpenCode's own tools (`opencode export <id>`, or `opencode --session <id>` in the run's directory).
- the session title is not among them: OpenCode titles a session in the background, with a model call over the first
  message, and `run --format json` prints no event for it. canopy names the session instead (below).
- the cost: the sum over `step_finish` events, one per model call, of `part.cost` in dollars and `part.tokens` (input,
  output, reasoning, cache read, cache write), each call's cost at most $1,000,000 and each count at most 10^12. If one
  does not validate, the run reports no cost rather than too little. Events with no model call cost nothing. A run
  killed mid-call (a timeout) reports what its finished calls cost, a lower bound. A subagent's calls are its own
  session's, and not counted.
- the peak context: the most one `step_finish` was sent, its input, cache read, and cache write together, so how large
  the run's context grew. 0 when it made no model call.
- the first call: what the first `step_finish` was sent, counted the same way, and its cache write, each None when it
  made no model call. All of a run's fixed overhead (the system prompt, the agent's body, the tool schemas) is in its
  first call, so less the prompt canopy sent it is the overhead, and the cache write says whether the provider had
  the prefix cached: small on a warm start, the whole prefix on a cold one (MEASUREMENTS 2026-10-13 F11, F12).
- the tool calls: each `tool_use` event, printed once its call ended, `completed` or `error`, rolled up by `part.tool`:
  how many calls, how many ended in an error, and the characters of what they returned (`state.output`, or
  `state.error` for an error). One that does not validate is not counted. A tool's name is kept as printed but for
  control characters and runs of whitespace, cut at 200 characters, and a run keeps at most 200 tools, the calls of
  any after them counted under `(other tools)`, which no runtime names a tool: far more than a runtime offers, and few
  enough that output no runtime printed cannot fill the journal. A subagent's calls are its own session's, and not
  counted.

With the report the harness records the tool rollup in `run_tools` (§11), and the digest of the definitions snapshot
the run loaded, the name of its directory (`core/definitions.py`), so a change to a prompt, an override, or a
definition splits the runs into before and after. The digest only when the runtime reported something: a template
that prints plain text may not load the snapshot at all.

Wherever canopy prints what a run or a tick cost, the CLI (`Usage.describe`) and the web UI alike, it says it as
`$0.25, 3.5k tokens, 5.5k peak context`. The tokens are every kind but cache reads: input, cache write, output, and
reasoning, summed over the calls. Cache reads are left out of the headline because each call reads again what the
calls before it were sent, so their sum grows with the square of a session's length and dwarfs the rest: a run of 40
calls over a 50k context reads two million tokens from the cache, which says nothing about what it did. The peak
context says what the sum hid, how large the context got. Each kind is still kept apart in the journal, and a
transcript shows each call's (§22). A run recorded before the peak was kept prints its tokens alone. It once said
`new tokens`; the operator found the word drew a distinction that was no use to them (2026-10-15), so it is just
`tokens`, and the hover on it in the web UI says what is left out. A log line's and the API's `new_tokens` and
`peak_context` are the same two counts, their names unchanged.

The default `overseer_cmd`, `worker_cmd`, `split_cmd`, `plan_cmd`, `chore_cmd`, and `review_cmd` ask for events. A
tick records what its overseer reports on the tick (§6), `_run` what a worker, split, or plan reports on the run, as it
prints it (§8, §11), `_chore` what a chore reports on its chore run (§19), and `_review` what a reviewer reports on its
review run (§21). So every agent run canopy starts records what it cost, and the web UI's spend (§22) sums them all, a running
worker's so far. A template of the operator's that asks
for no events records nothing, and its runs are missing from the spend. A tick's output file and a run log hold the
events as printed, and the web UI reads one session's back from them as its transcript (§22).

### Session titles

Every runtime template may name `{title}`, the run's session title, and the defaults pass it as
`opencode run --title={title}`, so OpenCode's session list names each session as canopy does:

- a worker or split run: `<KEY> <kind>: <the ticket's title>` (§7), or `<KEY> <kind>` before the overseer names it;
- a tick's overseer: `tick <id>`; a chore: `chore:<name>`; a review: `review <PR URL>`.

The title is read when the run starts, so a rename shows in canopy at once and in the runtime from the ticket's next
run. canopy names sessions rather than reading OpenCode's own titles because those are not in the events (above):
reading one back would take an OpenCode-only command after every run, where the runtime is otherwise only a command
template (§12), and its model writes it from canopy's prompt, which is mostly the same for every run of a kind.

Like `{prompt}`, `{title}` is replaced inside a word, after the template is split, in the same pass as the other
placeholders. The defaults keep `--title=` and the title in one word, so a title is never read as an option, and every
title starts with a letter or digit (a key, `tick`, `chore:`, `review`), so not even as a word of its own.

### Where the runtime finds canopy's definitions

Rationale in D040 and D044.

canopy snapshots its bundled `agents/` and `skills/` into `<state_dir>/runtime/<digest>/`, named for a digest of their
contents (`definitions.py`). Two definitions are rendered from config first, so a change to what they are rendered from
makes a new snapshot rather than changing one:

- `canopy-worker-private` gets the tracker's MCP server and the tools of it a private worker may call (§22).
- `canopy-overseer` gets the overseer's prompt, the operator's override if there is one (§12), as its body from a marked
  line on, followed by the shipped `tracker-<provider>` skill for `tracker.provider`, without its frontmatter, when
  canopy ships one. OpenCode sends an agent's body as its system prompt, which the provider caches across ticks with
  the tool schemas; a tick's message is its state block alone (§6). The skill stays in `skills/` too, for the workers.
  An override canopy cannot read refuses the snapshot, which fails the tick and every run started from it, as a
  snapshot that is not private does (below): a run without its definitions would run without the prompt. A definition
  canopy did not render, such as the shipped file loaded by hand, tells the overseer to print `no prompt supplied` and
  exit.

A snapshot is written to a temporary directory, renamed into place, and never changed, so overlapping runs never load a
partial set. The overseer run and each `_run` use the installed canopy's snapshot, creating it if missing. A snapshot
canopy made is readable only by the operator; one that is a symlink, someone else's, or open to others (for example from
a checkout of a shared workspace, §18) is refused: the overseer's refusal fails the tick, a worker's is a `crashed` run.
When no run is live, reconcile removes other snapshots and temporary directories over an hour old; a live run may be an
earlier canopy's, still loading its snapshot. OpenCode scans both `agent/` and `agents/` (and `skill/` and `skills/`) in
a config directory, and writes a `.gitignore` and `node_modules/` into each one it loads, the snapshot included.

Command templates name the current snapshot with `{definitions_dir}` (§12), required in every template that runs a
canopy-shipped agent (`overseer_cmd`, `worker_cmd`, `private_worker_cmd`, `split_cmd`, §25's `plan_cmd`, §19's
`chore_cmd`, §21's `review_cmd`):

```toml
overseer_cmd = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer --format json
    --title={title} {prompt}'''
worker_cmd   = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --format json
    --title={title} {prompt}'''
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
the state directory's files are, how to read the journal read-only, how to answer "why was KEY not picked up", and how
to look into chore and review findings and draft tickets from them, filed only when the operator says and never
labeled. canopy installs it nowhere: the operator saves it where their runtime reads skills, such as
`~/.agents/skills/canopy/SKILL.md`, and again after upgrading. It is not in the definitions snapshot, where it would
help no run, so a `$HOME` copy,
which canopy's own runs also load, never meets a same-named skill. It opens by telling an agent started by canopy
(`CANOPY_TICK_ID` set, or a canopy prompt) to follow its prompt instead. It grants nothing: the overseer's and worker's
bash rules apply either way.

### Shell completion

`canopy completion SHELL` prints the script that completes canopy in bash (4.4 or newer), zsh, or fish; the operator
loads it from their shell's startup file, as its help shows. The script is click's: on Tab it runs `canopy` with
`_CANOPY_COMPLETE` set, which click answers before any command runs. Commands, options, and choices complete from the
CLI's definition, less the commands only the overseer runs inside a tick (`dispatch`, `decide`, `queried`, `attention`,
`mirror`, `ticket set`, and `chore` and `review`'s `run` and `wait`): they would refuse the operator anyway, so Tab does
not offer them, though `--help` still lists them and a command typed in full still completes its arguments. Repository names
complete from the map of the workspace the shell is in, and chore names from its config; outside a workspace, or when
its config does not load, they complete to nothing rather than fail. Ticket keys do not complete: that would mean
opening the journal on every Tab. The command prints click's template itself rather than calling its `source()`, whose
bash version check runs bash outside `canopy.infra.procs`.

## 14. Attention list

After every tick the list is rendered to `<state_dir>/attention.md` (`.canopy/attention.md` in the workspace), readable
only by the operator: grouped by reason, one line per item with ticket key, age, and detail (usually a link).
`canopy status` prints it too, after a line for the last tick: its status, how long ago it started, its summary, and
its overseer's cost when the runtime reported it, and a line each for a pause and the notice to workers in force (§6,
§8). Items disappear when their cause is gone; there is no manual
dismissal.

`canopy status` also lists the tickets the operator started (§22), each with its title (§7), status, phase, and the
message it awaits a reply to, running workers, and the ten runs that ended most recently, the last first: ticket and its
title, kind, status, how long ago it ended, and each PR it reported; its harness note or else its summary, on one line
with control characters dropped and cut at 160 characters; and its session id, its cost, tokens, and peak context
when the runtime reported them (§13), and its run log.

Reasons are exactly the attention rows in the phase table plus `crashed`, `unpushed`, `unknown_result`, `worker_failed`,
`attempt_limit`, a private ticket's `awaiting_reply` (§22), `canopy_unavailable` (§6 step 5), and in a workspace
`repo_missing` and the overseer's `multi_repo`, `split_unlabeled`, and `split_self_labeled` (§18). Chores add
`chore_failed` and their findings, listed by chore after the ticket items (§19). Reviews add `review_failed` and
`review_limit`, about a PR (§21). A notice to workers adds the overseer's `notice_rerun`: a check failed while a notice
was in force, the notice has ended, and no newer run of the check exists, so the operator reruns it (§8). An item about
one unit of a ticket names its repository and is shown as `KEY (repo)`.

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

A tick raises `canopy_unavailable` when `canopy --version` fails from the overseer's environment, and runs no overseer
(§6 step 5). It is about neither a ticket nor a repository, and is shown as `-`. Its detail says why, and its cause is
gone at the first tick that ends otherwise.

The overseer records an item with `canopy attention <KEY> <reason> [--repo NAME] --detail "<link or text>"`, every tick
the cause holds. `--repo` names the unit it is about, such as the PR waiting on a reviewer. The item is stored as a
decision with action `attention:<reason>`, not in a separate table (D020). The current list is the attention decisions
of the latest `ok` tick: an item disappears the first tick that does not record it, and a failed or `skipped` tick
leaves the previous list standing. A `canopy_unavailable` tick adds its one item to that list while it is the latest
tick to have ended, open since the first such tick after the last `ok` one. The overseer's state block lists its own
open items (`attention`, §6 step 4), so it records each again until it sees the cause gone. Dry-run ticks count like
live ones. An item's age runs from the first tick of its unbroken run. Reasons must match `[a-z][a-z0-9_]*`.

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
- One operator on several repositories. Answered in M6 by the workspace (§18): one queue, and state per workspace
  under its root, with its private config since M49. Repositories that are not one queue go in separate workspaces, each
  with its own journal and locks.
