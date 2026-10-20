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
planned like any other unless the operator skips its plan: no agent waives one (D126).

### Approving a plan

The operator approves the newest plan as its file stands, their edits included. A reply (§22) newer than the plan asks
for changes: the overseer dispatches `plan` again with the reply in the planner's prompt, and the new plan supersedes
the old; an approval sent before that re-plan starts wins, as the operator's later word. The approval authorizes the
`implement`, not the plan's text as an instruction (TRUST_MODEL T1). Two guards hold it in code (§4, principle 2):
`unplanned` refuses an `implement` while the ticket needs a plan and has none approved;
`plan_changed` refuses an `implement` or `resume` when the approved plan's file is missing or changed since approval.

### The prompt

A plan runs in a desk of worktrees at their bases (§18), with no branch and nothing pushed, within
`capacity.max_workers`; under `tracker.private` (§22), a ticket's first plan starts it privately. The planner,
`canopy-planner` (§13), has no shell, web fetch, or subagent tools, reads only inside its desk and through the private
worker's tracker read tools (§22), without which it is not run, and writes one file, its plan. The ticket's text and the
code are data to it (T1).
Result contract, the last line of its text (§13), validated (D026):

```json
{"status":"done|blocked|failed","summary":"...","question":"<only when blocked>"}
```

`done` records the file as the ticket's newest plan, `proposed`; without a valid plan file the run is `unknown`.
`blocked`'s question is recorded as a worker message (§22), on a public ticket too, since the planner cannot comment.

### Phases and the overseer's part

Plans add the phase `plan_proposed` to §7: the newest plan waits on the operator, asked through attention `plan_review`
(§14), holding no run or slot, until a reply makes the next action a new `plan`. A `ready` ticket that needs a plan and
has none waiting or approved dispatches `plan`; one whose planner is blocked with no reply since is `needs_human`, and
the harness raises `awaiting_reply` rather than re-plan until attempts run out. The state block gives the plan's status,
attempts, and facts the harness computes so the overseer compares no times (`changes_asked`, `blocked`), never
its text.

### Workers follow the plan

The `implement` and `resume` prompts name the worker's copy of the plan and its outline, not its text, so a plan can be
as long as it needs; with an approved plan, an override that leaves it out is refused (D093). Each run gets a fresh copy
of the approved plan, checked against its hash first: a plan changed, superseded, or approved again since dispatch fails
the run. The copy is excluded from git and removed before the slot is returned. A worker can still commit it by force,
publishing a private ticket's plan; the prompt forbids it and push verification (§8) notes it.

### Where plans live

A plan is a markdown file in canopy's state directory, outside the journal, so the operator reads it, and edits it until
approving it, with their own tools. The journal holds each plan's status (`proposed`, `approved`, `superseded`), hashes,
and approval, never its text. canopy never overwrites or deletes a plan file, never reads one the journal does not
record or through a link, and shows a missing file as missing, never as an empty plan. Workers see only their copy
(§24); a plan's event to sinks (§20) carries none of its text.

### Commenting on a plan

The web UI lets the operator comment on passages and edit a plan in place (D120). A plan is model text (T1): its HTML is
never rendered, an image never fetched, and a link is not a link (D113). A comment is a thread anchored by its passage's
words, found again on each new plan; asking for changes sends the open threads as one reply (§22). A saved edit never
overwrites unseen one made elsewhere. Only the web channel writes threads and edits, behind its token (T8).

### Open

- A plan-and-go mode that implements without waiting.
