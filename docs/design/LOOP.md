# The loop

Part of the canopy design, normative like all of it: the tick, ticket phases, dispatch and the worker contract, slot
release, and stacking. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[canopy design](README.md). Next: [Operating canopy](OPERATING.md).

- [6. Tick](#6-tick)
- [7. Ticket phases and next actions](#7-ticket-phases-and-next-actions)
- [8. Dispatch and the worker contract](#8-dispatch-and-the-worker-contract)
- [9. Aggressive release](#9-aggressive-release)
- [10. Dependencies and stacking](#10-dependencies-and-stacking)

## 6. Tick

`canopy loop` (below) runs ticks one after another; `canopy tick` runs one, by hand or from a scheduler. A tick does,
in order:

1. Acquire the lock. If held, log and exit 0, recording no tick.
2. Apply pending migrations, close any tick still running as abandoned (holding the lock proves its process is gone),
   with each run it recorded and did not start (§40), and record the tick with the canopy version running it. Its id
   tags all logs. Migrations wait while any detached run's own process is alive, since it writes the old schema; a
   journal with migrations this canopy does not know is refused (D068).
3. **Reconcile local state.** A run of any kind whose own process is gone is marked `crashed`, what is left of its
   agent killed, and its slots returned. A slot leased under canopy's prefix with no live run is returned, in every
   pool (§18). Memory proposals expire (§28). A live tick starts the operator's queued tasks (§36). Each source that
   reads runs its connector once, and what it read whole replaces what the journal held; a source that fails changes
   nothing and the tick goes on (§30). Drafts are checked against what the `vcs` run read (§29). Capacity is
   `max_workers` less the running runs, review runs, and task runs. If the pool cannot be read or a return fails, the
   tick fails and the overseer does not run. The tick records the newest journal message it could read, which marks
   what was acknowledged (§22) and what idle pacing compares against, and records the harness's own attention items
   (§14).
4. **Render the state block**, the overseer's whole message: one JSON object holding what the overseer needs to decide
   every ticket left to it (§37), ordered from what changes rarely to what changes every tick so the provider can
   cache it. After its fixed sections come the observations (§30): what the connectors last read of each ticket and
   its units, each fresh, stale, or unobserved. The overseer's prompt is its agent definition's system prompt (§13),
   not part of the block. The block lists the overseer's own open attention items with what each names, not their
   detail, which may quote a comment, so none is recorded twice (§37).
5. **Check the disk and the overseer's tools, then run the overseer.** If the state directory's or the workspace's
   filesystem has less than `loop.min_free_disk_mib` free, the tick records `attention:disk_low` and closes
   `disk_low`: the overseer and the runs it would start are what fill a disk, and a full one can kill the loop
   mid-write. Reconcile has run, so what frees space still does. If the server of the overseer's tools (§27), started
   as the runtime would start it, does not answer `initialize`, the tick records `attention:canopy_unavailable` and
   closes `canopy_unavailable` without running an overseer that could record nothing (MEASUREMENTS 2026-10-12). If the
   runtime does not list the overseer's chosen model, or its list cannot be read (§13), the tick records the item and
   closes `model_missing` or `model_list_failed` the same way, never running it on another model. A tick, the
   operator's too, whose block leaves the overseer nothing, no ticket, due chore with a `when` (§37), or review to start
   or wait on (§21), runs none: it checks the disk, since the harness's dispatches fill one too, skips the other two
   checks, owes no duty, makes the harness's dispatches, and closes `ok` with the attention list as it stands (§37).

   Then run `overseer_cmd` in the workspace root (§18), with `CANOPY_TICK_ID` set and its tools named in its environment
   alone (§27); they refuse unless it names a running tick (D020). Its output goes to a log only the operator can read,
   never to the journal, but for what a run's events give its row (§8): its session, its spend, and its latest tool
   call, which `canopy status` and the tick's page show while it runs. It succeeded if it exited 0 and a line of its
   final message (§13) is exactly `CANOPY_TICK_DONE`, which catches a run that exits 0 short of the last step; otherwise
   the tick closes `overseer_failed`. Every decision is about a ticket: with no server to read (§13), it has no outage
   to skip over.

   Once its run ends, whatever it ended as, the tick starts every run it asked for, each recorded at the ask and none
   in its process tree, with the harness's own, in §7's order, each under its guards again (§8, §40). One the tick
   does not start is closed unstarted as it closes.

   **The overseer's duties.** A successful run is then checked for what a tick owes: a decision for every ticket in
   the block and every ticket the query returned (§7), except those stopped, recently done, or decided by the harness
   (§37); and a run, wait, or refusal for every chore due. A duty left undone closes the tick `overseer_failed`, naming
   each, so the attention list stands; its dispatches still start. Why: the prompt alone did not hold a cheaper
   overseer to the procedure (MEASUREMENTS 2026-10-15). The check sees that a duty was done, not that it was done well.

   In a dry run (D036), dispatch checks the live guards (§8) and starts nothing, no cursor advances, and nothing is
   marked done. What the overseer writes is rendered into a later prompt, so its tools validate its keys, verbs,
   reasons, phases (§7), and cursor ids, and bounds its free text.
6. Close the tick with a summary.
7. **Publish attention** (§14): rewrite `attention.md` from the journal, then deliver to each notification sink (§20)
   what changed since it last heard. This follows the close because the list is the latest `ok` tick's. A failure here
   does not change the tick's status. Release the lock.

Workers outlive the tick, as detached processes owned by `canopy _run`. A detached process (a run, chore, or review,
or the daemon) is alive exactly while it holds its lifelock, which nothing it starts inherits; a pid could be reused.
Every kind of detached run shares this lifecycle and crash rule; a new kind joins that set.

### The loop

`canopy loop` is how ticks are meant to run (D042), in the foreground until stopped:

1. Take the loop lock; a second loop refuses. Each tick still takes the tick lock (step 1 above).
2. Apply pending migrations and start the web UI's server (§22).
3. Run a tick exactly as `canopy tick` does. An error the tick does not handle is logged, and the loop goes on.
4. Print what the tick did and what the overseer cost (§13).
5. Wait the configured interval, lengthened after idle ticks and ended at a gate (Idle pacing, below). An operator
   message (§22), a run ending, or a poll that sees something new (below) ends the wait early, but never sooner than
   `loop.min_gap_minutes` after the tick ended, which bounds how often the overseer runs. The operator can end the
   wait by hand. During the wait the loop polls the connectors (Ticks and polls, below).
6. Repeat from 3 until the operator stops the loop or a set number of ticks has run.

Pausing holds the loop's ticks while the web UI and workers go on. The pause is a journal fact (§11) that outlives the
loop; paused, the wait never ends by itself, and a tick the operator asks for still runs, as does a hand-run
`canopy tick`. Pausing, resuming, and starting or stopping the daemon refuse inside canopy's own ticks and runs, so no
agent can hold off later ticks or undo the operator's pause (TRUST_MODEL T1).

Stopping the loop never stops a run, which is detached (§8); `canopy stop` does, per ticket. A reload rereads the
config files (§12) for the next tick, and a config that does not load leaves the old one in place. Rejected: rereading
before every tick (a half-saved edit would apply itself). Prompt files are read every tick.

The daemon runs the same loop in its own session, so it outlives the terminal; nothing installs it with the OS or
restarts it (D042). Stopping it refuses while runs are running, since a canopy that changes the journal does not start
under them; told to wait, it ticks no more and stops once they end.

### Ticks and polls

A tick is the overseer's turn and costs a model run; a poll only runs the connectors (§30), at no model's cost. So
during each wait the loop runs every source every `connect.every_minutes` after the last read, a tick's or a poll's,
whatever `loop.interval_minutes` and `loop.min_gap_minutes` are. A poll takes the tick lock, and is skipped, not waited
for, while a tick holds it; none runs while the loop is paused. It records its runs with no tick and checks the drafts
its `vcs` run read (§29). It raises no attention item, since the list is a tick's and the next tick runs every source
again before recording its items.

A poll that read every source whole ends the wait when a tick would now record or list what the latest tick, as it
ended, did not: a decision, or a ticket, a row on one, an item past a cursor (§7), a due chore, or a PR the review query
found (§21) listed to the overseer. That is compared by what is decided and listed, never by wording, so reading again
what that tick saw, or an edit to an item it saw, wakes nothing. A poll that reads less than it was asked ends the wait
once, so the tick runs the sources again and raises `connector_failed` if they still fail (§30); the polls after it wake
nothing, since what they would compare may rest on what was not read, until one reads every source whole. The tick
records the poll as what woke it. Rejected: a tick on every poll, which writes a tick's rows to learn what one
comparison answers. A reply a `slack` source records is the operator's message, not an observation, and ends the wait as
any does (§20). A hand-run `canopy tick` runs the sources as any tick does, and nothing polls without the loop.

### Idle pacing

A tick that finds nothing new costs a full overseer run and buys nothing. So the loop waits longer after each idle tick
in a row, and wakes early on what the polls see. It does not poll GitHub or the tracker from Python (D003), run a
cheaper pre-check agent or a probe that fingerprints the world, or take webhooks (TRUST_MODEL T8).

A tick is **idle** when it closed `ok`, dispatched nothing (a dry run paces as a live one would), and nothing reached
the journal after the previous tick read it (step 3): no run started or ended, no poll ended the wait, and the
operator did nothing. Rejected: idle as a tick that changed nothing, since records that repeat on unchanging state kept
any tick from counting (MEASUREMENTS 2026-10-14).

After each idle tick in a row that ran the overseer the wait doubles, up to `loop.idle_max_minutes` and never below the
base wait; one that ran none cost nothing and leaves the count as it was. The timer is the overseer's second look at
what it was left and waited on, since the polls see the rest; its runs on a quiet queue then come cold (§40). Whatever
pacing chose, the wait ends at the earliest harness gate ahead: the CI cooldown's end (§8), a chore coming due (§19), a
PR head settling (§21), or a notice lapsing (§8); a gate already open sets no deadline, so it cannot make the loop
spin. A run ending ends the wait, so a long wait never sits on canopy's own work, and the world, such as CI going red,
is seen within a poll. Each tick records whether it was idle and what ended the wait before it, for spend (§11).

## 7. Ticket phases and next actions

The overseer derives phases each tick from the observations (§30) alone: a subject they leave stale, or that no source
reads, is the harness's `wait` (§37). They are recorded for the status view, never read back as truth. The PR phases,
`pushed_no_pr` to `merged`, are a unit's (§18).

A ticket's title, its display name in canopy, is one short line the overseer sets. It is model-written, so it stays out
of `attention.md` and the `text` format, and the Slack sink escapes it (§20).

| Phase | Derived from | Next action |
|---|---|---|
| `ready` | one of `tracker.labels` present, not closed, no run active, no branch, no open blocker | dispatch `implement`, or `plan` when the ticket needs one and has none (§25) |
| `plan_proposed` | the ticket's newest plan waits on the operator (§25) | attention `plan_review`; dispatch `plan` again after an operator message |
| `blocked` | as `ready`, but a blocker ticket is open | dispatch `implement` stacked on the blocker's branch if its PR is open and green (§10), else wait |
| `running` | active `runs` row | wait |
| `pushed_no_pr` | branch exists, no PR | dispatch `resume` with instruction to open the PR |
| `conflicted` | PR open, GitHub reports it conflicts with its base | dispatch `resume` to bring the base in |
| `ci_running` | PR open, checks pending, and no trusted feedback that waited out its time on them (below) | wait |
| `ci_red` | PR open, checks failed, newer than cursor | dispatch `resume` for `ci`, with anything else the unit has (§8, One resume for what comes back to a PR); at the attempt limit, attention; in cooldown, wait; held for a notice, wait (§8); left by a worker as flaky, attention, or wait if the harness kicked it (§23) |
| `review_pending` | with `review.agent_prs`: checks pass, no approval, head commit not reviewed (§21) | review it |
| `review_findings` | with `review.agent_prs` and `canopy:review` trusted: findings on the head's review, newer than the cursor | as comments (§7) |
| `changes_requested` | a trusted reviewer's comments or requested changes newer than cursor | dispatch `resume` with the comments; if the overseer judges a comment needs a human (design pushback, scope), attention instead |
| `untrusted_review` | review feedback newer than cursor from a reviewer not in `trust.trusted_reviewers`, with no operator message about it | attention: the operator says what to do with `canopy reply` (below) |
| `green_unreviewed` | checks pass, no approval | attention: needs a reviewer |
| `approved` | approved, not merged | attention: ready to merge |
| `merged` | every unit's PR merged, and no other repository left to change (§18) | mark ticket `done` in the journal; humans handle the tracker transition |
| `needs_human` | `needs_human_label` present, no authorized reply newer than it | wait |
| `human_replied` | authorized reply newer than the label, or an operator message newer than the message cursor | dispatch `resume` pointing at the reply; the worker removes the label |

The attention these rows name, but `needs_author`'s and `flaky_rerun`'s, which are judgment, is the harness's, raised
from its cause (§14); the overseer records `wait` there.

A PR's checks are its head commit's check runs and commit statuses. GitHub runs no checks on a PR that conflicts with
its base, so `conflicted` comes before every CI and review phase; the `resume` attempt limit bounds its repeats (D030).
Trusted feedback waits on pending checks, so one `resume` can carry a red build with it, but only
`policy.feedback_ci_wait_minutes` from when a source first observed it: a queue of builds would otherwise hold it as long
as the queue lasts. Past that the unit is not `ci_running`, and the poll that finds it so ends the loop's wait (§39).

**Order.** Dispatches take capacity in this order, whoever decides them (§37): a review the operator requested; a human
waiting (`human_replied`, `changes_requested`, `review_findings`); `conflicted` and `ci_red`; `pushed_no_pr`; the
loop's own and the query's reviews; then `ready`, a blocker before what it blocks. Work in flight comes before new work,
and a person waiting before a machine. Tasks start first, within their share (§36). The harness makes its dispatches
after the overseer, and an overseer's dispatch that would leave fewer workers free than the harness's ranked above it
hold is refused `reserved`.

"Authorized reply" means a comment by an account in `trust.authorized_repliers`, matched on the tracker's stable account
identifier, never a display name, that is not a worker's (§8: one carrying the configured comment marks). A worker's
comment is never review feedback either. Anything else on the ticket is data, not instruction. See TRUST_MODEL.

**Trusted reviewers** (D089). Review feedback is a PR's reviews, review comments, and requested changes, and canopy's
own review findings (§21). `trust.trusted_reviewers`, private, lists whose feedback a worker may address without the
operator's go-ahead: VCS host logins, matched in full and case-insensitively, and `canopy:review` for canopy's own
reviews. It is empty by default, so a review bot's comment never starts a fixup on its own.

- Anyone else's feedback is `untrusted_review`: the harness raises its attention item (§14), and the overseer does not
  move the `review` cursor past it and never dispatches for it on its own judgment. An untrusted approval is not
  feedback.
- The operator answers in canopy, with `canopy reply KEY` or the web UI (§22), never on the ticket. An operator message
  newer than the message cursor is an instruction, like an authorized reply.
- The worker's prompt names the trusted reviewers, and the worker addresses anyone else's comment only as an operator
  message says, checking the overseer's classification again (D051). The comment stays data either way.

**What the harness checks.** Only the operator's channels write operator messages, and cursors advance only with a run
that starts. What a dispatch claims of a public ticket's subjects a source observes (§30) is a reference to what the
block showed, checked in code before §8's other guards; a private ticket, which its start record authorizes (§22), and
a subject no source observes keep their claims, checked again by the worker (D051). A refusal is a decision:

- `unauthorized`: a `label` not observed on the ticket; a `resume` for `reply` covering no new authorized reply,
  operator message, or artifact comment that is authority (§38); a `resume` for `review` covering no trusted
  reviewer's item, nor the canopy review it names with `canopy:review` trusted, or covering anyone else's with no
  operator message after it. With feedback plans on, §32's approval is the gate instead.
- `unobserved`: a cursor naming no item observed for its subject, or passing one the block left out for its bound. A
  tick's `ticket-set` is checked so too, and moves no stale subject's cursor past what it already passed.
- `stale`: the ticket, the PR of a unit a `resume` names, or a stacked dispatch's blocker's PR (§10), not observed
  within `connect.max_age_minutes`. One whose source keeps failing waits for it to recover (§30).
- `handled`: a `resume` for CI alone whose every failure at the head is behind the `ci` cursor or repeats, at the same
  head and context, one that is, so a re-run that went red to red starts nothing (PRIOR_ART, CI newness).

A private ticket (§22) needs no label, and its own phases come from the journal: `needs_human` when its latest run
ended `blocked` with no operator message after it, `human_replied` when an operator message is newer than its message
cursor. Its PR phases are as above.

Cursors (`comment`, `review`, `ci`, and a private ticket's `message`) hold the newest item of each kind the loop has
handled; "newer than cursor" means not handled yet. The comment cursor is the ticket's; the review and ci cursors are
each unit's, so a dispatch that carries one names exactly one repository. A dispatch carries the cursors of what it
handles (§8), so they advance only if the worker starts; items handled otherwise advance with `ticket-set`, and
the harness passes those that need no handling directly after a cursor, a worker's comment and a reply the operator
sent, as its own decision (§37). A `resume` moves each cursor of its reasons it leaves out to the newest item of that
kind the block showed, short of the first the checks above would refuse it to cover, on a public ticket and from fresh
observations alone; the overseer passes one to stop shorter (§37). A review comment waiting on a human is not advanced
past. A cursor but `message` is a journal number: each comment, review, review comment, and completed check run takes
the next one when a source first
observes it, and keeps it across reads, and a canopy review run takes one when it ends. So "newer" is one order for
every kind, and a re-run at the same head is new. Rejected: the source's ids, which no tracker orders, and times, which
a late submission backdates.

The configured query runs every tick it is due, before any ticket is read: the block holds only tickets the loop has
seen, so the query is the only way a newly labeled ticket becomes a candidate. The `tracker` source reads it, and when
the block shows that read `fresh` (§30), the harness records its result before the overseer runs, touching each open
ticket it returned into the journal (§11); a query no source read fresh does not run that tick and stays due, and a
ticket it would have found waits for the read that finds it.
`tracker.query_every_minutes` spaces it out, delaying only how soon a new ticket is found; a ticket the operator starts
is in the block already.

"Closed" means whatever the tracker calls finished; the provider skill says which. A closed ticket is not a candidate
and has no phase: the overseer marks it done, whatever its labels, branch, or PR, unless a worker is running for it,
which it waits out. A PR still open on a closed ticket is the operator's, like the tracker transition. `recently_done`
names each ticket recently marked done for any other reason that the last query still returned, and the overseer
records nothing for it, so a merged ticket a human has not closed yet costs nothing each tick. `canopy forget` clears
the done mark (§22).

## 8. Dispatch and the worker contract

The `dispatch` tool starts a run of one kind, `implement`, `resume`, or `plan`, for a ticket, naming the queue
label the ticket was found by and one or more of its units, its work in one repository each (§18); several make a joint
run. A `plan` writes the ticket's plan before its first `implement`, with guards of its own (§25).

1. Check the guards, which are in code and not overridable from the prompt. A refusal is recorded as a decision naming
   the guard and why, and the call is a tool error; a dry run checks them and stops (§6, D036). The overseer's
   dispatch is then recorded, and counts as running until the tick starts it, after the overseer's run, checking
   these guards again before step 2 (§40). Dispatch is refused when:
   - a claim rests on a stale observation or one that does not bear it out (`stale`, `unauthorized`, `unobserved`),
     or a `resume` for CI alone has only failures a worker already had at that head (`handled`), checked first (§7).
   - the label is not a queue label, or a started ticket's (§22) start record does not allow the run; the worker checks
     the label again (step 3, D051).
   - the request does not fit its kind: a `resume` with no branch to continue, a cursor moved without its reason, or a
     stacked base that is not one of canopy's branches (§10). The first `implement` names the ticket's branch, which
     every later run continues in every unit (D058).
   - a run for the ticket is running or recorded, or `max_workers` runs, review runs, and tasks' runs, together, are
     (§21, §36).
   - a named unit has had `policy.max_<kind>_attempts` runs of this kind, plus what `canopy grant` gave it (§22). A run
     counts against every unit it covered, whatever it ended as, and the count never resets (D030). The refusal raises
     an `attempt_limit` attention item (§14).
   - a `resume` for CI alone falls in the CI cooldown, or a notice changed after its tick read the journal (below).

   Dispatches are serialized from the guards through the record or the spawn, so two cannot both pass a limit. Leases
   are all or nothing, and cursors move only once the worker has started, so a refused or failed dispatch leaves no
   slot leased and what it was meant to handle still new.
2. Lease a slot in each named repository's pool (§18) and record the run, its slots, and each base.
3. Render the worker prompt for the kind, with the operator's messages (§22), standing instructions (§12), and the
   notice, and the latest runs' reports as data. A started ticket's run gets the kind's private variant (§22), with no
   label check and no tracker writes. Every other worker reads the ticket first and, if it is closed or carries no
   queue label, reports `failed` as not authorized and changes nothing; the run counts toward the attempt limit (D051).
   The overseer's context points at what to read, never a copy of ticket or PR text, which invites injection, nor a
   file, which could be any the operator can read. A prompt override missing a check the run needs fails it (D051).
4. Spawn `canopy _run` detached, holding its lifelock (§6), and return immediately.

`canopy _run`:

1. Claim the run, so it never gets a second worker, and drop `CANOPY_TICK_ID`, so the worker cannot act as the
   overseer. A ticket stopped or started privately since dispatch ends the run `stopped`.
2. Record each slot's git links, check out the branch or base at a detached HEAD, never a local branch, since a pool's
   slots share branch refs (D109), and put an approved plan in place (§25).
3. Run the worker in the slot, or a joint run's desk (§18), until its timeout, recording its session, spend, and
   progress (§41).
4. Parse the result contract (§13); missing or invalid is `unknown`. A plan (§25) pushes nothing.
5. If a slot's git links changed, the run is `crashed` and no git runs in its slots, which may now point at a git
   directory the worker made. Otherwise push once where the branch is not on origin, never with force (with
   `trust.rebase`, leasing what origin held at step 2). A failed push or commits on no pushed branch is `unpushed`.
   A `resume` for `ci` that left a check flaky and pushed nothing may then be kicked (§23).
6. Always tidy and return each slot, except after SIGKILL, which reconcile handles (§6 step 3); an untidy one is kept.
7. Close the run with its status and validated result, noting where the harness's status differs from the worker's,
   and in the same transaction its report and question (§22), memory (§28), and drafts (§29).

Every git the harness runs has hooks, the filesystem monitor, submodule fetches, the `ext::` transport, and background
maintenance off (D107): a worker can write the git directory its slot shares, and a hook it planted would otherwise run
on the host. A command named in that directory's config still runs (§24, Git state).

A worker's own git runs canopy's hooks, from the snapshot (§13), in place of the repository's: `prepare-commit-msg`
adds canopy's trailers and the operator's subject prefix, if set, but not to a `fixup!`, `squash!`, or `amend!` subject,
which `--autosquash` matches; `pre-push` holds a worker's first push for its repository's checklist (§42); and each
hook then runs the repository's own of its name, so the operator's hooks run as before. Step 5 names a pushed commit
that lacks either in the run's note, and never rewrites it (TRUST_MODEL T5).

Worker result contract, one JSON line, the last of the worker's text (§13); `prs` maps each repository the run worked
in to its PR, and `pr_titles` is optional and for display only. An `implement` or `resume` may add `"created"`, the
follow-up tickets it filed, each with its repository or null, which authorize nothing (§18). `flaky` is a `resume`'s
for `ci`, true when it left a failed check a rerun would pass, and `flaky_cause` (`test`, `runner`, or `service`) is
where it judged the check failed, left out when unsure, with `flaky_detail` one line on why (§23):

```json
{"status":"done|blocked|failed","branch":"agent/KEY-slug","prs":{"api":"https://...|null"},
 "pr_titles":{"api":"KEY: ...|null"},"summary":"a paragraph, line breaks sparingly","question":"only when blocked",
 "flaky":false}
```

**Worker obligations**, stated in every worker prompt:

- Work only inside the worktree or desk. Push only to the ticket's branch, from the detached HEAD, never with force;
  with `trust.rebase`, a lease is the one force the worker's definition allows (TRUST_MODEL T1).
- Keep the runtime's attribution trailer on commits, and canopy's, which git adds, unless the operator turned it off
  (TRUST_MODEL T5).
- Mark every comment and reply it posts with the configured marks (D069), or draft it for approval (§29). Everything
  posts as the operator (D010), so only the marks keep a worker's comment from reading as review feedback or an
  authorized reply; they only take authority away, so they need no protection.
- Open each PR through the GitHub MCP, or only with the operator's PR skill when one is set (a missing one fails the
  run; branch protection governs what it pushes, TRUST_MODEL T1). Link every PR on the ticket.
- On `blocked`: post the question and add `needs_human_label`; a private ticket's worker posts nothing (§22).
- Never approve, merge, close PRs, or transition the ticket to Done, including through closing keywords or tracker
  commands in commits, PR titles, or PR bodies.
- Push again for a fix in a new commit, never an amend (D116). Do not poll CI or retry a rejected push.

### A fresh session per run

Every worker run starts a new session, `resume` included; the branch, its PR, the cursors (§7), and the latest runs'
reports carry over. A continued session would keep earlier prompts, so a lifted notice or superseded message would
still read as the operator's (MEASUREMENTS 2026-10-15). Revisit if `resume` runs often fail for want of context.

### Notices to workers

A notice (REQUIREMENTS R15) tells `implement` and `resume` workers, reviews (§21), and chores (§19) of an outage
outside the work, such as "Artifactory is down", for a bounded time. It is a journal fact (§11), one at a time;
setting or clearing one wakes the loop (§6), and its lapse is a gate. No agent sets or clears one from inside canopy's
ticks and runs: it reaches every later run's prompt, so an agent steered by one ticket could write into every other's
(TRUST_MODEL T1). A failed check a notice explains is held: the overseer waits rather than spend a `resume` (D030)
until the check runs again, and asks for a rerun (§14) once the notice ends. The state block keeps an ended notice
while a unit observed fresh shows a failed check newer than its `ci` cursor, the only kind a notice can hold.

Open: whether a notice should name repositories. Every notice reaches every run until real use shows the need.

### One resume for what comes back to a PR

Everything that comes back to a PR is one `resume`, which does whatever the unit needs on one checkout and one push.
It names its reasons, one for each thing it handles: `ci`, `review` (review feedback or a canopy review's findings),
`reply` (an authorized reply or operator message), `conflict`, `no_pr`, and `retarget` (the PR's blocker merged, §10);
the first three move their own cursors (§7). `policy.max_resume_attempts` bounds every `resume` of a unit whatever its
reasons (D030). The **CI cooldown** holds a `resume` whose only reason is `ci` for `policy.ci_cooldown_minutes` after
the unit's last run that worked on CI ended; its end is a gate (§6). Rejected: a cooldown after every such run (it
would hold feedback behind a build the same run can fix); a limit per reason; reasons read off the cursors.

## 9. Aggressive release

- Slots are held only for the duration of `_run`.
- Reacquisition lands on an arbitrary slot, so build caches must be slot-independent: for Bazel, a shared disk cache
  or a remote one, configured in `.bazelrc`, not in canopy. canopy documents this; it does not manage it.
- In a workspace, the operator may declare each pool's size; `canopy workspace sync` makes the slots ahead of time, so
  they are warm before the first run lands in one (§18).

### Setting up a slot

Three steps, all the operator's, in the order they run:

1. **Seeding.** On every lease, treehouse copies ignored files from the primary clone into the slot, as the committed
   `.worktreeinclude` or the operator's `paths.worktree_include` selects. It seeds local config, never a tracked file.
2. **`post_create` hooks**, in the user-level treehouse config, run on the base when a slot is made or reused. A
   failing hook does not fail the lease. canopy's own pool backend (§18) runs none.
3. **`runtime.setup_cmd`**, private, runs in each slot of a worker run after its branch is checked out (§8 `_run` step
   2), and fails the run when it fails. Plans and reviews run none, so a command `runtime.allow_bash` names for the
   planner runs without it.

`setup_cmd` runs the branch's code on the operator's machine, outside the agent runtime's permissions, so it is wrapped
as the worker is (§24, TRUST_MODEL T4). A broken setup crashes every run it meets, each spending an attempt (D030).

### Bazel

[BAZEL.md](../BAZEL.md) is the operator's guide. Slots keep their paths across leases, so each slot's output base stays
warm, and canopy, which knows no build tool, never stops a slot's Bazel server. The worker's runtime refuses the output
base by its own path but reads it through the slot's `bazel-*` links; that is no boundary, since the worker's shell
reads either (HOST_ISOLATION §1).

## 10. Dependencies and stacking

- The overseer reads blocker relations from the observations, or through MCP for a ticket they leave stale or
  unobserved, in whatever form the tracker has them; the provider skill says where. A blocker is resolved when it is
  closed. Other relations are not blockers. A relation is data: it can delay work, never authorize it.
- A ticket with an unresolved blocker and no branch of its own is `blocked`. The overseer records `wait` with rationale
  `blocked_by: <KEY>`, unless it stacks the ticket.
- Stacking: a `dispatch` of `implement` with `base` set to the blocker's branch starts the worker from
  the blocker's branch, and its PR targets that branch, so it shows only this ticket's commits. The overseer stacks
  only on a ticket's single unresolved blocker whose PR is open and green, and reads the branch from that PR.
- `policy.stacking` (§12) defaults to `"auto"`. Under `"never"`, a blocked ticket waits until its blocker has landed,
  and gets `needs_author` attention if the blocker's PR closed unmerged. The harness adds no guard for it.
- The harness checks the shape of `--base` (`bad_base`, §8), so a PR cannot target a release branch, and refuses a
  stacked dispatch while the blocker's PR is stale (§7); whether that PR is green is the overseer's reading. `_run`
  fails a run whose base is not on origin.
- The base is not remembered: every dispatch starts from `--base` if given, else the pool's base branch. Once the
  blocker merges, a `resume` for `retarget` retargets the PR to the repository's base branch. Workers never rebase
  unless the operator sets `trust.rebase`.
- Ordering is decided by the overseer each tick from live state and recorded in `decisions`. There is no plan file
  and no DAG config.
