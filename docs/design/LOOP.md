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

1. Acquire the lock. If held, log and exit 0, writing no `ticks` row.
2. Apply pending migrations. Close any `ticks` row still `running` as `abandoned`: holding the lock proves its process
   is gone. Insert a `ticks` row; its id tags all logs. Migrations wait while any `running` run's `_run`, chore run's
   `_chore`, or review run's `_review` is alive, since it writes the old schema; so does the error for a journal
   with migrations this canopy does not know (D068). Until then, the tick and any command that opens the journal fail
   saying so.
3. **Reconcile local state.**
   - Each `runs` row with `status='running'` whose pid (the `canopy _run` process) is dead or never recorded: kill what
     is left of the worker's process group (`runs.worker_pid`), mark the run `crashed`, run
     `treehouse return --force --if-lease-id` on every slot it leased (`run_slots`), remove its desk if it was a joint
     run, and log it. A zombie counts as dead. A pid reused by an unrelated process reads as alive, so that run stays
     running: a residual, not a guard.
   - Each leased slot in `treehouse status --json` with no live `runs` row and `lease_holder` matching our prefix:
     return it and log it. In a workspace this covers every cloned repository's pool, and a run's slots go back to the
     pools of the repositories they record (§18). A desk canopy made whose ticket has no running run is removed;
     anything else under `desks/` is left alone.
   - Each `chore_runs` row with `status='running'` whose `_chore` is dead or never recorded: kill what is left of its
     agent's process group and mark it `crashed` (§19). Chore runs hold no slot and take no worker capacity.
   - Each `review_runs` row with `status='running'` whose `_review` is dead or never recorded: kill what is left of its
     reviewer, remove its directory, return its slot, and mark it `crashed` (§21). This runs before the worker runs'
     reconcile, and a running review's lease is never returned as stale.
   - `capacity = max_workers - count(runs and review runs where status='running')`: a review holds a slot.
   - If `treehouse status` or a return fails, close the tick as `reconcile_failed` and stop; the overseer does not run.
   - Record on the tick the newest message in the journal and the time: every message up to it, and every run,
     chore run, and review run that started or ended before it, was there for this tick to read (`ticks.message_id`,
     `ticks.read_at`). The latest `ok` tick's message is what the web UI calls acknowledged (§22); idle pacing reads
     both (below).
   - Record as this tick's decisions the harness's attention items for runs (§14), `awaiting_reply` for each started
     ticket whose latest question has no operator message after it (§22), `chore_failed` for each configured chore
     whose latest ended run did not end `ok` (§19), and `repo_missing` for each mapped repository with no clone.
4. **Render the overseer prompt**: `prompts/overseer.md` (or the override), plus a generated `## State` section holding
   one JSON object: tick id, current time, whether it is a dry run, workspace root; the workspace (name, the path of
   `MAP.md` if any) and its repositories (name, path, summary, whether cloned, its
   pool's leased slots, §18); tracker config (provider, query, labels, needs-human label); trust config (authorized
   repliers, branch prefix, PR label); capacity; policy (limits and stacking); running workers and their repositories;
   and the `tickets` rows not marked done. Each ticket has its phase, branch, and comment, message, and mirror cursors
   (§22); its units (§18), each with repository, branch, PR, phase, review and ci cursors, runs so far of each kind,
   the runs of each kind the operator granted past the policy's limit if any (`granted`, §8), and when fix-ci may next
   run if still ahead; and its latest run (id, kind, status, branch, each repository it leased in
   with its starting base, start and end). A ticket the operator started has a `private` object (§22): its start
   record's status, its message cursor, the operator's messages newer than it, and the question awaiting a reply, if
   any. `chores` (§19) is present only when chores are configured. `mirror` holds the per-tick mirror limit and this
   tick's heredoc delimiter (§22).
5. **Run the overseer** with `overseer_cmd`, cwd = the workspace root (§18), timeout
   `overseer_timeout_minutes`, and `CANOPY_TICK_ID` in its environment. `canopy dispatch`, `decide`, `attention`, and
   `mirror` refuse if it is unset or names a tick that is not running (D020). Its stdout and stderr go to
   `<state_dir>/ticks/<tick id>.log`, readable only by the operator (and its end on the tick's page, §22), never to
   the journal. The session id and cost the runtime reported (§13) go on the `ticks` row, whether or not the run
   succeeded. The run succeeded if it exited 0 and the last non-empty line of its text (§13) is `tick complete`;
   otherwise the tick closes as `overseer_failed`. A successful run that recorded a tick-wide `skip`
   (`mcp_unavailable`, `tracker_unsupported`) closes the tick as `skipped`, which leaves the attention list standing,
   so an outage does not resolve and re-raise every item.

   In `--dry-run` (D036), the state block says so. `canopy dispatch` checks the live guards (§8), counting each
   dispatch this dry run already recorded as a running run, and records refusals the same way. An allowed dispatch
   starts nothing and is recorded as `dispatch:<kind>` with its cursors, context, and rationale
   `dry run: not dispatched; would work on <branch>` (plus `in <repositories>` in a workspace). `canopy ticket set`
   records phases, but neither it nor `canopy dispatch --cursor` advances cursors, and `--done` does not mark the
   ticket done. `canopy mirror` records the comment and moves no mirror cursor. The rest of the tick is live: reconcile
   closes dead runs and returns stale leases, and the tick's attention items become the attention list and are notified.

   `canopy decide` takes `wait`, `skip`, or `done`; only a tick-wide `skip` (such as `mcp_unavailable`) omits the key.
   What the overseer writes is rendered into the next prompt, so the CLI bounds it: keys and attention reasons are
   validated, phases come from §7's table, cursor ids must match `[A-Za-z0-9][A-Za-z0-9_.:/-]*`, and rationales,
   details, and worker context are cut at 2000 characters.
6. Close the `ticks` row with a summary.
7. **Publish attention** (§14): rewrite `attention.md` from the journal, then deliver to each notification sink (§20)
   the list's change since that sink last heard, the events it takes, and a digest when due; `notify.cmd` is the sink
   `default`. This follows the close because the list is the latest `ok` tick's, which may be this one; after a failed
   or skipped tick it is the one before. A failure here is logged and does not change the tick's status. Release the
   lock.

Workers dispatched during a tick outlive it, as detached processes owned by `canopy _run`.

### The loop

`canopy loop [--dry-run] [--every MINUTES] [--ticks N] [--defer MINUTES] [--no-serve]` is how ticks are meant to run
(D042), in the foreground until stopped:

1. Take `<state_dir>/loop.lock`; if another loop holds it, refuse and exit 1. Each tick still takes the separate tick
   lock (step 1 above), so a hand-run `canopy tick` runs between the loop's ticks or finds the lock busy.
2. Apply pending migrations before the first tick. Start the web UI's server in a thread, unless `--no-serve` or
   `serve.enabled = false`; without a usable listener secret, say why and serve nothing (§22). The header names its
   URL. With `--defer`, wait that many minutes from here before the first tick; the header says when it will run. The
   wait ends early as the one in step 5 does, by an operator message (no sooner than a minute after the loop started)
   or `t`, and a stop during it ends the loop with no tick.
3. Run a tick exactly as `canopy tick` does, passing `--dry-run` through. An error the tick code does not handle ends
   that tick as `error` in the loop's output; the traceback goes to the log and the loop goes on. The next tick closes
   the row left `running` as `abandoned`.
4. Print the tick's status, duration, and summary; each decision except `wait` and attention items, with its
   rationale; attention items added (`+`) and resolved (`-`); running workers, the list's size, what the tick's
   overseer cost in dollars and tokens when the runtime reported it, and the wait that follows.
5. Wait, measured from the end of the tick, for `--every`, else `loop.interval_minutes`, whatever the tick's status,
   lengthened after idle ticks and ended at a gate (Idle pacing, below). This pacing rule is `pacing.wait`; ROADMAP
   M13 will lengthen it by tick cost. An operator message recorded since the tick began, such as a `canopy reply`, ends
   the wait early, but no sooner than a minute after the tick began (`repeat.WAKE_MIN_SECONDS`; §22); so does a run
   ending (below). On a terminal, pressing `t` (`repeat.TICK_NOW_KEY`, either case) ends it at once, with no floor
   (the floor guards against bursts of messages; a keypress is deliberate); keys pressed during the tick are dropped,
   but `p` (below). While the loop is paused, the wait does not end at its deadline (Pausing, below).
6. Repeat from 3 until `--ticks N` ticks have run or the operator stops the loop.

Pausing (taken on request, 2026-10-13): the operator can hold the loop's ticks without stopping it, so the web UI
stays up, the countdown stays on screen, and the workers already dispatched keep going.

- The pause is a journal row (`pause`, §11; `core/pause.py`), so every channel writes the same fact: `p` at the
  loop's terminal (`repeat.PAUSE_KEY`, either case) pauses and resumes, as do `canopy pause` and `canopy resume`
  and the web UI's header (§22). Each records its channel (`loop`, `cli`, `web`) and logs `loop paused` or
  `loop resumed` with it. Pausing a paused loop keeps the first pause's time and channel.
- The wait reads it at every step. Paused, it does not end at its deadline or on an operator message or a run ending:
  it holds, drawing `paused since 14:02 (web); no tick until resumed` instead of the countdown. A message or run
  ending still moves the deadline as it would (step 5), so resuming ticks at once if the deadline has passed, and
  otherwise the countdown goes on to it. The tick running when a pause comes finishes; `p` pressed during it is read
  when it ends, so the tick's block already says `paused: no tick until resumed` in place of the next tick.
- A loop started while paused holds its first tick the same way, and its header says so; with `--defer`, the
  deferral counts down and then holds. The pause outlives the loop: it is the operator's, lifted only by a resume.
- `t` during a pause runs one tick and the loop stays paused, as a hand-run `canopy tick` does: either is the
  operator asking for that tick. Ctrl-C ends a paused loop at once, as during any wait.
- `canopy pause` and `canopy resume` refuse inside canopy's own ticks and runs (`inside_run`), as `start` and
  `reply` do: an agent that could pause the loop could hold off every tick after its own, and one that could resume
  it could undo the operator's pause (TRUST_MODEL T1). `canopy status` names a pause after its last tick line.
- Not a scheduler's: a hand-run or cron-run `canopy tick` ignores the pause, and nothing but the loop reads it.
  Rejected: holding the pause in the loop's memory (lost on a restart, and the CLI could not reach it); stopping the
  workers too (`canopy stop --now` does that per ticket).

Stopping: SIGINT (Ctrl-C) or SIGTERM during the wait ends the loop at once. During a tick, the first lets the tick
finish and ends the loop without waiting; both exit 0. A second aborts the tick: the overseer's process group is killed
as on a timeout, the command exits 1, and the next tick closes the row as `abandoned`. Dispatched workers are
unaffected. A signal less than one second (`repeat.SAME_SIGNAL_SECONDS`, monotonic clock) after the first is the same
keypress. The web UI's server stops with the loop.

Config is read once at loop start; restart to apply a change. Prompt files are read every tick.

Output uses rich (D043). On a terminal, a spinner with elapsed time shows during a tick and a countdown during the
wait, redrawn in place and cleared when done. To a file or pipe, output is plain text, one block per tick. The JSON log
gains `loop started` and `loop stopped` lines, with no tick id, a `loop defers its first tick` line with `--defer`, a
`loop waits` line per tick, a line when a key, a message, or a run ending ends a wait, and `loop paused` and
`loop resumed` lines with their channel.

Keys are read by `infra/keys.py`, only when output goes to a terminal and stdin is a terminal the loop holds in the
foreground: the terminal is put in cbreak mode (no Enter, no echo; Ctrl-C and Ctrl-Z still signal) for as long as the
loop runs and restored when it stops. Otherwise no keys are read, and the header and countdown do not mention them;
a paused wait then names `canopy resume` and the web UI instead of `p`.

### Idle pacing

ROADMAP M21; `loop/pacing.py`. A tick that finds nothing new costs a full overseer run and buys nothing, however
cheap that run was, and most ticks overnight and at weekends are like that. So the loop waits longer after each idle
tick in a row, and wakes early on the events that end idleness that it can see itself. It does not poll GitHub or the
tracker from Python (D003), run a cheaper pre-check agent first, keep quiet hours, or take webhooks (TRUST_MODEL T8).

A tick is **idle** when all of these hold, each read from the journal by the loop:

- It closed `ok`. Any other status is not idle and resets the count: a failing tick keeps today's pacing.
- Its decisions are only `wait`, a ticket's `skip` (such as `not_labeled`, every tick), attention items, and refusals
  that lift by themselves (`pacing.QUIET_REFUSALS`): `running`, `capacity`, and `chore_capacity` (on a run ending),
  `cooldown`, `not_due`, and `outside_hours` (at a known time, below), and `attempt_limit` (never). Any dispatch,
  `done`, `mirror` (a new tracker comment), or other refusal makes it not idle. A tick-wide `skip` closes the tick
  `skipped`, which is not idle already.
- The attention list after it is the list before it, compared as the loop's per-tick block already compares them.
- No ticket or unit changed its phase, branch, a cursor, or `done`, and no ticket was seen for the first time.
- No run, chore run, or review run started or ended, and no operator message was recorded, after the previous tick
  read the journal for the overseer's state (`ticks.read_at` and `ticks.message_id`, §6 step 3). Something the
  previous tick could not have seen keeps this one from counting as idle, even when it happened while the previous
  tick was still running. The previous tick is the journal's, whatever ran it; one that never read the journal, such
  as a `reconcile_failed` tick or the first tick of all, makes this one not idle.

The wait after a tick is then:

- `base` (`--every`, else `loop.interval_minutes`) after a tick that is not idle;
- after the n-th idle tick in a row, `max(base, min(base * 2^n, loop.idle_max_minutes))`. With the defaults, 30, 60,
  120, then 120 for as long as nothing changes. It is never shorter than `base`, so idle pacing is off whenever the
  cap is not above `base`: set `loop.idle_max_minutes` to `loop.interval_minutes`, or pass an `--every` at or above
  it. Off, the loop paces as before M21: `base` after every tick, no gate shortens it, and only an operator message
  wakes it. A shorter `--every` keeps idle pacing, from that base.

`loop.idle_max_minutes` (user-only, default 120) is at least `loop.interval_minutes` when set; left unset under a
longer interval, it is no error and idle pacing is off. The count lives in the loop, not the journal: a restarted loop
starts at `base`, and a hand-run `canopy tick` between the loop's ticks counts like any other. When M13's cost pacing
is built, the wait is the longer of the two rules' waits, and what follows bounds that combined wait.

Whatever pacing chose, the wait ends no later than the earliest harness gate still ahead when the tick ends, both what
the state block shows: a `fix-ci` cooldown's end (§8) and a configured chore's `due_at` (§19). A gate opening is acted
on when it opens, even sooner than `base`. One already open, such as a chore the overseer passed over because its `when`
says not now, sets no deadline, so it cannot make the loop spin.

Besides an operator message, the wait ends early, with the same one-minute floor (`repeat.WAKE_MIN_SECONDS`), when a
run, chore run, or review run ended after the tick read the journal for the overseer's state (`ticks.read_at`): after
anything that tick could have seen. A run that ends while the overseer is running is picked up a minute after the tick
began, not a full interval later. The tick that follows is not idle, so the wait after it is `base` again, and the tick
after that looks for the CI on a worker's push at today's pace. That holds at any count, so a long wait never sits on
canopy's own work.

What idle pacing cannot see is the world: a teammate's review comment or a PR's CI going red is picked up at the next
tick, up to `loop.idle_max_minutes` late, or later only when M13's budget asks for a longer wait. That cap is the
trade, and the operator's knob. A sink's digest (§20) is due at a delivery, so it can lag by as much. The header names
the cap, the per-tick block shows the count with the wait, as `idle 3, next tick in 1h 00m at 03:41` (no count after a
tick that was not idle), and the `loop started` log line records `idle_max_minutes`; each tick's `loop waits` line
records whether it was idle, the count, and the wait chosen, in seconds.

The journal records the same on each tick the loop ran, for spend (ROADMAP M33): `ticks.idle`, whether the tick was idle
by the rule above, and `ticks.woken_by`, what ended the wait before it: `start` (the loop's first tick, after any
`--defer` ran its length), `timer` (the wait ran its length), `gate` (a gate shortened it and it ran out), `message`,
`run`, or `key`. A pause does not change it: a tick held past its deadline until the operator resumed records what it
would have without the pause, and one the operator ran during the pause records `key`. The loop classifies every tick
with idle pacing off too, though only pacing counts them, so the journal says what the overseer's spend bought whatever
the pacing; a `loop waits` line's `idle` is then the tick's classification, and its count stays 0. Both are NULL on a
tick the loop did not run, such as a hand-run `canopy tick`: the rule compares the journal before and after the tick,
and only the loop reads it before. A tick the loop has no id for (`lock_busy`, or `error`, where tick code raised)
records nothing.

## 7. Ticket phases and next actions

The overseer derives phases each tick from live state. They are recorded in `tickets.phase` for the status view, never
read back as truth. A ticket's own phase is recorded only when the overseer runs `canopy ticket set --phase`, while it
records a decision for every ticket a tick looks at, so the status view and the web UI fall back on the newest
decision since the ticket was last forgotten (`not recorded, last decision wait`), and say `not seen by a tick yet`
only when there is none. The PR phases, `pushed_no_pr` to `merged`, are a unit's (§18), recorded in
`ticket_units.phase`: `canopy ticket set` needs `--repo` for one.

A ticket's title, `tickets.title`, is its name in canopy, for display only like its phase. The overseer gives it with
`canopy ticket set <KEY> --title '<title>'`, a few words from the ticket's own title, the first tick the state block
shows the ticket with no title, and again only when the ticket's own title changes. The CLI drops control characters,
collapses whitespace to one line, refuses an empty title, and cuts it at 80 characters; a dry run records it, as it
records a phase. It is shown beside the key (`PROJ-1: <title>`) in `canopy status`, `canopy show`, and the web UI, and
it is the session title of the ticket's runs (§13). It never reaches `attention.md` or a notification: those go to
sinks the operator may share (§20), and a title is model-written text. `canopy forget` keeps it.

| Phase | Derived from | Next action |
|---|---|---|
| `ready` | one of `tracker.labels` present, not closed, no run active, no branch, no open blocker | dispatch `implement` |
| `blocked` | as `ready`, but a blocker ticket is open | dispatch `implement` stacked on the blocker's branch if its PR is open and green (§10), else wait |
| `running` | active `runs` row | wait |
| `pushed_no_pr` | branch exists, no PR | dispatch `resume` with instruction to open the PR |
| `conflicted` | PR open, GitHub reports it conflicts with its base | dispatch `resume` to merge the base in |
| `ci_running` | PR open, checks pending | wait |
| `ci_red` | PR open, checks failed, newer than cursor | dispatch `fix-ci`; at the attempt limit, attention; in cooldown, wait |
| `review_pending` | with `review.agent_prs`: checks pass, no approval, head commit not reviewed (§21) | review it |
| `review_findings` | with `review.agent_prs` and `canopy:review` trusted: findings on the head's review, newer than the cursor | as comments (§7) |
| `changes_requested` | a trusted reviewer's comments or requested changes newer than cursor | dispatch `resume` with the comments; if the overseer judges a comment needs a human (design pushback, scope), attention instead |
| `untrusted_review` | review feedback newer than cursor from a reviewer not in `trust.trusted_reviewers`, with no operator message about it | attention: the operator says what to do with `canopy reply` (below) |
| `green_unreviewed` | checks pass, no approval | attention: needs a reviewer |
| `approved` | approved, not merged | attention: ready to merge |
| `merged` | every unit's PR merged, and no other repository left to change (§18) | mark ticket `done` in the journal; humans handle the tracker transition |
| `needs_human` | `needs_human_label` present, no authorized reply newer than it | wait |
| `human_replied` | authorized reply newer than the label, or an operator message newer than the message cursor | dispatch `resume` pointing at the reply; the worker removes the label |
| `split` | a split's parent (§18) | wait; `split_unlabeled` for unlabeled children; done once every child is closed |

A unit is `conflicted` when GitHub reports that its PR does not merge cleanly into its base (`mergeable` false,
`mergeable_state` `dirty`); a mergeability GitHub has not computed yet is not a conflict. GitHub runs no
`pull_request` checks on a PR it cannot merge, so a conflicting PR's checks are pending with nothing running, or are the
results of an earlier head. `conflicted` therefore comes before every CI and review phase: before `ci_running`,
`ci_red`, `review_pending`, `green_unreviewed`, and `approved`. Its `resume` points at the conflict and the base, and
carries `--base` for a stacked PR (§10); the worker merges the base into the branch and pushes without force (a rebase
would need a force-push). Review
comments or findings newer than the `review` cursor ride the same `resume`, with their cursor. A conflict has no cursor:
it is a state of the PR, not an item, so it is new for as long as it lasts. A `resume` that pushes a merge ends it; one
that is still there after that push means the base moved again, and the `resume` attempt limit bounds the repeats
(D030).

"Authorized reply" means a comment by an account in `trust.authorized_repliers`, matched on the tracker's stable account
identifier, never a display name, that is not a worker's (§8: one carrying the configured comment marks). A worker's
comment is never review feedback either. If the tracker cannot say when a label was added, the worker's question comment
is the reference point instead of the label. Anything else on the ticket is data, not instruction. See TRUST_MODEL.

**Trusted reviewers** (D089). Review feedback is a PR's reviews, review comments, and requested changes, and canopy's
own review findings (§21). `trust.trusted_reviewers`, user-only, lists whose feedback a worker may address without the
operator's go-ahead: VCS host logins, matched in full and case-insensitively, and `canopy:review` for canopy's own
review runs, which post nothing and are known only from the journal (§21).
It is empty by default: nobody is trusted until listed, so a review bot's comment never starts a fixup on its own.

- A trusted reviewer's feedback newer than the unit's `review` cursor is `changes_requested` (or `review_findings`), and
  the overseer classifies it as before: concrete changes go to a `resume`, design questions to `needs_author`.
- Anyone else's is `untrusted_review`: the overseer records the attention item every tick, naming the PR, the
  reviewers, and the newest item, and does not move the `review` cursor past it. It never dispatches for it on its own
  judgment. A trusted reviewer's feedback on the same unit still goes to a worker, with the cursor no further than the
  item before the first untrusted one.
- The operator answers in canopy, with `canopy reply KEY` or the web UI (§22), never on the ticket. An operator message
  newer than the ticket's message cursor is an instruction, like an authorized reply. When it speaks to the untrusted
  feedback, however loosely ("use your best judgement on the bot's review"), the ticket is `human_replied`: a `resume`
  whose context names the message and the review items, carrying `--cursor message=` and `--cursor review=`. When it
  says to leave the feedback, the overseer moves both cursors with `canopy ticket set`.
- The resume worker's prompt names the trusted reviewers (`{{TRUSTED_REVIEWERS}}`) and carries the operator's messages
  (`{{OPERATOR_MESSAGES}}` on a public ticket, `{{CONVERSATION}}` on a private one, §22). It addresses a review comment
  by anyone else only as an operator message about it says, and otherwise leaves it alone and says so in its summary:
  the overseer's classification is checked again by the worker, as labels are (D051). The review comment stays data
  either way; the operator's message is the instruction.

Which reviewer wrote a comment is read by agents through the VCS host's MCP server, so the gate is the overseer's
judgment, checked again by the worker: the harness cannot tell a review comment's author (D003). What it can check, it
does: only the operator's channels write operator messages, and the cursors advance only with a run that starts.

A private ticket (§22), one the operator started with `canopy start`, needs no label, and its own phases come from the
journal: `needs_human` when its latest run ended `blocked` and no operator message came after it, `human_replied` when
an operator message is newer than its message cursor. Its PR phases are as above.

Cursors (`comment`, `review`, `ci`, and a private ticket's `message`, a journal message id) hold the newest item of each
kind the loop has handled, in the tracker's and GitHub's own ids, except `review`, which holds a time (below); "newer
than cursor" means not handled yet. The comment cursor is the ticket's; the review and ci cursors are each unit's, since
each unit has its own PR. `canopy ticket set` names the unit with `--repo`, and a dispatch that carries one names
exactly one repository. A dispatch that handles new
items carries their cursors (`--cursor`, §8), so they advance only if the worker starts. Items handled by a wait, a
done, or an attention item advance with `canopy ticket set`. A review comment waiting on a human is not advanced past,
so its attention item is recorded every tick until a human answers it.

The `review` cursor is the time of the newest review feedback handled, in UTC as `YYYY-MM-DDTHH:MM:SSZ`: a review's
`submitted_at`, an inline review comment's `created_at`, or, for canopy's own review run (§21), its `reviewed_at`, the
run's end to the second. GitHub numbers reviews and review comments separately, and review runs are canopy's own, so no
id orders all three. In that one form, times compare as strings; an item at the cursor's own second is handled, as a
review's inline comments share its second. `--cursor review=` refuses any other form, so a cursor the overseer writes is
always comparable. A cursor an earlier canopy wrote is an id, or `run:<id>`; the overseer is told to look up that item's
time and write it, and to treat a cursor that names nothing as empty. Until it has, that unit's review state is as
ambiguous as before.

"Closed" means whatever the tracker calls finished: Jira status category Done, GitHub issue state closed, and so on. The
provider skill says which.

## 8. Dispatch and the worker contract

`canopy dispatch <KEY> --label LABEL --kind implement|fix-ci|resume|split [--repo NAME]... [--slug SLUG] [--base BRANCH]
[--request COMMENT_ID] [--context TEXT] [--cursor NAME=ID]...`:

Each `--repo` names a unit of the ticket, its work in one repository (§18); naming several makes a joint run. Every
dispatch names at least one, in a workspace of one repository too.

1. Check the guards. They are in code and not overridable from the prompt. A refusal is recorded as a decision
   `refused:<guard>` with the reason, and the command exits 1. A dry run checks the same guards and stops, counting
   each dry-run dispatch already recorded this tick as a running run for `running` and `capacity` (§6, D036). In
   order:
   - `unauthorized`: no `--label`, or one not in `tracker.labels`, compared case-insensitively. The decision records
     the label in its configured spelling; the refusal does not list the configured labels. This does not prove the
     label is on the ticket; the worker's own read is the independent check (step 3, D051). A `split` without
     `--request` is refused here too (§18). A started ticket (§22) needs no `--label`: its start record is checked
     instead, in code, and a `--label` given for it is ignored.
   - `stopped`: the ticket's start record is stopped (§22), whatever label is passed. `private`: a `split` of a
     started ticket, since a split creates tickets in the tracker. `no_read_tools`: a started ticket when no tracker
     tools are known for its worker (§22).
   - `bad_request`: `--request` on a kind other than `split`.
   - `unknown_repo`: no `--repo`, or one not in the map or with no primary clone; for a split's child, any repository
     but the one the split recorded for it. Naming a repository the ticket has no unit in yet adds that unit (§18,
     D058). A repository named twice is one unit. A `--repo` that is not a repository name at all (`[a-z][a-z0-9-]*`) is
     a usage error, like a bad key.
   - `bad_split`: a `split` naming fewer than two repositories, for a ticket with a branch, or
     for a split's child; and any dispatch for a ticket a split already made children of (§18). A split's `--slug` is
     `bad_slug` and its `--base` `bad_base`.
   - `bad_slug`: a slug that is not lowercase words joined by hyphens; any `--slug` with `fix-ci` or `resume`; or, on
     a later `implement`, a `--slug` naming another branch than the ticket's. The ticket's first `implement` names its
     branch, and every later dispatch continues it in every unit (D058).
   - `no_branch`: `fix-ci` or `resume` for a ticket with no `tickets.branch`, or naming a unit no `implement` has
     covered.
   - `bad_base`: a `--base` that is not `<trust.branch_prefix>` plus one plain ref component (letters, digits, `_`,
     `-`, starting with a letter or digit, at most 200 characters), or that is the run's own branch (§10).
   - `running`: a run for KEY is running.
   - `attempt_limit`: a named unit has already had as many runs of this kind as its limit: `policy.max_<kind>_attempts`
     plus the runs the operator granted that unit with `canopy grant` (§22). A run counts against every unit it
     covered, whatever it ended as; the count never resets (D030). A split's count and limit are the ticket's, and
     only config raises it. The refusal also records the `attempt_limit` attention item (§14), about that unit.
   - `cooldown`: `fix-ci` only, less than `policy.fix_ci_cooldown_minutes` after the latest fix-ci run covering a named
     unit ended.
   - `capacity`: `max_workers` runs and review runs, together, are running (§21).

   Later failures are recorded the same way: `no_slot` (a lease failed, or would grow a workspace's pool past its
   declared size, §18), `bad_prompt` (the worker prompt did not render), `spawn_failed`. None leaves a slot leased:
   leases are all or nothing, so when any repository's `get` fails, slots already leased for the dispatch are returned
   before the refusal is recorded. A `get` that exits 0 with unparseable output is `no_slot` too: canopy returns the
   slot at once if it can read the path, lease id, and holder; if not, the rationale says so and the next reconcile
   returns it (§6 step 3). A blocking `flock` on `<state_dir>/dispatch.lock`, held from the guard checks through the
   spawn, serializes dispatches so two cannot both pass the capacity check or the attempt limit. `--cursor NAME=ID`
   pairs are applied as `canopy ticket set` would, only once the worker has started, so what a refused dispatch was
   meant to handle stays new for the next tick.
2. `treehouse get --lease --lease-holder canopy:<KEY> --json` in each named repository's pool (§18). Record the `runs`
   row (kind, branch, started_at, whether it is private) and a `run_slots` row per slot (repository, slot path, lease
   id, holder, and base branch: `--base` if given, else treehouse's). Each repository becomes a unit of the ticket, with
   the run's branch.
3. Render the worker prompt for the kind with: KEY, tracker provider, branch name, PR label, needs-human label, timeout,
   the attempt number (one more than the most runs of the kind in any unit covered) and that unit's limit, a
   `{{REPOSITORIES}}` section listing each repository's path, base branch, journaled PR, and summary, the authorized
   repliers, the trusted reviewers and, on a public ticket, the operator's latest messages (§7), the queue labels,
   whether the run is stacked on another ticket's branch (§10), how to open a PR (`{{OPEN_PR}}`, below), the context,
   and the result contract below, whose `prs` skeleton (`{{PRS}}`) names each repository.
   - Every worker reads the ticket first and, if it is closed or carries none of the queue labels, reports `failed`
     with a summary starting `not authorized:` and changes nothing. That run counts toward the attempt limit.
   - The branch is `<trust.branch_prefix><KEY>-<slug>`, named by the first `implement`. The overseer picks the slug
     from the ticket title: lowercase words joined by single hyphens, at most 40 characters, `work` if none is given.
   - The context is the overseer's `--context`: at most 2000 characters pointing at what to read (links, comment ids,
     check names), never a copy of ticket or PR text, which would invite injection, and never a file, whose path
     could pull any file the operator can read into the prompt. The worker reads that text itself and checks a reply's
     author against the authorized repliers, rendered from the user config.
   - Placeholders are `{{NAME}}`, replaced in one pass. An unknown one is `bad_prompt`, as is a worker prompt without
     `{{LABELS}}`, so an older override fails closed (D051). A joint run's prompt also needs `{{REPOSITORIES}}` and
     `{{PRS}}`, its worker's only way to learn its repositories; an override without them still serves runs in one
     repository. For older overrides, `{{SLOT}}` is the worker's working directory and `{{BASE}}` and `{{PR_URL}}` the
     one repository's base and PR. With `runtime.pr_skill` set, an `implement` or `resume` prompt without
     `{{OPEN_PR}}` is `bad_prompt` too, so an override that still names the GitHub MCP fails closed. A public
     ticket's prompt without `{{OPERATOR_MESSAGES}}` is `bad_prompt` once the operator has written to the ticket in
     canopy (§22, D093), and still renders for a ticket the operator never wrote to.
   - A started ticket's run renders the kind's private variant, `worker-<kind>-private.md` (§22): no label check, no
     tracker writes, and `{{CONVERSATION}}`, the ticket's latest journal messages, which an override must keep.
     The start record is read again in the transaction that inserts the run, so a `canopy stop` that commits first
     refuses the dispatch (`stopped`) and its leases are returned.
   - The prompt is written to `<state_dir>/runs/<run_id>.prompt`, readable only by the operator.
4. Spawn `python -m canopy _run <run_id>` with canopy's own interpreter, detached (`setsid`, stdin from `/dev/null`,
   stdout and stderr appended to `<state_dir>/runs/<run_id>.log`, cwd the workspace root). Record its
   pid in the run and return immediately.

`canopy _run <run_id>` (hidden from `--help`):

1. Claim the run: set its pid to this process's, only if the run is `running` and its pid is unset or already this
   pid; refuse otherwise, so the overseer cannot start a second worker on a run. Drop `CANOPY_TICK_ID` from the
   environment so the worker cannot act as the dispatching tick's overseer. Read the ticket's start record again
   (§22): a private run whose ticket was stopped since, or a public run whose ticket was started privately since, ends
   `stopped` before any git step, and its slots are returned.
2. Before any git step, read each slot's `.git` file, a worktree's link to the pool's git directory, and record it in
   `run_slots.git_link`, and make the run's object directory, `<state_dir>/runs/<id>.objects/` (below). In each slot:
   `git fetch --prune origin`, then `git checkout --detach origin/<branch>` if it exists, else
   `git checkout --detach origin/<base>`. No run makes a local branch: a pool's slots share the repository's branch
   refs, so one would be state every slot sees, and the worker pushes HEAD by refspec (D109). Detached, a bare
   `git push` has no branch to target under git's default `push.default`; under `matching`, or with a
   `remote.origin.push`, it pushes what those name, which is why the prompts push by refspec. A local branch of the
   run's name that an earlier canopy left, and that origin's branch (or the base) already holds, is deleted; one with
   commits origin lacks is kept. Note HEAD's commit and the length of HEAD's reflog. A base missing from origin (such as
   a stacked-on branch deleted when its PR merged) fails the run as `crashed` before the worker starts, with a note,
   whether the branch is new or continued. Then, with `runtime.setup_cmd` set, run it in each slot in turn (§9):
   cwd the slot, `CANOPY_REPO` the repository's name, `CANOPY_BRANCH` the run's branch (HEAD is detached, so git does
   not name it), `CANOPY_RUN_ID` the run's id, `CANOPY_GIT_OBJECTS` the object directory, timeout
   `runtime.setup_timeout_minutes`, output appended to the run log. An exit other than 0, a timeout, or a command that
   cannot start fails the run as `crashed` before the worker starts, with a note naming the repository in a workspace;
   the slots are returned as on any exit (step 6).
3. Run `worker_cmd` (`private_worker_cmd` for a private run, §22), timeout `worker_timeout_minutes`, with
   `CANOPY_RUN_ID` set to the run's id, `CANOPY_GIT_OBJECTS` to the object directory, and cwd = the slot, or for a
   joint run the desk (§18), which
   `_run` makes now with one link per slot. Record the worker's pid in `runs.worker_pid`; the worker leads its own
   process group. Its stdout and stderr go to the run log.
4. Parse the last non-empty line of the worker's text as the result contract: its stdout, or the text of OpenCode's
   JSON events (§13). Missing or invalid means `status='unknown'`; a timeout means `status='timeout'`. Record the
   session id and cost the events reported on the run at once, also after a timeout, so a git failure after this step
   does not lose them.

   A split (§18) differs: step 2 checks each slot out at its base, detached, with no branch, and runs no setup, since
   the splitter has no shell; step 3 runs `split_cmd` in the desk; step 4 parses and validates the split's result;
   step 5 is skipped, since a split pushes nothing.
5. If any slot's `.git` file no longer holds what step 2 read, record `status='crashed'`, with a note naming each such
   slot, and run no git in any slot of the run: the file may now point at a git directory the worker made, which would
   take host git past D107's flags.
   Otherwise, if the worker left anything in the object directory, git in each slot from here on reads it as well as the
   slot's own objects (`GIT_OBJECT_DIRECTORY` and `GIT_ALTERNATE_OBJECT_DIRECTORIES`), and a push puts origin's
   remote-tracking ref, which every slot shares, back as it was: pointed at a commit only the run's directory holds, it
   would break git in every slot once that directory goes. In each slot, verify the branch is pushed
   (`git ls-remote origin refs/heads/<branch>` equals HEAD). If not and HEAD holds commits past step 2's, push once,
   without force: `git push origin HEAD:refs/heads/<branch>`. Then, since HEAD alone holds a detached worker's commits,
   look in HEAD's reflog entries since step 2 for commits that neither HEAD, origin's branch, nor any of origin's
   branches holds: a worker that checked something else out left them behind. If any slot's push failed or left commits
   behind, record `status='unpushed'`, naming each repository in a workspace: the checkpoint invariant failed and a
   human looks.
6. Always: remove a joint run's desk, tidy each slot (`runs/tidy.py`): put back its `.git` file if the run changed it,
   and, if the object directory holds anything, check it out detached at `origin/<base>` with `--force`, delete its own
   refs (`refs/worktree/*`, `refs/bisect/*`, `refs/rewritten/*`), `ORIG_HEAD`, and `FETCH_HEAD`, and expire its HEAD
   reflog, so nothing in it names an object only that directory holds; then
   `treehouse return --force --if-lease-id <id> --if-lease-holder <holder> <slot>` for every slot, in its repository's
   pool. A trap runs this on any exit path: normal exit, exception, and SIGTERM, SIGHUP, or SIGINT (the run is then
   `crashed`). Then delete the object directory. A slot that cannot be tidied is not returned, and the directory is kept
   for the operator. SIGKILL cannot be trapped; reconcile tidies and returns that run's slots from what step 2 recorded.
7. Update the `runs` row: ended_at, status, result_json, and in the same transaction record the run's messages about
   its ticket (§22): a `report`, its summary (else the harness's note, else the status) with each PR on a line, and
   for a `blocked` run its `question`. A git failure before or after the worker is `crashed`.
   `result_json` holds the validated result, text fields cut at 2000 characters, plus a `harness` note saying why the
   status differs from what the worker reported. `prs` is kept to the run's repositories, or filled from `pr` for a
   run in one; each plain `https://` URL is copied to its unit's `pr_url`, for display and the next run's prompt.

Every git the harness runs, here, in a review (§21), and in `canopy init` and `canopy workspace sync`, goes through
`core/hostgit.py`, which adds `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c fetch.recurseSubmodules=false
-c protocol.ext.allow=never` (D107). A slot shares its git directory with the pool and the primary clone, and a worker
can write there, so without them a hook or monitor it planted would run on the host, outside the worker, in step 2 or
5 or in a later run or review. A command named in that directory's config (a filter driver,
`remote.<name>.uploadpack`) still runs; closing that takes a git directory the worker cannot write (HOST_ISOLATION
§4.2). The worker's own git is unaffected, so its push runs the repository's hooks; step 5's fallback push runs none,
so a repository whose push needs one (Git LFS's `pre-push`) depends on the worker pushing.

The object directory is for a sandboxed worker (HOST_ISOLATION §4.2), which cannot write the git directory its slot
shares, objects included. `_run` passes it as `CANOPY_GIT_OBJECTS` and never sets git's own variables for the worker:
those reach every git its tools run, so a commit in any other repository would land there and break that repository
once the directory goes. A sandbox wrapper, which knows its worker is sandboxed, points git at it. An unsandboxed
worker ignores it, the directory stays empty, and steps 5 and 6 run as if it did not exist. Rejected: deleting the
directory without tidying the slots (git in the slot, and `gc` in the primary clone, then fail); letting a sandboxed
worker write the shared object directory (it could delete objects other slots need); a temporary directory (reconcile
could not find it after a SIGKILL).

Worker result contract, one JSON line, last line of the worker's text (§13):

```json
{"status":"done|blocked|failed","branch":"agent/KEY-slug","prs":{"api":"https://...|null"},
 "summary":"one paragraph","question":"only when blocked"}
```

`prs` maps each repository the run worked in to its PR. A single-URL `pr`, as older prompt overrides print, is still
read for a run in one repository.

Worker obligations, stated in every worker prompt:

- Work only inside the worktree, or a joint run's desk. Push only to `agent/<KEY>-*`, never with force, once per
  repository, as `git push origin HEAD:refs/heads/<branch>` from the detached HEAD; create no local branch. A resume
  that merges its base merges `origin/<base>`, which step 2 fetched, and does not fetch.
- Keep the runtime's attribution trailer on commits, or add a `Co-authored-by: canopy worker` trailer (TRUST_MODEL T5).
- Mark every comment and reply it posts, on the ticket or a PR: start it with `trust.comment_prefix` (`CANOPY:` by
  default) and end it with `trust.comment_suffix` (empty by default), each when it is set (D069). Below.
- Open each PR through the GitHub MCP, or, with `runtime.pr_skill` set, only with that skill (below).
- Comment on the ticket describing what was done and linking every PR. In a joint run, each PR's body links its sibling
  PRs and says which merges first.
- On `blocked`: post the question as a ticket comment, add `needs_human_label`, and push nothing half-finished or
  speculative beyond a WIP commit. A private ticket's worker posts nothing on the ticket: its result line's `summary`
  and `question` are its report and question (§22).
- Never approve, merge, close PRs, or transition the ticket to Done, including indirectly: no closing keywords
  (`Fixes #12`) or tracker commands (Jira smart commits) in commit messages, PR titles, or PR bodies.
- Push once. Do not poll CI. Do not retry.

Everything posts as the operator (D010), who is usually an authorized replier, so without a mark a worker's PR reply
would read back as new review feedback and spend a `resume` attempt, and its ticket comment could pass for an
authorized reply. A comment that carries every mark set, starting with the prefix if there is one and ending with the
suffix if there is one, outside any quote, is a worker's, whoever its author. The overseer, which reads the marks from
the state block's `trust`, and workers never read one as an authorized reply, a split request, or review feedback: it
makes no ticket `human_replied` or `changes_requested`, is not a new comment for `green_unreviewed`, and needs no
handling, so a cursor may advance past it (§7). The marks can only take authority away, so they need no protection:
anyone who marks a comment of theirs only silences it, and a comment without them is judged as before. They are plain
text, which every tracker's markup keeps as written (Jira's would show or drop an HTML comment), and they tell a person
reading the PR or ticket what wrote the comment. The harness never reads comments; the marks are for the agents that
do. Worker prompts get them as `{{MARK_COMMENTS}}`, the instruction to mark, and `{{WORKER_COMMENT}}`, how to recognize
a marked comment. Changing the marks leaves earlier workers' comments reading as the operator's. A prompt override
without the placeholders still renders, and its workers' comments read as the operator's, as they all did before D069.

How a worker opens a PR is the one step an operator may need done their own way: an employer's tooling that adds
metadata, a stacked-PR tool, or a host the GitHub MCP serves badly. It is the operator's skill, not a harness command
that opens PRs, which would put VCS knowledge in code. `runtime.pr_skill`, user-only, names a skill
of the operator's, which `implement` and `resume` workers then open every PR with, and in no other way; with it unset
they use the GitHub MCP. Workers get the instruction as `{{OPEN_PR}}`. A skill that is not available fails the run: the
worker opens no PR and reports `failed` with a summary starting `no PR skill:`, rather than falling back to the MCP
whose PRs the operator set the skill to avoid. The skill is ordinary customization (§13): it sits where the runtime
reads skills, under a name no repository canopy works in uses, since OpenCode picks either of two same-named skills and
a repository's could stand in for the operator's. Any program it runs must be on the `PATH` of the shell that runs
canopy, which workers inherit. It changes only how the PR is opened; every other obligation above still holds. The
branch is `{{BRANCH}}`, pushed without force, and `_run` still checks it is on origin (step 5). A program that pushes by
itself is past the bash rules, which match the command text, so branch protection governs (TRUST_MODEL T1). The PR
targets the listed base, carries the ticket key and `trust.pr_label` with no closing keywords, and its URL goes in the
result's `prs`. The overseer and later workers still read the PR through the GitHub MCP, so it must be one that server
can read. `fix-ci` and `split` open no PRs and ignore the key. Updating an existing PR, such as retargeting a stacked
one, stays with the MCP.

## 9. Aggressive release

- Slots are held only for the duration of `_run`.
- Reacquisition lands on an arbitrary slot, so build caches must be slot-independent: for Bazel, a shared disk cache
  or a remote one (below), configured in the operator's or the repository's `.bazelrc`, not in canopy. canopy
  documents this; it does not manage it.
- In a workspace, the operator may declare each pool's size; `canopy workspace sync` makes the slots ahead of time, so
  their hooks and build caches are warm before the first run lands in one (§18).

### Setting up a slot

Three steps, all the operator's, in the order they run:

1. **Seeding.** On every `get`, a reused slot's too, treehouse copies ignored files from the primary clone into the
   slot: those the committed `.worktreeinclude` selects, or, with `paths.worktree_include` set, those the operator's
   own manifest selects instead. canopy passes it as `--include-file`, by its absolute path, on every lease: a run's,
   a review's, and sync's. treehouse reads one manifest, so a personal one replaces the committed one; copy in the
   committed lines to keep them. Its lines are git's exclude-file patterns and select only ignored files, so it can
   seed local config (`user.bazelrc`, `.env.local`) and never a tracked file. A missing file fails the lease, `no_slot`
   (§8), before treehouse touches a slot.
2. **`post_create` hooks**, in the user-level treehouse config, run after seeding when a slot is made or reused: on
   the base, before `_run` checks out the run's branch. A failing hook is printed and the lease stands. They suit
   setup that depends on the base alone, such as a toolchain or a warm fetch.
3. **`runtime.setup_cmd`**, user-only, runs in each slot of a worker run after `_run` checks out its branch (§8
   `_run` step 2), and fails the run when it fails. It suits setup that depends on the branch or must succeed:
   installing the branch's dependencies, generating code its build needs. It is split into words as `notify.cmd` is,
   with no shell and no placeholders; one command serves every repository, telling them apart by `CANOPY_REPO` (§8).
   Splits and reviews run none: their agents have no shell.

`setup_cmd` runs the branch's code (a lockfile's install scripts, a generator) on the operator's machine, outside the
agent runtime's permissions. It is the code the worker's own shell runs a moment later, but outside any sandbox around
`worker_cmd`, so it is wrapped the same way (HOST_ISOLATION §4.4, TRUST_MODEL T4). A broken setup crashes every run it
meets, each spending an attempt (D030) and raising `crashed` (§14), whose note names it.

### Bazel

The operator's guide, with a `.bazelrc` recipe, examples of each setup step, sizing, and checks, is
[BAZEL.md](../BAZEL.md). What canopy relies on:

- Bazel keys a workspace's output base on the workspace's path. Slots keep their paths across leases, so each slot's
  output base stays warm for whichever run leases it next. Slots share work only through what the operator's
  `.bazelrc` shares: a disk cache and a repository cache, or a remote cache.
- canopy does not stop a slot's Bazel server when it returns the slot: the harness knows no build tool. The
  operator's `startup --max_idle_secs` ends it once no run has used the slot for that long, so a run that reuses the
  slot soon after finds it warm.
- `bazel-out/`, `bazel-bin/`, and `bazel-testlogs/` are links from the slot into its output base, outside the
  worktree. The worker's `external_directory: deny` is checked against the path as written, as the desk canary found
  for edits (ROADMAP M7), so the worker reads its outputs and test logs through the links and is refused the output
  base by its own path. That is no boundary: the worker's shell reads either (HOST_ISOLATION §1). The canary
  (`tests/canopy/test_opencode_canary.py`) checks it; it is opt-in, and its first real run confirms it.

## 10. Dependencies and stacking

- The overseer reads blocker relations through MCP, in whatever form the tracker has them (Jira "is blocked by" links,
  GitHub issue dependencies; the provider skill says where to look). A blocker is resolved when it is closed. Other
  relations (relates to, parent and child) are not blockers; a tracker without blocker relations leaves every ticket
  unblocked. A relation is data: it can delay work, never authorize it.
- A ticket with an unresolved blocker and no branch of its own is `blocked`. The overseer records `wait` with rationale
  `blocked_by: <KEY>`, unless it stacks the ticket.
- Stacking: `canopy dispatch <KEY> --label <label> --kind implement --base <blocker's branch>` starts the worker from
  the blocker's branch, and the worker opens its PR against that branch, so the PR shows only this ticket's commits.
  The overseer stacks only on a ticket's single unresolved blocker, only when the blocker's PR is open, not merged, and
  green, and reads the blocker's branch from that PR, not from the journal.
- `policy.stacking` (§12) defaults to `"auto"`: the overseer stacks when the conditions above hold. `"never"`: a
  blocked ticket waits until its blocker has landed (closed, and its PR merged if it had one). A blocker whose PR
  closed without merging never landed; the blocked ticket gets `needs_author` attention instead of a dispatch.
  `"never"` governs starting a ticket; one already stacked keeps its stacked PR, `resume`, and `fix-ci`. The state
  block carries it with the other policy and the overseer prompt follows it. The harness adds no guard: a
  `--base` dispatch under `"never"` is not refused.
- The harness checks only the shape of `--base` (`bad_base`, §8): under `trust.branch_prefix`, so a PR cannot target
  a release branch, and not the run's own branch. It does not look the base up in the journal (the blocker may be in
  another operator's queue) and cannot read
  PR state (D003). `_run` fails a run whose base is not on origin (§8 `_run` step 2).
- The base is not remembered. Every dispatch starts from `--base` if given, else the pool's base branch, in every
  repository it names, and the run records each (`run_slots.base_branch`, shown in the latest run's `repos` in the
  state block). While the blocker's PR is open, the overseer passes the same `--base` to the stacked ticket's `resume`
  and `fix-ci`. Once it merges, a `resume` without `--base` tells the worker to retarget the PR to the repository's
  base branch, merging that branch in if it conflicts. Workers never rebase, since their pushes never force.
- Ordering is decided by the overseer each tick from live state and recorded in `decisions`. There is no plan file
  and no DAG config.
