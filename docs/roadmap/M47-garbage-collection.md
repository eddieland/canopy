# M47. Garbage collection

DESIGN §26, D030, D086, D107. Asked for by the operator (2026-10-16): a plan for removing what canopy keeps forever.
Almost everything is kept: every run's, tick's, chore run's, and review's log and prompt, `canopy.log` unrotated, the
harness's attention rows recorded again each tick, a journal nothing checkpoints or vacuums, and loose objects in the
primary clones. Four stages, in order, each in its own PRs, a stage starting only once the one before has passed its
check, recorded on the `Status:` line.

What every stage holds to: no row a guard counts is deleted (`runs`, `run_slots`, `review_runs`, grants,
dismissals), nor a tick, ticket, message, or the overseer's own decisions; nothing a live run uses is touched; no
remote branch is deleted; and no flag shortens retention, which only the user file sets (§26, What it never removes).

**Stage 1, measure.** Nothing is removed.

- `canopy gc --dry-run [--json]`: for each kind in §26's table, the count, the bytes, and what a pass with the
  proposed defaults would remove. It refuses when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set; TRUST_MODEL T1 adds
  `gc` to the commands that do.
- `[retention]` in the user file (§26, Configuration), validated in full now (non-negative integers), so a later
  stage changes no key; read by nothing but the dry run yet.
- Check: the operator runs it on their live workspace, the result is a dated section of `MEASUREMENTS.md`, and the
  defaults in §26 are set from it.

**Stage 2, files.**

- The pass in reconcile, at most daily on a live tick, recording each in `gc_passes` (a new migration): run, tick,
  chore, and review files past their retention, and files with no row. A failed pass is logged and the tick goes on.
- `canopy.log` rotated past `log_max_mib`, its size checked on every live tick, every process logging through
  `WatchedFileHandler`.
- The web UI's transcript, prompt, and diff views say "removed after N days" for a file retention removed.
- Tests with the fakes: a live run's files, a running tick's, and a symlink are never removed; a dry tick runs no
  pass; a file with no row goes only after an hour.
- Check: a week of the operator's loop with the pass on; each day's `gc_passes` row matches what the dry run
  predicted, and no page the operator opens fails.

**Stage 3, the journal.**

- The pass deletes harness-raised attention rows, and M36's `connector_runs` and `derivations` where they exist, older
  than both the attention list's 1000-tick window and `journal_days`, keeping each connector source's newest run and
  the newest that recorded the query's result (§26, §30), then runs `PRAGMA wal_checkpoint(TRUNCATE)`. `canopy gc
  --vacuum` runs `VACUUM` while no run is live and the disk has room for a copy of the journal.
- Tests: with rows on both sides of the window, the attention list, each item's open-since, and the notification
  diff are the same before and after a pass; with fewer than 1000 `ok` ticks, a pass deletes no row.
- Check: on the operator's journal, the attention list and `canopy status` are unchanged across a pass, and the file
  shrinks after `--vacuum` by about what the dry run said.

**Stage 4, outside the journal.**

- `canopy gc --git`: `loose-objects` and `incremental-repack` maintenance in each primary clone with no leased slot,
  under `dispatch.lock`, through `hostgit.argv`.
- `canopy gc --caches`: empties the sandbox's per-role caches while no run of that role is live.
- The dry run lists remote branches no open run or unit names, for the operator to delete.
- Check: `--git` on a clone whose slots hold unpushed commits keeps every one of them, and a run after it pushes
  normally; a SCENARIOS entry, since it is worth running again on each git upgrade.
- Open: whether the pass runs `--git` on its own, weekly, after that check.

**Live checks.** Moved here from SCENARIOS (2026-10-22), keeping their numbers.

- **S59. What canopy keeps** (M47, stage 1's check, closed on real use 2026-10-21). Run `canopy gc --dry-run --json`
  on the live workspace and record each kind's count and bytes, and what a pass with §26's defaults removes, in
  `MEASUREMENTS.md`. Expect the run, tick, and review files, `canopy.log`, and the harness's attention rows to hold
  most of it; set §26's defaults from the numbers, or say why they stay. Run it again before a later stage of M47
  changes what a pass removes.
- **S60. A week of passes** (M47, stage 2's check). Let `canopy loop` run a week with the pass on, and each day run
  `canopy gc --dry-run --json` shortly before the pass is due, a day after the last `gc_passes.started_at`. Expect one
  `ok` row a day whose `removed` matches, kind by kind, the dry run's `removable` and `removable_size`, but for files
  that crossed their retention in between, with `failures` 0; `canopy.log` rotated past `log_max_mib`, with no more
  than `log_keep` rotated files; and every transcript, prompt, output, and diff the operator opens shown, or saying
  "removed after N days", never failing. Record the rows and the dry runs in `MEASUREMENTS.md`.
- **S62. The journal across a pass** (M47, stage 3's check). On the live workspace, shortly before a pass is due, save
  `attention.md`, `canopy status`, and `canopy gc --dry-run --json`; after the pass, expect the attention list, each
  item's age, and `canopy status` unchanged, and the `gc_passes` row's `rows` for the harness's attention, connector
  runs, and derivations equal to the dry run's `removable`. Then, between ticks, run `canopy gc --vacuum` and expect
  the journal to shrink by about the dry run's free pages plus the rows' pages the pass freed, and the next tick to run
  normally. Record the sizes and counts in `MEASUREMENTS.md`.
- **S65. Git in the primary clones** (M47, stage 4's check). Between ticks, with an idle slot holding a commit no
  remote has, run `canopy gc --dry-run`, then `canopy gc --git`. Expect each clone `packed`, its loose objects gone
  from the next dry run and its packs fewer or the same; the slot's commit still there (`git cat-file -t`); and the
  next run on that repository leasing, committing, and pushing as before. With a run live, expect its repository
  `skipped` and the others `packed`. Run it again after a git upgrade.

Status: in progress. Stage 1 is built (2026-10-18): `canopy gc --dry-run [--json]` and `[retention]`, validated in full.
The operator closed its check on real use (2026-10-21: the dry run works well on their workspace) with no
`MEASUREMENTS.md` section, so §26's defaults stay as proposed, and the unrun live measurement moved to `SCENARIOS.md`
(S59), and from there to this file (2026-10-22). Stage 2 is built against the fakes (2026-10-21): the daily pass over
files in reconcile, recorded in `gc_passes`; `canopy.log` rotated by each live tick; and the web UI's "removed after N
days". Its check, a week of the operator's loop with the pass on (S60), is the operator's. Stage 3 is built against the
fakes ahead of that check, at the operator's word (2026-10-21): the pass also deletes the harness's attention rows,
connector runs, and derivations outside the window and `journal_days`, recorded as rows in `gc_passes.removed`, and
checkpoints the journal; `canopy gc --vacuum` runs between ticks while no run is live. Its check, the journal across a
pass and a vacuum (S62), is the operator's too, after S60. Stage 4 is started at the operator's word (2026-10-23):
`canopy gc --git` is built against real git behind the fakes, run by hand only. git's run of both tasks at once
refuses a clone with no pack, so each is its own run, and git skips a run whose lock another holds saying nothing, so
canopy looks for the lock. Its check is S65; `--caches` and the dry run's remote branches are still to build.
