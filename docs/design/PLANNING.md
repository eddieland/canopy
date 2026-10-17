# Plans

Part of the canopy design, normative like all of it: a plan for a ticket, written and approved before any `implement`.
Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Sandboxed
runs](SANDBOXING.md). Next: [Garbage collection](GARBAGE_COLLECTION.md).

## 25. Plans before implementing (M44)

ROADMAP M44, REQUIREMENTS R18. The parts below are plans' files and journal records, plan runs, the gate
(`policy.plan`, `canopy plan`, and the `unplanned` and `plan_changed` guards), the overseer's part, the worker's copy,
and reading, editing, and commenting on a plan. §7, §8, §12, §14, §20, and §22 describe canopy with plans off; this
section says what plans change in each.

Without plans, the `implement` worker plans inside its own session, and nothing of that plan survives but the run's
summary. A **plan** is a run of its own that reads the ticket and the code and writes down how the work will be done,
before any `implement` starts. A worker that starts from an explicit plan the operator has read should do better than
one that plans as it goes. And the plan is kept, as a file of its own, so the operator can read later how any ticket
was approached.

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

- `policy.plan` says whether a ticket waits on an approved plan before its `implement`. `"off"` is canopy without
  plans; `"approve"` plans every ticket. A repository may only tighten policy (§12): it may set `"approve"`, never
  loosen the operator's `"approve"` to `"off"`.
- `max_plan_attempts` is a `max_<kind>_attempts` like the others (§8): plan runs per ticket, never reset (D030).
  `canopy grant KEY plan` adds one (§22, Granting attempts). As for a split, the count and limit are the ticket's, not
  a unit's: a plan covers every repository the ticket will touch.
- `plan_cmd` follows §12 and has the worker's timeout. A private ticket's plan uses it too: the planner writes nothing
  to the tracker on any ticket.

### Off unless configured

With `policy.plan` at `"off"` and no ticket of the operator's asking for a plan, nothing changes: the state block's
tickets carry no plan, the overseer prompt's plan rows do not apply, and `ready` dispatches `implement`.

### Which tickets are planned

A ticket needs a plan when its own setting says `plan`, or when it has none and `policy.plan` is `"approve"`. Only the
operator's channels (§22) set it, never the overseer or a worker:

- `canopy plan KEY` asks for a plan for this ticket, whatever the policy; on a ticket with a plan waiting or approved,
  for a new one.
- `canopy plan KEY --skip` waives the plan for this ticket, whatever the policy, so its `implement` goes ahead.
- `canopy start KEY --plan` starts a private ticket (§22) with its setting at `plan`.

Asking for a plan and `--skip` supersede the ticket's waiting or approved plan at once, with the setting. After
`canopy plan KEY` the ticket needs a plan and has none, so the next tick dispatches `plan`; after `--skip`, no
`plan_review` waits and no `implement` carries a plan.

Each refuses `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set, so no agent run can ask for, skip, or approve
a plan, and `unknown` for a ticket canopy has no record of. Each holds the dispatch lock (§8), so a dispatch's guards
see a ticket's plans from before the verb or after it, never between. Asking for a plan, `--skip`, and `start --plan`
refuse `bad_plan` while a plan run for the ticket is running, since its plan would land after the request. Asking for a
plan also refuses `bad_plan` once the ticket has a branch, which dispatch records with its first `implement` (§8), so a
plan never describes work already started (Open, below). `--skip` does not: on a ticket with a branch it drops the
plan from later runs, the way out when an approved plan's file is gone (`plan_changed`, below).

### Approving a plan

`canopy plan KEY --approve` approves the ticket's newest plan as its file stands now, the operator's edits included
(Where plans live, below), and records the file's SHA-256 as the approved hash. It refuses `inside_run`, and
`bad_plan` when the newest plan is not waiting (`proposed`), unless it is approved and its file has changed since; when
a plan run for the ticket is running; and when its file is missing, not a regular file, or no longer a plan (empty,
not UTF-8, or over 100,000 characters).

An operator message (`canopy reply KEY`, §22) newer than the newest plan asks for changes: the overseer dispatches
`plan` again with the reply in the planner's prompt, and the new plan supersedes the old. An approval sent after such a
reply but before the new plan run starts wins, as the operator's later word; the reply still reaches the `implement`
as an operator message. Once the new plan run has started, `--approve` refuses, and the operator approves the plan it
writes.

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
  as it stands; a file that is gone or unreadable cannot be approved, so then they ask for a new plan, or, on a ticket
  with a branch, `--skip` it.

A plan runs as a split does (§18): in a desk of the named repositories' worktrees, each at its base branch, detached,
with no branch and no setup command, since the planner has no shell. It pushes nothing, so there is no push
verification. Slots are returned and the desk removed on every exit path, and reconcile treats a dead plan run like
any other. A plan counts toward `capacity.max_workers`: it is an agent run, with spend. It works in a desk even over
one repository, so the copy of the plan it replaces (The prompt, below) is in no repository.

Under `tracker.private` (§22), a ticket's first plan starts it privately, as its first `implement` would; otherwise a
plan, which posts nothing, would be the ticket's first run, and the ticket would stay public for good.

### The prompt

`prompts/worker-plan.md` asks for a plan a later worker can follow. It carries the key, the repositories and their
base branches, the operator's messages (on a private ticket, its conversation), the standing instructions, the notice,
and the bound on a plan's length. On a re-plan, the plan it replaces, as its file stands, the operator's edits
included, is copied to `.canopy-plan.md` at the desk's root, and the operator's reply to it is among the messages. On a
public ticket the planner checks the queue label first, as every worker does (§8); `{{AUTHORIZATION}}` is that check,
or says there is none on a private ticket. An override must carry `{{AUTHORIZATION}}`, `{{REPOSITORIES}}`,
`{{OPERATOR_MESSAGES}}`, and `{{PLAN_OUT}}`. The ticket's text and the code are data (TRUST_MODEL T1).

Every plan has one outline, its headings fixed by the prompt, so the operator reads each plan the same way and sees
what one leaves out, and a worker's outline (Workers follow the plan, below) is a table of contents it can rely on. Its
steps are numbered, so a worker reports its progress against them. The harness does not check the outline: the
operator's edits or an override may change it. Rejected: the sections a living plan keeps, such as progress and a
decision log the worker updates as it goes. The approved plan is pinned by its hash and the worker's copy discarded, so
the worker's summary carries that instead.

The planner writes its plan, as markdown, to `.canopy-new-plan.md` at its desk's root (`{{PLAN_OUT}}`), the one file
its definition lets it edit, and canopy reads that file once the planner exits, before the desk is removed. It can
write the file a section at a time and revise it as it reads; the file at exit is the plan. Rejected:

- the plan in the result line: a long plan escaped into one JSON string is easy for a model to get wrong, and a result
  that does not parse records nothing.
- the plan as the final message: plain stdout has no message boundaries, and a plan split by a tool call would lose
  all but its end.

Result contract, one JSON line, last line of the agent's text (§13), validated with pydantic (D026):

```json
{"status":"done|blocked|failed","summary":"...","question":"<only when blocked>"}
```

- `done` records the planner's file as the ticket's newest plan, `proposed`, read as every plan file is (Where plans
  live, below). The 100,000-character bound is what an operator can read before approving; workers read a plan by its
  outline (Workers follow the plan, below).
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
ticket's plan: whether one is needed, the newest plan's id, status, and time, the ticket's plan runs and their limit
with its grants, and two facts the harness computes so the overseer compares no times: `changes_asked`, an operator
message newer than the current plan and than the latest plan run's start, which no planner has read; and `blocked`,
the latest plan run ended `blocked` with no operator message since. A re-plan that blocks therefore waits on the
operator rather than being dispatched again. Never the plan's text: the overseer has no use for it, and it is
model-written (T1). A ticket plans do not touch has no `plan` key, so with the policy off the block is unchanged.

`plan_review` is an attention reason (§14) the overseer raises every tick the plan waits. Its detail names the plan and
how to answer: `canopy show KEY`, then `canopy plan KEY --approve` or `canopy reply KEY`. Its cause is gone once the
plan is approved or superseded, or the ticket's plan is skipped.

Without the `needs_human` row, a `blocked` plan's ticket would be `ready` again next tick and dispatch `plan` until its
attempts ran out, each run asking the same question. The planner cannot label or comment on the ticket, so the harness
raises `awaiting_reply` for its question every tick, as for a started ticket's (§22). The operator's `canopy reply`
ends the wait, and the next `plan` carries the reply among the operator's messages.

### Workers follow the plan

The `implement` and `resume` prompts, and their private variants, carry `{{PLAN}}`. With an approved plan it names the
worker's copy (below) and gives the plan's outline, its markdown headings, bounded; without one it is `None.`. Once a
ticket has an approved plan, an override without `{{PLAN}}` is `bad_prompt`, as for `{{OPERATOR_MESSAGES}}` (§8, D093),
so an older override cannot drop it; for a ticket with none it still renders.

The prompt does not carry the plan's text. The worker reads the outline, then the sections it needs, as it reads the
code, so a long plan costs a run what it reads of it, and a plan can be as long as the work needs, within the bound.

A plan is model-written from ticket text: it describes the work, as the ticket does, and the prompt's obligations come
before it, as they come before the standing instructions. The prompt has the worker leave its copy out of every commit
and say which of the plan's steps it finished, by number, and where the work left the plan and why.

### Where plans live

A plan is a markdown file of its own, outside the journal: `<state_dir>/plans/<KEY>/<run>.md`, where `run` is the id of
the plan run that wrote it. The operator reads, greps, and edits it with their own tools, and a ticket's plans are a
directory listing. The journal holds what canopy decides by: each plan's status, its hashes, and its approval
(Journal, below), never its text.

- **Writing it.** A plan is written readable only by the operator, refusing a symlink, as a run's prompt is (§8).
  `plans/` and each ticket's directory are operator-only, and one that is not, a symlink or another owner's, refuses
  the write, as §18 refuses such a `.canopy/`. The path is built from the key and the run id, never read from the
  journal, and a key cannot hold a path separator (§17). A plan file is never overwritten: a name already taken fails
  the run `crashed` with a note, and nothing is recorded. The journal records the plan after the file, with the file's
  SHA-256 as written; a file with no record, from a run that died between the two, is never read, and its name belongs
  to that run alone.
- **Editing it.** A `proposed` plan's file is the operator's to edit, in any editor or the web UI's plan editor
  (Commenting on a plan, below), until they approve it: they can fix a step rather than ask for a whole new plan.
  `--approve` takes the file as it then stands. `canopy show` and the web UI show the file as it is, and say when it
  differs from what the planner wrote.
- **After approval.** The approved hash pins the text the operator approved. `implement` and `resume` dispatches
  refuse `plan_changed` when the file no longer matches it, and the run checks again before it copies the plan for a
  worker, failing `crashed` with a note if it changed in between. An edit after approval is answered by approving
  again or by asking for a new plan.
- **Reading it.** Every read, by `canopy show`, the web UI, `--approve`, dispatch, and the run, opens a regular file
  without following links and reads at most 100,000 characters of UTF-8, as §21 reads a review's diff. A missing or
  unreadable file is shown as such, never as an empty plan. A hash is of the whole file's bytes, never of a bounded
  read: a file over the bound is no longer a plan, so `--approve` refuses it and it never matches an approved hash.
- **Keeping it.** canopy never deletes a plan file. A superseded plan's file stays, as its record does, so a ticket's
  history of plans is on disk; `canopy forget` supersedes plans and leaves files. Removing old ones is the operator's,
  and a backup of canopy's state takes `plans/` with the journal.
- **Workers cannot reach it.** `canopy-worker` reads nothing outside its cwd, and the sandbox (§24) denies `.canopy/`.
  A worker reads the plan from its own copy (below), written for its run alone.

### The worker's copy

A run reads a copy of the approved plan. Dispatch records on the run the plan its `{{PLAN}}` names, and the run copies
that plan alone: one superseded or approved again since the dispatch, whose text may differ from the outline the
prompt gave, fails the run `crashed` before the worker starts, as a changed file does, and a plan approved after a
dispatch whose prompt named none is not copied. The run checks the file against the approved hash and writes it to
`.canopy-plan.md` in the worker's cwd, after branch setup and the operator's setup command (§8) and before the worker
starts:

- in a joint run, at the desk's root (§18), which is in no repository.
- in a one-repository run, at the worktree's root. The repository's `info/exclude`, which every slot shares, gets the
  line `/.canopy-plan.md`, so `git add -A` leaves the copy out.

The copy is written fresh for each run, so a worker that edits it changes only its own run, never the plan's file. It
is removed, never following a link, before the slot is returned, on every exit path, and a leftover from a run that
died is removed when reconcile cleans up the slot (§6 step 3). It cannot sit beside the run's prompt in
`<state_dir>/runs/`, since the worker reads nothing outside its cwd and the sandbox (§24) denies `.canopy/`.

Ignored is not untrackable: a worker can still commit the copy with `git add -f`, which on a private ticket would
publish its plan with the branch, against R18's "posted nowhere". The prompt forbids it, and push verification (§8)
gives the run a harness note when a pushed branch's head holds `.canopy-plan.md`, so `canopy show` and the web UI say
so. The harness does not rewrite the pushed branch.

### Agent definition

canopy ships `canopy-planner` in the definitions directory (§13):

- no shell, web fetch, or subagent tools; reads only inside its desk.
- one file it may write, `.canopy-new-plan.md`: its `edit` rules deny everything else. A file of that name in a
  worktree is allowed too; it is reset with the slot and never read. `external_directory: deny` keeps every edit
  inside the desk and its links. The planner canary checks the rules against a real model.
- MCP: its tracker tools are the private worker's (§22): the tracker server's tools denied by a wildcard, then only
  `tracker.read_tools` allowed. It reads the ticket but cannot comment, label, or create. With no read tools known for
  the provider, a plan dispatch refuses `no_read_tools`, rather than run a planner that cannot read the ticket.

### Reading plans

- `canopy show KEY` prints the newest plan as its file stands, its status, and when it was approved, and says when the
  file was edited since the planner wrote it, changed since it was approved, or is not a plan any more; `--plans`
  prints every plan and the open comments. A ticket plans do not touch shows no plan.
- The web UI's ticket page (§22) shows the newest plan in the plan editor, with `Approve`, `Ask for changes`, and
  `Skip`, and earlier plans read only. A waiting or approved plan is editable while no plan run for the ticket is
  running, and `Approve` or `Ask for changes` saves an unsaved edit first, so the approval takes what the operator sees
  and the planner reads it. `Approve`, `Skip`, and asking for a plan go through the same code as `canopy plan`, with
  the same refusals; `Ask for changes` is a reply. Leaving the page, by a link or by closing the tab, while an edit is
  not saved or a comment or the note holds words not yet sent, asks first, so nothing typed is lost unseen.
- A `plan.proposed` event (§20) tells the operator's sinks a plan is waiting: the ticket and its title, the run, and the
  plan's id. It carries no plan text, so nothing of the plan leaves the machine through a Slack sink. It is in the
  `runs` group and urgent to a batching sink; a sink that takes only attention hears of the plan from `plan_review`.

### Commenting on a plan

A reply to the whole plan makes the operator say in words where each change goes. The web UI shows a plan in an
editor instead, where the operator comments on its passages, as on a shared document, and edits it in place; asking
for changes sends those comments to the planner, each with the passage it is on. `ui/DESIGN.md` holds the editor's
page-level detail.

- **The editor** is Tiptap on ProseMirror (D120), Markdown in and out. A plan opened and left alone writes back as it
  was read. A plan is model text (TRUST_MODEL T1), so what the editor has no node for stays characters: HTML is never
  read as HTML and an image is never fetched, both shown and written back as written, and a link keeps its address
  but is not a link (D113).
- **A comment** is a thread on a passage: the comment and its replies, open until the operator resolves it. It is
  anchored by the passage's words and a little text either side, never by a position, which the first edit above it
  would make wrong. On a new plan, each thread is looked for again by its words. A passage that is gone is found
  nowhere, and its thread says `passage gone` rather than move to other words: a reworded passage may no longer be what
  the comment was about. A new plan rewrites what it was asked to change, so its comments lose their passages together,
  and the operator can resolve all of those at once. To read what a new plan changed rather than the whole of it again,
  the editor marks, while asked, the words it added and those it removed since the plan it replaces, word by word, as
  each plan reads in the editor (`ui/src/lib/plan-diff.ts`), so formatting alone is no change. An open thread's comment
  and replies can be edited in place; nothing marks one edited.
- **Ask for changes** sends the open threads, in the plan's order, as one operator message: each passage quoted, its
  comment and replies, then the operator's note on the whole plan, if any, and, when the operator edited the plan's
  text, a line saying so: the planner keeps what it was not asked to change, but reads the plan it replaces as its own,
  and the line says which words are the operator's, to keep. It is a reply, within `canopy reply`'s bound (§22), so the
  re-plan works as Approving a plan, above, says. A request over the bound is not sent; the operator resolves or
  shortens some. Resolved threads ask for nothing.
- **Editing** in the web UI edits the plan's file, as the operator's own editor would: through the web channel behind
  its token (T8), with the same care as the planner's write (operator-only, refusing a symlink or a file that is not
  regular), replaced whole so a reader never sees half a file. It saves only a `proposed` or approved plan's file, an
  approved one then needing approval again (`plan_changed`); it refuses `bad_plan` while a plan run for the ticket is
  running, and when the file changed since the editor read it, by its hash, so an edit made elsewhere is never
  overwritten unseen. This save is the largest body the web channel takes, which sets its body limit (§22). Until an
  edit is saved, the editor says `Unsaved edits` beside `Save`, and ⌘S (Ctrl+S) saves it, as a document's Save does,
  rather than open the browser's own.
- **In the journal** (M44): a thread belongs to the ticket, not to one plan, so it carries from plan to plan and is
  anchored again on each. Threads and replies are written only by the web channel, behind its token (T8). A comment
  is the operator's words and the passage it quotes, not the plan, so it lives in the journal while the plan's text
  stays in its file. `canopy show KEY --plans` lists the newest plan's open threads; there is no CLI verb to comment,
  since a passage is chosen by selecting it.

### Journal

The schema is in `migrations/`.

- Each plan is recorded with its ticket, its run, its status (`proposed`, `approved`, or `superseded`), the hash and
  size of the file as the planner wrote it, and the approved hash, time, and channel. No body: the text is the plan's
  file. Records are never deleted. A new plan supersedes the ticket's current one as it is recorded, and the journal
  holds each ticket to one plan that is not superseded.
- A ticket records its own plan setting: unset, `plan`, or `skip`.
- `canopy grant KEY plan` is recorded per ticket, only added to: a plan's limit is the ticket's, where other grants are
  a unit's (§22, Granting attempts).
- An `implement` or `resume` run records the approved plan it was dispatched to follow (The worker's copy, above).
- A plan run is a run of kind `plan` with its slots, no branch, and its validated result. Its report message (§8) is
  its summary.
- `canopy forget` (§22) supersedes a waiting or approved plan, so a forgotten ticket under `"approve"` is planned again.

### Trust model changes

What plans add to TRUST_MODEL, with the overseer prompt, `worker-plan.md`, and the `canopy-planner` definition:

- T1: an approved plan is data, not an operator instruction. It is model-written from ticket text, which anyone who
  can edit the ticket shapes. The operator's approval authorizes the `implement`; the worker's obligations come before
  the plan, and a plan cannot widen what a worker may do.
- T3: plan runs count toward `capacity.max_workers` and are limited by `max_plan_attempts`, never reset. `unplanned`
  is a guard in code.
- T6: the planner writes one file, its plan, in its desk: no other edits, no shell, and only the tracker's read tools.
  Residual: a worker can commit its copy of the plan by name, which on a private ticket publishes the plan with its
  branch. The prompt forbids it and push verification reports it; nothing prevents it.
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
- Whether a repository that tracks a `.canopy-plan.md` of its own at its root needs another name for the copy: the copy
  would write over it in the worktree, and push verification would report it as the worker's.
- Whether `fix-ci` runs should get the plan's copy too. They fix a failure, not the plan's work, so for now they do not.
- Whether the planner should answer each thread in its result, by thread id, rather than only through the new plan.
- Whether a reworded passage should be found again by its nearest match, rather than shown as gone.
- Whether threads stay open for comment once a plan is approved, for the `implement` to read.
