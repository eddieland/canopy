# Epics

Part of the canopy design, normative like all of it: one plan for work that spans several tickets, approved once, and a
plan per ticket that points back to it. Sections are numbered across the whole design; the [README](README.md) has the
map. Previous: [The operator's checklist](CHECKLIST.md). Next: [Messages to running agents](MESSAGES.md).

## 43. Epics

Being built (REQUIREMENTS R28, ROADMAP M67). Built: the epic, its members, and their bound, from the CLI; its plan runs,
which record a plan `proposed`; its approval, replies, and members registered against its entries; a member's planner,
which reads the epic's approved plan, its plan recording which, and names where it departs from it, raised as
`epic_drift`; stopping it, from the CLI and the web UI; its plan waiting on the operator, on the attention list; and a
re-approval meeting each member it reaches where it stands and telling the operator once, the changed ids told to a
member's next plan run, not yet to its `implement` or `resume`.

§25 plans one ticket. Work that spans several has no plan of its own, so each ticket's planner settles the shared
questions again and the operator approves them again. An **epic** is that work as canopy's own subject: the
operator's goal, its plan, approved once, and its member tickets, each planned against it. It starts from PRIOR_ART's
"Shared plans across tickets": a shallow plan for the whole with ids that never change, a thin entry per ticket pointing
back to it, and each ticket's own plan written just before it is built. The word is canopy's: the tracker's epic is
always a **tracker epic**, and is never one of canopy's by itself.

### The epic and its members

The operator submits an epic's goal in their own words, naming its repositories and, if canopy is to file its
tickets, the tracker project; `epic:N` names it afterwards (D075). Like a task (§36), it is private, its conversation
never touches the tracker, and it never reaches the overseer, which neither sees its text nor decides whether it is
planned. The submission authorizes its plan runs, and its text is the operator's instruction; replies, approvals,
stopping it, and adding or removing a member take the same channels, each refused inside a tick or any run (TRUST_MODEL
T1).

A **member** is a ticket the operator added, or one a filing run filed for it (below), at any time, before its plan or
after; an epic may have none, since the operator often plans the whole first and decides from its plan which
tickets to file. A ticket is a member of at most one epic, and at most `policy.max_epic_tickets` are members
of one. Membership authorizes nothing: a member is worked only once a label or a start says so (§7, D123), and it is
then a ticket like any other, one worker at a time (§6). A tracker's epic, parent, or sub-issue link is data and never
makes a ticket a member, as the tracker skills say of blockers and parents (§17). The operator may name a tracker epic on
an epic: the tracker source then reads its children (§30), and each that is not a member is a suggestion,
`epic_suggestion` (§14), until the operator adds it or removes it, which dismisses it. A suggestion makes nothing
a member.

### Its plan

A plan run as §25's: the planner, in a desk at the epic's repositories' bases (§18), writes one file, recorded
`proposed` in the state directory beside tickets' plans and archived with them; the operator approves it by hash, as its
file stands, or replies to ask for changes, and a new plan supersedes the old. The tick starts it in code, before the
overseer, as it starts a task: once after the submission, and once after each reply newer than its newest plan. One plan
run per epic at a time, within `capacity.max_workers`, its attempts counted against `policy.max_plan_attempts` and
never reset (D030). No agent approves an epic's plan: `policy.planner_may_approve` does not reach it. A plan waiting on
the operator, while no plan run of its epic works, is an attention item, `plan_review` on `epic:N`, as a ticket's is
(§25), naming the epic and never its text; its approval, a reply, until the next plan, or a stop ends it. A stop ends
only an epic's planning: no tick starts a plan run of it again and a reply to it is refused, while its plan may still
be approved and its members changed.

Its outline is fixed: `Goal`; `Requirements`, each `R<n>` tracing to the operator's words; `Contracts` between the
tickets, each `C<n>` with what it is, who provides it, and who uses it; `Breakdown`, each entry `B<n>` with the `R`s it
covers, the contracts it provides and uses, its repositories, and what it comes after; `Decisions`, as §25's; `Out of
scope`. It is shallow by rule: it writes no ticket's steps, and it is bounded as a plan is. The ids and the breakdown
are the one part of a plan canopy reads, from the file as the operator approved it, in the shape the outline fixes: a
plan whose ids repeat or will not parse is `unknown`, and an edit that breaks them or reuses a removed id cannot be
approved. They are data, used only to compare one approval with the next and to route entries to members; the plan's
text is never an instruction to the harness (T1).

### Members from the breakdown

The usual path is the operator's: they file the tickets themselves, when and as they choose, and register each with the
membership command against the entries it fulfils, one or more, or none for a ticket the breakdown did not foresee. An
entry names the approved plan's id, and a registration that names one it does not hold is refused. Registering a member
again replaces its entries; what reaches it, and whether it is trivial, follow from its entries and the plan approved
now. canopy never asks for a ticket per entry: the epic's status lists each entry with its members, or none yet,
so the plan shows what is left to file.

Filing them is an option, never the default. Only when the operator asks, once the plan is approved, a filing run files
the entries they name, as a task files tickets (§36): the private worker (§22), whose create tool alone writes to the
tracker, files each unlabeled in the epic's project, sets the tracker's blocker relation between them by their
`after` (§10), and names in each body the epic and the `R`s it covers, as data. It writes no code and pushes
nothing. canopy records each key its result pairs with a named entry as a member of it, checking only the key's text
against the project, the entry, and the bound, and that it is no epic's member yet (D003); any other raises
`epic_ticket_unrecorded` (§14) until the operator replies to the epic. A filed ticket authorizes nothing
until the operator labels or starts it (T1, D123).

### A member's plan

`policy.plan` decides whether a member is planned, as for any ticket, save one case below. A member's planner gets the
epic plan's outline, a copy of it checked against its approved hash, and the entries the member fulfils, as an
`implement` gets its own plan (§25), never its text inlined, so a member's plan cannot hold a copy gone stale. The
member's plan gains `## Epic`: the `R`s it covers, the contracts it provides and uses, and the siblings its `Out
of scope` names; a member of no entry says which `R`s it takes on. Its row records the hash of the epic plan it
was written against, and its `implement` and `resume` get the same copy beside their own plan.

**A trivial member.** A member whose every entry the epic plan marks trivial, with a reason, by §25's bar at the
level `policy.planner_may_approve` sets, skips its own plan; a member of no entry is never trivial, and at no level is
one touching security, credentials, destructive data changes, or migrations trivial, and with the key off no entry is.
The operator's approval of the epic plan, which they read with the mark, approves it, and its `implement` follows
the epic plan's copy directly. A member whose own setting asks for a plan (§25) is planned, whatever the mark.

**Upward.** A member's planner whose `Decisions` depart from a contract or a requirement names those ids in its result
line, and the harness raises `epic_drift` (§14) naming the member and the ids, those the epic plan holds. Such a plan
waits on the operator, whatever `policy.planner_may_approve` says. The operator settles it one of
three ways, and each ends the item: approving the epic plan again, amended to the member's choice; approving the
member's plan as written, which accepts the departure for that member alone; or asking for a new plan of either.

### When its plan changes

A re-approval compares the ids with the plan approved before it: an id added, removed, or whose text changed is changed,
and a member is reached when one of its entries changed or covers, provides, or uses a changed id. A member of no entry
is reached by every change, since canopy cannot tell which ids it relies on. A member whose entry the new plan removed
stays a member, of no entry, until the operator removes it or registers it again. For each reached member, by where it
stands:

- a plan still `proposed` is superseded as stale, naming the changed ids, and the next `plan` is told them;
- an approved plan whose ticket has no branch yet has its `implement` refused, `epic_changed`, until the operator
  approves the plan again, against the new epic plan, or asks for a new one;
- a run in flight, or a ticket with a branch or a PR, is never paused or touched: its next run is told the changed ids,
  as data, once, and keeps to its own approved plan. Nothing built is rewritten.
- a trivial member with no branch yet has no plan of its own: the re-approval that reached it approves it again while
  the new plan still marks it trivial, the operator having read the change, and otherwise leaves it to be planned.

The operator hears once, an `epic.changed` event (§20) in the `runs` group, naming the reached members each way,
and decides.

### Close-out

Once every member's PRs have merged, the operator may ask for one review over them together, for defects at the seams no
PR's review saw, as a review request (§21) whose reviewer reads the merged diffs of every member with the epic
plan's copy. Never automatic, and never posted: each PR has merged, so its findings stay in canopy, on the epic.

### Guards in code

§4, principle 2: membership, the epic plan's approval, and filing are the operator's alone; a member's plan is
approved as §25 says; `policy.max_epic_tickets` bounds the members; one plan run per epic at a time, its
attempts never reset; still one worker per ticket. `epic_changed` refuses an `implement` as above, as
`plan_changed` does (§25).

### Trust model changes

TRUST_MODEL gains them as each is built: T1 (an epic's text, replies, membership, approval, and filing are the
operator's, written only through the operator's channels; its plan, a filing run's keys, a member's drift, and a
tracker epic's children are data, and a suggestion makes nothing a member), T3 (one plan run per epic, attempts never reset,
`policy.max_epic_tickets`), and T7 (`policy.max_epic_tickets` a shared file may only lower).

### Rejected

- The plan in the tracker's epic body: its text is data (T1), a private ticket's plan would leak, and Copilot and Linear
  freeze a copy at dispatch.
- The plan's text inlined into each member's plan: copies go stale (Hermes, Taskmaster, BMAD v6).
- One run that implements several members: one worker per ticket, and agent-orchestrator removed its decomposition for
  the PRs it fragmented.
- Filing or approving without the operator: PRIOR_ART's incidents are where that was the default.
- A plan per tracker epic, found by the overseer: membership would then be the tracker's word.
- Pausing a member in flight when the plan changes (Factory Missions): it is told, and the operator decides.

### Open

- A member in two epics, when one asks for it.
