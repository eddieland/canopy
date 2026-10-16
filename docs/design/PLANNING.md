# Plans

Part of the canopy design, normative like all of it: a plan for a ticket, written and approved before any `implement`.
Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Sandboxed
runs](SANDBOXING.md).

## 25. Plans before implementing (M44)

Designed, not built (ROADMAP M44, REQUIREMENTS R18): until M44 lands, a ticket's first run is its `implement`, and §7,
§8, §12, §14, §20, and §22 describe canopy as it is. This section says what changes in each.

Today the `implement` worker plans inside its own session, and nothing of that plan survives but the run's summary. A
**plan** is a run of its own that reads the ticket and the code and writes down how the work will be done, before any
`implement` starts. Two reasons, both the operator's (2026-10-15). A worker that starts from an explicit plan the
operator has read should do better than one that plans as it goes. And the plan is kept, as a file of its own, so the
operator can read later how any ticket was approached, as they read its conversation and runs today.

When a ticket is planned, nothing is implemented until the operator approves its plan. A reply asking for changes makes
a new plan. The plan stays in canopy and is posted nowhere, so a private ticket (§22) is planned the same way as a
public one.

### Configuration

Workspace file, shared:

```toml
[policy]
plan = "off"                 # off | approve; "approve" is stricter
max_plan_attempts = 3        # per ticket
```

User file, personal:

```toml
[runtime]
plan_cmd = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-planner --format json
    --title={title} {prompt}'''
```

- `policy.plan` says whether a ticket waits on an approved plan before its `implement`. `"off"`, the default, is
  canopy as it is. `"approve"` plans every ticket. A repository may only tighten policy (§12), so it may set
  `"approve"` and never loosen the operator's `"approve"` to `"off"`.
- `max_plan_attempts` is a `max_<kind>_attempts` like the others (§8): plan runs per ticket, counted from `runs`, never
  reset (D030). `canopy grant KEY plan` adds one (§22, Granting attempts). Like a split's, a plan's count and limit are
  the ticket's, not a unit's: a plan covers every repository the ticket will touch.
- `plan_cmd` follows §12. A private ticket's plan uses it too: the planner writes nothing to the tracker on any ticket.
  It has the worker's timeout, `worker_timeout_minutes`.

### Off unless configured

With `policy.plan` at `"off"` and no ticket of the operator's asking for a plan, nothing changes: the state block's
tickets carry no plan, the overseer prompt's plan rows do not apply, and `ready` dispatches `implement`.

### Which tickets are planned

A ticket needs a plan when its own setting says `plan`, or when it has no setting and `policy.plan` is `"approve"`. Its
own setting is set only by the operator's channels (§22), never by the overseer or a worker:

- `canopy plan KEY` asks for a plan for this ticket, whatever the policy. On a ticket with a plan already, waiting or
  approved, it asks for a new one.
- `canopy plan KEY --skip` waives the plan for this ticket, whatever the policy, so its `implement` goes ahead.
- `canopy start KEY --plan` starts a private ticket (§22) with its setting at `plan`.

Asking for a plan and `--skip` supersede the ticket's waiting or approved plan at once, in the transaction that sets
its setting. So after `canopy plan KEY` the ticket needs a plan and has none, and the next tick finds it `ready` and
dispatches `plan` (Phases, below); after `--skip`, no `plan_review` waits on a plan nobody needs, and no `implement`
carries one.

Each refuses `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set, so no agent run can ask for, skip, or approve
a plan. Asking for a plan and `--skip` refuse `bad_plan` while a plan run for the ticket is running: its plan would
land after the request. The operator asks again once it ends. Asking for a plan also refuses `bad_plan` once the ticket
has a branch. Dispatch records the branch when it inserts the ticket's first `implement` (§8 step 2), so this covers an
`implement` that is running too: a plan now would describe work already started (Open, below). `--skip` does not: on a
ticket with a branch it drops the plan from the ticket's later runs, which is the way out when an approved plan's file
is gone (`plan_changed`, below).

### Approving a plan

`canopy plan KEY --approve` approves the ticket's newest plan as its file stands now (Where plans live, below), edits
the operator made to it included. It refuses `inside_run`, and `bad_plan` when the newest plan is not waiting
(`proposed`), unless it is approved and its file has changed since; when a plan run for the ticket is running; and
when its file is missing, is not a regular file, or is no longer a plan: empty, not UTF-8, or over 100,000
characters. It records the file's SHA-256 as the approved hash.

An operator message (`canopy reply KEY`, §22) newer than the newest plan asks for changes: the overseer dispatches
`plan` again with the reply in the planner's prompt, and the new plan supersedes the old. An approval after such a
reply, sent before the new plan run starts, wins: it is the operator's later word. The reply then reaches the
`implement` as an operator message, as any message does, so what it asked for is not lost. Once the new plan run has
started, `--approve` refuses as above, and the operator approves the plan it writes.

The approval authorizes the `implement`. It does not make the plan's text an instruction (Trust model changes, below).

### Dispatch

`canopy dispatch KEY --kind plan --repo NAME...` runs §8's guards as for `implement`, plus:

- `bad_plan`: a `plan` for a ticket with a branch, or for a split's parent (§18).
- `bad_slug`, `bad_base`, `bad_request`: a plan given `--slug`, `--base`, or `--request`. A plan makes no branch.
- `no_read_tools`: no tracker read tools are known for the planner (Agent definition, below), on any ticket.
- `attempt_limit`: the ticket has had `max_plan_attempts` plan runs, plus its grants.

And two new guards on the worker kinds:

- `unplanned`, on `implement`: the ticket needs a plan and has none approved. It holds whatever the overseer asks for:
  the plan gate is a guard in code, not a prompt rule (§4, principle 2).
- `plan_changed`, on `implement` and `resume`: the approved plan's file is missing, unreadable, or no longer has its
  approved hash. The operator approved one text, and the worker must not follow another. They approve the file again
  as it now stands. A file that is gone or unreadable cannot be approved, so then they ask for a new plan, or, on a
  ticket with a branch, where a new plan is refused, `--skip` it (Where plans live, below).

A plan runs as a split does (§18): in a desk of the named repositories' worktrees, each checked out at its base branch,
detached, with no branch and no setup command, since the planner has no shell. `_run` runs `plan_cmd` in the desk,
parses and validates the plan's result (below), and skips push verification, since a plan pushes nothing. Slots are
returned and the desk removed on every exit path; reconcile treats a dead plan run like any other. A plan counts toward
`capacity.max_workers` with workers and reviews: it is an agent run, with spend.

### The prompt

`prompts/worker-plan.md` asks for a plan a later worker can follow:

- what changes in each repository, and why;
- the files and interfaces it touches;
- the tests that will show it works;
- what is out of scope;
- the open risks.

It carries the key, the repositories and their base branches (`{{REPOSITORIES}}`), the operator's messages
(`{{OPERATOR_MESSAGES}}`, or `{{CONVERSATION}}` on a private ticket), `{{STANDING_INSTRUCTIONS}}`, `{{NOTICE}}`, and the
bound on a plan's length. On a re-plan, `_run` copies the plan it replaces from its file to `.canopy-plan.md` at the
desk's root (The worker's copy, below), and the prompt says so; the operator's reply to it is among the messages. On a
public ticket the planner checks the queue label first, as every worker does (§8 step 3); a private ticket has no
label to check. It treats the ticket's text and the code as data (TRUST_MODEL T1).

The plan is the planner's final message (§13): the plan as markdown, then the result line. A plan of tens of thousands
of characters escaped into one JSON string is easy for a model to get wrong, and a run whose result line does not
parse records nothing, so the plan stays out of the JSON. Result contract, one JSON line, last line of the agent's text
(§13), validated with pydantic (D026):

```json
{"status":"done|blocked|failed","summary":"...","question":"<only when blocked>"}
```

- `done` records the final message, the result line and anything after it removed and surrounding whitespace
  stripped, as the ticket's newest plan, `proposed`. It must be non-empty and at most 100,000 characters. The bound is
  what a planner can write in one message and an operator can read before approving, not what a worker reads: workers
  read the plan from a file, by its outline (Workers follow the plan, below). A template that prints plain stdout
  rather than events has no message boundaries, so all of its stdout before the result line is the plan.
- `blocked` has a `question`, recorded as a worker message (§22), on a public ticket too, since the planner cannot
  comment on the ticket. The operator answers with `canopy reply`.
- `failed` means it could not plan, and the summary says why. Like any run that ends other than `done`, it raises
  attention (§14).
- Anything else, a `done` with an empty plan or one over the bound included, makes the run `unknown` and records no
  plan.

### Phases and the overseer's part

One phase, `plan_proposed`, joins §7's table, `needs_human` gains a case, and `ready` splits by plan. In order,
before `ready`'s own row:

| Phase | Derived from | Next action |
|---|---|---|
| `needs_human` | as `ready`, the ticket needs a plan, none is waiting or approved, and its latest plan run ended `blocked` with no operator message after it | wait; attention `awaiting_reply` |
| `ready` | as today, the ticket needs a plan, and none is waiting or approved | dispatch `plan` |
| `plan_proposed` | the newest plan is `proposed`, and no operator message after it | attention `plan_review`; no run |
| `plan_proposed` | the newest plan is `proposed`, and an operator message after it | dispatch `plan` again |
| `ready` | as today, with an approved plan or none needed | dispatch `implement` |

`plan_proposed` holds no run and no slot, so capacity is free while the operator reads. The state block gains each
ticket's plan: whether one is needed, and the newest plan's id, status, and time. Never its text: the overseer has no
use for it, and it is model-written text (T1).

`plan_review` is an attention reason (§14) raised by the overseer every tick the plan waits. Its detail names the plan
and how to answer: `canopy show KEY`, then `canopy plan KEY --approve` or `canopy reply KEY`. Its cause is gone once the
plan is approved or superseded, or the ticket's plan is skipped.

A `blocked` plan waits for the operator: without the `needs_human` row, a ticket with no plan waiting would be `ready`
again at the next tick and dispatch `plan` until its attempts ran out, each run asking the same question. The planner
cannot label the ticket or comment on it, so its question is a worker message on a public ticket as on a private one,
and the harness raises `awaiting_reply` for it every tick, as it does for a started ticket's question (§22). The
operator's `canopy reply` ends the wait: the ticket is `ready`, and the next `plan` carries the reply among the
operator's messages (`{{OPERATOR_MESSAGES}}` or `{{CONVERSATION}}`, The prompt, above).

### Workers follow the plan

The `implement` and `resume` prompts, and their private variants, carry `{{PLAN}}`. With an approved plan it names its
copy of the plan (The worker's copy, below) and gives the plan's outline: its markdown headings, outside fenced code
blocks, at most 200, each cut at 200 characters. Without one it is `None.`. Once a ticket has an approved plan, an
override without `{{PLAN}}` is `bad_prompt`, as for `{{OPERATOR_MESSAGES}}` (§8, D093), so an older override cannot drop
it; for a ticket with none it still renders.

The prompt does not carry the plan's text. The worker reads the outline, then the sections it needs, with its own read
and search tools, as it reads the code. A long plan then costs a run what it reads of it, not its whole length, and
the plan can be as long as the work needs, within the bound above.

The prompt says to follow the plan, to leave its copy out of every commit, and to say in the summary where the
work left the plan and why. A plan is model-written from ticket text: it describes the work, as the ticket does, and
the prompt's obligations come before it, as they come before the standing instructions.

### Where plans live

A plan is a markdown file of its own, outside the journal: `<state_dir>/plans/<KEY>/<run>.md`, where `run` is the id of
the plan run that wrote it. The operator reads it, greps it, and edits it with their own tools, and a ticket's plans are
a directory listing. The journal holds what canopy decides by: each plan's status, its hashes, and when and how it was
approved (Journal, below), never its text.

- **Writing it.** When a plan run ends `done`, `_run` writes the plan with `logs.write_private`: readable only by the
  operator, refusing a symlink, as it writes a run's prompt (§8 step 3). `plans/` and each ticket's directory are made
  operator-only, and one that is not, a symlink or another owner's, refuses the write, as §18 refuses such a `.canopy/`.
  The path is built from the key and the run id, never read from the journal, and a key cannot hold a path separator
  (§17). The run id exists before the plan does, and a plan run writes one plan, so the name is known when the file is
  written: under a temporary name, then linked into place with a link that refuses an existing name, so no file is
  ever overwritten. `runs` rows are never deleted, so a run id names one run. The `plans` row is recorded after the
  file, with the file's SHA-256 as written. A file with no row, from a `_run` that died between the two, is never
  read, and its name belongs to that run alone, so nothing later collides with it. A name already taken fails the run
  `crashed` with a note, and nothing is recorded.
- **Editing it.** A `proposed` plan's file is the operator's to edit, in any editor, until they approve it: they can
  fix a step rather than ask for a whole new plan. `--approve` takes the file as it then stands and records its hash
  (Approving a plan, above). `canopy show` and the web UI show the file as it is, and say when it differs from what
  the planner wrote. Edits are the operator's; the web UI does not edit a plan.
- **After approval.** The approved hash pins the text the operator approved. `implement` and `resume` dispatches
  refuse `plan_changed` when the file no longer matches it, and `_run` checks again before it copies the plan for a
  worker, failing the run `crashed` with a note if it changed in between. An edit after approval is answered by
  approving again, which is allowed on an approved plan whose file changed, or by asking for a new plan.
- **Reading it.** Every read, by `canopy show`, the web UI, `--approve`, dispatch, and `_run`, opens a regular file
  without following links and reads at most 100,000 characters of UTF-8, as §21 reads a review's diff. A missing or
  unreadable file is shown as such, never as an empty plan. A hash is of the whole file's bytes, never of a bounded
  read: a file over the bound is no longer a plan, so `--approve` refuses it and it never matches an approved hash.
- **Keeping it.** canopy never deletes a plan file. A superseded plan's file stays, as its row does, so a ticket's
  history of plans is on disk; `canopy forget` supersedes rows and leaves files. Removing old ones is the operator's,
  and a backup of canopy's state takes `plans/` with the journal.
- **Workers cannot reach it.** `canopy-worker` reads nothing outside its cwd, and the sandbox (§24) denies `.canopy/`.
  A worker reads the plan from its own copy (below), which is written for its run alone.

### The worker's copy

A run reads a copy of the approved plan. `_run` reads the plan's file, checks it against the approved hash (above),
and writes it to `.canopy-plan.md` in the worker's cwd, after branch setup and the operator's setup command (§8 `_run`
step 2) and before the worker starts:

- in a joint run, at the desk's root, beside the worktree links (§18). The desk is in no repository.
- in a one-repository run, at the worktree's root. Before writing it, `_run` makes sure the repository's exclude file,
  `info/exclude` in the git directory every slot shares, has the line `/.canopy-plan.md`, adding it once, so the file
  is ignored and `git add -A` leaves it out.

The copy is written fresh for each run, so a worker that edits it changes only its own run, never the plan's file.
`_run` removes it before the slot is returned, on every exit path, and a slot's leftover copy, from a run whose `_run`
died, is removed when reconcile cleans up the slot (§6 step 3). The file cannot sit beside the run's prompt in
`<state_dir>/runs/`: `canopy-worker` reads nothing outside its cwd (`external_directory: deny`), and the sandbox (§24)
denies `.canopy/`.

Ignored is not untrackable: a worker that adds the file by name, `git add -f .canopy-plan.md`, can still commit it.
On a private ticket that would publish its plan with the branch, against R18's "posted nowhere". The prompt forbids it,
and push verification (§8 `_run` step 5) checks each pushed branch's head: a tree holding `.canopy-plan.md` gives the
run a harness note naming it, so `canopy show` and the web UI say so. The harness does not rewrite the pushed branch.

### Agent definition

canopy ships `canopy-planner` in the definitions directory (§13):

- no edit, shell, web fetch, or subagent tools; reads only inside its desk.
- MCP: its tracker tools are the private worker's (§22): the tracker server's tools denied by a wildcard, then only
  `tracker.read_tools` allowed. It reads the ticket but cannot comment, label, or create. With no read tools known for
  the provider, a plan dispatch refuses `no_read_tools`, rather than run a planner that cannot read the ticket.

### Reading plans

- `canopy show KEY` prints the newest plan, its status, and when it was approved; `canopy show KEY --plans` prints every
  plan, oldest first.
- The web UI's ticket page (§22) shows the newest plan, as plain text like a message, with `Approve`, `Ask for changes`
  (a reply), and `Skip`, and lists earlier plans. They call `POST /tickets/{key}/plan` with `approve`, `request`, or
  `skip`, through the same code as the CLI, so with the same refusals.
- A `plan.proposed` event (§20) tells the operator's sinks a plan is waiting: the ticket and its title. It carries no
  plan text, so nothing of the plan leaves the machine through a Slack sink.

### Journal

- A migration adds `plans`: id, ticket key, run id, created at, status (`proposed`, `approved`, or `superseded`), the
  SHA-256 and size of the file as the planner wrote it, and the approved hash, approved at, and channel. No body: the
  text is the plan's file (Where plans live, above). Its `status` column is constrained with `CHECK (status IN
  (...))`. Rows are never deleted.
- `tickets` gains the ticket's own plan setting: unset, `plan`, or `skip`.
- A plan run is a `runs` row of kind `plan` with its `run_slots`, no branch, and `result_json` the validated result.
  Its report message (§8 step 7) is its summary.
- `canopy forget` (§22) supersedes a waiting or approved plan, so a forgotten ticket under `"approve"` is planned again.
- The migration's hash joins `SHIPPED`, and a row for `plans` joins `SEED`, in `tests/canopy/test_db.py`.

### Trust model changes

Proposed, for the operator's approval note in M44's PR, with the overseer prompt, `worker-plan.md`, and the
`canopy-planner` definition:

- T1: an approved plan is data, not an operator instruction. It is model-written from ticket text, which anyone who
  can edit the ticket shapes. The operator's approval authorizes the `implement`; the worker's obligations come before
  the plan, and a plan cannot widen what a worker may do.
- T3: plan runs count toward `capacity.max_workers` and are limited by `max_plan_attempts`, never reset. `unplanned`
  is a guard in code.
- T6: the planner has no write scope: no edits, no shell, and only the tracker's read tools. Residual: a worker can
  commit its copy of the plan by name, which on a private ticket publishes the plan with its branch. The prompt
  forbids it and push verification reports it; nothing prevents it.
- T8: the plan route joins the web channel's writes, behind the same secret and per-session token as the others.

### Open

- A plan-and-go mode, `policy.plan = "auto"`, that implements without waiting, if the operator wants plans without the
  gate.
- Whether a ticket that already has a branch can be planned again before a large `resume`.
- Whether plans help: compare attempts and spend per ticket (M33) on planned and unplanned tickets.
- Whether M38 makes the plan gate the harness's decision rather than the overseer's.
- Whether `canopy forget` keeps the ticket's own plan setting, as it keeps the start record.
- Whether a committed copy of the plan should raise an attention item, not only a note on the run.
- Whether canopy should prune old plan files, as issue #424 asks of M36's per-tick tables.
- Whether `fix-ci` runs should get the plan's copy too. They fix a failure, not the plan's work, so for now they do not.
