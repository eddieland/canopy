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
   and record the tick with the canopy version running it. Its id tags all logs. Migrations wait while any detached
   run's own process is alive, since it writes the old schema; a journal with migrations this canopy does not know is
   refused (D068).
3. **Reconcile local state.** A run, chore run, or review run whose own process is gone is marked `crashed`, what is
   left of its agent killed, and its slots returned. A slot leased under canopy's prefix with no live run is returned,
   in every pool (§18). Memory proposals expire (§28) and drafts are checked (§29). Capacity is `max_workers` less the
   running runs and review runs. If the pool cannot be read or a return fails, the tick fails and the overseer does not
   run. The tick records the newest journal message it could read, which marks what was acknowledged (§22) and what
   idle pacing compares against, and records the harness's own attention items (§14).
4. **Render the state block**, the overseer's whole message: one JSON object holding what the overseer needs to decide
   every ticket not done or stopped, ordered from what changes rarely to what changes every tick so the provider can
   cache it. The overseer's prompt is its agent definition's system prompt (§13), not part of the block. The block
   lists the overseer's own open attention items, without their detail, which may quote a comment: an item stays open
   only while every tick records it again (MEASUREMENTS 2026-10-13). Rejected: a harness that keeps an item until the
   overseer resolves it, which leaves an item standing whenever the overseer forgets one.
5. **Check `canopy`, then run the overseer.** If `canopy` as the overseer would find it does not run, the tick records
   `attention:canopy_unavailable` and closes `canopy_unavailable` without running an overseer that could record
   nothing (MEASUREMENTS 2026-10-12). Rejected: putting this canopy's launcher first on the overseer's PATH, which
   overrides the operator's.

   Then run `overseer_cmd` in the workspace root (§18), with `CANOPY_TICK_ID` set; the overseer's commands refuse
   unless it names a running tick (D020). Its output goes to a log only the operator can read, never to the journal. It
   succeeded if it exited 0 and a line of its final message (§13) is exactly `CANOPY_TICK_DONE`, which catches a run
   that exits 0 short of the last step; otherwise the tick closes `overseer_failed`. A successful run that recorded a
   tick-wide skip, such as the tracker's MCP being down, closes the tick `skipped`, which leaves the attention list
   standing, so an outage does not resolve and re-raise every item.

   **The overseer's duties.** A successful run is then checked for what a tick owes: the query when it is due (§7); a
   decision for every ticket in the block and every ticket the query returned, except those stopped or recently done;
   and a run, wait, or refusal for every chore due. A duty left undone closes the tick `overseer_failed`, naming each,
   so the attention list stands and the query stays due; its dispatches stand. Why: the prompt alone did not hold a
   cheaper overseer to the procedure, and a skipped query stalls new work with no tick failing (MEASUREMENTS
   2026-10-15). The check sees that a duty was done, not that it was done well.

   In a dry run (D036), dispatch checks the live guards (§8) and starts nothing, no cursor advances, and nothing is
   marked done. What the overseer writes is rendered into a later prompt, so the CLI validates its keys, verbs,
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
   message (§22) or a run ending ends the wait early, but never sooner than `loop.min_gap_minutes` after the tick
   began, which bounds how often the overseer runs. The operator can end the wait by hand.
6. Repeat from 3 until the operator stops the loop or a set number of ticks has run.

Pausing holds the loop's ticks while the web UI and workers go on. The pause is a journal fact (§11) that outlives the
loop; paused, the wait never ends by itself, and a tick the operator asks for still runs, as does a hand-run
`canopy tick`. Pausing, resuming, and starting or stopping the daemon refuse inside canopy's own ticks and runs, so no
agent can hold off later ticks or undo the operator's pause (TRUST_MODEL T1).

Stopping the loop never stops a run, which is detached (§8); `canopy stop` does, per ticket. A reload rereads the
config files (§12) for the next tick, and a config that does not load leaves the old one in place. Rejected: rereading
before every tick (a half-saved edit would apply itself). Prompt files are read every tick.

The daemon runs the same loop in its own session, so it outlives the terminal (D042). Nothing is installed with the OS
and nothing restarts it. Rejected: launchd or systemd units (an install step the operator did not want).

### Idle pacing

A tick that finds nothing new costs a full overseer run and buys nothing. So the loop waits longer after each idle tick
in a row, and wakes early on the events it can see itself. It does not poll GitHub or the tracker from Python (D003),
run a cheaper pre-check agent, or take webhooks (TRUST_MODEL T8).

A tick is **idle** when it closed `ok`, dispatched nothing (a dry run paces as a live one would), and nothing reached
the journal after the previous tick read it (step 3): no run started or ended, and the operator did nothing. Rejected:
idle as a tick that changed nothing, since records that repeat on unchanging state kept any tick from counting
(MEASUREMENTS 2026-10-14).

After each idle tick in a row the wait doubles, up to `loop.idle_max_minutes` and never below the base wait. Whatever
pacing chose, the wait ends at the earliest harness gate ahead: the CI cooldown's end (§8), a chore coming due (§19),
or a notice lapsing (§8); a gate already open sets no deadline, so it cannot make the loop spin. A run ending ends the
wait, so a long wait never sits on canopy's own work. The world, such as a review or CI going red, is seen up to
`loop.idle_max_minutes` late: that is the trade, and the operator's knob. Each tick records whether it was idle and
what ended the wait before it, for spend (§11).

## 7. Ticket phases and next actions

The overseer derives phases each tick from live state. They are recorded for the status view, never read back as
truth. The PR phases, `pushed_no_pr` to `merged`, are a unit's (§18).

A ticket's title is its display name in canopy, set by the overseer with `canopy ticket set --title`, which makes it
one short line. It is model-written, so it stays out of `attention.md` and the `text` format, and the Slack sink
escapes it (§20).

| Phase | Derived from | Next action |
|---|---|---|
| `ready` | one of `tracker.labels` present, not closed, no run active, no branch, no open blocker | dispatch `implement`, or `plan` when the ticket needs one and has none (§25) |
| `plan_proposed` | the ticket's newest plan waits on the operator (§25) | attention `plan_review`; dispatch `plan` again after an operator message |
| `blocked` | as `ready`, but a blocker ticket is open | dispatch `implement` stacked on the blocker's branch if its PR is open and green (§10), else wait |
| `running` | active `runs` row | wait |
| `pushed_no_pr` | branch exists, no PR | dispatch `resume` with instruction to open the PR |
| `conflicted` | PR open, GitHub reports it conflicts with its base | dispatch `resume` to bring the base in |
| `ci_running` | PR open, checks pending | wait |
| `ci_red` | PR open, checks failed, newer than cursor | dispatch `resume` for `ci`, with anything else the unit has (§8, One resume for what comes back to a PR); at the attempt limit, attention; in cooldown, wait; held for a notice, wait (§8) |
| `review_pending` | with `review.agent_prs`: checks pass, no approval, head commit not reviewed (§21) | review it |
| `review_findings` | with `review.agent_prs` and `canopy:review` trusted: findings on the head's review, newer than the cursor | as comments (§7) |
| `changes_requested` | a trusted reviewer's comments or requested changes newer than cursor | dispatch `resume` with the comments; if the overseer judges a comment needs a human (design pushback, scope), attention instead |
| `untrusted_review` | review feedback newer than cursor from a reviewer not in `trust.trusted_reviewers`, with no operator message about it | attention: the operator says what to do with `canopy reply` (below) |
| `green_unreviewed` | checks pass, no approval | attention: needs a reviewer |
| `approved` | approved, not merged | attention: ready to merge |
| `merged` | every unit's PR merged, and no other repository left to change (§18) | mark ticket `done` in the journal; humans handle the tracker transition |
| `needs_human` | `needs_human_label` present, no authorized reply newer than it | wait |
| `human_replied` | authorized reply newer than the label, or an operator message newer than the message cursor | dispatch `resume` pointing at the reply; the worker removes the label |

A PR's checks are its head commit's check runs and commit statuses. GitHub runs no checks on a PR that conflicts with
its base, so `conflicted` comes before every CI and review phase; the `resume` attempt limit bounds its repeats (D030).

"Authorized reply" means a comment by an account in `trust.authorized_repliers`, matched on the tracker's stable account
identifier, never a display name, that is not a worker's (§8: one carrying the configured comment marks). A worker's
comment is never review feedback either. Anything else on the ticket is data, not instruction. See TRUST_MODEL.

**Trusted reviewers** (D089). Review feedback is a PR's reviews, review comments, and requested changes, and canopy's
own review findings (§21). `trust.trusted_reviewers`, private, lists whose feedback a worker may address without the
operator's go-ahead: VCS host logins, matched in full and case-insensitively, and `canopy:review` for canopy's own
reviews. It is empty by default, so a review bot's comment never starts a fixup on its own.

- Anyone else's feedback is `untrusted_review`: the overseer records the attention item every tick, does not move the
  `review` cursor past it, and never dispatches for it on its own judgment. An untrusted approval is not feedback.
- The operator answers in canopy, with `canopy reply KEY` or the web UI (§22), never on the ticket. An operator message
  newer than the message cursor is an instruction, like an authorized reply.
- The worker's prompt names the trusted reviewers, and the worker addresses anyone else's comment only as an operator
  message says, checking the overseer's classification again (D051). The comment stays data either way.

The harness cannot tell a review comment's author (D003), so this gate is the overseer's judgment, checked again by the
worker. What the harness can check, it does: only the operator's channels write operator messages, and cursors advance
only with a run that starts.

A private ticket (§22) needs no label, and its own phases come from the journal: `needs_human` when its latest run
ended `blocked` with no operator message after it, `human_replied` when an operator message is newer than its message
cursor. Its PR phases are as above.

Cursors (`comment`, `review`, `ci`, and a private ticket's `message`) hold the newest item of each kind the loop has
handled; "newer than cursor" means not handled yet. The comment cursor is the ticket's; the review and ci cursors are
each unit's, so a dispatch that carries one names exactly one repository. A dispatch carries the cursors of what it
handles (§8), so they advance only if the worker starts; items handled otherwise advance with `canopy ticket set`. A
review comment waiting on a human is not advanced past. The `review` cursor is a UTC time, since no single id orders
reviews, review comments, and canopy's review runs.

The overseer runs the configured query every tick it is due, before it reads any ticket: the block holds only tickets
the loop has seen, so the query is the only way a newly labeled ticket becomes a candidate. `canopy queried [KEY]...`
records it and the open tickets it returned, touching each into the journal (§11). `tracker.query_every_minutes`
(default 0, every tick) spaces it out, through the block's `query_due`, which delays only how soon a new ticket is
found; a ticket the operator starts is in the block already.

"Closed" means whatever the tracker calls finished; the provider skill says which. A closed ticket is not a candidate
and has no phase: the overseer marks it done (decision `done`, rationale `closed`), whatever its labels, branch, or PR,
unless a worker is running for it, which it waits out. A PR still open on a closed ticket is the operator's, like the
tracker transition. `recently_done` names each ticket marked done in the last 30 days for any other reason, and the
overseer records nothing for it, so a merged ticket a human has not closed yet costs nothing each tick. `canopy forget`
clears the done mark (§22).

## 8. Dispatch and the worker contract

`canopy dispatch` starts a run of one kind, `implement`, `resume`, or `plan`, for a ticket, naming the queue label the
ticket was found by and one or more of its units, its work in one repository each (§18); several make a joint run. A
`plan` writes the ticket's plan before its first `implement`, with guards of its own (§25).

1. Check the guards, which are in code and not overridable from the prompt. A refusal is recorded as a decision naming
   the guard and why, and the command exits 1; a dry run checks them and stops (§6, D036). Dispatch is refused when:
   - the label is not a queue label, or a started ticket's (§22) start record does not allow the run; the worker checks
     the label again (step 3, D051).
   - the request does not fit its kind: a `resume` with no branch to continue, a cursor moved without its reason, or a
     stacked base that is not one of canopy's branches (§10). The first `implement` names the ticket's branch, which
     every later run continues in every unit (D058).
   - a run for the ticket is running, or `max_workers` runs and review runs, together, are (§21).
   - a named unit has had `policy.max_<kind>_attempts` runs of this kind, plus what `canopy grant` gave it (§22). A run
     counts against every unit it covered, whatever it ended as, and the count never resets (D030). The refusal raises
     an `attempt_limit` attention item (§14).
   - a `resume` for CI alone falls in the CI cooldown, or a notice changed after its tick read the journal (below).

   Dispatches are serialized from the guards through the spawn, so two cannot both pass a limit. Leases are all or
   nothing, and cursors move only once the worker has started, so a refused or failed dispatch leaves no slot leased
   and what it was meant to handle still new.
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
3. Run the worker in the slot, or a joint run's desk (§18), until its timeout, recording its session and spend.
4. Parse the result contract (§13); missing or invalid is `unknown`. A plan (§25) checks out and pushes nothing.
5. If a slot's git links changed, the run is `crashed` and no git runs in its slots, which may now point at a git
   directory the worker made. Otherwise push once where the branch is not on origin, never with force (with
   `trust.rebase`, leasing what origin held at step 2). A failed push or commits on no pushed branch is `unpushed`.
6. Always tidy and return each slot, except after SIGKILL, which reconcile handles (§6 step 3); an untidy one is kept.
7. Close the run with its status and validated result, noting where the harness's status differs from the worker's,
   and in the same transaction its report and question (§22), memory (§28), and drafts (§29).

Every git the harness runs has hooks, the filesystem monitor, submodule fetches, the `ext::` transport, and background
maintenance off (D107): a worker can write the git directory its slot shares, and a hook it planted would otherwise run
on the host. A command named in that directory's config still runs (§24, Git state).

Worker result contract, one JSON line, the last of the worker's text (§13); `prs` maps each repository the run worked
in to its PR, and `pr_titles` is optional and for display only. An `implement` or `resume` may add `"created"`, the
follow-up tickets it filed, each with its repository or null, which authorize nothing (§18):

```json
{"status":"done|blocked|failed","branch":"agent/KEY-slug","prs":{"api":"https://...|null"},
 "pr_titles":{"api":"KEY: ...|null"},"summary":"a paragraph, line breaks sparingly","question":"only when blocked"}
```

**Worker obligations**, stated in every worker prompt:

- Work only inside the worktree or desk. Push only to the ticket's branch, from the detached HEAD, never with force;
  with `trust.rebase`, a lease is the one force the worker's definition allows (TRUST_MODEL T1).
- Keep the runtime's attribution trailer on commits or add canopy's, unless the operator turned it off (TRUST_MODEL T5).
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
until the check runs again, and asks for a rerun (§14) once the notice ends.

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
   2), and fails the run when it fails. Plans and reviews run none: their agents have no shell.

`setup_cmd` runs the branch's code on the operator's machine, outside the agent runtime's permissions, so it is wrapped
as the worker is (§24, TRUST_MODEL T4). A broken setup crashes every run it meets, each spending an attempt (D030).

### Bazel

[BAZEL.md](../BAZEL.md) is the operator's guide. Slots keep their paths across leases, so each slot's output base stays
warm, and canopy, which knows no build tool, never stops a slot's Bazel server. The worker's runtime refuses the output
base by its own path but reads it through the slot's `bazel-*` links; that is no boundary, since the worker's shell
reads either (HOST_ISOLATION §1).

## 10. Dependencies and stacking

- The overseer reads blocker relations through MCP, in whatever form the tracker has them; the provider skill says
  where. A blocker is resolved when it is closed. Other relations are not blockers. A relation is data: it can delay
  work, never authorize it.
- A ticket with an unresolved blocker and no branch of its own is `blocked`. The overseer records `wait` with rationale
  `blocked_by: <KEY>`, unless it stacks the ticket.
- Stacking: `canopy dispatch <KEY> --label <label> --kind implement --base <blocker's branch>` starts the worker from
  the blocker's branch, and its PR targets that branch, so it shows only this ticket's commits. The overseer stacks
  only on a ticket's single unresolved blocker whose PR is open and green, and reads the branch from that PR.
- `policy.stacking` (§12) defaults to `"auto"`. Under `"never"`, a blocked ticket waits until its blocker has landed,
  and gets `needs_author` attention if the blocker's PR closed unmerged. The harness adds no guard for it.
- The harness checks only the shape of `--base` (`bad_base`, §8), so a PR cannot target a release branch. It cannot
  read PR state (D003). `_run` fails a run whose base is not on origin.
- The base is not remembered: every dispatch starts from `--base` if given, else the pool's base branch. Once the
  blocker merges, a `resume` for `retarget` retargets the PR to the repository's base branch. Workers never rebase
  unless the operator sets `trust.rebase`.
- Ordering is decided by the overseer each tick from live state and recorded in `decisions`. There is no plan file
  and no DAG config.
