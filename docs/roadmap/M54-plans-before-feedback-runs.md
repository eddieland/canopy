# M54. Plans before feedback runs

REQUIREMENTS R21, DESIGN §7, §21, §25, and §32, TRUST_MODEL T1, T3, T7, and T8, D089. Needs M44, M53, and M56.
Asked for by the operator (2026-10-17): plan each `resume` before it runs, so that the operator accepts planned fixes
rather than first sorting the feedback into trusted and untrusted reviewers' (D089), and plan again as new feedback or
a new CI state reaches the PR before they accept. The design is DESIGN §32, beside M44's plans in §25.

- **The setting.** `policy.feedback_plan`, `"off"` or `"approve"`. Private, unlike `policy.plan`: it is stricter for a
  trusted reviewer's feedback, which waits for the operator, and looser for anyone else's, which starts a read-only
  plan run without their go-ahead, so a shared file must not choose it (T7). `"off"` is canopy as today.
- **What a feedback plan covers.** Under `approve`, every `resume` but `pushed_no_pr`'s waits on one. Feedback no longer
  splits by reviewer before a plan: each new item on the unit's PR (a review comment from anyone, canopy's review
  findings, a failed check, a conflict with the base, an authorized reply on the ticket) goes to the planner, with the
  PR's checks at its head. A failed check is an item because M56 makes fixing CI part of `resume`, so one plan, and one
  run, covers a round's comments and its red CI together. A round that is only red CI waits on its plan too, as the
  operator asked, trivial or not (M55's triage was removed, D126), unless its planner says it needs no review under
  `policy.planner_may_approve` (DESIGN §25). A worker's own comments and the replies the operator sent through canopy
  (M53) are not items. The plan shows each item's author, and whether they are trusted, so the operator weighs it;
  trust no longer decides what runs.
- **The planner.** M44's planner, definition, desk, prompt shape, and file, with the PR and its items in place of a
  ticket's first plan; it posts nothing and pushes nothing. Its plan is a markdown file the operator reads, edits, and
  comments on as M44's are, with one section per item, and its result line lists each item it covers by M53's thread or
  comment id with what it proposes: `change`, `decline`, `ask`, or `leave`, and for a change or a decline the reply it
  would draft. An id the reader did not return is refused, with a harness note on the run. A run kind of its own,
  with `policy.max_feedback_plan_attempts` per unit (default 6), raised with `canopy grant`, never reset (D030).
- **Approving is the go-ahead.** The operator approves the plan whole, or ticks the items to address, from the PR's
  page or `canopy plan`. Approval records the file's hash, as M44's does, and an operator message on the ticket naming
  the plan and the items to address and to leave, by number, never quoting them, as M32's `send` does: the plan's text
  stays data (T1), and the message is the instruction. The next tick dispatches the `resume` with the approved plan as
  `{{PLAN}}` and its items, refused `plan_changed` as M44's is. `untrusted_review` is not raised for an item a feedback
  plan covers; `plan_review` is, naming the PR. The cursor passes every item the approval named.
- **Re-planning.** A feedback plan records what it was written against: the PR's head, the newest item it covers, and
  each check's conclusion at that head, from M53's reader, which this milestone extends with M36's `check` line for
  one PR. While a plan waits, the reader reads its PR each tick, and the harness marks the plan `stale`, in code, when
  the head moved, an item arrived, or a check's conclusion changed. A stale plan is planned again once the PR has had
  no new item for `policy.feedback_quiet_minutes` (default 10), so a reviewer's ten comments in five minutes make one
  plan, not ten. The new plan carries the old one, the operator's edits and comments on it, and what changed; it
  supersedes the old one, and a plan run already running is not stopped. Approving a stale plan is refused `stale` the
  first time, naming what changed, and approving again after that approves it; feedback after an approval waits for
  the next plan.
- **In place on the PR.** The plan shows on M53's threads view: each thread carries the plan's proposal and its section,
  the checks the plan read sit above the diff, and a stale plan says what changed since. Once the `resume` runs, the
  same thread shows its draft reply (M53) under the proposal it carried out.
- **Code shared.** Nothing new to build twice: M44's planner, gate, approval by hash, plan editor, and margin comments;
  M53's reader, threads view, and diff with cards on its lines; M32's `send`, whose message is the approval's. Item
  ids are M53's, so a plan's items, a draft's thread, and an observed review comment are one id.
- **TRUST_MODEL**, in the PR that builds it: T1 (under `approve`, any reviewer's feedback starts a read-only plan run
  without the operator's go-ahead, and a worker acts only on items the operator approved; D089's gate becomes the
  approval on PRs a feedback plan covers); T3 (feedback plan attempts per unit, and the quiet period, in code, so a
  stream of comments from a bot spends a bounded number of plan runs); T7 (`policy.feedback_plan` is private); T8
  (approving a feedback plan, whole or by item, is among the web channel's writes, as `canopy plan --approve` is).
  D089 gains the revisit it implies: with feedback plans on, trust labels inform the operator rather than gate a run.
- Tests with the fakes: a trusted reviewer's comment under `approve` dispatches a feedback plan and no `resume`; an
  untrusted one does the same and raises no `untrusted_review`; an approval by item sends a `resume` with exactly those
  items; a new comment, a new head, and a changed check each mark a waiting plan `stale`; the quiet period holds a
  re-plan; approving a stale plan refused once; the attempt limit; `"off"` leaves every snapshot unchanged.
- **A plan that changes nothing.** A plan whose items are all `leave`, `decline`, or `ask` changes no code, so under
  M53's `approve` it needs no approval: its `resume` only drafts the replies, which wait on the operator anyway. Under
  `post` it needs approval as any plan does, since its replies would go out unseen.
- Settled by the operator (2026-10-17): the quiet period is 10 minutes by default, six feedback plans a unit, and the
  setting private.
- **Drafts start from the plan.** The `resume` that follows an approved plan starts each draft (M53) from the reply
  the plan proposed for its item, changing it only where the work departed from the plan, and the threads view marks
  what changed from the approved proposal, as the plan page marks what changed between plans (`plan-diff.ts`). The
  operator rereads only the departures (left to judgment by the operator, 2026-10-17).

Accept: written with the design, before work starts. Live, once built: on one of the loop's PRs, a coworker and a bot
each leave review comments; one feedback plan covers both; a new comment and a red check before the operator approves
make one new plan after the quiet period; the operator approves it with one item unticked; the `resume` that follows
addresses exactly the ticked items.

Status: in progress. Designed 2026-10-19 (DESIGN §32, Plans before feedback runs, beside §25's plans). The design
settles what the sketch left open: a blocker that merged is an item too, so every `resume` but `pushed_no_pr`'s has
items to plan; the PR's review items reach the planner as the `vcs` source observed them, with each check's conclusion
at the head, in a desk holding the unit's slot at that head, so a review item's id the source did not observe is
refused, and an item no plan covers goes to the next plan; `unplanned` and `plan_changed` refuse the `resume` in code,
and one approval goes ahead once, spent by the `resume` that starts; a reply on a waiting plan asks for changes, as on a
ticket's plan; a waiting plan makes the unit `plan_proposed`, and the state block says whether it is stale and its quiet
period has passed; and a re-plan inside the quiet period is refused in code. No round is triaged: M55, whose feedback
half that was, is deferred (2026-10-20). Open for the operator: whether a `resume` the operator's own
message asks for waits on a plan; whether `ask` asks the reviewer or the operator; how the planner reads a failed
check's log; whether a round's first plan waits out the quiet period; and whether the `resume` of a plan that changes
nothing is held to pushing nothing in code. Built 2026-10-20, against the fakes, the foundation: the private
`policy.feedback_plan` and `policy.max_feedback_plan_attempts` (6, per unit, granted with `canopy grant KEY
feedback-plan`, never reset); the `feedback-plan` run, the planner in a desk of the units' slots at the PR's head, with
its PRs read whole first and their items, less the operator's sent replies, workers' comments, resolved threads, and
items a spent plan covered, in the desk as data; its result's items checked, an id it was not given refused with a
harness note; migration 0053's `feedback_plans` and `feedback_plan_items`, with row types; `unplanned` and
`plan_changed` refusing a `resume` but `no_pr`'s alone, the plan spent by the `resume` that starts, which follows it in
place of the ticket's plan, its prompt naming the approved items by id; a new feedback plan refused while one waits
with no change asked, or its approval waits for its `resume`; `canopy plan KEY --approve` approving it whole; the state
block's `feedback_plan`, only under `approve` or once a ticket had a feedback plan run, and the overseer's rows for it;
and TRUST_MODEL T1, T3, and T7. Built 2026-10-20, against the fakes, planning again: migration 0076's snapshot of
what each plan saw (each PR's head, each check's conclusion there, and each item and reply it was given, by id with
its body's hash); staleness computed in code from it, with a reason per change (a moved head, a changed check, a new
item, a reply on a thread named as answering its item and marked when the PR's author or a trusted reviewer wrote it,
an edit to a covered item, a resolved covered thread), and the state block's `stale` and `quiet_passed`;
`policy.feedback_quiet_minutes` (10), from the newest item, reply, head, or check conclusion, a head or conclusion
timed from when canopy first saw it (migration 0076's `feedback_plan_moves`), a re-plan of a stale plan inside it
refused `quiet`, after it allowed, its desk carrying the old plan and a file of what changed; approving a stale plan
refused `stale` once, naming what changed; a thread one item, its other comments given beside it as replies; and the
next round what is new since the last plan's snapshot, with the items a failed `resume` handed back. Settled for it,
open to the operator: the PR's author is `observed_prs.author`, and the operator's own reply on GitHub counts as
feedback; any edit to a covered item makes its plan stale; an approved plan not yet spent is not planned again; a reply
on the ticket plans nothing again; and snapshots are kept with their plan. A changed check makes a plan stale from the
`vcs` connector's `check` lines, which canopy's own reader reports since it grew to the connector contract (M36). Built
2026-10-21, against the fakes, approval by item: `canopy plan KEY --approve --item N ...` approves only the items
named, by the number `canopy show KEY` lists each with, `--leave N ...` all but those, and `--message` adds the
operator's own words; migration 0077 marks each item left out and the approval's message. Every operator approval,
whole or by item, writes an operator message of its own on the ticket naming the plan and the items to address and to
leave, as `item 2 (id 502)`, never quoting them, with their words after; the planner's writes none. The `resume`'s
`{{PLAN}}` lists only the approved items, names those left out, and points at the newest such message; an item left
out goes to the next plan as an uncovered item does; and the overseer gives the `resume` that message's cursor.
`canopy show KEY` prints the current feedback plan, its file, and its items. Settled by the operator: an item is
named by its number on input, and by number and id wherever canopy mentions it; and an approval answers no question a
run asked, which still waits on a reply. Settled for it, open to the operator: an approved plan not yet spent may be
approved again for other items or with a message, which writes a new message; whole approval writes a message too; and
an item left out is not marked handled, so its next plan offers it whatever changed. Built 2026-10-22, against the
fakes, the plan on the PR's page: its threads carry the ticket's current feedback plan, where it stands (waiting, stale
with each change in the harness's words, approved, or spent), its file as text, and each item's proposal and reply on
its thread's card, an item on no thread listed with its reply; and the page approves it whole or by item, with the
operator's words, through `canopy plan --approve`'s function in channel `web`, refused as the CLI is, a write T8 now
names with its residual. Built 2026-10-22, against the fakes, failed checks and conflicts as items: each check failed at
a PR's head, but one its repository's `human_checks` names, and the PR's conflict with its base, are in the planner's
items file with an id canopy gives them, below zero, from a hash of the PR, the head, and the check's name or the base,
so it never meets an observed id and is the same on every read of that head; they are planned, numbered, approved or
left by item, named in `{{PLAN}}` and `canopy show` as reviews are, and on the PR's page as a check by its name or a
conflict, and an uncovered or left one goes to the next plan; migration 0092 widens `feedback_plan_items.item` and
records whether each PR conflicted, so a conflict that comes or goes at an unmoved head makes a waiting plan stale.
Settled for it, open to the operator: a check or a conflict carries no reply; a handled one stays handled until a push,
even if the check is run again and fails at the same head; a conflict while the host is still working out mergeability
is no change; and a merged blocker still reaches the planner as context. Left: drafts starting from the plan, the plan
that changes nothing, and a merged blocker as an item.
