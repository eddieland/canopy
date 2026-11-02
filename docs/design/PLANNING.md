# Plans

Part of the canopy design, normative like all of it: a plan for a ticket, written and approved before any `implement`.
Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Sandboxed
runs](SANDBOXING.md). Next: [Garbage collection](GARBAGE_COLLECTION.md).

## 25. Plans before implementing

REQUIREMENTS R18. §7, §8, §12, §14, §20, and §22 describe canopy with plans off; this section says what plans change. A
**plan** is a run of its own that reads the ticket and the code and writes down how the work will be done, before any
`implement`, so the worker starts from a plan the operator has read, and the plan is kept for later. When a ticket is
planned, nothing is implemented until the operator approves its plan. The plan stays in canopy and is posted nowhere, so
a private ticket (§22) is planned the same way as a public one.

### Which tickets are planned

`policy.plan` is off or `"approve"` (every ticket is planned), and a repository may only tighten it (§12); a ticket's
own setting overrides it. Only the operator's channels (§22) set that, ask for a new plan, or waive one: each is refused
inside any agent run. A plan is never asked for once the ticket has a branch, so it never describes work already
started. Plan runs are limited per ticket, never reset (D030), and raised only by the operator's grant. Trivial work is
planned like any other unless the operator skips its plan; no agent waives one, though its planner may spare the
operator's review (D126, below).

### Approving a plan

The operator approves the newest plan as its file stands, their edits included. A reply (§22) newer than the plan asks
for changes: the overseer dispatches `plan` again with the reply in the planner's prompt, and the new plan supersedes
the old; an approval sent before that re-plan starts wins, as the operator's later word. An approval may carry the
operator's notes, written with it as their message on the ticket, which the `implement` reads beside the plan, so a
small point needs no re-plan. The approval authorizes the `implement`, not the plan's text as an instruction
(TRUST_MODEL T1). Two guards hold it in code (§4, principle 2):
`unplanned` refuses an `implement` while the ticket needs a plan and has none approved;
`plan_changed` refuses an `implement` or `resume` when the approved plan's file is missing or changed since approval.

**The planner's word.** Under `policy.planner_may_approve`, private (T7) and off by default, a planner may say its plan
needs no review, with a one-line reason; the harness then records the plan approved as written, the planner's approval
and never the operator's, and the `implement` goes ahead with nothing waiting on them. The key is a level, `strict`,
`normal`, or `lenient`, and each sets its own bar in the planner's prompt; at every level a plan touching security,
credentials, destructive data changes, or migrations needs review, and the ticket's text cannot argue it away. It
costs no run of its own, as a judge before the plan did (D126): the planner has read the ticket and the code. It fails
closed: only a `done` result that says so with a reason counts, and a plan that replaces a current one, or a ticket
whose own setting asks for a plan, waits on the operator, who has had a word on it. The sinks hear of it (§20); the
plan and its reason stay to read.

### The prompt

A plan runs in a desk of worktrees at their bases (§18), with no branch and nothing pushed, within
`capacity.max_workers`; under `tracker.private` (§22), a ticket's first plan starts it privately. The planner,
`canopy-planner` (§13), has no web fetch or subagent tools, and no shell but what `runtime.allow_bash` names for it
(§13), reads only inside its desk, its worktrees' history through canopy's read-only git tools (§27), and the ticket
through the private worker's tracker read tools (§22), without which it is not run, and writes one file, its plan.
The ticket's text and the code are data to it (T1).
Result contract, the last line of its text (§13), validated (D026):

```json
{"status":"done|blocked|failed","summary":"...","question":"<only when blocked>","effort":"small|medium|large","review":"needed|not_needed","review_reason":"..."}
```

`done` records the file as the ticket's newest plan, `proposed`; without a valid plan file the run is `unknown`. Its
`effort`, how much work the plan is for its worker as the planner judged, is kept with it for the operator to read;
one outside the three drops alone, never the plan. Nothing decides on it.
`blocked`'s question is recorded as a worker message (§22), on a public ticket too, since the planner cannot comment.

### Phases and the overseer's part

Plans add the phase `plan_proposed` to §7: the newest plan waits on the operator, asked through attention `plan_review`
(§14), holding no run or slot, until a reply makes the next action a new `plan`. A `ready` ticket that needs a plan and
has none waiting or approved dispatches `plan`; one whose planner is blocked with no reply since is `needs_human`, and
the harness raises `awaiting_reply` rather than re-plan until attempts run out. The state block gives a ticket with no
branch yet the plan's status, attempts, and facts the harness computes so the overseer compares no times
(`changes_asked`, `blocked`), never its text.

### Workers follow the plan

The `implement` and `resume` prompts name the worker's copy of the plan and its outline, not its text, so a plan can be
as long as it needs; with an approved plan, an override that leaves it out is refused (D093). Each run gets a fresh copy
of the approved plan, checked against its hash first: a plan changed, superseded, or approved again since dispatch fails
the run. The copy is excluded from git and removed before the slot is returned. A worker can still commit it by force,
putting the plan in its PR; the prompt forbids it and push verification (§8) notes it.

### Where plans live

A plan is a markdown file in canopy's state directory, outside the journal, so the operator reads it, and edits it until
approving it, with their own tools. The journal holds each plan's status (`proposed`, `approved`, `superseded`), hashes,
and approval, never its text. canopy never overwrites or deletes a plan file, never reads one the journal does not
record or through a link, and shows a missing file as missing, never as an empty plan. Workers see only their copy
(§24); a plan's event to sinks (§20) carries none of its text.

`canopy archive DIR`, the operator's alone, copies every plan, superseded and feedback plans included, into a directory
of theirs, each under a front matter of its row and its planner's persona, models, and cost, since status, approval,
voice, model, and spend live only in the journal; the cost is its own run's and, summed, every plan run of its kind on
the ticket since the last plan approved, so a plan that took several tries shows what all of them cost. Each is named
for its run, status, and title, so a listing reads without opening a plan.
Beside each goes the prompt its planner was given, named for its run, so a plan can be read with what it was written
from; a plan run keeps its prompt as long as its plan (§26). It rewrites a file only when its plan or row changed, and
removes only a plan's own earlier name when its status or title moved it, so the directory can be a repository the
operator pushes and git sees a rename. Asked to, it also writes each planned ticket's conversation (§22) beside its
plans, every message oldest first, each body quoted under a heading canopy writes, so no body can pass for another
message. An edit replaces a plan's file, so canopy keeps a copy of each plan as its planner wrote it, never rewritten,
and an edited plan goes with that original beside it, so what the operator changed before approving can always be
read. The operator's comments on a ticket's plans go beside them too, each thread with its passage and replies, quoted
as a conversation's bodies are. A `README.md` in each ticket's directory lists its plans, then the implements and
resumes that followed them, each with the plan it followed, and the ticket's PRs with their states as last read, so the
archive alone says what came of a plan; one in the directory lists every ticket. An index is canopy's only while its
first line says so, so the operator's own is never touched, and a title in one is escaped text, never inside a link,
as is a PR's URL that is not a plain one (T1).
With `paths.plan_archive`, a clone's top level, a live tick does the same into its `<workspace>/`, or into the top
level itself with `paths.plan_archive_workspace_dir` off, prompts too unless `paths.plan_archive_prompts` is off,
comments unless `paths.plan_archive_comments` is off, conversations only with `paths.plan_archive_conversations`,
commits what it wrote there alone (at the top level, each
planned ticket's directory and its own index, never the operator's files beside them), and pushes to the clone's
upstream, never forcing: an upstream that refuses it for commits another clone pushed has them fetched and this clone's
commits rebased onto them, so the push is a fast-forward, and a rebase that cannot finish is aborted. `archive_unpushed`
stays open while the archive is not all there, so a failed push is retried each tick. A tick writes at most a thousand
files, so a long history goes in over several, each push bounded, and reads again only the plans whose row or files
changed, and the conversations with a new message, since it last found them as they stand. It archives at most once
each `paths.plan_archive_every_minutes`, timed from the archive's last commit in the clone, so the remote is pushed to
a few times a day, except while `archive_unpushed` is open; a tick that waits, and a dry run, only read the clone
(TRUST_MODEL T6).

### Commenting on a plan

The web UI lets the operator comment on passages and edit a plan in place (D120). A plan is model text (T1): its HTML is
never rendered, an image never fetched, and a link is not a link (D113). A Mermaid fence is drawn as its diagram, an
image beside its code, which stays the document (D131). A comment is a thread anchored by its passage's
words, found again on each new plan; asking for changes sends the open threads as one reply (§22). A saved edit never
overwrites unseen one made elsewhere. Only the web channel writes threads and edits, behind its token (T8).

### Open

- A plan-and-go mode that implements without waiting.
