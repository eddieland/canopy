# Plans

Part of the canopy design, normative like all of it: a plan for a ticket, written and approved before any `implement`.
Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Sandboxed
runs](SANDBOXING.md). Next: [Garbage collection](GARBAGE_COLLECTION.md).

## 25. Plans before implementing

REQUIREMENTS R18. §7, §8, §12, §14, §20, and §22 describe canopy with plans off; this section says what plans change.

Without plans, the `implement` worker plans inside its own session and nothing of that plan survives. A **plan** is a
run of its own that reads the ticket and the code and writes down how the work will be done, before any `implement`. A
worker that starts from a plan the operator has read should do better, and the plan is kept, so the operator can read
later how any ticket was approached. When a ticket is planned, nothing is implemented until the operator approves its
plan. The plan stays in canopy and is posted nowhere, so a private ticket (§22) is planned the same way as a public one.

### Which tickets are planned

`policy.plan` is `"off"` (canopy without plans: the state block and dispatch are unchanged) or `"approve"` (every
ticket is planned). A repository may only tighten it (§12). `max_plan_attempts` limits plan runs per ticket, never
reset (D030), raised by `canopy grant KEY plan`; the count is the ticket's, not a unit's, since a plan covers every
repository the ticket touches. `plan_cmd` follows §12 with the worker's timeout.

A ticket needs a plan when its own setting says `plan`, or when it has none and `policy.plan` is `"approve"`. Only the
operator's channels (§22) set it, never the overseer or a worker: `canopy plan KEY` asks for a plan (a new one if one
is waiting or approved), `canopy plan KEY --skip` waives it, and `canopy start KEY --plan` starts a private ticket
needing one. Asking or skipping supersedes the ticket's waiting or approved plan at once. Each refuses `inside_run`
inside any agent run, so no run can ask for, skip, or approve a plan, and holds the dispatch lock (§8). Asking refuses
`bad_plan` while a plan run for the ticket is running, and once the ticket has a branch, so a plan never describes work
already started; `--skip` works on a ticket with a branch, the way out when an approved plan's file is gone.

### Approving a plan

`canopy plan KEY --approve` approves the newest plan as its file stands now, the operator's edits included, and records
the file's SHA-256 as the approved hash. It refuses `inside_run`; and `bad_plan` while a plan run is running, when the
newest plan is neither waiting nor approved-and-changed, or when its file is missing or no longer a plan.

An operator message (`canopy reply KEY`, §22) newer than the newest plan asks for changes: the overseer dispatches
`plan` again with the reply in the planner's prompt, and the new plan supersedes the old. An approval sent before that
re-plan starts wins, as the operator's later word. The approval authorizes the `implement`; it does not make the plan's
text an instruction (TRUST_MODEL T1).

### Dispatch

`canopy dispatch KEY --kind plan` runs §8's guards as for `implement`, plus `bad_plan` (the ticket has a branch, or is
a split's parent, §18), refusals of `--slug`, `--base`, and `--request` (a plan makes no branch), `no_read_tools`, and
`attempt_limit`. Two guards join the worker kinds, both in code whatever the overseer asks (§4, principle 2):

- `unplanned`, on `implement`: the ticket needs a plan and has none approved (nor a triage's waiver, below).
- `plan_changed`, on `implement` and `resume`: the approved plan's file is missing, unreadable, or no longer has its
  approved hash. The operator approved one text, and the worker must not follow another.

A plan runs as a split does (§18): in a desk of the repositories' worktrees at their base branches, with no branch, no
setup command, and nothing pushed. It counts toward `capacity.max_workers`, its slots are returned on every exit path,
and reconcile treats a dead plan run like any other. Under `tracker.private` (§22), a ticket's first plan starts it
privately, as its first `implement` would.

The planner, `canopy-planner` (§13), has no shell, web fetch, or subagent tools, reads only inside its desk, and may
write one file, its plan. Its tracker tools are the private worker's read tools (§22); with none known, a plan refuses
`no_read_tools` rather than run a planner that cannot read the ticket.

### The prompt

`prompts/worker-plan.md` carries the key, the repositories, the operator's messages, the standing instructions, and the
notice; on a re-plan, the plan it replaces, as its file stands, is copied into the desk. An override must carry
`{{AUTHORIZATION}}`, `{{REPOSITORIES}}`, `{{OPERATOR_MESSAGES}}`, and `{{PLAN_OUT}}`. The ticket's text and the code are
data (TRUST_MODEL T1). Every plan has one outline with numbered steps, fixed by the prompt and not checked by the
harness, so the operator reads each plan the same way and a worker can report progress by step.

The planner writes its plan as markdown to one file in its desk (`{{PLAN_OUT}}`), which canopy reads once the planner
exits. Rejected: the plan in the result line (a long JSON string is easy to get wrong) or as the final message (stdout
has no message boundaries). Result contract, one JSON line, last line of the agent's text (§13), validated (D026):

```json
{"status":"done|blocked|failed","summary":"...","question":"<only when blocked>"}
```

`done` records the file as the ticket's newest plan, `proposed`. `blocked`'s question is recorded as a worker message
(§22), on a public ticket too, since the planner cannot comment; the operator answers with `canopy reply`. `failed`
raises attention (§14). Anything else, a `done` with no valid plan file included, is `unknown` and records no plan.

### Phases and the overseer's part

One phase, `plan_proposed`, joins §7's table, `needs_human` gains a case, and `ready` splits by plan. In order, before
`ready`'s own row:

| Phase | Derived from | Next action |
|---|---|---|
| `needs_human` | as `ready`, the ticket needs a plan, none is waiting or approved, and its latest plan run ended `blocked` with no operator message after it | wait; attention `awaiting_reply` |
| `ready` | as today, the ticket needs a plan, and none is waiting or approved | dispatch `plan` |
| `plan_proposed` | the newest plan is `proposed`, and no operator message after it | attention `plan_review`; no run |
| `plan_proposed` | the newest plan is `proposed`, and an operator message after it | dispatch `plan` again |
| `ready` | as today, with an approved plan or none needed | dispatch `implement` |

`plan_proposed` holds no run and no slot. The state block gives each ticket plans touch its plan's status and attempts,
and facts the harness computes so the overseer compares no times (`changes_asked`, `blocked`), never the plan's text,
which is model-written (T1). A ticket plans do not touch has no `plan` key. `plan_review` (§14) names how to answer:
`canopy show KEY`, then `--approve` or `canopy reply`. A blocked planner's question raises `awaiting_reply` every tick
until the operator replies, rather than dispatching `plan` again until its attempts run out.

### Workers follow the plan

The `implement` and `resume` prompts carry `{{PLAN}}`: the path of the worker's copy and the plan's outline, bounded, or
`None.`. Once a ticket has an approved plan, an override without it is `bad_prompt` (§8, D093). The prompt does not
carry the plan's text: the worker reads the sections it needs, so a plan can be as long as the work needs. The plan is
model-written from ticket text; the prompt's obligations come before it, as before the standing instructions, and the
worker reports which steps it finished and where it left the plan and why.

Dispatch records on the run the plan its `{{PLAN}}` names. The run copies that plan alone into the worker's cwd before
the worker starts, after checking it against the approved hash; a plan changed, superseded, or approved again since
dispatch fails the run `crashed`. In a one-repository run the copy is excluded from git. The copy is fresh for each
run, so a worker's edit changes only its own run, and it is removed before the slot is returned on every exit path.
Ignored is not untrackable: a worker can commit the copy by force, which on a private ticket would publish its plan.
The prompt forbids it, and push verification (§8) notes it on the run; the harness does not rewrite the branch.

### Where plans live

A plan is a markdown file of its own under `<state_dir>/plans/<KEY>/`, named by the run that wrote it, outside the
journal, so the operator reads, greps, and edits it with their own tools. The journal holds what canopy decides by:
each plan's status (`proposed`, `approved`, `superseded`), its hashes, and its approval, never its text. A ticket has at
most one plan not superseded, and records are never deleted.

- **Writing.** Operator-only, refusing a symlink or a directory that is not the operator's, as a run's prompt is (§8).
  The path is built from the key and the run id, never read from the journal. A plan file is never overwritten, and a
  file the journal has no record of is never read.
- **Editing.** A `proposed` plan's file is the operator's to edit until they approve it. `canopy show` and the web UI
  say when it differs from what the planner wrote. An edit after approval needs approval again (`plan_changed`).
- **Reading.** Every read opens a regular file without following links and reads at most 100,000 characters of UTF-8,
  as §21 reads a review's diff; a missing or unreadable file is shown as such, never as an empty plan. A hash is of the
  whole file, so a file over the bound is no longer a plan and never matches an approved hash.
- **Keeping.** canopy never deletes a plan file; `canopy forget` supersedes plans and leaves files. A backup of canopy's
  state takes `plans/` with the journal.
- **Out of workers' reach.** A worker reads nothing outside its cwd, and the sandbox (§24) denies `.canopy/`; it reads
  only its copy.

### Reading plans

`canopy show KEY` prints the newest plan, its status, and whether its file changed since written or approved; `--plans`
prints every plan and the open comments. The web UI gives a plan a page of its own, `/tickets/KEY/plan`, with
`Approve`, `Ask for changes`, and `Skip`, which go through the same code and refusals as `canopy plan` and `canopy
reply`; a `plan_review` item shows the plan's card, so a plan is approved from where it is listed as waiting.
`ui/DESIGN.md` holds the pages. A `plan.proposed` event (§20) tells the operator's sinks a plan is waiting and carries
no plan text, so nothing of the plan leaves the machine through a sink.

### Commenting on a plan

A reply to the whole plan makes the operator say in words where each change goes, so the web UI shows a plan in an
editor where the operator comments on passages and edits in place.

- **The editor** is Tiptap on ProseMirror (D120), Markdown in and out. A plan is model text (T1): HTML is never read as
  HTML, an image is never fetched, and a link is not a link (D113).
- **A comment** is a thread on a passage, open until resolved, anchored by the passage's words, never by a position.
  Threads belong to the ticket and are found again on each new plan; a passage found nowhere says `passage gone` rather
  than move to other words. The editor marks what a new plan changed since the one it replaces.
- **Ask for changes** sends the open threads, each with its passage, and the operator's note, as one reply within
  `canopy reply`'s bound (§22), saying when the operator edited the text. The page shows `changes_asked` until a
  planner reads it, so a second request is never sent unawares.
- **Saving an edit** writes the plan's file as the planner's write does, replaced whole. It refuses `bad_plan` while a
  plan run is running and when the file changed since the editor read it, so an edit made elsewhere is never
  overwritten unseen. This save sets the web channel's body limit (§22).
- Threads and edits are written only by the web channel, behind its token (T8). There is no CLI verb to comment.

### Triage before a plan

REQUIREMENTS R22, partly built; ROADMAP M55 lists what remains. With plans on, a typo fix still costs a planner run and
the operator's reading. A **triage** is a cheaper run that reads the ticket and the code and judges, by the operator's
own words for what is trivial, whether the work needs a plan. Trivial: the plan is waived and the `implement` goes ahead
unplanned. Otherwise, or if anything goes wrong, the ticket is planned as before.

**Configuration.** `policy.plan_triage` (`"off"` by default) turns it on, `policy.trivial` says in plain language what
counts as trivial (required when on), and `runtime.plan_triage_cmd` runs it, ideally on a cheaper model. Both policy
keys are private, unlike the rest of `policy.*`: triage loosens the operator's plan gate, so a shared file must neither
turn it on nor define trivial (TRUST_MODEL T7). With triage off nothing changes, and a `needs-plan` dispatch refuses
`triage_off`.

**When.** A triage is due when triage is on, the ticket needs a plan only because `policy.plan` is `"approve"` (a
ticket the operator set to `plan` is planned whatever a triage would say), and the ticket has no branch, no plan run,
and no triage run. So a ticket is triaged at most once, before its first plan, never reset and never granted (D030).
The state block's `plan` gains `triage_due` and `waived`, and one row joins the plan rows, before the one that
dispatches `plan`:

| Phase | Derived from | Next action |
|---|---|---|
| `ready` | as today, the ticket needs a plan, none is waiting or approved, and its triage is due | dispatch `needs-plan` |

**Dispatch.** `--kind needs-plan` runs §8's guards as for a `plan`, plus `triage_off`, `triaged` (the ticket has had a
triage, however it ended), and `bad_triage` (no triage is due for another reason). Under `tracker.private`, a triage
that is a ticket's first run starts it privately, so the `implement` it waives the plan for is private too.

**The run.** Shaped as §23's `triage-ci`: read-only, a verdict, no slot, no git steps, counted within
`capacity.max_workers`, with its own timeout. It runs in the ticket's desk over links to each repository's primary
clone, which may lag the base branch, and the shadowing check (§13) covers each link. Its definition,
`canopy-plan-triage`, is the planner's with nothing to edit: only the tracker's read tools, `no_read_tools` without
them. `worker_cmd_prefix` does not wrap it (§12). Its prompt, `prompts/plan-triage.md`, checks authorization first (§8
step 3), carries `policy.trivial` and the operator's messages, answers `plan` when unsure, and treats the ticket's own
claim to be trivial as data (T1). An override must carry `{{AUTHORIZATION}}` and `{{TRIVIAL}}`, and
`{{OPERATOR_MESSAGES}}` once the operator has written (D093). Result contract, validated (D026):

```json
{"status":"done|failed","reason":"one sentence","verdict":"trivial|plan"}
```

The reason, cut to one line, is the run's report (§8 step 7). Anything else is `unknown`.

**Failing closed.** Only `done` with `trivial` waives the plan. Any other end leaves the ticket needing its plan with
its one triage spent, so the next tick dispatches `plan`. Nothing is retried, and no §14 run reason is raised, since the
plan follows at once; `canopy health` (§11) lists the failure.

**The waiver** is a journal fact written by the harness from the validated result, never by an agent or a command, so
the plan gate stays a guard in code: `unplanned` passes only an approved plan, none needed, or a waiver in force. It is
in force only while the ticket's own setting is unset: `canopy plan KEY` undoes it, `--skip` replaces it, and `canopy
forget` ends it (the ticket is planned again, not triaged again). `canopy show` says the plan was waived, by which run,
and why. A waiver goes ahead without the operator's glance, which would give back the time triage saves. No worker hears
of it: `{{PLAN}}` is `None.`, and the triage's reason, model text from the ticket, reaches no worker's prompt.

**A second opinion after.** Size says little about risk, so no line count is checked. Where `review.agent_prs` is on,
the reviewer, not told of the waiver, judges each PR's impact (§21). When a `done` review of a waived ticket's PR judges
it `high`, the harness raises `not_trivial` every tick until the ticket is done or forgotten or the operator's `--skip`
replaces the waiver. It stops nothing: the PR's human review is still the gate.

**Feedback rounds.** Designed with feedback plans (ROADMAP M54). Fixed now: a round is triaged at most once, in code,
and a `trivial` round returns to the rules for feedback without plans (§7, D089), so triage never lets an untrusted
reviewer's text start a worker.

Rejected: triage by the overseer (it would lift a code guard with no validated verdict, and reads no code); a planner
that may answer no plan is needed (its run is the cost saved); a leased slot for a run that only reads; a retry or a
grant (a second try only delays the plan); triage choosing the worker's model.

### Trust model

TRUST_MODEL holds the rules plans and triage add: an approved plan is data, not an instruction (T1); plan runs and the
one triage per ticket are bounded in code and `unplanned` is a guard in code (T3); the planner writes only its plan
and the triage nothing, and a triage is not sandboxed until a sandbox role holds it (T6, §24); triage's keys are
private (T7); the web channel's plan writes are behind its token (T8). Residuals: a worker can commit its copy of the
plan; ticket text can talk a triage into `trivial`; a primary clone may lag the code a verdict rests on.

### Open

- A plan-and-go mode, `policy.plan = "auto"`, that implements without waiting.
- Whether a ticket with a branch can be planned again before a large `resume`.
- Whether plans help: compare attempts and spend on planned and unplanned tickets.
- Whether M38 makes the plan gate the harness's decision rather than the overseer's.
- Whether `canopy forget` keeps the ticket's own plan setting.
- Whether a committed copy of the plan should raise an attention item, not only a note.
- Whether canopy should prune old plan files.
- Whether a repository that tracks its own file of the copy's name needs another name for the copy.
- Whether the planner should answer each thread by id, and a reworded passage be found by its nearest match.
- Whether threads stay open once a plan is approved, for the `implement` to read.
- Feedback rounds' triage: what a round is, how its triage is counted, and whether it raises `not_trivial` (M54).
- Which sandbox role holds `plan_triage_cmd` (§24): it reads primary clones, which neither role expects.
- Whether a waiver should send an event of its own to the operator's sinks.
