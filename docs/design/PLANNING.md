# Plans

Part of the canopy design, normative like all of it: a plan for a ticket, written and approved before any `implement`.
Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Sandboxed
runs](SANDBOXING.md). Next: [Garbage collection](GARBAGE_COLLECTION.md).

## 25. Plans before implementing (M44)

Designed, and built only in part (ROADMAP M44, REQUIREMENTS R18): the plan editor (Commenting on a plan, below) is in,
over mock data, and so are plans' files and rows (Where plans live and Journal, below; `core/plans.py`), plan runs:
`canopy dispatch --kind plan`, the planner, its prompt, and `_run` writing the plan (Dispatch, The prompt, and Agent
definition, below), and the gate: `policy.plan`, the operator's `canopy plan` verbs, `canopy start --plan`, `canopy
grant KEY plan`, and the `unplanned` and `plan_changed` guards (Which tickets are planned, Approving a plan, and
Dispatch, below), and the overseer's part: the phases, the state block's plan, `plan_review`, a blocked planner's
`awaiting_reply`, and `plan.proposed` (Phases and the overseer's part, and Reading plans, below), and the worker's
copy: `{{PLAN}}`, `.canopy-plan.md` where the worker starts, and the harness note on a pushed copy (Workers follow the
plan, and The worker's copy, below). Until M44 lands, §22 describes the ticket page as it is, and `canopy show` prints
no plan. This section says what changes in each.

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
a plan, and `unknown` for a ticket canopy has no record of, as `canopy reply` does: the setting is a column of the
ticket's row. Each holds the dispatch lock (§8) while it reads and writes, so a dispatch's guards read a ticket's plans
from before the verb or after it, never between. Asking for a plan, `--skip`, and `start --plan` refuse `bad_plan`
while a plan run for the ticket is running: its plan would land after the request. The operator asks again once it
ends. Asking for a plan also refuses `bad_plan` once the ticket has a branch. Dispatch records the branch when it
inserts the ticket's first `implement` (§8 step 2), so this covers an `implement` that is running too: a plan now
would describe work already started (Open, below). `--skip` does not: on a ticket with a branch it drops the plan from
the ticket's later runs, which is the way out when an approved plan's file is gone (`plan_changed`, below).

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
`capacity.max_workers` with workers and reviews: it is an agent run, with spend. It works in a desk even over one
repository, so the copy of the plan it replaces (The prompt, below) is in no repository.

Under `tracker.private` (§22), a ticket's first plan starts it privately, as its first `implement` would: otherwise a
plan, which posts nothing, would be the ticket's first run, and the ticket would stay public for good.

### The prompt

`prompts/worker-plan.md` asks for a plan a later worker can follow:

- what changes in each repository, and why;
- the files and interfaces it touches;
- the tests that will show it works;
- what is out of scope;
- the open risks.

It carries the key, the repositories and their base branches (`{{REPOSITORIES}}`), the operator's messages
(`{{OPERATOR_MESSAGES}}`, which on a private ticket holds its conversation), `{{STANDING_INSTRUCTIONS}}`, `{{NOTICE}}`,
and the bound on a plan's length. On a re-plan, `_run` copies the plan it replaces, the ticket's current plan, from its
file as it stands, the operator's edits included, to `.canopy-plan.md` at the desk's root (The worker's copy, below),
and the prompt says that a file there is the plan it replaces; the operator's reply to it is among the messages. On a
public ticket the planner checks the queue label first, as every worker does (§8 step 3); a private ticket has no
label to check. One prompt serves both: `{{AUTHORIZATION}}` is the label check on a public ticket and says there is
none on a private one, and an override must carry it, `{{REPOSITORIES}}`, `{{OPERATOR_MESSAGES}}`, and `{{PLAN_OUT}}`.
It treats the ticket's text and the code as data (TRUST_MODEL T1).

The planner writes its plan, as markdown, to `.canopy-new-plan.md` at its desk's root (`{{PLAN_OUT}}`), the one file its
definition lets it edit (Agent definition, below), and `_run` reads that file once the planner exits, before the desk
is removed. A plan of tens of thousands of characters escaped into one JSON string is easy for a model to get wrong,
and a run whose result line does not parse records nothing, so the plan stays out of the JSON. It stays out of the
final message too, an earlier design (2026-10-16): a template that prints plain stdout has no message boundaries, so
everything it printed before the result line would have been the plan; a plan split across messages by a tool call
would have lost all but its end; and a long plan had to come in one message. A file has none of these: the planner can
write it a section at a time and revise it as it reads, and the file as it stands at exit is the plan. Result contract,
one JSON line, last line of the agent's text (§13), validated with pydantic (D026):

```json
{"status":"done|blocked|failed","summary":"...","question":"<only when blocked>"}
```

- `done` records the planner's file as the ticket's newest plan, `proposed`, read as every plan file is (Where plans
  live, below): a regular file, never through a link, non-empty UTF-8 of at most 100,000 characters. The bound is what
  an operator can read before approving, not what a worker reads: workers read the plan from a file, by its outline
  (Workers follow the plan, below).
- `blocked` has a `question`, recorded as a worker message (§22), on a public ticket too, since the planner cannot
  comment on the ticket. The operator answers with `canopy reply`.
- `failed` means it could not plan, and the summary says why. Like any run that ends other than `done`, it raises
  attention (§14).
- Anything else, a `done` whose file is missing, empty, over the bound, or not a regular file included, makes the run
  `unknown` and records no plan.

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
use for it, and it is model-written text (T1). A ticket plans do not touch, needing none and with no plan or plan run,
has no `plan` key, so with the policy off the block is as it was. The key also carries the ticket's plan runs and their
limit, with its grants, and the two facts the rows above turn on, computed by the harness so the overseer compares no
times: `changes_asked`, an operator message newer than the newest plan that is not superseded and than the latest plan
run's start, which no planner has read; and `blocked`, the latest plan run ended `blocked` with no operator message
since. A reply the re-plan has read is older than that run's start, so a re-plan that blocks waits on the operator
rather than being dispatched again.

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
  the planner wrote. Edits are the operator's: in their own editor, or in the web UI's plan editor, which writes the
  file the same way (Commenting on a plan, below).
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
died, is removed when reconcile cleans up the slot (§6 step 3): both tidy the slot with the same step, which removes the
copy first, never following a link. The file cannot sit beside the run's prompt in
`<state_dir>/runs/`: `canopy-worker` reads nothing outside its cwd (`external_directory: deny`), and the sandbox (§24)
denies `.canopy/`.

Ignored is not untrackable: a worker that adds the file by name, `git add -f .canopy-plan.md`, can still commit it.
On a private ticket that would publish its plan with the branch, against R18's "posted nowhere". The prompt forbids it,
and push verification (§8 `_run` step 5) checks each pushed branch's head: a tree holding `.canopy-plan.md` gives the
run a harness note naming it, so `canopy show` and the web UI say so. The harness does not rewrite the pushed branch.

### Agent definition

canopy ships `canopy-planner` in the definitions directory (§13):

- no shell, web fetch, or subagent tools; reads only inside its desk.
- one file it may write: its `edit` rules deny `*`, then allow `.canopy-new-plan.md` alone. OpenCode matches an edit's
  path relative to the project, `/` for a desk outside a checkout, and its `*` crosses `/`, so a file of that name in a
  worktree is allowed too; it is reset with the slot and never read. `external_directory: deny` keeps every edit inside
  the desk and its links. The rules come after the MCP patterns, since OpenCode matches each key against the
  permission's name as a wildcard, and `*edit*` after them would deny the edit tool, and take it from the model
  altogether. The planner canary checks them against a real model.
- MCP: its tracker tools are the private worker's (§22): the tracker server's tools denied by a wildcard, then only
  `tracker.read_tools` allowed. It reads the ticket but cannot comment, label, or create. With no read tools known for
  the provider, a plan dispatch refuses `no_read_tools`, rather than run a planner that cannot read the ticket.

### Reading plans

- `canopy show KEY` prints the newest plan, its status, and when it was approved; `canopy show KEY --plans` prints every
  plan, oldest first.
- The web UI's ticket page (§22) shows the newest plan in the plan editor (Commenting on a plan, below), with
  `Approve`, `Ask for changes`, and `Skip`, and lists earlier plans. They call `POST /tickets/{key}/plan` with
  `approve`, `request`, or `skip`, through the same code as the CLI, so with the same refusals.
- A `plan.proposed` event (§20) tells the operator's sinks a plan is waiting: the ticket and its title, the run, and the
  plan's id. It carries no plan text, so nothing of the plan leaves the machine through a Slack sink. It is in the
  `runs` group, recorded with the plan's row, and urgent to a batching sink; a sink that takes only attention hears of
  the plan from `plan_review`.

### Commenting on a plan

A reply to the whole plan makes the operator say in words where each change goes. The web UI shows a plan in an
editor instead, where the operator comments on its passages, as on a shared document, and edits it in place; asking
for changes sends those comments to the planner, each with the passage it is on. Asked for by the operator
(2026-10-16). The editor is built ahead of the rest of M44, over mock data at `/plan-editor`, and M44 puts it on the
ticket's page.

- **The editor** (`ui/src/components/plan-editor.tsx`) is Tiptap on ProseMirror (D120), Markdown in and out
  (`ui/src/lib/plan-schema.ts`): headings, lists, task lists, tables, quotes, code blocks, and inline marks, through a
  toolbar or Markdown's own shortcuts. A plan opened and left alone writes back as it was read. A line the plan wraps
  inside a paragraph, as planners wrap Markdown, reads as a space, so the paragraph reflows to the editor's width, and
  writes back as the wrap it was; kept as a newline, it would show as a line break and turn into a hard break at the
  first keystroke beside it. A list or task item that wraps stays one paragraph and writes back with its lines indented
  under its marker, as CommonMark reads it; Tiptap's own reader would make a wrapped task two paragraphs. Text pasted as
  Markdown, as a plan or a chat's answer is copied from a terminal or an editor, is read by the same parser, so it
  pastes as headings, lists, and marks, its HTML still characters; prose, a copy from the editor itself, a paste with
  Shift held (paste as plain text), and anything pasted into a code block paste as the text they are. What is copied out
  of more than one block copies, as plain text, as the Markdown that writes it, so a list keeps its markers and a
  heading its `#`; words within one block copy as the words, as from any page. A plan is model text (TRUST_MODEL T1), so
  what the editor has no node for stays characters: HTML is never read as HTML and an image is never fetched, both shown
  and written back as written, and a link keeps its address, shown on hover, but is not a link (D113).
- **A comment** is a thread on a passage: the comment, its replies, open until the operator resolves it. It is
  anchored by the passage's words and up to 32 characters either side, whitespace collapsed
  (`ui/src/lib/plan-anchors.ts`), never by a position, which the first edit above it would make wrong. While the plan
  is edited, a passage's highlight moves with the text around it, and its anchor follows its words. On a new plan,
  each thread is looked for again by its words, the text around it choosing between copies. A passage that is gone is
  found nowhere, and its thread says `passage gone` rather than move to other words: a reworded passage may no longer
  be what the comment was about. While a thread is open, its comment and each reply can be edited in place; Ask for
  changes sends what they say then. Nothing marks one edited, since the journal keeps a comment's body alone, and only
  the operator writes there.
- **Ask for changes** sends the open threads, in the order the plan reads, as one operator message: each passage
  quoted (cut at 160 characters), its comment and replies, then the operator's note on the whole plan, if any
  (`changeRequest` in `ui/src/lib/plan-threads.ts`). It is a reply, through `canopy reply`'s code and within its
  4,000-character bound, so the re-plan works as Approving a plan, above, says: the planner reads it among the
  operator's messages, with the plan it replaces. A request over the bound says so and is not sent; the operator
  resolves or shortens some. Resolved threads ask for nothing.
- **Editing** in the web UI edits the plan's file (Where plans live, above), as the operator's own editor would:
  saving writes the editor's Markdown over the file, through the web channel behind its token (T8), with the same
  care as the planner's write (operator-only, refusing a symlink or a file that is not regular), under a temporary
  name renamed into place, so a reader never sees half a file. It saves only a `proposed` plan's file, or an approved
  one's, which then needs approving again (`plan_changed`); it refuses `bad_plan` while a plan run for the ticket is
  running, and when the file changed since the editor read it, by its hash, so an edit made elsewhere is never
  overwritten unseen. `--approve` then takes the file as it stands, as it would after any edit.
- **In the journal** (M44): a thread belongs to the ticket, not to one plan, so it carries from plan to plan and is
  anchored again on each. A `plan_threads` table (id, ticket key, quote, prefix, suffix, body, created at, resolved at)
  and `plan_replies` (id, thread id, body, created at), written only by the web channel, behind its token (T8). A
  comment is the operator's words and the passage it quotes, not the plan, so it lives in the journal while the plan's
  text stays in its file. `canopy show KEY --plans` lists the newest plan's open threads under it, each with its
  passage; there is no CLI verb to comment, since a passage is chosen by selecting it.

### Journal

- A migration adds `plans`: id, ticket key, run id, created at, status (`proposed`, `approved`, or `superseded`), the
  SHA-256 and size of the file as the planner wrote it, and the approved hash, approved at, and channel. No body: the
  text is the plan's file (Where plans live, above). Its `status` column is constrained with `CHECK (status IN
  (...))`. Rows are never deleted. A new plan supersedes the ticket's current one in the transaction that records it,
  and a partial unique index holds each ticket to one plan that is not superseded.
- `tickets` gains the ticket's own plan setting, `plan_setting`: NULL for unset, `plan`, or `skip`.
- `ticket_grants` holds `canopy grant KEY plan`: the ticket, the kind, the runs, and when, only added to. A plan's
  limit is the ticket's, and `attempt_grants` holds units' (§22, Granting attempts).
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
- T6: the planner writes one file, its plan, in its desk: no other edits, no shell, and only the tracker's read tools.
  Residual: a worker can
  commit its copy of the plan by name, which on a private ticket publishes the plan with its branch. The prompt
  forbids it and push verification reports it; nothing prevents it.
- T8: the plan route joins the web channel's writes, behind the same secret and per-session token as the others, and
  so do saving an edited plan's file and the comments on a plan.

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
- Whether the planner should answer each thread in its result, by thread id, rather than only through the new plan.
- Whether a reworded passage should be found again by its nearest match, rather than shown as gone.
- Whether threads stay open for comment once a plan is approved, for the `implement` to read.
