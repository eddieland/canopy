# M67. Epic plans, shared by many tickets

REQUIREMENTS R28, DESIGN §10, §18, §22, §25, §36, TRUST_MODEL T1, T3, T7. Asked for by the operator (2026-11-02): a
ticket's plan (§25) works for one ticket, and work that spans several has no plan of its own, so each ticket's planner
settles the shared questions again and the operator approves them again. One plan for the whole, approved once, and a
simpler plan per ticket that points back to it. A sketch: the design, a section beside §25, comes before any code, and
PRIOR_ART "Shared plans across tickets" is what it starts from.

- **The epic.** canopy's own subject, like a task (§36), `epic:N`: the operator submits its goal in their own
  words, names its repositories, and adds or removes member tickets at any time, before or after its plan, each through
  their own channels alone and refused inside a tick or any run (T1). It may start with no members: the operator often
  plans it first and decides from the plan which tickets to file. A tracker's epic, parent, or sub-issue link is data:
  it never makes a ticket a member by itself, as the tracker skills already say of blockers and parents (§17). The
  operator may name a tracker epic on the epic: a ticket under it that is not a member is put to them as a suggestion
  (§14), which they confirm or dismiss with the membership command; a suggestion makes nothing a member.
- **Its plan.** A plan run as §25's: the planner, the desk at the repositories' bases, one file written, approved by the
  operator by hash, `proposed`, `approved`, `superseded`, in the state directory beside a ticket's plans and archived
  with them. Its outline is fixed, as a ticket's is: `Goal`; `Requirements`, each `R<n>` with an id that never changes,
  tracing to the operator's words; `Contracts` between the tickets, each what it is, who provides it, and who uses it;
  `Breakdown`, each proposed ticket a `B<n>` whose id never changes either, with the `R`s it covers, its repositories,
  and what it comes after; `Decisions`, as a ticket's plan writes them; `Out of scope`. It is shallow by
  rule: it does not write a ticket's steps, and it is bounded as a plan is.
- **Members from the breakdown.** The usual path is the operator's: they file the tickets themselves, when and as
  they choose, and register each later with the membership command, naming the `B`s it fulfils, one or more, or none
  for a ticket the breakdown did not foresee. Whatever they choose to file is theirs; canopy never requires a ticket
  per entry. The epic's status lists each entry with its member, or none yet, so the plan shows what is left to
  file. canopy filing them is an option, never the default: only when the operator asks, once the plan is approved, a
  run files the entries they name as a task's does (§36): unlabeled, in the project the epic names, ordered with
  the tracker's blocker relation (§10), each naming its epic and its `R`s in its body as data. canopy records
  them as members of their entries, checking only their text (D003); they authorize nothing until the operator labels
  or starts them (T1, D123).
- **A member's plan.** Its planner gets the epic plan's outline, a hash-checked copy, and the `B`s the member
  fulfils, as an `implement` gets its own plan (§25), and the plan's outline gains `## Epic`: the `R`s it covers,
  the contracts it provides and uses, and the siblings its `Out of scope` names; a member of no entry says which `R`s it
  takes on. The member's plan row records the hash of the epic plan it was written against. `policy.plan` is
  unchanged, save one case: a member whose every entry the `Breakdown` marks trivial, by M55's bar at the level
  `policy.planner_may_approve` sets, and never one touching security, credentials, destructive data changes, or
  migrations, skips its own plan. The operator's approval of the epic plan approves it, and its `implement`
  follows the epic plan's copy directly.
- **When the epic plan changes.** A re-approval keeps the ids. A member's plan still `proposed` is marked stale,
  naming the ids that changed, and planned again; an approved one whose ticket has no branch yet has its `implement`
  refused, `epic_changed`, until the operator approves it again or asks for a re-plan; a run in flight, or a
  ticket with a PR, is never paused or touched: its next run is told which ids changed, as data, and keeps to its own
  approved plan. A member whose entry the new plan removed stays a member, of no entry, until the operator removes it or
  registers it again. The operator hears once, an `epic.changed` event (§20) naming the members each way, and
  decides. Nothing built is rewritten.
- **Upward.** A member's planner whose `Decisions` depart from a contract or a requirement says so in its result, and
  the harness raises `epic_drift` (§14) naming the member, for the operator to amend the epic or the plan.
- **Close-out.** Once every member's PRs merged, the operator may ask one review over them together, for defects at the
  seams no PR's review saw, as a review request (§21). Never automatic.
- **Guards in code** (§4): membership and both approvals operator-only; `policy.max_epic_tickets` bounds the
  members; one plan run per epic at a time, attempts never reset (D030); still one worker per ticket (§6).
- **Rejected:** the plan in the tracker's epic body (its text is data, T1; a private ticket's plan would leak; Copilot
  and Linear freeze a copy at dispatch); inlining the plan's text into each member's plan (copies go stale: Hermes,
  Taskmaster, BMAD v6); one run that implements several members (one worker per ticket, and agent-orchestrator removed
  its decomposition for the PRs it fragmented); filing or approving without the operator (the incidents in PRIOR_ART
  are where that was the default); a plan per tracker epic found by the overseer (membership would then be the
  tracker's word).
- **Settled by the operator** (2026-11-02): a member in flight is not paused when the epic changes, only told;
  the planner writes the epic plan, the operator approving or asking for changes as with a ticket's; a tracker's
  epic may suggest members for the operator to confirm; a member skips its own plan only when it is trivial; the
  epic is often planned before its tickets exist, to decide which to file, so the operator filing them and
  registering each later against its entry is the usual path, and canopy filing them an option. Named an epic
  (2026-11-03), first an initiative; the tracker's is a tracker epic.
- **Tests with the fakes**, once designed: an epic planned with no members and approved; a ticket filed outside
  canopy registered later against its entry, and one against none; the status listing the entries still without a
  member; the breakdown filed on request and recorded; a member's planner given the outline and copy, its plan carrying
  the hash; a changed epic marking a proposed member stale, refusing an approved one's `implement`, and leaving a
  running one alone but told; drift raised; a tracker epic's ticket suggested and a member only once confirmed; a trivial
  member implemented without a plan of its own, and one touching a migration planned; membership and approval refused
  inside a run; the bound; `test_prompt_sizes.py` for the prompts, `core/test_db.py` and `test_records.py` for the rows.

Accept: live, on the operator's workspace, one epic of three tickets, planned before any of them existed and at
least one filed by the operator and registered after its plan was approved: its plan approved once, each member's plan
citing its `R`s and the contracts, the first member's PR providing a contract the second's uses, and a change to the
epic plan after the first merged leaving it alone, marking the second's proposed plan stale, and telling the
operator once.

Status: in progress. Sketched 2026-11-02 from the survey in PRIOR_ART, and the open points settled by the operator
the same day; designed in §43, before any code; what is built is named at the top of §43. Built 2026-11-06, when the
epic plan changes: its approval meets each member the change reaches where it stands, in the approval's transaction
under the dispatch lock: a plan still `proposed` is superseded, marked with the ids that reached it; an approved plan's
`implement` on a ticket with no branch is refused, `epic_changed`, until the operator approves the plan again or asks
for a new one; a run in flight or a branch is left alone; each keeps the ids as a notice its next plan run is told
once, and `canopy show epic:N` lists; and the operator hears once, `epic.changed` in the `runs` group, and in the
approval's output. Chosen conservatively, for the operator to change: a member is told only the ids that reached it,
and one of no entry every id; a member with no plan, run, branch, or notice is not reached, nothing of it being written
against the older plan; a plan run at work when the plan changes lands its plan `proposed`, unmarked, its notice
holding the `implement` until the operator approves a plan of it, a planner's approval not enough; a notice is spent
when the plan run told it starts, whether or not it writes a plan; and no event when no member was reached. Built
2026-11-09: a member's `implement` and `resume` read the epic's approved plan as its planner does, from a copy checked
against the approved hash where the worker starts, ignored by git, removed with the plan's copy before the slot goes
back, and named in a harness note if pushed; their prompts name the entries the ticket fulfils and say to keep to the
contracts it provides and uses; and the next of them takes the member's pending notice, told once that work done and
its own approved plan stand. Chosen conservatively, for the operator to change: the copy is read as the run starts,
as the planner's is, so a member removed between the dispatch and the start gets none though its prompt named it; and
a worker override without `{{EPIC}}` is refused for a member, as a planner's is. Built 2026-11-09, a trivial member:
one whose every registered entry the approved epic plan marks trivial needs no plan of its own under `policy.plan`, so
its `implement` follows the epic's copy alone, read from the plan as approved now, which is the re-approval too: a plan
that still marks it keeps it so, one that drops the mark makes it wait on its own plan. The guard, the state block's
`plan.needed`, the harness's `attempt_limit`, `canopy show`, and the plan's page read it in one place
(`epics.plan_needed`). Chosen conservatively, for the operator to change: with `planner_may_approve` off no mark
counts, whatever a plan says; a member registered against an entry the plan dropped is not trivial; and a plan of its
own written before the mark is left as it is. Left for this bullet: the web UI's approval naming the members reached.
Built 2026-11-06, upward: a member's planner names in its result's `drift` the ids of the epic plan it departs from,
held to that plan's requirements and contracts, recorded with its plan, and the harness raises `epic_drift` on the
member while that plan waits, ending as §43 says, a reply to the epic after the plan being its ask for a new epic plan,
or once the ticket is done or stopped. Chosen conservatively, for the operator to change: the item also ends when the
ticket leaves the epic, and a plan with drift is never approved on its planner's word.
