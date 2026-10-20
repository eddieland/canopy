# Feedback plans

Part of the canopy design, normative like all of it: a plan for what comes back to a PR, approved by the operator
before the `resume` that acts on it. Sections are numbered across the whole design; the [README](README.md) has the
map. Previous: [Personas](PERSONAS.md). Next: [A clock for running agents](CLOCK.md).

## 32. Plans before feedback runs

Designed, not built (REQUIREMENTS R21, ROADMAP M54).

§7, §8, §21, and §29 describe what comes back to a PR without feedback plans; this section says what they change. A
**feedback plan** is §25's plan written for one unit's PR rather than a ticket's first work, so a `resume` starts from
fixes the operator accepted, rather than from feedback the operator first sorted by whose it is (D089). The operator
reads one plan of the round, sees whose each item is, and approves what to address; the go-ahead is that approval,
checked in code, rather than the reviewer's name, checked by the overseer and the worker.

### The setting

`policy.feedback_plan` is `"off"`, which changes nothing, or `"approve"`. It is private (§12, TRUST_MODEL T7),
unlike `policy.plan`: it is stricter for a trusted reviewer's feedback, which then waits for the operator, and looser
for anyone else's, which starts a plan run that reads only, without the operator's go-ahead. The quiet period before
a plan is written again (Planning again) is `policy.feedback_quiet_minutes`.

### What a plan covers

Under `approve`, every `resume` but one whose only reason is `no_pr` (§8) waits on an approved feedback plan. An
**item** is each new thing on the unit's PR that a `resume` would handle: a review or review comment from anyone,
canopy's review findings (§21), a failed check, a conflict with the base, a blocker that merged (§10), and an
authorized reply on the ticket. Fixing CI is part of `resume` (§8), so one plan, and one run, covers a round's
comments and its red CI together, and a round of red CI alone waits on its plan too. A worker's comments and the
replies the operator sent through canopy (§29) are not items. A review item's id is the one the `vcs` source observed
(§29, §30), so a plan's item, a draft's thread, and an observed comment share it.

Feedback no longer splits by reviewer: the plan shows each item's author and whether `trust.trusted_reviewers` lists
them, so the operator weighs it, and `untrusted_review` is not raised for an item a feedback plan covers.

### The planner

A feedback plan is a run kind of its own, run as §25's are, within capacity: the same definition, a desk with the
unit's slot at the PR's head, and one file written, its plan. It posts nothing and pushes nothing. Its prompt carries
the PR's review items as the `vcs` source observed them and each check's conclusion at the head, all data to it (T1),
and it reads the ticket as §25's planner does. Its plan has a section for each item, and its result line adds to §25's
the items it covers, each by id with what it proposes, `change`, `decline`, `ask`, or `leave`, and for a change or a
decline the reply it would draft (§29). A review item's id the source did not observe is refused, with a harness note
on the run; an item no plan covers stays unhandled and goes to the next plan. Feedback plan runs are limited per unit,
never reset (D030), and raised only by the operator's grant.

### Approving

The operator approves the newest plan whole, or ticks the items to address, from the PR's page or `canopy plan`; only
the operator's channels do, each refused inside any agent run, the web channel's behind its token (T8). As in §25,
approval records the file's hash, and a reply newer than a waiting plan asks for changes. It also writes an operator
message on the ticket naming the plan and the items to address and to leave, by number, never quoting them, as sending
findings does (§21): the plan's text stays data, and the message is the instruction (T1).

The next tick dispatches the `resume` with the approved plan, which its worker follows as in §25, and the ticked
items. Two guards hold it in code: `unplanned` refuses a `resume` under `approve` that carries no approved feedback
plan, unless its only reason is `no_pr`, and `plan_changed` refuses one whose plan's file changed since approval. An
approval goes ahead once: the `resume` that starts spends it, and the items it named are handled then, as a cursor's
are (§7). Feedback that arrives after an approval waits for the next plan.

**A plan that changes nothing.** A plan whose items are all `decline`, `ask`, or `leave` changes no code. Under
`trust.review_replies = "approve"` (§29) it needs no approval, and `unplanned` lets its `resume` through: that run
only drafts the replies, which wait on the operator anyway. Under `post` it is approved as any plan is, since its
replies would go out unseen.

### Planning again

A feedback plan records what it was written against: the PR's head, the newest item it covers, and each check's
conclusion at that head. While it waits, the harness marks it stale, in code, when what the connectors observe (§30)
shows the head moved, an item arrived, or a check's conclusion changed. A stale plan is planned again once the PR has
had no new item for `policy.feedback_quiet_minutes`, and a re-plan inside that quiet period is refused in code, so a
reviewer's burst of comments makes one new plan, not one each, and a bot's stream of them spends a bounded number of
plan runs (T3). The new plan carries the old one, the operator's edits and comments on it, and what changed, and
supersedes it; a plan run already running is not stopped. Approving a stale plan is refused `stale` the first time,
naming what changed; approving it again approves it, and what changed waits for the next plan.

### The overseer's part

In §7's table, under `approve`, each phase whose next action is a `resume`, but `pushed_no_pr`, whose `resume` has the
reason `no_pr`, dispatches a feedback plan first, and the `resume` once it is approved. While the unit's plan waits it
is `plan_proposed`, with `plan_review` naming its PR (§14). The state block gives each unit's plan status, attempts, and
facts the harness computes, whether it is stale and whether its quiet period has passed, so the overseer compares no
times; never the plan's text.

### On the PR, and the drafts after

The operator reads the plan on the PR's page, each thread with the plan's proposal for it (§29), and a stale plan says
what changed. The `resume` that follows starts each draft from the reply the plan proposed for its item, changing it
only where the work departed from the plan, and the thread marks those changes, so the operator rereads only them.

### Open

- Whether a `resume` the operator's own message asks for, with no plan waiting, waits on a plan too, its message an
  item, or goes ahead as their word does without feedback plans.
- Whether `ask` puts a question to the reviewer, drafted as a reply, or to the operator, answered before approving.
- How the planner reads a failed check's log: the `vcs` source observes no logs (§30), and the planner reads only its
  desk and the tracker.
- Whether a round's first plan waits out the quiet period, as a re-plan does.
- Whether the `resume` of a plan that changes nothing is held in code to pushing nothing; only its prompt says so.
