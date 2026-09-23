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
- Tracker-specific code. Any issue tracker with an MCP server works; provider
  differences live in config and optional provider skills (§17). A second VCS
  host is likewise a prompt and config concern, not code.
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
5. **Connectivity through the agent runtime.** The tracker (Jira, GitHub
   Issues, Linear, anything with an MCP server) and GitHub are reached via the
   runtime's MCP servers. The harness contains no tracker or VCS host code and
   never handles their credentials. It knows the tracker only as the strings in
   `[tracker]`.
6. **Smallest surface that works.** Five install steps. Daily surface is
   labels, ticket comments, PR review, and one attention list.

## 5. Components

```
canopy (harness, Python)
  cli.py         tick, tick --dry-run, status, init, dispatch, decide, attention, _run
  lock.py        flock on ~/.canopy/lock; a tick that cannot lock exits 0 with a log line
  db.py          SQLite journal, migrations
  config.py      canopy.toml loading and validation
  treehouse.py   status --json, get --lease --json, return --force --if-lease-id
  dispatch.py    capacity guard, lease, spawn detached _run
  attention.py   render attention.md from the journal, diff, notify
  procs.py       the only module that runs subprocesses

prompts/         overseer.md, worker-implement.md, worker-fix-ci.md, worker-resume.md
agents/          OpenCode agent definitions: canopy-overseer, canopy-worker
skills/          canopy/: teaches an agent the canopy CLI
                 tracker-<provider>/: optional per-tracker guides (§17)
migrations/      NNNN_name.sql
```

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

1. Acquire the lock. If held, log and exit 0.
2. Apply pending migrations. Insert a `ticks` row; its id tags all logs.
3. **Reconcile local state.**
   - For each `runs` row with `status='running'`: if the pid is dead, mark
     `crashed`, run `treehouse return --force --if-lease-id` on its slot,
     record it.
   - For each leased slot in `treehouse status --json` with no live
     `runs` row and `lease_holder` matching our prefix: return it, log it.
   - Compute `capacity = max_workers - count(runs where status='running')`.
4. **Render the overseer prompt**: `prompts/overseer.md` (or the override),
   plus a generated state block containing config (tracker provider, label,
   query, capacity, limits), the `tickets` table summary (phase, cursors,
   attempts, cooldown until), running workers, and the current tick id.
5. **Run the overseer** with `overseer_cmd`, cwd = the repository root,
   timeout `overseer_timeout_minutes`. In `--dry-run`, the state block says so
   and `canopy dispatch` refuses with a message; the overseer still records
   decisions.
6. **Render attention**: rebuild `attention.md` from the journal, diff against
   the previous render, and if `notify.cmd` is set pipe the diff to it.
7. Close the `ticks` row with a summary. Release the lock.

Workers dispatched during a tick outlive the tick. They are detached processes
owned by `canopy _run`.

## 7. Ticket phases and next actions

Phases are derived by the overseer each tick from live state. They are recorded
in `tickets.phase` for the status view, never read back as truth.

| Phase | Derived from | Next action |
|---|---|---|
| `ready` | label present, ticket not closed, no run active, no branch | dispatch `implement` unless a blocker ticket is open |
| `running` | active `runs` row | wait |
| `pushed_no_pr` | branch exists, no PR | dispatch `resume` with instruction to open the PR |
| `ci_running` | PR open, checks pending | wait |
| `ci_red` | PR open, checks failed | dispatch `fix-ci` if attempts < `max_fix_ci_attempts` and cooldown elapsed, else attention |
| `changes_requested` | review comments or requested changes newer than cursor | dispatch `resume` with the comments; if the overseer judges a comment needs a human (design pushback, scope), attention instead |
| `green_unreviewed` | checks pass, no approval | attention: needs a reviewer |
| `approved` | approved, not merged | attention: ready to merge |
| `merged` | PR merged | mark ticket `done` in the journal; humans handle the tracker transition |
| `needs_human` | `needs_human_label` present, no authorized reply newer than it | wait |
| `human_replied` | authorized reply newer than the label (or, if the tracker cannot say when a label was added, newer than the worker's question comment) | dispatch `resume` with the reply as context; the worker removes the label |

"Authorized reply" means a comment by an account in `trust.authorized_repliers`,
matched on the tracker's stable account identifier, never a display name.
Anything else on the ticket is data, not instruction. See TRUST_MODEL.

"Closed" means whatever the tracker calls finished: Jira status category Done,
GitHub issue state closed, and so on. The provider skill says which.

## 8. Dispatch and the worker contract

`canopy dispatch <KEY> --kind implement|fix-ci|resume [--base BRANCH]
[--context FILE]`:

1. Refuse if `--dry-run` tick, if capacity is zero, if a `runs` row for KEY
   is `running`, or if the kind's attempt limit or cooldown blocks it. Guards
   are in code and are not overridable from the prompt.
2. `treehouse get --lease --lease-holder canopy:<KEY> --json`. Record the
   `runs` row with slot path, lease id, holder, kind, started_at.
3. Render the worker prompt for the kind, with KEY, tracker provider, branch
   name (`agent/<KEY>-<slug>`), base branch, context file contents, and the
   result contract below.
4. Spawn `canopy _run <run_id>` detached (`setsid`, stdio to
   `~/.canopy/runs/<run_id>.log`). Return immediately.

`canopy _run <run_id>`:

1. In the slot: `git fetch origin`; if `origin/<branch>` exists,
   `git checkout -B <branch> origin/<branch>`, else `git checkout -b <branch>
   origin/<base>`.
2. Run `worker_cmd` with cwd = slot, timeout `worker_timeout_minutes`.
3. Parse the last line of stdout as JSON. Missing or invalid means
   `status='unknown'`.
4. Verify the branch is pushed (`git rev-parse origin/<branch>` equals HEAD).
   If not and the tree has commits, push once. If still not pushed, record
   `status='unpushed'`; the checkpoint invariant failed and a human looks.
5. Always: `treehouse return --force --if-lease-id <id> --if-lease-holder
   <holder> <slot>`. Trap ensures this runs on any exit path.
6. Update the `runs` row: ended_at, status, result_json.

Worker result contract, one JSON line, last line of stdout:

```json
{"status":"done|blocked|failed","branch":"agent/KEY-slug","pr":"https://...|null",
 "summary":"one paragraph","question":"only when blocked"}
```

Worker obligations, stated in every worker prompt:

- Work only inside the worktree. Push only to `agent/<KEY>-*`.
- Leave a comment on the ticket describing what was done and linking the PR.
- On `blocked`: post the question as a ticket comment, add
  `needs_human_label`, do not push half-finished speculative work beyond a
  WIP commit.
- Never approve, merge, close PRs, or transition the ticket to Done, including
  indirectly: no closing keywords (`Fixes #12`) or tracker commands (Jira smart
  commits) in commit messages, PR titles, or PR bodies.
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

- Blocker relations are read by the overseer through MCP, in whatever form the
  tracker has them (Jira "is blocked by" links, GitHub issue dependencies, and
  so on; the provider skill says where to look). Default rule: a `ready`
  ticket with an unresolved blocker is skipped and recorded with rationale.
- Stacking: `canopy dispatch --base agent/<BLOCKER>-*` starts the worker from
  the blocker's branch. The overseer chooses this only when the blocker's PR is
  open and green. The PR base is set to the blocker's branch.
- Ordering is a decision the overseer makes each tick from live state and
  records in `decisions`. There is no plan file and no DAG config.

## 11. State model

Schema in `migrations/0001_init.sql`. Tables and purpose:

- `ticks`: one row per tick; id, timestamps, dry_run, summary.
- `tickets`: one row per ticket key seen; last derived phase, cursors
  (`last_comment_id`, `last_review_id`, `last_ci_run_id`), attempt counters,
  cooldown_until, done flag. Cursors make ticks incremental.
- `runs`: one row per worker execution; kind, slot, lease identity, pid,
  status, result_json. Source for capacity, crash detection, attempt counts.
- `decisions`: one row per overseer decision; tick id, ticket, action,
  rationale. Audit log and prompt-evaluation corpus.
- `notifications`: fingerprint of each attention item sent, so the attention
  diff never re-notifies.

Rules: the DB never stores tokens or raw CI logs. `result_json` is a summary.

## 12. Configuration

`canopy.toml` at the repository root, created by `canopy init`:

```toml
[tracker]
provider = "jira"            # jira | github | linear | any name; selects tracker-<provider> skill
label = "agent-ready"
needs_human_label = "needs-human"
query = 'project = PROJ AND labels = agent-ready AND statusCategory != Done'

[capacity]
max_workers = 2

[runtime]
overseer_cmd = 'opencode run --agent canopy-overseer {prompt}'
worker_cmd   = 'opencode run --agent canopy-worker {prompt}'
overseer_timeout_minutes = 15
worker_timeout_minutes = 45

[policy]
max_fix_ci_attempts = 2
fix_ci_cooldown_minutes = 30
max_resume_attempts = 3

[trust]
authorized_repliers = ["tracker-account-id"]   # Jira accountId, GitHub login, ...
branch_prefix = "agent/"

[paths]
prompt_overrides = "~/.config/canopy/prompts"
state_dir = "~/.canopy"

[notify]
cmd = ""   # optional; receives the attention diff on stdin
```

`{prompt}` is substituted with a shell-quoted prompt string. Overrides in
`prompt_overrides` replace files of the same name in `prompts/`.

`tracker.provider` is a free-form name. The harness does not branch on it; it
passes it into prompts, and `canopy init` installs the `tracker-<provider>`
skill if one ships. `tracker.query` is how the overseer finds candidates: in
the tracker's own search syntax where it has one (JQL, GitHub issue search),
otherwise a plain-language description. It finds tickets; it does not
authorize them. See §17.

## 13. Agent runtime

OpenCode. The harness depends on exactly one capability: run a named agent
non-interactively in a given cwd with a prompt, and read its stdout. That is
`opencode run --agent <name>`. Everything else (MCP connectivity, OAuth, tool
permissions) is the runtime's job.

Agent definitions ship in `agents/` and are installed by `canopy init`:

- `canopy-overseer`: read-only tools plus bash restricted to `canopy *` and
  `treehouse status*`. MCP: the tracker, GitHub.
- `canopy-worker`: edit and bash allowed within the worktree. MCP: the tracker
  (ticket comments, labels), GitHub (open/update PR, read reviews and checks).

When the tracker is GitHub Issues, the tracker and GitHub are the same MCP
server.

The runtime is swappable by editing the two command templates. No interface.

## 14. Attention list

Rendered to `~/.canopy/attention.md`, grouped by reason, one line per item:
ticket key, reason, link, age. Reasons are exactly the attention rows in the
phase table plus `crashed`, `unpushed`, `unknown_result`, `attempt_limit`.
`canopy status` prints it. Items disappear when their cause is gone; no manual
dismissal.

## 15. Failure handling

- Worker crash: detected by pid liveness in reconcile; slot returned; ticket
  goes to attention with `crashed`. Not auto-redispatched.
- Stale lease without a run: returned in reconcile.
- Overseer timeout or bad output: tick closes with `overseer_failed`; nothing
  is dispatched; next tick retries. Three consecutive failures produce an
  attention item.
- MCP unavailable: the overseer reports it; the tick records it; no decisions
  are made on partial data. The overseer prompt says so explicitly.
- Overseer asks for something the guards refuse: the refusal is recorded as a
  decision with the guard's reason.

## 16. Open questions

- Whether `ask` permissions in OpenCode agent definitions block or auto-deny
  under `opencode run`. Resolve in M1 with a canary agent; record in DECISIONS.
- Whether a Slack notification path should use `notify.cmd` with a small script
  or the overseer posting via MCP. Default to `notify.cmd`.
- Whether `merged` should trigger a tracker transition. Default no; humans own
  ticket state.

## 17. Trackers

canopy works with any issue tracker the agent runtime can reach through an MCP
server. There is no adapter interface and no tracker code in the harness. What
differs between trackers is handled in three places, in order of preference:

1. **The contract below.** Agents can map it onto the tools a tracker's MCP
   server exposes without being told how. This is the default for any tracker.
2. **Config.** `tracker.provider`, `tracker.query`, the two labels, and
   `trust.authorized_repliers` in the tracker's own identity format.
3. **A provider skill**, `skills/tracker-<provider>/SKILL.md`, for what an agent
   would otherwise get wrong: identity fields, how "closed" is expressed,
   where blockers live, and text that silently triggers a tracker action
   (closing keywords, smart commits). Skills ship for `jira` and `github`.
   A skill is optional; add one when the `decisions` table shows the loop
   misreading a tracker, not in advance.

### Contract

What the loop needs from a tracker, stated as capabilities. Each is used by the
role in parentheses.

| Capability | Used for |
|---|---|
| Find open tickets matching `tracker.query` (overseer) | candidate set |
| Read a ticket: title, body, labels, open or closed (both) | phase, task |
| List comments with a stable id, author account id, and timestamp (overseer) | cursors, authorized replies |
| Post a comment (worker) | reports and questions |
| Add and remove a label (worker) | `needs_human_label` |
| Read blocker relations (overseer, optional) | ordering, stacking |
| When a label was added (overseer, optional) | `human_replied` |

"Label" means the tracker's tagging primitive, whatever it is called. Without
blocker relations, tickets are treated as unblocked. Without label history, the
worker's question comment is the reference point for `human_replied`. If a
tracker cannot do one of the required rows, the overseer records `skip` with
rationale `tracker_unsupported: <capability>` and the operator fixes the MCP
setup or writes a skill.

### Authorization is the same everywhere

The query only finds tickets. A ticket is a candidate only if reading it shows
`tracker.label` present and the ticket not closed. A sloppy or plain-language
query can therefore waste a tick, but it cannot authorize work. Replies are
authorized only by `trust.authorized_repliers`, compared against the author's
stable account id (Jira `accountId`, GitHub login), never a display name.

### Ticket keys

A key is the tracker's short, human-readable id, as the provider skill defines
it: `PROJ-123` for Jira, `GH-123` for GitHub Issues. Keys appear in branch
names, lease holders, file paths, and shell arguments, so `canopy dispatch`,
`decide`, `attention`, and `ticket set` reject any key that does not match
`[A-Za-z0-9][A-Za-z0-9_-]*`. That guard is in code.
