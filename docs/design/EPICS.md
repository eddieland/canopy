# Epics

Part of the canopy design, normative like all of it: one plan for work that spans several tickets, approved once, and a
plan per ticket that points back to it. Sections are numbered across the whole design; the [README](README.md) has the
map. Previous: [The operator's checklist](CHECKLIST.md). Next: [Messages to running agents](MESSAGES.md).

## 43. Epics

Being built (REQUIREMENTS R28, ROADMAP M67).

§25 plans one ticket. Work that spans several has no plan of its own, so each ticket's planner settles the shared
questions again and the operator approves them again. An **epic** is that work as canopy's own subject: the
operator's goal, its plan, approved once, and its member tickets, each planned against it: a shallow plan for the whole
with ids that never change, a thin entry per ticket pointing back to it, and each ticket's own plan written just before
it is built (PRIOR_ART, "Shared plans across tickets"). The tracker's epic is always a **tracker epic**, never one of
canopy's by itself.

### The epic and its members

The operator submits an epic's goal in their own words, naming its repositories and, if canopy is to file its
tickets, the tracker project; `epic:N` names it afterwards (D075). Like a task (§36), it is private, its conversation
never touches the tracker, and it never reaches the overseer. The submission authorizes its plan runs, and its text is
the operator's instruction; replies, approvals, stopping it, and adding or removing a member take the same channels,
each refused inside a tick or any run (TRUST_MODEL T1).

A **member** is a ticket the operator added, or one a filing run filed for it, at any time, before its plan or after.
A ticket is a member of at most one epic, and at most `policy.max_epic_tickets` are members of one. Membership
authorizes nothing: a member is worked only once a label or a start says so (§7, D123), and it is then a ticket like any
other, one worker at a time (§6). A tracker's epic, parent, or sub-issue link is data and never makes a ticket a member
(§17). The children of a tracker epic the operator names on an epic (§30) that are not members are suggestions,
`epic_suggestion` (§14), until the operator adds or removes each.

### Its plan

A plan run as §25's: the planner, in a desk at the epic's repositories' bases (§18), writes one file, recorded
`proposed`; the operator approves it by hash, as its file stands, or replies to ask for changes, and a new plan
supersedes the old. The tick starts it in code, before the overseer, as it starts a task: once after the submission,
and once after each reply newer than its newest plan. One plan run per epic at a time, within `capacity.max_workers`,
its attempts counted against `policy.max_plan_attempts` and never reset (D030). No agent approves an epic's plan:
`policy.planner_may_approve` does not reach it. A plan waiting on the operator is `plan_review` on `epic:N` (§25),
naming the epic and never its text, until its approval, a reply, or a stop. A stop ends only an epic's planning: no
plan run of it starts again and a reply is refused, while its plan may still be approved and its members changed.

Its outline is fixed: `Goal`; `Requirements` (`R<n>`, each tracing to the operator's words); `Contracts` between the
tickets (`C<n>`: what it is, who provides it, who uses it); `Breakdown` (`B<n>`: the `R`s it covers, the contracts it
provides and uses, its repositories, what it comes after); `Decisions`; `Out of scope`. It writes no ticket's steps. The
ids and the breakdown are the one part canopy reads, from the file as approved: a plan whose ids repeat or will not
parse is `unknown`, and an edit that breaks them or reuses a removed id cannot be approved. They are data, used only to
compare one approval with the next and to route entries to members; the plan's text is never an instruction (T1).

### Members from the breakdown

The operator files the tickets themselves, as they choose, and registers each against the entries it fulfils, one or
more, or none for a ticket the breakdown did not foresee; an entry the approved plan does not hold is refused, and
registering again replaces a member's entries. canopy never asks for a ticket per entry: the epic's status lists each
entry with its members, so the plan shows what is left to file.

Only when the operator asks, once the plan is approved, a filing run files the entries they name, as a task files
tickets (§36): the private worker, whose create tool alone writes to the tracker, files each unlabeled in the epic's
project with the tracker's blocker relation by `after` (§10). It writes no code. canopy records each key its result
pairs with a named entry as a member, checking only the key's text against the project, the entry, and the bound,
and that it is no epic's member yet (D003); any other raises `epic_ticket_unrecorded` (§14) until the operator replies
to the epic. A filed ticket authorizes nothing until labeled or started.

### A member's plan

`policy.plan` decides whether a member is planned, as for any ticket. A member's planner gets a copy of the epic plan
checked against its approved hash, and the entries it fulfils, never the text inlined, so no copy goes stale; its
`implement` and `resume` get the same copy. Its plan gains `## Epic`: the `R`s it covers, the contracts it provides and
uses, and the siblings it leaves out, and its row records the epic plan's hash.

**A trivial member.** A member whose every entry the epic plan marks trivial, with a reason, by §25's bar at the level
`policy.planner_may_approve` sets (none with it off), skips its own plan: the operator's approval of the epic plan
approves it. A member of no entry, one touching security, credentials, destructive data changes, or migrations, or one
whose own setting asks for a plan, is never trivial.

**Upward.** A member's plan whose `Decisions` depart from a contract or a requirement names those ids, and the harness
raises `epic_drift` (§14). The operator settles it by approving the epic plan amended to the member's choice, approving
the member's plan as written, which accepts the departure for it alone, or asking for a new plan of either.

### When its plan changes

A re-approval compares the ids with the plan approved before it. A member is reached when one of its entries changed or
covers, provides, or uses a changed id; a member of no entry by every change. A member whose entry was removed stays a
member, of no entry. Each reached member, by where it stands:

- a plan still `proposed` is superseded as stale, and the next `plan` is told the changed ids;
- an approved plan with no branch yet has its `implement` refused, `epic_changed`, until the operator approves it again
  or asks for a new one;
- a run in flight, or a ticket with a branch or a PR, is never touched: its next run is told the changed ids once, as
  data. Nothing built is rewritten;
- a trivial member with no branch yet is approved again while the new plan still marks it trivial.

The operator hears once, an `epic.changed` event (§20) naming the reached members, and decides.

### Close-out

Once every member's PRs have merged, the operator may ask for one review over them together, for defects at the seams:
a review request (§21) reading every member's merged diff with the epic plan. Never automatic, and never posted: its
findings stay in canopy, on the epic.

### Guards in code

Membership, the epic plan's approval, and filing are the operator's alone (§4, principle 2); `policy.max_epic_tickets`
bounds the members, and a shared file may only lower it (T7); one plan run per epic, its attempts never reset; one
worker per ticket; `epic_changed` refuses an `implement` as `plan_changed` does (§25).

### Rejected

- The plan in the tracker's epic body: its text is data (T1), and a private ticket's plan would leak.
- One run that implements several members: one worker per ticket.
- Filing or approving without the operator: PRIOR_ART's incidents are where that was the default.
- A plan per tracker epic, found by the overseer: membership would then be the tracker's word.

### Open

- A member in two epics, when one asks for it.
