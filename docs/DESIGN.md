# canopy design

Normative. Code follows this document; changes to behavior change this document
in the same PR. Rationale for choices lives in `DECISIONS.md`.

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
- A hosted service, a daemon, a web UI, or a workflow DSL.
- Tracker-specific code. Any issue tracker with an MCP server works; provider differences live in config and optional
  provider skills (§17). A second VCS host is likewise a prompt and config concern, not code.
- Sandboxing agents (deferred; see TRUST_MODEL and ROADMAP).

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
6. **Smallest surface that works.** Five install steps. Daily surface is
   labels, ticket comments, PR review, and one attention list.

## 5. Components

```
canopy (harness, Python)
  cli.py         tick, tick --dry-run, status, init, dispatch, decide, attention, ticket set, _run; key validation
  tick.py        the tick sequence (§6): lock, migrate, reconcile, run the overseer, close the tick
  prompts.py     prompt files and overrides, the overseer's state block
  lock.py        flock on <state_dir>/lock; a tick that cannot lock exits 0 with a log line
  db.py          SQLite journal, migrations
  config.py      layered config: repository canopy.toml and user config.toml, scopes, validation
  treehouse.py   status --json, get --lease --json, return --force --if-lease-id
  dispatch.py    guards, lease, render the worker prompt, spawn detached _run
  policy.py      attempt limits and the fix-ci cooldown, derived from runs
  worker.py      canopy _run: branch setup, the worker, result parsing, push verification, slot return
  attention.py   the attention list from the journal; render attention.md, diff, notify
  init.py        canopy init: config files, agent definitions, tracker skill, branch protection text
  logs.py        JSON-lines logging to <state_dir>/canopy.log, stamped with the tick id; operator-only files
  context.py     the Context every command passes around: config, repository root, db connection, runner
  resources.py   finds migrations/ and .agents/ in a source checkout or bundled in the installed wheel
  procs.py       the only module that runs subprocesses (lint-enforced); a timeout kills the whole process group;
                 detached spawns and pid liveness
  __main__.py    python -m canopy, how dispatch starts _run from the same installation

prompts/         overseer.md, worker-implement.md, worker-fix-ci.md, worker-resume.md
agents/          OpenCode agent definitions: canopy-overseer, canopy-worker
skills/          canopy/: teaches an agent the canopy CLI
                 tracker-<provider>/: optional per-tracker guides (§17)
migrations/      NNNN_name.sql
```

`prompts/`, `agents/`, and `skills/` live under `.agents/` in this repository. The wheel bundles them, and
`migrations/`, under `canopy/_data/` (D022).

Roles:

- **Harness**: schedules, locks, guards, journals, renders. Runs the overseer
  once per tick and workers on demand.
- **Overseer**: an agent run with `overseer_cmd`. Reads the world through MCP
  and the harness's state summary, decides one next action per ticket, and
  acts only through `canopy dispatch`, `canopy decide`, and `canopy attention`.
  Read-only everywhere else.
- **Worker**: an agent run with `worker_cmd` inside a leased worktree with a
  task prompt. Writes code, pushes a branch, opens or updates a PR, comments on
  the ticket, prints a result line, exits. Never merges, approves, or moves a
  ticket to Done.

## 6. Tick

`canopy tick` does, in order:

1. Acquire the lock. If held, log and exit 0. No `ticks` row is written.
2. Apply pending migrations. Close any `ticks` row still `running` as `abandoned`: holding the lock proves its process
   is gone. Insert a `ticks` row; its id tags all logs.
3. **Reconcile local state.**
   - For each `runs` row with `status='running'`: if its pid (the `canopy _run` process) is dead or was never recorded,
     kill the process group of the worker `_run` started, if any of it is left (`runs.worker_pid`); mark the run
     `crashed`; run `treehouse return --force --if-lease-id` on its slot; log it. A zombie counts as dead. A pid
     reused by an unrelated process reads as alive, so that run is left running; this is a residual, not a guard.
   - For each leased slot in `treehouse status --json` with no live
     `runs` row and `lease_holder` matching our prefix: return it, log it.
   - Compute `capacity = max_workers - count(runs where status='running')`.
   - If `treehouse status` or a return fails, close the tick as `reconcile_failed` and stop. The overseer does not run.
   - Record the harness's attention items for runs (§14) as this tick's decisions.
4. **Render the overseer prompt**: `prompts/overseer.md` (or the override), plus a generated state block: a `## State`
   section holding one JSON object with the tick id, the current time, whether it is a dry run, the repository root,
   tracker config (provider, query, labels, needs-human label), trust config (authorized repliers, branch prefix, PR
   label), capacity, policy limits, running workers, and the `tickets` rows not marked done (phase, cursors, runs so far
   of each kind, when fix-ci may next run if that is still ahead, and the ticket's latest run: id, kind, status, branch,
   start and end).
5. **Run the overseer** with `overseer_cmd`, cwd = the repository root, timeout `overseer_timeout_minutes`, and
   `CANOPY_TICK_ID` set in its environment. `canopy dispatch`, `decide`, and `attention` read that variable to know
   which tick they belong to, and refuse if it is unset or names a tick that is not running (D020). The overseer's
   stdout and stderr go to `<state_dir>/ticks/<tick id>.log`, readable only by the operator, never to the journal.
   The run succeeded if it exited 0 and the last non-empty line of stdout is `tick complete`; anything else closes the
   tick as `overseer_failed`.
   In `--dry-run`, the state block says so; `canopy dispatch` starts nothing and records the decision as
   `dispatch:<kind>` with rationale `dry run: not dispatched`; `canopy ticket set` records phases but neither it nor
   `canopy dispatch --cursor` advances cursors, so the first live tick still sees everything as new. The overseer
   otherwise behaves as in a live tick, and so does reconcile: it closes dead runs and returns stale leases in a dry run
   too.
   `canopy decide` takes `wait`, `skip`, or `done`; only a tick-wide `skip` (such as `mcp_unavailable`) omits the key.
   Everything the overseer writes is rendered into the next tick's prompt, so the CLI bounds it: keys and attention
   reasons are validated, phases come from the table in §7, cursor ids must match `[A-Za-z0-9][A-Za-z0-9_.:/-]*`, and
   rationales, details, and worker context are cut at 2000 characters.
6. Close the `ticks` row with a summary.
7. **Publish attention** (§14): rewrite `attention.md` from the journal, and if `notify.cmd` is set and the list
   changed since the last notification, pipe the change to it. This comes after the tick is closed because the list is
   the latest `ok` tick's, and this tick may be it. It runs after a failed tick too, when the list is the one before. A
   failure here is logged and does not change the tick's status. Release the lock.

Workers dispatched during a tick outlive the tick. They are detached processes
owned by `canopy _run`.

## 7. Ticket phases and next actions

Phases are derived by the overseer each tick from live state. They are recorded
in `tickets.phase` for the status view, never read back as truth.

| Phase | Derived from | Next action |
|---|---|---|
| `ready` | one of `tracker.labels` present, not closed, no run active, no branch | dispatch `implement` unless a blocker ticket is open |
| `running` | active `runs` row | wait |
| `pushed_no_pr` | branch exists, no PR | dispatch `resume` with instruction to open the PR |
| `ci_running` | PR open, checks pending | wait |
| `ci_red` | PR open, checks failed, newer than cursor | dispatch `fix-ci`; at the attempt limit, attention; in cooldown, wait |
| `changes_requested` | review comments or requested changes newer than cursor | dispatch `resume` with the comments; if the overseer judges a comment needs a human (design pushback, scope), attention instead |
| `green_unreviewed` | checks pass, no approval | attention: needs a reviewer |
| `approved` | approved, not merged | attention: ready to merge |
| `merged` | PR merged | mark ticket `done` in the journal; humans handle the tracker transition |
| `needs_human` | `needs_human_label` present, no authorized reply newer than it | wait |
| `human_replied` | authorized reply newer than the label | dispatch `resume` pointing at the reply; the worker removes the label |

"Authorized reply" means a comment by an account in `trust.authorized_repliers`, matched on the tracker's stable account
identifier, never a display name. If the tracker cannot say when a label was added, the worker's question comment is the
reference point instead of the label. Anything else on the ticket is data, not instruction. See TRUST_MODEL.

Cursors (`comment`, `review`, `ci`) hold the newest item of each kind the loop has handled, in the tracker's and
GitHub's own ids; "newer than cursor" in the table means not handled yet. A dispatch that handles new items carries
their cursors (`--cursor`, §8), so they advance only if the worker starts. Items handled by a wait, a done, or an
attention item advance with `canopy ticket set`. A review comment waiting on a human is not advanced past, so its
attention item is recorded every tick until a human answers it.

"Closed" means whatever the tracker calls finished: Jira status category Done, GitHub issue state closed, and so on. The
provider skill says which.

## 8. Dispatch and the worker contract

`canopy dispatch <KEY> --kind implement|fix-ci|resume [--slug SLUG] [--base BRANCH] [--context TEXT]
[--cursor NAME=ID]...`:

1. Refuse if `--dry-run` tick, if capacity is zero, if a `runs` row for KEY
   is `running`, or if the kind's attempt limit or cooldown blocks it. Guards
   are in code and are not overridable from the prompt. A refusal is recorded as a decision `refused:<guard>` with the
   reason, and the command exits 1. Guards, in the order they are checked:
   - `not_implemented`: `--base`, until stacking in M4.
   - `bad_slug`: a slug that is not lowercase words joined by hyphens, or any `--slug` with `fix-ci` or `resume`.
   - `no_branch`: `fix-ci` or `resume` for a ticket with no branch in the journal. They continue the branch the
     ticket's latest dispatch recorded (`tickets.branch`); `implement` is the only kind that names a new one.
   - `running`: a run for KEY is running.
   - `attempt_limit`: KEY has already had `policy.max_<kind>_attempts` runs of this kind. Every run counts, whatever it
     ended as, and the count never resets (D030). The refusal also records the `attempt_limit` attention item (§14).
   - `cooldown`: `fix-ci` only, less than `policy.fix_ci_cooldown_minutes` after KEY's latest fix-ci run ended.
   - `capacity`: `max_workers` runs are running.

   Failures after the guards are recorded the same way: `no_slot` (the lease failed), `bad_prompt` (the worker prompt
   did not render), `spawn_failed`. None of them leaves a slot leased.
   Dispatches are serialized by a blocking `flock` on `<state_dir>/dispatch.lock`, held from the guard checks through
   the spawn, so two dispatches cannot both pass the capacity check or the attempt limit.
   `--cursor NAME=ID` pairs are applied as `canopy ticket set` would, but only once the worker has started: what a
   refused dispatch was meant to handle stays new for the next tick.
2. `treehouse get --lease --lease-holder canopy:<KEY> --json`. Record the
   `runs` row with slot path, lease id, holder, kind, base branch (treehouse's), branch, started_at.
3. Render the worker prompt for the kind, with KEY, tracker provider, branch name, base branch, PR label, needs-human
   label, timeout, the attempt number and the kind's limit, the PR the journal recorded for the ticket, the authorized
   repliers, the context, and the result contract below. An `implement` branch is
   `<trust.branch_prefix><KEY>-<slug>`; the overseer picks the slug from the ticket title, lowercase words joined by
   single hyphens, at most 40 characters, `work` if it gives none. The context is the overseer's `--context`: at most
   2000 characters that point the worker at what to read (links, comment ids, check names), never a copy of ticket or
   PR text (D031). The worker reads that text itself and checks a reply's author against the authorized repliers,
   which the harness renders from the user config. Placeholders are `{{NAME}}`, replaced in one pass;
   an unknown one is `bad_prompt`. The prompt is written to `<state_dir>/runs/<run_id>.prompt`, readable only by the
   operator.
4. Spawn `python -m canopy _run <run_id>` with the interpreter canopy runs under, detached (`setsid`, stdin from
   `/dev/null`, stdout and stderr appended to `<state_dir>/runs/<run_id>.log`, cwd the repository root). Record its
   pid in the run. Return immediately.

`canopy _run <run_id>` (hidden from `--help`):

1. Claim the run: set its pid to this process's pid, only if the run is `running` and its pid is unset or already this
   pid. Anything else is refused, so the overseer cannot start a second worker on a run. Drop `CANOPY_TICK_ID` from the
   environment, so the worker cannot act as the overseer of the tick that dispatched it.
2. In the slot: `git fetch origin`; if `origin/<branch>` exists,
   `git checkout -B <branch> origin/<branch>`, else `git checkout --no-track -B <branch>
   origin/<base>`. `-B` because a branch left in the pool's repository by an earlier run on another slot would make
   `-b` fail; `--no-track` so that a bare `git push` never targets the base. Note the branch's commit.
3. Run `worker_cmd` with cwd = slot, timeout `worker_timeout_minutes`. Record the worker's pid in `runs.worker_pid`;
   the worker leads its own process group. The worker's stdout and stderr go to the run log.
4. Parse the last non-empty line of stdout as the result contract. Missing or invalid means `status='unknown'`; a
   timeout means `status='timeout'`.
5. Verify the branch is pushed (`git ls-remote origin refs/heads/<branch>` equals the local branch).
   If not and the branch has commits since step 2, push once, without force. If still not pushed, record
   `status='unpushed'`; the checkpoint invariant failed and a human looks.
6. Always: `treehouse return --force --if-lease-id <id> --if-lease-holder
   <holder> <slot>`. Trap ensures this runs on any exit path: a normal exit, an exception, and SIGTERM, SIGHUP, or
   SIGINT (the run is then `crashed`). SIGKILL cannot be trapped; reconcile handles it.
7. Update the `runs` row: ended_at, status, result_json. A git failure before or after the worker is `crashed`.
   `result_json` holds the validated result, text fields cut at 2000 characters, plus a `harness` note saying why the
   status differs from what the worker reported. A reported `pr` that is a plain `https://` URL is copied to
   `tickets.pr_url` for display.

Worker result contract, one JSON line, last line of stdout:

```json
{"status":"done|blocked|failed","branch":"agent/KEY-slug","pr":"https://...|null",
 "summary":"one paragraph","question":"only when blocked"}
```

Worker obligations, stated in every worker prompt:

- Work only inside the worktree. Push only to `agent/<KEY>-*`, never with force.
- Keep the runtime's attribution trailer on commits, or add a `Co-authored-by: canopy worker` trailer (TRUST_MODEL T5).
- Leave a comment on the ticket describing what was done and linking the PR.
- On `blocked`: post the question as a ticket comment, add
  `needs_human_label`, do not push half-finished speculative work beyond a
  WIP commit.
- Never approve, merge, close PRs, or transition the ticket to Done, including indirectly: no closing keywords
  (`Fixes #12`) or tracker commands (Jira smart commits) in commit messages, PR titles, or PR bodies.
- Push once. Do not poll CI. Do not retry.

## 9. Aggressive release

- Slots are held only for the duration of `_run`.
- Reacquisition lands on an arbitrary slot, so build caches must be
  slot-independent (for Bazel: shared `--disk_cache` or a remote cache,
  configured in the repository, not in canopy). canopy documents this; it does
  not manage it.
- treehouse `post_create` hooks (user-level config) are the place for
  per-slot environment setup. canopy does not duplicate them.

## 10. Dependencies and stacking

- Blocker relations are read by the overseer through MCP, in whatever form the tracker has them (Jira "is blocked by"
  links, GitHub issue dependencies, and so on; the provider skill says where to look). Default rule: a `ready` ticket
  with an unresolved blocker is skipped and recorded with rationale.
- Stacking: `canopy dispatch --base agent/<BLOCKER>-*` starts the worker from
  the blocker's branch. The overseer chooses this only when the blocker's PR is
  open and green. The PR base is set to the blocker's branch.
- Ordering is a decision the overseer makes each tick from live state and
  records in `decisions`. There is no plan file and no DAG config.

## 11. State model

Schema in `migrations/0001_init.sql`. Tables and purpose:

- `ticks`: one row per tick; id, timestamps, dry_run, status, summary. Status is `running`, `ok`, `overseer_failed`,
  `reconcile_failed`, or `abandoned`. A tick that cannot take the lock writes no row, although the schema comment lists
  `lock_busy`.
- `tickets`: one row per ticket key seen; last derived phase, branch, PR URL, cursors
  (`last_comment_id`, `last_review_id`, `last_ci_run_id`), done flag. Cursors make ticks incremental. Attempt counts
  and the fix-ci cooldown are not stored; they are derived from `runs` (D030, migration 0003).
- `runs`: one row per worker execution; kind, slot, lease identity, pid of `canopy _run`, pid of the worker agent
  (`worker_pid`, migration 0002), status, result_json. Status is `running`, `done`, `blocked`, `failed` (the three the
  worker reports), `unknown`, `timeout`, `unpushed`, or `crashed`. Source for capacity, crash detection, attempt
  counts, and the fix-ci cooldown.
- `decisions`: one row per overseer decision; tick id, ticket, action,
  rationale. Audit log and prompt-evaluation corpus.
- `notifications`: one row per attention item that `notify.cmd` was told about and that is still open, keyed by a
  fingerprint of its ticket and reason, so an open item is notified once (§14).

Rules: the DB never stores tokens or raw CI logs. `result_json` is a summary.

## 12. Configuration

Configuration is layered. Each layer overrides the one before it, key by key:

1. Built-in defaults in `config.py`.
2. **Repository file**, `canopy.toml` at the repository root. Committed and shared by everyone who runs canopy on the
   repository. Optional.
3. **User file**, `$XDG_CONFIG_HOME/canopy/config.toml` (default `~/.config/canopy/config.toml`). Personal to the
   operator, never committed. Required.

Every key has a scope. A **shared** key may be set in either file, and the user file wins. A **user-only** key may be
set only in the user file. A repository file that sets a user-only key is a config error: canopy names the key and
refuses to run. Unknown keys are errors in both files.

| Key | Scope | Why |
|---|---|---|
| `tracker.provider` | shared | a property of the repository's tracker |
| `tracker.query` | shared | the repository scopes it to a project; a user may narrow it |
| `tracker.needs_human_label` | shared | a signal to people; queues are already disjoint |
| `tracker.labels` | user-only | defines this operator's queue |
| `policy.*` | shared; the repository may only tighten | limits spend and retries |
| `trust.branch_prefix`, `trust.pr_label` | shared | team conventions for spotting agent work |
| `trust.authorized_repliers` | user-only | who may steer this operator's workers |
| `capacity.*` | user-only | the operator's machine and spend |
| `runtime.*` | user-only | commands run on the operator's machine |
| `notify.*` | user-only | a command run on the operator's machine |
| `paths.*` | user-only | where prompts and state are read from |

Anyone who can push to the repository, or any branch the operator happens to have checked out, controls the repository
file. That is why keys that run commands, choose prompts, spend money, or authorize anyone are user-only. See
TRUST_MODEL T7.

Repository file, committed:

```toml
[tracker]
provider = "jira"            # jira | github | linear | any name; selects tracker-<provider> skill
needs_human_label = "needs-human"
query = 'project = PROJ AND statusCategory != Done'

[policy]
max_implement_attempts = 2
max_fix_ci_attempts = 2
fix_ci_cooldown_minutes = 30
max_resume_attempts = 3

[trust]
branch_prefix = "agent/"
pr_label = "agent"
```

User file, personal:

```toml
[tracker]
labels = ["agent-ready-yourname"]

[capacity]
max_workers = 2

[runtime]
overseer_cmd = 'opencode run --agent canopy-overseer {prompt}'
worker_cmd   = 'opencode run --agent canopy-worker {prompt}'
overseer_timeout_minutes = 15
worker_timeout_minutes = 45

[trust]
authorized_repliers = ["tracker-account-id"]   # Jira accountId, GitHub login, ...

[paths]
prompt_overrides = "~/.config/canopy/prompts"
state_dir = "~/.canopy"

[notify]
cmd = ""   # optional; receives the attention diff on stdin
```

Built-in defaults are the values shown above, except `tracker.provider`, `tracker.query`, and `tracker.labels`, which
have no default and must be set, and `trust.authorized_repliers`, which defaults to empty (nobody can resume blocked
work).

Rules:

- **Queues are per operator.** `tracker.labels` is a non-empty list. A ticket is in this operator's queue if it carries
  any of them. Two operators must never share a label: the guards (one worker per ticket, attempt limits, cooldowns)
  see only the local journal, so two loops on one label both work the same tickets. canopy cannot detect this; choosing
  distinct labels is an operator responsibility (TRUST_MODEL §7).
- **The repository may only tighten policy.** A `policy.*` value from the repository file is used only if it is
  stricter than the built-in default: a lower attempt limit or a longer cooldown. Otherwise the default stands. The user
  file may set any value, including a looser one: repository policy is a shared default, not a limit a team can impose
  on an operator. The operator is fully trusted (TRUST_MODEL §3), and a harness on their machine could not enforce one
  anyway. The rule exists so a commit cannot loosen limits for operators who never set them.
- `trust.branch_prefix` must be non-empty and end in `/`, and is made of plain ref components: letters, digits, `_`,
  and `-`, each starting with a letter or digit, joined by `/`. Branch names reach git's argv.
- `canopy init` writes the user file if it is missing, with `tracker.labels = ["agent-ready-<$USER>"]`, and prints the
  label. It writes `canopy.toml` only if the repository has none. It never overwrites either file.
- Reading is `tomllib`, merging is a key-by-key dict merge, and validation is pydantic models that carry each key's
  type, default, scope, and tighten direction (D026). Scope and tighten checks run per file before the merge, so errors
  name the file that caused them.

A command template is split into words with shell quoting rules (`shlex`), then `{prompt}` is replaced inside each
word. No shell runs, so the prompt always lands in exactly one argument whatever it contains (D023). Both templates must
contain `{prompt}` exactly once. `notify.cmd` is split the same way and has no placeholder; its input is on stdin.

Overrides in `prompt_overrides` replace files of the same name in `prompts/`. The default is `prompts/` next to the user
file, `~/.config/canopy/prompts` unless `XDG_CONFIG_HOME` says otherwise, and an empty value means the default.
`paths.*` values must be absolute or start with `~`: canopy runs from the repository root, so a relative path would let
the repository supply the operator's prompts or state (TRUST_MODEL T7).

`tracker.provider` is a free-form name. The harness does not branch on it; it passes it into prompts, and `canopy init`
installs the `tracker-<provider>` skill if one ships. `tracker.query` is how the overseer finds candidates: in the
tracker's own search syntax where it has one (JQL, GitHub issue search), otherwise a plain-language description. It
finds tickets; it does not authorize them. See §17. The repository's query usually leaves the label out; an operator
can override it in the user file to include their labels and save the overseer some reads.

## 13. Agent runtime

OpenCode. The harness depends on exactly one capability: run a named agent
non-interactively in a given cwd with a prompt, and read its stdout. That is
`opencode run --agent <name>`. Everything else (MCP connectivity, OAuth, tool
permissions) is the runtime's job.

Agent definitions ship in `agents/` and are installed by `canopy init`:

- `canopy-overseer`: read-only tools plus bash restricted to `canopy *` and `treehouse status*`. MCP: the tracker,
  GitHub.
- `canopy-worker`: edit and bash allowed within the worktree. MCP: the tracker (ticket comments, labels), GitHub
  (open/update PR, read reviews and checks).

When the tracker is GitHub Issues, the tracker and GitHub are the same MCP server.

The runtime is swappable by editing the two command templates. No interface.

## 14. Attention list

Rendered to `<state_dir>/attention.md` (`~/.canopy/attention.md` by default), readable only by the operator, after
every tick: grouped by reason, one line per item with ticket key, age, and detail (usually a link). Reasons are exactly
the attention rows in the phase table plus `crashed`, `unpushed`, `unknown_result`, `worker_failed`, `attempt_limit`.
`canopy status` prints the list too. Items disappear when their cause is gone; no manual dismissal.

The harness raises the run reasons itself, every tick, after reconcile (D028). A ticket not marked done whose latest run
ended `crashed` is `crashed`; `unpushed` is `unpushed`; `unknown` or `timeout` is `unknown_result`; `failed` is
`worker_failed`. The detail names the run, its kind and branch, the harness note or the worker's summary, and the run
log. The cause is gone when a newer run starts for the ticket or the ticket is marked done. The overseer does not
dispatch such a ticket again until an authorized replier has commented after the run ended; that is how a human says
"try again".

The overseer records an item with `canopy attention <KEY> <reason> --detail "<link or text>"`, every tick the cause
holds. It is stored as a decision with action `attention:<reason>`; there is no separate table (D020). The current list
is the attention decisions of the latest `ok` tick, so an item disappears the first tick that does not record it, and a
failed tick leaves the previous list standing. An item's age runs from the first tick of its unbroken run. Reasons must
match `[a-z][a-z0-9_]*`.

`attempt_limit` is raised both ways: the overseer records it when the state block shows a ticket at its limit for the
work it needs, and `canopy dispatch` records it with an `attempt_limit` refusal. Either way it lasts as long as the
overseer keeps asking for that work.

Notification (D032). An item is identified by its ticket and reason; its detail can be reworded without making it new.
When `notify.cmd` is set, each tick compares the list with the `notifications` table: items not in the table are new,
and rows whose item is no longer listed are resolved. If either exists, the command gets one message on stdin, a
summary line, a `+ KEY reason: detail` line per new item, a `- KEY reason` line per resolved one, and the path of
`attention.md`. Only when it exits 0 within 60 seconds are new items added to the table and resolved ones removed, so a
failed notification is retried next tick, an open item is never notified twice, and an item that comes back after
going away is new again.

## 15. Failure handling

- Worker crash: detected by pid liveness in reconcile; what is left of the worker is killed; slot returned; ticket
  goes to attention with `crashed`. Not auto-redispatched: the harness never restarts a run, and the overseer prompt
  waits for an authorized reply (§14). Every kind has an attempt limit in code, so an overseer that redispatches
  anyway stops at `policy.max_<kind>_attempts` (D030).
- Worker exits without a result, times out, reports `failed`, or leaves commits unpushed: `_run` returns the slot and
  records the status; the ticket goes to attention (§14).
- Stale lease without a run: returned in reconcile.
- treehouse unavailable or failing in reconcile: tick closes with `reconcile_failed`; the overseer does not run.
- Overseer timeout or bad output: tick closes with `overseer_failed`; nothing
  is dispatched; next tick retries. Three consecutive failures produce an
  attention item.
- MCP unavailable: the overseer reports it; the tick records it; no decisions
  are made on partial data. The overseer prompt says so explicitly.
- Overseer asks for something the guards refuse: the refusal is recorded as a
  decision with the guard's reason.

## 16. Open questions

- Whether `ask` permissions in OpenCode agent definitions block or auto-deny
  under `opencode run`. Answered from OpenCode's source in M1: `ask` is auto-rejected and `deny` is enforced (D021).
  The live canary (`tests/canopy/test_opencode_canary.py`) is opt-in; its first real run confirms or overturns this.
- Whether a Slack notification path should use `notify.cmd` with a small script
  or the overseer posting via MCP. Default to `notify.cmd`.
- Whether `merged` should trigger a tracker transition. Default no; humans own
  ticket state.
- One operator on several repositories. The user file is shared across them, and `state_dir` and the lock are global.
  Whether the user file needs per-repository tables, and whether state should be per repository, stays open until
  someone does it.

## 17. Trackers

canopy works with any issue tracker the agent runtime can reach through an MCP server. There is no adapter interface and
no tracker code in the harness. What differs between trackers is handled in three places, in order of preference:

1. **The contract below.** Agents can map it onto the tools a tracker's MCP server exposes without being told how. This
   is the default for any tracker.
2. **Config.** `tracker.provider`, `tracker.query`, the queue labels, `needs_human_label`, and
   `trust.authorized_repliers` in the tracker's own identity format.
3. **A provider skill**, `.agents/skills/tracker-<provider>/SKILL.md`, for what an agent would otherwise get wrong:
   identity fields, how "closed" is expressed, where blockers live, and text that silently triggers a tracker action
   (closing keywords, smart commits). Skills ship for `jira` and `github`. A skill is optional; add one when the
   `decisions` table shows the loop misreading a tracker, not in advance.

### Contract

What the loop needs from a tracker, stated as capabilities. Each is used by the role in parentheses.

| Capability | Used for |
|---|---|
| Find open tickets matching `tracker.query` (overseer) | candidate set |
| Read a ticket: title, body, labels, open or closed (both) | phase, task |
| List comments with a stable id, author account id, and timestamp (overseer) | cursors, authorized replies |
| Post a comment (worker) | reports and questions |
| Add and remove a label (worker) | `needs_human_label` |
| Read blocker relations (overseer, optional) | ordering, stacking |
| When a label was added (overseer, optional) | `human_replied` |

"Label" means the tracker's tagging primitive, whatever it is called. Without blocker relations, tickets are treated as
unblocked. Without label history, the worker's question comment is the reference point for `human_replied`. If a tracker
cannot do one of the required rows, the overseer records `skip` with rationale `tracker_unsupported: <capability>` and
the operator fixes the MCP setup or writes a skill.

### Authorization is the same everywhere

The query only finds tickets. A ticket is a candidate only if reading it shows one of `tracker.labels` present and the
ticket not closed. A sloppy or plain-language query can therefore waste a tick, but it cannot authorize work. Replies
are authorized only by `trust.authorized_repliers`, compared against the author's stable account id (Jira `accountId`,
GitHub login), never a display name.

### Ticket keys

A key is the tracker's short, human-readable id, as the provider skill defines it: `PROJ-123` for Jira, `GH-123` for
GitHub Issues. Keys appear in branch names, lease holders, file paths, and shell arguments, so `canopy dispatch`,
`decide`, `attention`, and `ticket set` reject any key that does not match `[A-Za-z0-9][A-Za-z0-9_-]*`. That guard is in
code.
