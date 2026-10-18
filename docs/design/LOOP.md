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
2. Apply pending migrations. Close any tick still `running` as `abandoned`: holding the lock proves its process is
   gone. Record the tick, with the version of canopy running it, which its decisions name through their tick. The
   version is read once as the process starts, so a `canopy loop` running across an upgrade records the code it runs,
   not the code installed. Its id tags all logs. Migrations wait while any running worker, chore, or review run's own
   process is alive, since it writes the old schema; so does the error for a journal with migrations this canopy does
   not know (D068). Until then, the tick and any command that opens the journal fail saying so.
3. **Reconcile local state.**
   - Each running run whose `canopy _run` process is gone (below): kill what is left of the worker's process group,
     mark the run `crashed`, return every slot it leased with `treehouse return --force --if-lease-id`, remove its
     desk if it was a joint run, and log it.
   - Each leased slot in `treehouse status --json` held under our prefix with no live run: return it and log it. In a
     workspace this covers every cloned repository's pool (§18). A desk canopy made whose ticket has no running run is
     removed; anything else under `desks/` is left alone.
   - Each running chore run whose `_chore` is gone: kill what is left of its agent and mark it `crashed` (§19). Chore
     runs hold no slot and take no worker capacity.
   - Each running review run whose `_review` is gone: kill what is left of its reviewer, remove its directory, return
     its slot, and mark it `crashed` (§21). This runs before the worker runs' reconcile, and a running review's lease
     is never returned as stale.
   - Each pending memory proposal written more than 14 days ago expires, in every mode (§28).
   - Each PR a draft waits on is read, and its drafts checked against what a whole read returned (§29).
   - `capacity = max_workers - (running runs + running review runs)`: a review holds a slot.
   - If `treehouse status` or a return fails, close the tick as `reconcile_failed` and stop; the overseer does not run.
   - Record on the tick the newest journal message and the time: everything up to that point was there for this tick
     to read. The latest `ok` tick's point is what the web UI calls acknowledged (§22); idle pacing reads it (below).
   - Record as this tick's decisions the harness's attention items for runs (§14), `awaiting_reply` for each started
     ticket whose latest question has no operator message after it (§22), and for each public ticket whose latest plan
     run asked one (§25), `chore_failed` for each configured chore whose latest ended run did not end `ok` (§19), and
     `repo_missing` for each mapped repository with no clone.
4. **Render the state block**, the overseer's whole message: a generated `## State` section holding one compact JSON
   object on one line, since it is re-read on every step. The overseer's prompt (`prompts/overseer.md` or the
   operator's override, §12) is not in it but is the body of the overseer's agent definition (§13), sent as the system
   prompt, so a tick soon after the last reads prompt and tools from the provider's cache and writes only the block
   fresh (MEASUREMENTS 2026-10-13, F11). The tracker's provider skill, when canopy ships one, rides along in the
   definition, saving a tool call every tick.

   The object holds, from what changes rarely to what changes every tick (for a runtime that caches part of a
   message): the workspace and its map; tracker, trust, and policy config; the repositories (§18); the tickets not
   marked done, except stopped ones, each with its phase, branch, cursors, units (§18), latest run, and, if started, its
   operator messages and pending question (§22); `stopped`; `recently_done` (§7); split children (§18); chores and
   reviews when configured; recent notices to workers (§8); the overseer's open attention items; then capacity,
   running workers, the mirror limit and delimiter (§22), whether this tick runs the tracker query (`query_due`, §7),
   tick id, time, and whether it is a dry run. `stopped` names stopped tickets by key alone: none is a candidate and
   the overseer records nothing for one, so a ticket stopped for weeks adds no decision to every tick.

   `attention` lists the open items the overseer recorded (§14), without their detail, which may quote a comment; the
   harness's and chores' items are left out, since the overseer never records them. An item stays open only while
   every tick records it again, and without the list the overseer dropped items it could not see (MEASUREMENTS
   2026-10-13 F17). So the prompt has it record each again unless it saw this tick that the cause is gone, and end a
   tick that could not read a cause as `mcp_unavailable`. Rejected: a harness that keeps an item until the overseer
   resolves it, which needs a resolve verb anyway and leaves an item standing whenever the overseer forgets one.
5. **Check `canopy`, then run the overseer.** The overseer acts only through `canopy`, so a tick first runs
   `canopy --version` as the overseer would find it: from the tick's PATH, in the workspace root, with
   `CANOPY_TICK_ID` set, for at most 60 seconds. If it fails, the tick records `attention:canopy_unavailable` with
   why, closes as `canopy_unavailable`, and the overseer does not run, rather than pay to read the whole world with no
   way to record anything (MEASUREMENTS 2026-10-12, F1). Like any tick that is not `ok`, it leaves the attention list
   standing, and adds its one item while it is the latest tick (§14), so the operator hears at once. It is not idle.
   Rejected: putting this canopy's launcher first on the overseer's PATH, which misses a launcher whose environment is
   gone, cannot find the launcher reliably for every install method, and overrides the operator's PATH. The launcher
   answers `--version` without importing the CLI, so the check is cheap and proves the launcher and its environment
   start, not that every dependency imports.

   Then run the overseer with `overseer_cmd`, cwd the workspace root (§18), timeout `overseer_timeout_minutes`, and
   `CANOPY_TICK_ID` set. `canopy dispatch`, `decide`, `queried`, `attention`, and `mirror` refuse if it is unset or
   names a tick that is not running (D020). Its output goes to `<state_dir>/ticks/<tick id>.log` as it prints it, its
   stderr after once it ends, readable only by the operator, never to the journal. Its session is recorded as soon as
   it prints one, what it has spent at each model call's end, and session and cost (§13) again when it ends. It
   succeeded if it exited 0 and a line of its final message (§13), trimmed of whitespace and backticks, is exactly
   `CANOPY_TICK_DONE`; otherwise the tick closes as `overseer_failed`. Text around that line is
   allowed, since models summarize and a tick lost on its summary is lost to the attention list (MEASUREMENTS
   2026-10-12, F2). The check is on the final message because it catches a run that exits 0 short of the last step (a
   refused tool call, a cut-off session); the token is a word no model writes by chance. A successful run that recorded
   a tick-wide `skip` (`mcp_unavailable`, `tracker_unsupported`) closes the tick `skipped`, which leaves the attention
   list standing, so an outage does not resolve and re-raise every item.

   **The overseer's duties.** A successful run is then checked for the duties a tick owes: a `queried` decision when
   `query_due` was true; a decision of its own (not a mirror) for every ticket in the block's `tickets` and every
   ticket `queried` names, except those in `stopped` or `recently_done`; and a chore run, wait, or refusal for every
   chore due and not running. A duty left undone closes the tick as `overseer_failed`, naming each one. Closed `ok`,
   its list would become the attention list, resolving every item of a ticket it left out, and a query it never ran
   would count as run; failed, the list stands, the query stays due, and the next block carries every ticket left out.
   Its dispatches stand. A ticket that entered the journal while the overseer ran is owed nothing until the next tick.
   Why: the prompt alone did not hold a cheaper overseer to the procedure; it skipped the query, which stalls new work
   with no tick failing (MEASUREMENTS 2026-10-15 F31). The check sees that each duty was done, not done well; that
   waits on a connector (ROADMAP M36, M37). Duties it cannot see (mirroring, re-recording attention items, titles,
   cursors, `review.query`) the prompt lists beside the checked ones, as equally binding.

   `canopy queried [KEY]...` records, as one tick-wide decision, that the tick ran the tracker query and which open
   tickets it returned, if any. It touches each into the journal at once (§11), so the next block has it even if this
   tick ends without deciding it. A result too large for one decision is refused and recorded in several calls. It is a
   quiet decision for idle pacing, as a wait is.

   In `--dry-run` (D036), the state block says so. `canopy dispatch` checks the live guards (§8), counting this dry
   run's recorded dispatches as running, and records refusals as usual; an allowed dispatch starts nothing and is
   recorded as `dispatch:<kind>` saying what it would work on. `canopy ticket set` records phases but advances no
   cursor and marks nothing done; `canopy mirror` moves no mirror cursor. The rest of the tick is live: reconcile, and
   the attention list and its notifications.

   `canopy decide` takes `wait`, `skip`, or `done`; only a tick-wide `skip` omits the key. Its rationale must give a
   tick-wide reason (`mcp_unavailable`, `tracker_unsupported`), and a ticket's skip may not give one. Why: an overseer
   left to guess the form put a tick-wide reason under a made-up key (`queue`) on ticks whose tracker worked, and on
   one of them ended at the skip with every ticket undecided. What the overseer writes is rendered into the next
   prompt, so the CLI bounds it: keys and attention reasons are validated, phases come from §7's table, cursor ids must
   match `[A-Za-z0-9][A-Za-z0-9_.:/-]*`, and rationales, details, and worker context are cut at 2000 characters.
6. Close the tick with a summary.
7. **Publish attention** (§14): rewrite `attention.md` from the journal, then deliver to each notification sink (§20)
   the list's change since that sink last heard, the events it takes, and a digest when due; `notify.cmd` is the sink
   `default`. This follows the close because the list is the latest `ok` tick's, which may be this one; after a failed
   or skipped tick it is the one before. A failure here is logged and does not change the tick's status. Release the
   lock.

Workers dispatched during a tick outlive it, as detached processes owned by `canopy _run`.

A detached process (`_run`, `_chore`, `_review`) is alive exactly while it holds its lifelock, an `flock` on
`<id>.lock` beside its `<id>.log`. The spawn takes it before the process exists, so it is held before the pid is
recorded, and the kernel releases it however the process exits. Nothing the process starts inherits it, so a worker
left running after its `_run` died does not keep the run alive, and reconcile kills it. A second spawn on the same log
is refused while the first holds it. A pid alone could not tell a reused pid or a zombie from a live process without
`/proc`; it remains the fallback for a run from before lifelocks. The file is removed once the run is closed, never
earlier. Every kind of detached run shares this lifecycle and crash rule, adding only what is its own (a worker's
messages and slots, a review's slot); a new kind joins that set rather than copying it.

### The loop

`canopy loop` is how ticks are meant to run (D042), in the foreground until stopped:

1. Take `<state_dir>/loop.lock`; if another loop holds it, refuse and exit 1. Each tick still takes the separate tick
   lock (step 1 above), so a hand-run `canopy tick` runs between the loop's ticks or finds the lock busy.
2. Apply pending migrations before the first tick. Start the web UI's server in a thread, unless `--no-serve` or
   `serve.enabled = false`; without a usable listener secret, say why and serve nothing (§22). With `--defer`, wait
   that many minutes before the first tick. That wait ends early as the one in step 5 does, by an operator message (no
   sooner than `loop.min_gap_minutes` after the loop started) or `t`, and a stop during it ends the loop with no tick.
3. Run a tick exactly as `canopy tick` does, passing `--dry-run` through. An error the tick code does not handle ends
   that tick as `error` in the loop's output; the traceback goes to the log and the loop goes on. The next tick closes
   the row left `running` as `abandoned`.
4. Print the tick's status, summary, decisions other than waits, attention items added and resolved, running workers,
   and what the overseer cost when the runtime reported it (§13), and the wait that follows.
5. Wait, measured from the end of the tick, for `--every`, else `loop.interval_minutes`, whatever the tick's status,
   lengthened after idle ticks and ended at a gate (Idle pacing, below). Pacing does not read tick cost (ROADMAP M13,
   deferred). An operator message recorded since the tick began, such as a `canopy reply`, ends the wait early (§22);
   so does a run ending (below). The wait never ends sooner than `loop.min_gap_minutes` (private, default 1) after the
   tick began, whatever ended it, which bounds how often the overseer runs: a burst of messages, runs ending one after
   another, or a gate opening just after a tick would otherwise run ticks back to back. On a terminal, pressing `t`
   ends it at once, with no floor (a keypress is deliberate, as a hand-run `canopy tick` is); keys pressed during the
   tick are dropped, except `p` (below). Tick now in the web UI (§22) does the same, but one asked for during a tick is
   kept, and ends the wait after it at once: a click is not stray input the way a key typed at a spinner can be. Like
   a reload, the request is for this process alone, with no journal row. While the loop is paused, the wait does not
   end at its deadline (Pausing, below).
6. Repeat from 3 until `--ticks N` ticks have run or the operator stops the loop.

Pausing: the operator can hold the loop's ticks without stopping it, so the web UI stays up and dispatched workers keep
going.

- The pause is a journal fact (§11), so every channel writes the same one: `p` at the loop's terminal, `canopy pause`
  and `canopy resume`, and the web UI (§22), each recording its channel. It outlives the loop, lifted only by a resume.
- Paused, the wait does not end at its deadline, on an operator message, or on a run ending, though those still move
  the deadline (step 5), so a resume past it ticks at once. A tick running when a pause comes finishes. A loop started
  while paused holds its first tick. `t`, or Tick now in the web UI, runs one tick and the loop stays paused, as a
  hand-run `canopy tick` does.
- `canopy pause` and `canopy resume` refuse inside canopy's own ticks and runs (`inside_run`), as `start` and `reply`
  do: an agent that could pause the loop could hold off every tick after its own, and one that could resume it could
  undo the operator's pause (TRUST_MODEL T1).
- Only the loop reads the pause; a hand-run or cron-run `canopy tick` ignores it. Rejected: holding the pause in the
  loop's memory (lost on a restart, and unreachable from the CLI); stopping the workers too (`canopy stop --now` does
  that per ticket).

Stopping: SIGINT (Ctrl-C) or SIGTERM during the wait ends the loop at once. During a tick, the first lets the tick
finish and ends the loop without waiting; both exit 0. A second aborts the tick: the overseer's process group is killed
as on a timeout, the command exits 1, and the next tick closes the row as `abandoned`. A signal within a second of the
first is the same keypress. The web UI's server stops with the loop. SIGHUP does not stop the loop but reloads its
config (below), unless the terminal hung up.

- After a Ctrl-C, the loop starts no tick but waits for the runs still running (workers, reviews, chores) to end,
  naming them, with the web UI still served. A run whose own process is gone does not count: it never ends by itself,
  and the next tick's reconcile closes it. A second Ctrl-C ends the wait and leaves the runs running; either way the
  loop exits 0.
- SIGTERM does not wait for runs, so `canopy daemon stop` returns once the tick ends, not once every worker has.
- Runs are detached (§8), so stopping the loop never stops one; `canopy stop --now` does, per ticket.

Reloading config: SIGHUP or Reload in the web UI makes the loop read the workspace, user, and private files again
(§12), so a change needs no restart: the next tick's limits, the pace, and what the web UI serves. `--every` still
holds; `serve.*` keys and the listener secret take a restart (§22).

- A running tick finishes on the config it started with; a wait applies it at once, keeping its own length. A reload
  never starts a tick: editing config is not a request for a tick.
- A config that does not load leaves the loop on the one it had, saying why; the web UI refuses it (`config_invalid`).
- A terminal hanging up sends SIGHUP too, and then the loop ends at once. Under `nohup` it reloads instead, since that
  loop is meant to outlive its terminal; with no controlling terminal, as under a service manager, every SIGHUP is a
  reload.
- Every `canopy` command the overseer and workers run reads the files itself, so a reload changes nothing about what
  those can do.
- Rejected: reading the files before every tick (a half-saved edit would apply itself; the operator chooses when), and
  a journal row for the request, as the pause has (the request is for this process alone, and a signal reaches it from
  any shell).

Detached: `canopy daemon start [LOOP OPTIONS]` runs the same loop, with the options `canopy loop` takes, in its own
session from the workspace root, so it outlives the terminal and the shell that started it (D042).

- It is started as dispatch starts `_run` (§8): the interpreter running canopy, in the environment of the shell that
  ran `start`, so the agents find what a loop in that shell would. Its output is appended to
  `<state_dir>/daemon.log`, and a lifelock beside the log for its whole life, which is what says it runs. Its pid is in
  `daemon.pid`, for `stop` to signal; a pid alone is never taken to mean it runs.
- `start` refuses while the daemon runs or another loop holds `loop.lock`, and waits until the loop takes that lock. A
  loop that exits first, on a config error or an option `canopy loop` refuses, fails the start with what it printed.
- `stop` sends SIGTERM, so the loop ends as Stopping (above) says: at once during the wait, once the running tick
  finishes otherwise, and `stop` waits for that. `status` says whether it runs, since when, and where its output is,
  and tells a daemon that ended without `stop` apart from one never started.
- With no controlling terminal, its output is plain text, no keys are read, and every SIGHUP is a reload.
- `start` and `stop` refuse inside canopy's own ticks and runs (`inside_run`), as `pause` does: the overseer may run
  any `canopy` command, and one that could stop the loop could end every tick after its own (TRUST_MODEL T1).
- Nothing is installed with the OS and nothing restarts it: a daemon that ends, or a reboot, leaves the loop stopped
  until the operator starts it again. Its log is appended to across starts and never trimmed.
- Rejected: launchd or systemd units (an install step, which the operator did not want); restarting it on failure
  (a loop that exits on a config error would restart into the same error).

Prompt files are read every tick.

Output uses rich (D043): on a terminal, a spinner during a tick and a countdown during the wait; to a file or pipe,
plain text, one block per tick. Keys are read only when stdin and stdout are a terminal the loop holds in the
foreground; otherwise none are read or mentioned.

### Idle pacing

ROADMAP M21. A tick that finds nothing new costs a full overseer run and buys nothing, and most ticks overnight and at
weekends are like that. So the loop waits longer after each idle tick in a row, and wakes early on the events that end
idleness that it can see itself. It does not poll GitHub or the tracker from Python (D003), run a cheaper pre-check
agent, keep quiet hours, or take webhooks (TRUST_MODEL T8).

A tick is **idle** when all of these hold, each read from the journal:

- It closed `ok`. Any other status is not idle and resets the count: a failing tick keeps today's pacing.
- Its decisions are only `wait`, a ticket's `skip`, attention items, and refusals that lift by themselves: `running`,
  `capacity`, and `chore_capacity` (on a run ending), `cooldown`, `not_due`, and `outside_hours` (at a known time,
  below), and `attempt_limit` (never). Any dispatch, `done`, `mirror` (a new tracker comment), or other refusal makes
  it not idle.
- The attention list after it is the list before it.
- No ticket or unit changed its phase, branch, a cursor, or `done`, and no ticket was seen for the first time.
- Nothing reached the journal after the previous tick read it (§6 step 3): no run, chore run, or review run started or
  ended, and the operator recorded no message, started or stopped no ticket, granted nothing, and set or cleared no
  notice (§8). Something the previous tick could not have seen keeps this one from counting as idle, even when it
  happened while that tick was still running. A previous tick that never read the journal (`reconcile_failed`, or none
  at all) makes this one not idle.

The wait after a tick is then:

- `base` (`--every`, else `loop.interval_minutes`) after a tick that is not idle;
- after the n-th idle tick in a row, `max(base, min(base * 2^n, loop.idle_max_minutes))`. With the defaults, 30, 60,
  120, then 120 for as long as nothing changes. It is never shorter than `base`, so idle pacing is off whenever the
  cap is not above `base`. Off, the loop waits `base` after every tick, no gate shortens it, and only the operator's
  acts wake it (§22).

`loop.idle_max_minutes` (private, default 120) is at least `loop.interval_minutes` when set; left unset under a longer
interval, idle pacing is off. The count lives in the loop, not the journal: a restarted loop starts at `base`, and a
hand-run `canopy tick` between the loop's ticks counts like any other.

Whatever pacing chose, the wait ends no later than the earliest harness gate still ahead, as the state block shows it:
the CI cooldown's end (§8), a configured chore's `due_at` (§19), and the lapse of the notice in force (§8). A gate
opening is acted on when it opens, even sooner than `base`, though no sooner than `loop.min_gap_minutes` after the tick
began. A gate already open, such as a chore the overseer passed over, sets no deadline, so it cannot make the loop
spin.

Besides the operator's acts (§22), the wait ends early, with the same floor, when a run, chore run, or review run ended
after the tick read the journal. The tick that follows is not idle, so the wait after it is `base` again and the tick
after that looks for CI on a worker's push at today's pace: a long wait never sits on canopy's own work.

What idle pacing cannot see is the world: a teammate's review or a PR's CI going red is picked up at the next tick, up
to `loop.idle_max_minutes` late. That cap is the trade, and the operator's knob. A sink's digest (§20) can lag as much.

Churn (ROADMAP M28) is a tick that relabels a phase, or adds or drops an attention item, with nothing new to see:
nothing reached the journal and no gate came due since the tick before read it. A churned tick is not idle, so it
resets the count (MEASUREMENTS 2026-10-12 F5, 2026-10-13 F17). It is measured before it is fixed: the log lists each
`ok` tick's churn. It cannot tell a flap from the world or config changing; the `decisions` table can, by the
rationales either side, and prompt changes follow only when it shows a pattern.

For spend (ROADMAP M33; `canopy spend`, §11, and the web UI, §22), the journal records on each tick the loop ran
whether it was idle and what ended the wait before it (the timer, a gate, a message, a start or stop, a grant, a
notice, a run ending, or a key), as if there were no pause. The loop classifies every tick even with idle pacing off,
so the journal says what the overseer's spend bought whatever the pacing. A tick the loop did not run records neither,
since only the loop reads the journal before the tick.

## 7. Ticket phases and next actions

The overseer derives phases each tick from live state. They are recorded for the status view, never read back as
truth. A ticket's own phase is recorded only when the overseer runs `canopy ticket set --phase`, so the status view
and the web UI fall back on the newest decision since the ticket was last forgotten, and say `not seen by a tick yet`
when there is none. The PR phases, `pushed_no_pr` to `merged`, are a unit's (§18): `canopy ticket set` needs `--repo`
for one.

A ticket's title is its name in canopy, for display only like its phase: a few words from the ticket's own title,
set with `canopy ticket set --title` when the block shows none or the ticket's own title changes. The CLI drops control
characters, makes it one line, refuses an empty one, and cuts it at 80 characters. It names the ticket in canopy's
views and its runs' sessions (§13), and rides in `json` notifications (§20), where, being model-written, the Slack sink
escapes it; it stays out of `attention.md` and the `text` format. `canopy forget` keeps it.

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
| `split` | a split's parent (§18) | wait; `split_unlabeled` for unlabeled children; done once every child is closed |

A PR's checks are its head commit's check runs, which is all GitHub Actions writes, and its commit statuses only
beside them, for CI that writes statuses: statuses alone read an Actions repository as pending forever, with nothing
written, and a red PR waits instead of getting its `resume`.

A unit is `conflicted` when GitHub reports that its PR does not merge cleanly into its base; a mergeability not yet
computed is not a conflict. GitHub runs no `pull_request` checks on a PR it cannot merge, so `conflicted` comes before
every CI and review phase. Its `resume` points at the conflict and the base, with `--base` for a stacked PR (§10), and
carries any review items newer than the `review` cursor; the worker merges the base in, or with `trust.rebase` rebases
(§8 worker obligations). A conflict has no cursor: it is a state of the PR, new for as long as it lasts. One still
there after a pushed merge means the base moved again, and the `resume` attempt limit bounds the repeats (D030).

"Authorized reply" means a comment by an account in `trust.authorized_repliers`, matched on the tracker's stable account
identifier, never a display name, that is not a worker's (§8: one carrying the configured comment marks). A worker's
comment is never review feedback either. If the tracker cannot say when a label was added, the worker's question comment
is the reference point instead of the label. Anything else on the ticket is data, not instruction. See TRUST_MODEL.

**Trusted reviewers** (D089). Review feedback is a PR's reviews, review comments, and requested changes, and canopy's
own review findings (§21). `trust.trusted_reviewers`, private, lists whose feedback a worker may address without the
operator's go-ahead: VCS host logins, matched in full and case-insensitively, and `canopy:review` for canopy's own
review runs, which post nothing and are known only from the journal (§21). It is empty by default: nobody is trusted
until listed, so a review bot's comment never starts a fixup on its own.

- A trusted reviewer's feedback newer than the unit's `review` cursor is `changes_requested` (or `review_findings`):
  concrete changes go to a `resume`, design questions to `needs_author`.
- Anyone else's is `untrusted_review`: the overseer records the attention item every tick, naming the PR, the
  reviewers, and the newest item, does not move the `review` cursor past it, and never dispatches for it on its own
  judgment. A trusted reviewer's feedback on the same unit still goes to a worker, with the cursor no further than the
  item before the first untrusted one.
- An untrusted reviewer's approving review, its body included, is not feedback: it asks for nothing. Its inline
  comments are feedback like any other. The overseer moves the cursor past such an approval when nothing before it
  waits.
- The operator answers in canopy, with `canopy reply KEY` or the web UI (§22), never on the ticket. An operator message
  newer than the ticket's message cursor is an instruction, like an authorized reply. When it speaks to the untrusted
  feedback, however loosely, the ticket is `human_replied`: a `resume` naming the message and the review items,
  carrying both the `message` and `review` cursors. When it says to leave the feedback, the overseer moves both
  cursors with `canopy ticket set`.
- The resume worker's prompt names the trusted reviewers and carries the operator's messages (§22). It addresses a
  review comment by anyone else only as an operator message says, and otherwise leaves it alone and says so: the
  overseer's classification is checked again by the worker, as labels are (D051). The review comment stays data
  either way; the operator's message is the instruction.

Which reviewer wrote a comment is read by agents through the VCS host's MCP server, so the gate is the overseer's
judgment, checked again by the worker: the harness cannot tell a review comment's author (D003). What it can check, it
does: only the operator's channels write operator messages, and the cursors advance only with a run that starts.

A private ticket (§22), one the operator started with `canopy start`, needs no label, and its own phases come from the
journal: `needs_human` when its latest run ended `blocked` and no operator message came after it, `human_replied` when
an operator message is newer than its message cursor. Its PR phases are as above.

Cursors (`comment`, `review`, `ci`, and a private ticket's `message`) hold the newest item of each kind the loop has
handled, in the tracker's and GitHub's own ids, except `review`, which holds a time (below); "newer than cursor" means
not handled yet. The comment cursor is the ticket's; the review and ci cursors are each unit's, since each unit has its
own PR, so a dispatch that carries one names exactly one repository. A dispatch that handles new items carries their
cursors (`--cursor`, §8), so they advance only if the worker starts. Items handled by a wait, a done, or an attention
item advance with `canopy ticket set`. A review comment waiting on a human is not advanced past, so its attention item
is recorded every tick until a human answers it.

The `review` cursor is the time of the newest review feedback handled, in UTC as `YYYY-MM-DDTHH:MM:SSZ`: a review's
submission, an inline comment's creation, or the end of canopy's own review run (§21). GitHub numbers reviews and review
comments separately, and review runs are canopy's own, so no id orders all three; in that one form, times compare as
strings. An item at the cursor's own second is handled, as a review's inline comments share its second.
`--cursor review=` refuses any other form. A cursor an earlier canopy wrote as an id: the overseer looks up that item's
time and writes it, and treats a cursor that names nothing as empty.

The overseer runs the configured query every tick it is due, before it reads any ticket, even when the state block
already lists tickets. The block holds only tickets the loop has seen, so the query is the only way a newly labeled
ticket becomes a candidate, and a tick that skips it finds nothing wrong and closes `ok`: the queue stalls with nothing
failing, as it did with a cheaper overseer (MEASUREMENTS 2026-10-15 F31). It records the result with `canopy queried`,
and a tick whose block said the query was due fails without one (§6 step 5); a connector running the query in code
(ROADMAP M36) would also check the result is complete.

**Spacing the query.** The query is one of a tick's dearest reads (MEASUREMENTS 2026-10-13), and tickets enter the
queue slowly. So the operator may space it out with `tracker.query_every_minutes`. At 0, the default, every tick runs
it. Otherwise the state block's `query_due` is true only when that long has passed since the start of the newest live
tick that closed `ok` with `query_due` true, or when there is none. A dry run does not count as having run it, nor does
a tick that skipped or failed, which may not have read the result to the end. On a tick where it is false, the overseer
works the block's tickets alone, by the same rules: reads each, mirrors its comments, follows its PRs, and dispatches
it. What the operator gives up is how soon a newly labeled ticket is found: up to `query_every_minutes`, plus the
loop's wait. Idle pacing does not treat the next query as a gate: the setting is the least time between queries, not a
schedule. A ticket the operator starts is in the block already, so it never waits on the query. `review.query` is not
spaced: it is the operator's own list of PRs, and its cost has not been measured apart.

"Closed" means whatever the tracker calls finished: Jira status category Done, GitHub issue state closed, and so on. The
provider skill says which.

A closed ticket is not a candidate and has no phase: the overseer marks it done (decision `done`, rationale `closed`,
then `canopy ticket set --done`, so a tick cut off between the two records the decision again rather than losing it),
whatever its labels, branch, or PR, unless a worker is running for it, which it waits out. Otherwise a ticket closed
before `merged` would stay in the block and get a `skip` every tick. A closed ticket that only the query returns gets no
decision at all, so a query that matches closed tickets adds nothing to every tick. A PR still open on a closed ticket
is the operator's, like the tracker transition. A reopened ticket is found again by the query; a private one (§22)
comes back when the operator starts it again, which clears done.

A ticket marked done is not in `tickets`, so the block alone cannot tell the overseer that one the query returns is
finished. The common case is a merged ticket a human has not yet closed in the tracker: the overseer read it again each
tick, mirrored its comments again, and recorded `done` again, so no tick was idle and idle pacing never backed off. So
`recently_done` names each ticket marked done in the last 30 days, and the overseer leaves it out and records nothing
for it, whatever the tracker says. A ticket still open 30 days after its `done` decision drops out; the next tick marks
it done again, which lists it for another 30 days. The window bounds the list by the tickets a human might not have
closed yet.

Not listed: a ticket whose newest `done` has the rationale `closed`, which the rule above already passes over, so once
reopened the query finds it again; and a ticket marked done with no `done` decision since the operator last forgot it
(§22). A merged ticket reopened for follow-up is left out while listed; the operator brings it back with
`canopy forget`, which clears the done mark.

## 8. Dispatch and the worker contract

`canopy dispatch <KEY> --label LABEL --kind implement|resume|split|plan [--repo NAME]... [--reason REASON]...
[--slug SLUG] [--base BRANCH] [--request COMMENT_ID] [--context TEXT] [--cursor NAME=ID]...`:

Each `--repo` names a unit of the ticket, its work in one repository (§18); naming several makes a joint run. Every
dispatch names at least one, in a workspace of one repository too. A `plan` writes the ticket's plan before its first
`implement`, and runs as a split does, with guards of its own (§25).

1. Check the guards. They are in code and not overridable from the prompt. A refusal is recorded as a decision
   `refused:<guard>` with the reason, and the command exits 1. A dry run checks the same guards and stops, counting
   each dry-run dispatch already recorded this tick as a running run (§6, D036). In order:
   - `bad_kind`: `--kind fix-ci`, naming `resume --reason ci`: a `resume` fixes CI (below). The value stays among the
     run kinds only so the runs earlier canopy made still read.
   - `unauthorized`: no `--label`, or one not in `tracker.labels`, compared case-insensitively. The refusal does not
     list the configured labels. This does not prove the label is on the ticket; the worker's own read is the
     independent check (step 3, D051). A `split` without `--request` is refused here too (§18). A started ticket (§22)
     needs no `--label`: its start record is checked instead, and a `--label` given for it is ignored.
   - `stopped`: the ticket's start record is stopped (§22), whatever label is passed. `private`: a `split` of a
     started ticket, since a split creates tickets in the tracker. `no_read_tools`: a started ticket when no tracker
     tools are known for its worker (§22), or a labeled one its dispatch would start under `tracker.private`.
   - `bad_request`: `--request` on a kind other than `split`.
   - `bad_reason`: a `resume` with no `--reason`; a `--reason` on any other kind; a cursor without its reason (`ci` for
     `--cursor ci=`, `review` for `--cursor review=` and `--review-run`, `reply` for `--cursor comment=` and
     `message=`); or `retarget` with `--base`, which says the blocker is still open (One resume for what comes back to a
     PR, below).
   - `unknown_repo`: no `--repo`, or one not in the map or with no primary clone; for a split's child, any repository
     but the one the split recorded for it. Naming a repository the ticket has no unit in yet adds that unit (§18,
     D058). A `--repo` that is not a repository name at all is a usage error.
   - `bad_split`: a `split` naming fewer than two repositories, for a ticket with a branch, or for a split's child; and
     any dispatch for a ticket a split already made children of (§18). A split's `--slug` is `bad_slug` and its
     `--base` `bad_base`.
   - `bad_slug`: a slug that is not lowercase words joined by hyphens; any `--slug` with `resume`; or, on
     a later `implement`, a `--slug` naming another branch than the ticket's. The ticket's first `implement` names its
     branch, and every later dispatch continues it in every unit (D058).
   - `no_branch`: `resume` for a ticket with no branch, or naming a unit no `implement` has covered.
   - `bad_base`: a `--base` that is not `<trust.branch_prefix>` plus one plain ref component, or that is the run's own
     branch (§10).
   - `running`: a run for KEY is running.
   - `attempt_limit`: a named unit has already had as many runs of this kind as its limit: `policy.max_<kind>_attempts`
     plus the runs the operator granted that unit with `canopy grant` (§22). A run counts against every unit it
     covered, whatever it ended as; the count never resets (D030). A split's count and limit are the ticket's, and
     only config raises it. The refusal also records the `attempt_limit` attention item (§14), about that unit.
   - `cooldown`: a `resume` whose only reason is `ci`, less than `policy.ci_cooldown_minutes` after the latest run
     covering a named unit that worked on CI ended (below).
   - `capacity`: `max_workers` runs and review runs, together, are running (§21).

   Later failures are recorded the same way: `no_slot` (a lease failed, or would grow a workspace's pool past its
   declared size, §18), `bad_prompt` (the worker prompt did not render), `spawn_failed`. None leaves a slot leased:
   leases are all or nothing, so slots already leased for the dispatch are returned before the refusal is recorded. A
   lease whose output cannot be parsed is `no_slot` too, and its slot is returned at once if possible, else by the next
   reconcile (§6 step 3). A lock held from the guard checks through the spawn serializes dispatches, so two cannot both
   pass the capacity check or the attempt limit. `--cursor` pairs are applied only once the worker has started, so
   what a refused dispatch was meant to handle stays new for the next tick.
2. `treehouse get --lease --lease-holder canopy:<KEY> --json` in each named repository's pool (§18). Record the run and
   each slot it leased, with its base branch: `--base` if given, else treehouse's. Each repository becomes a unit of
   the ticket, with the run's branch.
3. Render the worker prompt for the kind: the ticket and tracker, the branch, the attempt number and limit, each
   repository's path, base, PR, and summary, the authorized repliers and trusted reviewers, the operator's latest
   messages on a public ticket (§7), the queue labels, whether the run is stacked (§10), how to open a PR (below), the
   context, and the result contract below, with a `prs` entry for each repository.
   - Every worker reads the ticket first and, if it is closed or carries none of the queue labels, reports `failed`
     with a summary starting `not authorized:` and changes nothing. That run counts toward the attempt limit.
   - The branch is `<trust.branch_prefix><KEY>-<slug>`, named by the first `implement`. The overseer picks the slug
     from the ticket title: at most 40 characters, `work` if none is given.
   - The context is the overseer's `--context`: at most 2000 characters pointing at what to read (links, comment ids,
     check names), never a copy of ticket or PR text, which would invite injection, and never a file, whose path
     could pull any file the operator can read into the prompt. The worker reads that text itself and checks a reply's
     author against the authorized repliers, rendered from the operator's config.
   - Placeholders are `{{NAME}}`, replaced in one pass. An unknown one is `bad_prompt`. So is a prompt override that
     lacks a placeholder carrying a check or an operator instruction the run needs, so an older override fails closed
     rather than silently drop it: `{{LABELS}}` always (D051); `{{REPOSITORIES}}` and `{{PRS}}` for a joint run;
     `{{OPEN_PR}}` in `implement` and `resume` with `runtime.pr_skill` set; `{{OPERATOR_MESSAGES}}` on a public ticket
     once the operator has written to it (§22, D093); `{{STANDING_INSTRUCTIONS}}` with that file set;
     `{{NOTICE}}` while a notice is in force; `{{BRANCH_UPDATE}}` with `trust.rebase`; in `implement` and
     `resume`, `{{COMMIT_ATTRIBUTION}}` or `{{COMMIT_TRAILER}}` once the trailer's name or address is changed, and
     `{{COMMIT_ATTRIBUTION}}` once the trailer is off. Older single-repository placeholders still render.
   - Every prompt but a split's carries the standing instructions, the operator's file `paths.worker_instructions`
     (§12), or `None.` without one; a file that is missing, not UTF-8, or over 4 KiB is `bad_prompt`, since a worker
     without it would work as if the operator had never written it. It is the operator's own text, an instruction like
     their messages, and the prompt's obligations come before it. Every prompt but a split's carries the notice in
     force, or `None.` (Notices to workers, below).
   - A public ticket's `implement` and `resume` prompts carry its latest three ended runs since any forget,
     each with its kind, how it ended, and its report and question (step 7). Each run starts a fresh session (below), so
     this is how a worker learns what the runs before it concluded. A report is worker text, so the prompt calls it data
     to check against the branch and PR, and keeps it off the ticket and PRs, since it may repeat the operator's
     messages. A private ticket's prompt has the same reports in its conversation. An override without it still renders.
   - Every `implement` and `resume` prompt says how to attribute commits: keep the runtime's trailer, or add
     the one from `trust.commit_trailer_name` and `trust.commit_trailer_email` (§12); with `trust.commit_trailer` off,
     add none.
   - A started ticket's run renders the kind's private variant, `worker-<kind>-private.md` (§22): no label check, no
     tracker writes, and the ticket's latest journal messages, which an override must keep. The start record is read
     again in the transaction that inserts the run, so a `canopy stop` that commits first refuses the dispatch
     (`stopped`) and its leases are returned. Under `tracker.private`, a labeled ticket's first dispatch writes the
     record and its run is private from the first (§22).
   - The prompt is written to `<state_dir>/runs/<run_id>.prompt`, readable only by the operator.
4. Spawn `python -m canopy _run <run_id>` with canopy's own interpreter, detached (`setsid`, stdin from `/dev/null`,
   output appended to `<state_dir>/runs/<run_id>.log`, cwd the workspace root), holding its lifelock (§6). Record its
   pid and return immediately.

`canopy _run <run_id>` (hidden from `--help`):

1. Claim the run: take it only if it is `running` and unclaimed or already this process's, so the overseer cannot
   start a second worker on a run. Drop `CANOPY_TICK_ID` from the environment so the worker cannot act as the
   dispatching tick's overseer. Read the ticket's start record again (§22): a private run whose ticket was stopped
   since, or a public run whose ticket was started privately since, ends `stopped` before any git step, and its slots
   are returned.
2. Before any git step, record each slot's `.git` link to the pool's git directory, and make the run's object
   directory, `<state_dir>/runs/<id>.objects/` (below). In each slot, fetch origin and check out `origin/<branch>`
   detached if it exists, else `origin/<base>`. No run makes a local branch: a pool's slots share the repository's
   branch refs, so one would be state every slot sees; the worker pushes HEAD by refspec (D109). A local branch of the
   run's name an earlier canopy left is deleted if origin already holds it, and kept if it has commits origin lacks.
   A base missing from origin (such as a stacked-on branch deleted when its PR merged) fails the run as `crashed`
   before the worker starts. Then, with `runtime.setup_cmd` set, run it in each slot in turn (§9), with cwd the slot,
   `CANOPY_REPO` the repository's name, `CANOPY_BRANCH` the run's branch (HEAD is detached), `CANOPY_RUN_ID`, and
   `CANOPY_GIT_OBJECTS` the object directory, timeout `runtime.setup_timeout_minutes`, output appended to the run log.
   A failure or timeout fails the run as `crashed` before the worker starts, naming the repository. An `implement` or
   `resume` for a ticket with an approved plan then gets its copy, `.canopy-plan.md`, checked against the approved
   hash (§25, The worker's copy); step 6 removes it, and step 5 notes a pushed branch that holds it.
3. Run `worker_cmd` (`private_worker_cmd` for a private run, §22), timeout `worker_timeout_minutes`, with
   `CANOPY_RUN_ID` and `CANOPY_GIT_OBJECTS` set, and cwd the slot, or for a joint run the desk (§18), which `_run` makes
   now with one link per slot. The worker leads its own process group, and its pid is recorded. Its output goes to the
   run log as it prints it. While it runs, `_run` records on the run what its events (§13) report so far: its session,
   its spend, and its latest tool call, so a running run shows more than `running` in `canopy status` and the web UI
   (§22). A write the journal refuses is logged and passed over, since raising would kill the worker.
4. Parse the last line of the worker's text that starts with `{` as the result contract (§13). Missing or invalid
   means `status='unknown'`; a timeout means `status='timeout'`. Record the session id and cost at once, also after a
   timeout, so a git failure after this step does not lose them.

   A split (§18) differs: step 2 checks each slot out at its base, detached, with no branch, and runs no setup, since
   the splitter has no shell; step 3 runs `split_cmd` in the desk; step 4 parses and validates the split's result;
   step 5 is skipped, since a split pushes nothing.
5. If any slot's `.git` link no longer holds what step 2 read, or the `commondir` in the git directory it names has
   changed, record `status='crashed'`, naming each such file, and run no git in any slot of the run: either may now
   point at a git directory the worker made, which would take host git past D107's flags.
   Otherwise git here also reads the run's object directory, and a push leaves the remote-tracking ref every slot
   shares as it was, since a ref to a commit only that directory holds would break every slot once it goes. In each
   slot, verify the branch is pushed (origin's branch equals HEAD). If not and HEAD holds commits past step 2's, push
   once, without force. With `trust.rebase`, the push leases the commit origin's branch held at step 2: a worker that
   rebased and did not push gets its work pushed, and a push anyone else made since is never overwritten. Then look
   for commits the worker made and left on no branch origin holds, such as by checking something else out, unless
   origin's branch already has the same change. If any push failed or left commits behind, record
   `status='unpushed'`, naming each repository: the checkpoint invariant failed and a human looks.
6. Always: remove a joint run's desk, and tidy each slot: put back its `.git` link and `commondir` if the run changed
   them, and, if the object directory holds anything, check the slot out detached at `origin/<base>` and drop its own
   refs and reflog, so nothing in it names an object only that directory holds; then return every slot with
   `treehouse return --force --if-lease-id <id> --if-lease-holder <holder>` in its repository's pool. A trap runs this
   on any exit path: normal exit, exception, and SIGTERM, SIGHUP, or SIGINT (the run is then `crashed`). Then delete
   the object directory. A slot that cannot be tidied is not returned, and the directory is kept for the operator.
   SIGKILL cannot be trapped; reconcile tidies and returns that run's slots from what step 2 recorded.
7. Close the run with its end time, status, and result, and in the same transaction record its messages about its ticket
   (§22), what it wrote of agent memory while a tier was on (§28), and its drafts under `approve` (§29): a `report`
   (its summary, else the harness's note, else the status, with each PR on a line), and for a `blocked` run its
   `question`. A git failure before or after the
   worker is `crashed`. The stored result is the validated one, text fields cut at 2000 characters, plus a `harness`
   note saying why the status differs from what the worker reported. `prs` is kept to the run's repositories; each plain
   `https://` URL becomes its unit's PR, for display and the next run's prompt, and its title in `pr_titles`, if any,
   is kept by that URL, replacing the one an earlier run reported.

Every git the harness runs, here, in a review (§21), and in `canopy init` and `canopy workspace sync`, runs with hooks,
the filesystem monitor, submodule fetches, and the `ext::` transport turned off (D107). A slot shares its git directory
with the pool and the primary clone, and a worker can write there, so without that a hook or monitor it planted would
run on the host, outside the worker, in step 2 or 5 or in a later run or review. A command named in that directory's
config (a filter driver, `remote.<name>.uploadpack`) still runs; closing that takes a git directory the worker cannot
write (§24, Git state). The worker's own git is unaffected, so its push runs the repository's hooks; step 5's fallback
push runs none, so a repository whose push needs one (Git LFS's `pre-push`) depends on the worker pushing. Git's
automatic background maintenance is off too, in the harness's git and, through `canopy workspace sync`, in each
primary clone's config (§18), so it never runs on the shared directory while other slots' runs use it.

The object directory is for a sandboxed worker (§24, Git state), which cannot write the git directory its slot shares,
objects included. `_run` passes it as `CANOPY_GIT_OBJECTS` and never sets git's own variables for the worker: those
reach every git its tools run, so a commit in any other repository would land there and break once the directory goes.
A sandbox wrapper points git at it, in the run's worktrees only. An unsandboxed worker ignores it, and steps 5 and 6
run as if it did not exist. Rejected: deleting the directory without tidying the slots (git in the slot, and `gc` in
the primary clone, then fail); letting a sandboxed worker write the shared object directory (it could delete objects
other slots need); a temporary directory (reconcile could not find it after a SIGKILL).

Worker result contract, one JSON line, last line of the worker's text (§13):

```json
{"status":"done|blocked|failed","branch":"agent/KEY-slug","prs":{"api":"https://...|null"},
 "pr_titles":{"api":"KEY: ...|null"},"summary":"one paragraph","question":"only when blocked"}
```

`prs` maps each repository the run worked in to its PR. A single-URL `pr`, as older prompt overrides print, is still
read for a run in one repository. `pr_titles` maps the same repositories to each PR's title as it stands, which need
not be the ticket's: a worker names its PR for the change it made, and a resume may rename it. Only `implement` and
`resume` prompts ask for it, as `{{PR_TITLES}}`, since only they open or reword PRs; it is optional, so an override
without it still records its PRs, untitled. A title is one line of at most 256 characters, GitHub's own limit, and is
for display only: the harness never reads it back, and the overseer and later workers read the PR itself. It is kept
by the PR's URL rather than on the unit, so `canopy forget`, which drops the unit, leaves it, as it leaves the PR's
reviews; a reviewer reports it too (§21), and the newest report wins.

Worker obligations, stated in every worker prompt:

- Work only inside the worktree, or a joint run's desk. Push only to `agent/<KEY>-*`, never with force, as
  `git push origin HEAD:refs/heads/<branch>` from the detached HEAD; create no local branch. A worker that brings its
  base in merges `origin/<base>`, which step 2 fetched, and does not fetch. With `trust.rebase`, it rebases onto
  `origin/<base>` instead, never merging, and pushes with `git push --force-with-lease origin HEAD:refs/heads/<branch>`:
  the one force the worker's definition then allows (TRUST_MODEL T1).
- Keep the runtime's attribution trailer on commits, or add canopy's: `Co-authored-by: canopy worker
  <noreply@canopy.invalid>` by default, with the name and address from `trust.commit_trailer_name` and
  `trust.commit_trailer_email` (§12, TRUST_MODEL T5). With `trust.commit_trailer` off, add none.
- Mark every comment and reply it posts, on the ticket or a PR: start it with `trust.comment_prefix` (`CANOPY:` by
  default) and end it with `trust.comment_suffix` (empty by default), each when it is set (D069). Below. Under
  `trust.review_replies = "approve"` it posts none on a PR, and on the ticket only without a tracker source that
  posts: it drafts each in its result's `drafts` instead, for the operator to send (§29).
- Open each PR through the GitHub MCP, or, with `runtime.pr_skill` set, only with that skill (below).
- Comment on the ticket describing what was done and linking every PR. In a joint run, each PR's body links its sibling
  PRs and says which merges first.
- A `resume` worker, once its pushes are done, reads the body of each PR it pushed to or retargeted, and edits it only
  where the body is now untrue of the PR or leaves out a change to behavior a reviewer must know of. It changes only
  those sentences, never the title, and never edits a body to restyle it or recount the run: a reviewer reads every
  edit, and the run's account is its replies and summary.
- On `blocked`: post the question as a ticket comment, add `needs_human_label`, and push nothing half-finished or
  speculative beyond a WIP commit. A private ticket's worker posts nothing on the ticket: its result line's `summary`
  and `question` are its report and question (§22).
- Never approve, merge, close PRs, or transition the ticket to Done, including indirectly: no closing keywords
  (`Fixes #12`) or tracker commands (Jira smart commits) in commit messages, PR titles, or PR bodies.
- Push again for anything fixed after a push, in a new commit, never an amend (D116). Do not poll CI. Do not retry a
  rejected push.

Everything posts as the operator (D010), who is usually an authorized replier, so without a mark a worker's PR reply
would read back as new review feedback and spend a `resume` attempt, and its ticket comment could pass for an
authorized reply. A comment that carries every mark set, outside any quote, is a worker's, whoever its author. The
overseer and workers never read one as an authorized reply, a split request, or review feedback, so it needs no
handling and a cursor may advance past it (§7). The marks can only take authority away, so they need no protection:
anyone who marks a comment only silences it. They are plain text, which every tracker's markup keeps, and tell a
person what wrote the comment. The harness never reads comments; the marks are for the agents that do. Changing the
marks, or a prompt override without them, leaves those workers' comments reading as the operator's.

How a worker opens a PR is the one step an operator may need done their own way: an employer's tooling, a stacked-PR
tool, or a host the GitHub MCP serves badly. So it is the operator's skill, not a harness command, which would put VCS
knowledge in code. `runtime.pr_skill`, private, names a skill that `implement` and `resume` workers then open every PR
with, and in no other way; unset, they use the GitHub MCP. A skill that is not available fails the run (`failed`, with
a summary starting `no PR skill:`) rather than fall back to the MCP the operator set it to avoid. The skill must have a
name no repository canopy works in uses, since a repository's same-named skill could stand in for it, and any program
it runs must be on canopy's `PATH`. It changes only how the PR is opened: `_run` still checks the branch is on origin
(step 5), and a program that pushes by itself is past the bash rules, so branch protection governs (TRUST_MODEL T1).
The PR targets the listed base, carries the ticket key with no closing keywords, must be readable through the GitHub
MCP, and its URL goes in `prs`. Updating an existing PR, such as retargeting a stacked one, stays with the MCP.

### A fresh session per run

Every worker run starts a new session, `resume` included; none continues the run before it. What carries
from one run to the next is the pushed branch, its PR, the ticket's cursors (§7), the overseer's `--context`, and what
the latest runs reported (step 3); the earlier session stays for the operator to open (§13). Why (MEASUREMENTS
2026-10-15):

- A prompt is rendered for its run: the notice, standing instructions, operator messages, attempt, and context. A
  continued session keeps every earlier prompt, so a lifted notice or superseded message would still read as the
  operator's: PRIOR_ART's contamination of long-lived sessions.
- A run lands on any slot (§9), and the earlier transcript names paths another ticket's run may hold by then.
- Feedback runs are short, and by the time one starts the provider's cache has expired, so a continued session would
  write the earlier run's whole context to the cache and read it back on every call.
- What the earlier run read, CI logs and review comments, would come along. A fresh run reads only what it needs.

Revisit if `resume` runs often end `blocked` or `failed` for want of what the earlier run worked out,
visible in their transcripts as steps spent finding it again.

### Notices to workers

A notice (ROADMAP M35, REQUIREMENTS R15) tells every run that builds, tests, or reads CI about something passing
outside the work, such as "Artifactory is down: CI builds will likely fail", for as long as it lasts. The standing
instructions (§12) never lapse, the overseer never reads them, and nothing shows they are in force, so a line about an
outage there outlives it or is forgotten.

- A notice is a journal fact, like the pause (§6, §11): its text, when and through which channel it was set, and when
  it lapses. One is in force at a time: setting another ends the one before, and `canopy notice --clear` ends it
  early. A lapsed notice reads as none; the rows stay for the overseer's look back (below).
- `canopy notice 'TEXT' [--for DURATION]` sets it, for up to seven days, four hours by default. `canopy notice` alone
  prints the one in force, and `canopy status` names it. The web UI sets it and clears it from the banner every page
  shows while one is in force (§22). Setting or clearing one refuses as `inside_run` when `CANOPY_TICK_ID` or
  `CANOPY_RUN_ID` is set, as `pause` and `reply` do: a notice reaches every later run's prompt, so an agent steered by
  one ticket's text could otherwise write instructions into every other ticket's runs (TRUST_MODEL T1). Reading it
  refuses nothing.
- Its text is bounded when it is set, at 1 KiB after trimming, so no dispatch fails on its size later: the operator
  hears `too_long` at once. A blank text is `empty`; a bad duration is `bad_duration`.
- Who hears it: `implement` and `resume` workers, public and private, under its own heading beside the
  standing instructions; reviews (§21); and chores (§19), in the generated run object the operator's file cannot drop.
  A split hears none: it builds nothing. The prompt is rendered at dispatch, so a running run keeps the prompt it
  started with. A worker leaves a failure the notice explains alone and says so in its summary; a reviewer does not
  count one as a finding.
- While a notice is in force, a prompt override without `{{NOTICE}}` is `bad_prompt` (step 3), so an old override
  cannot drop it silently. `canopy notice` names each such override when it sets one.
- The overseer reads the notices in force or ended in the last seven days (§6 step 4). A failed check whose run started
  while a notice was in force, and that the notice explains, is held: the overseer records `wait`, sends no `resume` for
  it, whose attempts never reset (D030), and leaves the `ci` cursor. It stays held after the notice ends until a newer
  run of that check exists, so an ending alone never sends a `resume` at the outage's failure. Once the notice has ended
  and no newer run exists, the overseer records `notice_rerun` (§14) for the operator to rerun the check; with M25
  built, `triage-ci` reruns it where triage is on. No guard in code: whether a failure is the one the notice names is
  judgment. What code does guard is the overseer deciding from a stale state block: a `resume` for `ci` dispatched after
  a notice was set or cleared since its tick read the journal is refused `notice_changed`, and the tick the notice wakes
  decides with it.
- Setting or clearing a notice is an operator act, like a message: it wakes the loop's wait, keeps the next tick from
  counting as idle, and is recorded as what woke it (§6). Its lapse is a gate the wait ends at, so held work is looked
  at again when the notice lapses.

Open: whether a notice should name repositories, so an outage in one repository's CI does not reach runs in another.
Every notice reaches every run until real use shows the need.

### One resume for what comes back to a PR

Everything that comes back to a PR is one kind of run, a `resume`, which on one checkout and one push does whatever
the unit needs, from fixing the build to answering its reviewers. A PR with a red check and a new review comment gets
one run, not two each pushing the same branch with its own prompt, limit, and cooldown, as when fixing CI was a kind of
its own (`fix-ci`, ROADMAP M56). With M54, a round of feedback is one plan as well as one run.

- **Reasons.** Every `resume` names why it runs with `--reason`, once for each:

  | Reason | Sent for | Its cursors |
  | --- | --- | --- |
  | `ci` | `ci_red`: failed checks, which the context names with their runs | `ci` |
  | `review` | `changes_requested` and `review_findings`: review feedback, or a canopy review's findings (`--review-run`) | `review` |
  | `reply` | `human_replied`: an authorized reply or an operator message, a go-ahead on untrusted feedback among them | `comment`, `message` |
  | `conflict` | `conflicted`: the PR conflicts with its base | none |
  | `no_pr` | `pushed_no_pr`: the branch is pushed and has no PR | none |
  | `retarget` | the PR's blocker merged, so the PR targets the repository's base branch again (§10) | none |

  The reasons are recorded on the run, and `canopy status`, the state block, and the web UI show them beside its kind,
  so a run sent for a red build still reads as one. They are named rather than read off the cursors, since three of
  them have no cursor and the cooldown must tell a run for CI alone. `bad_reason` (step 1) holds what the harness can
  check of them: each cursor the dispatch moves needs its reason. A reason needs no cursor, since a `ci` after a triage
  (§23) follows the cursor the triage moved.
- **One run for a round.** When a tick finds more than one reason on a unit, the unit's phase is the first in §7's
  table, and its one `resume` carries every reason, each with its cursors. `retarget` has no row there: the overseer
  reads that the blocker merged (§10), the harness cannot (D003), and the unit's phase is whatever its PR's state makes
  it, so a stacked PR that is also red gets one `resume` with `ci` and `retarget`. A failed check a notice holds is no
  reason (Notices to workers, above): a `resume` sent for anything else on the unit leaves that check, and the `ci`
  cursor, alone. A run that moves a unit's cursor names one repository, as any does.
- **One limit.** `policy.max_resume_attempts`, default 6, bounds every `resume` of a unit whatever its reasons (D030:
  derived from `runs`, never reset). Six is more than a fix-ci's and a resume's limits were together (2 and 3), since
  one run does what two did; the operator chose one limit (2026-10-17), accepting that a PR that keeps going red can
  spend the attempts its reviewers would have had. An old `fix-ci` run counts among a unit's resumes, and its `fix-ci`
  grants as its `resume` grants do, so nothing was migrated: a unit within the old defaults, at most 5 runs together,
  is within 6, and one past them had grants that carry over. `canopy grant KEY fix-ci` is refused (`bad_kind`) naming
  `resume`. Spend (§11) and the run lists show an old `fix-ci` run under its own kind.
- **The CI cooldown** (`cooldown`, step 1) holds a `resume` whose only reason is `ci` for `policy.ci_cooldown_minutes`
  (default 30) after the latest run covering a named unit that worked on CI ended: a `resume` with `ci` among its
  reasons, or an old `fix-ci`. So a red build still waits between attempts. A `resume` with any other reason is not
  held: it would run anyway, and fixing the build on the same checkout costs no attempt of its own. Its end is a gate
  the loop's wait ends at (§6).
- **One prompt.** `worker-resume.md` and its private variant carry a section on reading a failed check and its log,
  CI logs being untrusted text, under the reason `ci`. `{{REASONS}}` names the run's reasons, and the worker works the
  sections they name. An override without it still renders: step 3 refuses an override that drops a check or an
  operator instruction, and the reasons are neither, since the context names the same work. Nothing renders the old
  `worker-fix-ci.md` or `worker-fix-ci-private.md`, so while the operator's prompt overrides hold either, every
  `resume` is `bad_prompt` when its prompt renders, naming the file and saying to merge what it adds into the resume
  override and remove it: the operator's CI instructions are never dropped silently. That stops every `resume`, not
  only CI's, so the refusal also records a `fix_ci_override` attention item (§14) on the unit, as an `attempt_limit`
  refusal records its own, and a held unit never looks idle. A `resume` for CI alone gets the approved plan's copy
  (§25), as every `resume` does.

Rejected: a cooldown after every run that worked on CI, whatever the next one is for (it would hold feedback a reviewer
waits on, behind a build the same run can fix); a limit per reason (the operator chose one); reasons read from the
context's text (the harness reads no prose, and the cooldown is a guard in code).

## 9. Aggressive release

- Slots are held only for the duration of `_run`.
- Reacquisition lands on an arbitrary slot, so build caches must be slot-independent: for Bazel, a shared disk cache
  or a remote one (below), configured in the operator's or the repository's `.bazelrc`, not in canopy. canopy
  documents this; it does not manage it.
- In a workspace, the operator may declare each pool's size; `canopy workspace sync` makes the slots ahead of time, so
  their hooks and build caches are warm before the first run lands in one (§18).

### Setting up a slot

Three steps, all the operator's, in the order they run:

1. **Seeding.** On every lease, treehouse copies ignored files from the primary clone into the slot: those the
   committed `.worktreeinclude` selects, or, with `paths.worktree_include` set, those the operator's own manifest
   selects instead (it replaces the committed one; copy in its lines to keep them). canopy passes it on every lease: a
   run's, a review's, and sync's. Its lines are git's exclude-file patterns and select only ignored files, so it can
   seed local config (`user.bazelrc`, `.env.local`) and never a tracked file. A missing file fails the lease, `no_slot`
   (§8), before treehouse touches a slot.
2. **`post_create` hooks**, in the user-level treehouse config, run after seeding when a slot is made or reused: on
   the base, before `_run` checks out the run's branch. A failing hook is printed and the lease stands. They suit
   setup that depends on the base alone, such as a toolchain or a warm fetch. canopy's own pool backend (§18) runs
   none; what one did moves to `setup_cmd`, made to tolerate its own failure (`|| true`); BAZEL.md shows how.
3. **`runtime.setup_cmd`**, private, runs in each slot of a worker run after `_run` checks out its branch (§8 `_run`
   step 2), and fails the run when it fails. It suits setup that depends on the branch or must succeed: installing the
   branch's dependencies, generating code its build needs. It is split into words as `notify.cmd` is, with no shell
   and no placeholders; one command serves every repository, telling them apart by `CANOPY_REPO` (§8). Splits and
   reviews run none: their agents have no shell.

`setup_cmd` runs the branch's code (a lockfile's install scripts, a generator) on the operator's machine, outside the
agent runtime's permissions. It is the code the worker's own shell runs a moment later, but outside any sandbox around
`worker_cmd`, so it is wrapped the same way (§24, TRUST_MODEL T4). A broken setup crashes every run it meets, each
spending an attempt (D030) and raising `crashed` (§14), whose note names it.

### Bazel

The operator's guide, with a `.bazelrc` recipe, examples of each setup step, sizing, and checks, is
[BAZEL.md](../BAZEL.md). What canopy relies on:

- Bazel keys a workspace's output base on its path. Slots keep their paths across leases, so each slot's output base
  stays warm for whichever run leases it next. Slots share work only through what the operator's `.bazelrc` shares: a
  disk cache and a repository cache, or a remote cache.
- canopy does not stop a slot's Bazel server when it returns the slot: the harness knows no build tool. The
  operator's `startup --max_idle_secs` ends it once the slot has been idle that long.
- `bazel-out/`, `bazel-bin/`, and `bazel-testlogs/` are links from the slot into its output base, outside the
  worktree. The worker's `external_directory: deny` is checked against the path as written (ROADMAP M7), so the worker
  reads its outputs and test logs through the links and is refused the output base by its own path. That is no
  boundary: the worker's shell reads either (HOST_ISOLATION §1). An opt-in canary checks it.

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
  `"never"` governs starting a ticket; one already stacked keeps its stacked PR and its `resume` runs. The overseer
  prompt follows it; the harness adds no guard, so a `--base` dispatch under `"never"` is not refused.
- The harness checks only the shape of `--base` (`bad_base`, §8): under `trust.branch_prefix`, so a PR cannot target
  a release branch, and not the run's own branch. It does not look the base up in the journal (the blocker may be in
  another operator's queue) and cannot read PR state (D003). `_run` fails a run whose base is not on origin (§8 `_run`
  step 2).
- The base is not remembered. Every dispatch starts from `--base` if given, else the pool's base branch, in every
  repository it names, and the run records each, shown in the state block's latest run. While the blocker's PR is open,
  the overseer passes the same `--base` to the stacked ticket's `resume`. Once it merges, a `resume` for `retarget`,
  without `--base`, tells the worker to retarget the PR to the repository's base branch, bringing that branch in if it
  conflicts. Workers never rebase, since their pushes never force, unless the operator sets `trust.rebase`; then they
  rebase only the ticket's own commits onto it (`git rebase --onto`).
- Ordering is decided by the overseer each tick from live state and recorded in `decisions`. There is no plan file
  and no DAG config.
