# M45. canopy's own worktree pools, replacing treehouse in stages

D002, D107, D118. DESIGN §8, §9, §18, and §24. Needs M17, and M26's `commondir` check, which is in. Asked for by the
operator (2026-10-13): drop treehouse, so installing canopy needs no Go and its leases live in the journal. Asked again
(2026-10-16): slowly, with a lot of verification before treehouse goes.

Four stages, in order, each in its own PRs. A stage starts only once the one before has passed its check, recorded on
the `Status:` line. Until the last stage, treehouse stays installed and one config setting goes back to it.

What every stage holds to:

- **One interface, two pools.** `core/treehouse.py`'s four operations (`status`, `lease`, `return_slot`, `destroy`)
  become the interface every caller uses. treehouse is one implementation and `core/pool.py` the other; no caller
  learns which one it has.
- **The contract is the spec.** One test suite states each guarantee as a case, written against the interface, and
  runs it against real treehouse, the fake, and canopy's pool. A behavior with no case is not a guarantee. Where
  canopy's pool differs on purpose, DESIGN §18 says so and the case says which pool expects what.
- **The host stays safe.** Every git canopy's pool runs goes through `hostgit.argv` (D107), and a step in a slot after
  a run comes after `_run`'s link and `commondir` check (D118).

What treehouse does that canopy relies on or works around, from its source at the pinned `1185dc6` (checked in stage
1; DESIGN §18, What a pool guarantees, lists what the contract suite holds it to):

- Reuse and return reset a slot with `read-tree --reset -u` and `clean -fd`, no `-x`, and move HEAD to the base's tip,
  detached: ignored files (build outputs, `node_modules`, Bazel's links) survive, except those seeding wrote, which
  the reset removes first; untracked files and commits no branch holds do not.
- A slot is reused only when it is unleased, a worktree of this clone, clean (`status --porcelain
  --untracked-files=all`), has no process with its cwd inside it, and its HEAD is merged (an ancestor, or the same
  content as a squash) into the base or the base it was last leased on. A clean slot holding unmerged commits shows
  `available` and is passed over.
- `return` is conditional on the lease id and holder (exit 1 otherwise) and forced, so exit 3 never happens. It ends
  processes in the slot first (SIGTERM, then SIGKILL after two seconds), and parks the slot on its lease's base.
- Seeding copies the untracked, ignored files `.worktreeinclude` (or `--include-file`) selects, on every lease. A
  seed target already in the slot fails the lease, and treehouse then holds a reused slot under a `quarantined:`
  holder. A symlink is written as a regular file holding its target.
- `destroy` keeps a slot that is leased, in use, dirty, unverifiable, or unmerged into the default branch, and runs
  `git fetch` and `ls-remote` on `origin` first. `status` rewrites treehouse's state, forgets a slot whose directory
  is gone, and records a worktree it finds unrecorded as held; it moves no file.

**Stage 1, the contract.** No behavior changes.

- `tests/canopy/core/test_pool_contract.py`: a case for each guarantee above and each one `core/treehouse.py`'s callers
  depend on (reconcile, dispatch, reviews, sync, the worktrees page). It runs against the fake on every `make check`,
  and against real treehouse when `treehouse` is on `PATH` (`make pool-contract`).
- A CI job, on Linux, that builds treehouse at the pinned commit with `make treehouse` and runs the suite. Go
  is a CI-only dependency, like Node for the sandbox canary. Where the fake and real treehouse disagree, the fake is
  fixed.
- DESIGN §18 gains "What a pool guarantees", the list the suite checks, each line naming its case.
- Check: the suite passes against real treehouse on both platforms and against the fake.

**Stage 2, canopy's pool in shadow.** Built beside treehouse, wired to no caller.

- Leases are journal rows: a migration adds `slots` (repository, name, path, lease id and holder, leased at, base,
  the paths seeding wrote). A lease claims its row under the pool's own lock before it touches the worktree, in a
  transaction of its own rather than the run's, since the run is recorded only after its slots are leased; a lease
  with no run is reconcile's to return, as treehouse's is (DESIGN §18, canopy's pool).
- Layout: `<workspace>/pools/<repo>/<N>/<repo>`, with no hash of the remote, since a workspace's repository names are
  unique. The declared size is the only limit; a pool with none declared stops at 16, treehouse's default
  `max_trees`.
- Lease, reuse, return, and seeding as treehouse does them (above). Processes in a slot are found through `/proc` on
  Linux and `lsof` through `procs` on macOS, so no new dependency. `destroy` uses the fetched refs, no network call.
- The contract suite runs against canopy's pool too, every case, nothing skipped for one pool only, plus real-git
  tests for two leases at once and a crash between `worktree add` and the journal row.
- Shadow: each tick's reconcile also classifies every treehouse slot with canopy's own checks and logs a
  `pool_shadow_mismatch` line wherever they disagree. It changes nothing. Each mismatch the operator explains becomes
  a contract case, and canopy's checks are fixed until it passes.
- Check, live: a week of `canopy loop` on the real queue with the shadow on, whose every mismatch is explained, has a
  case, and passes.

**Stage 3, by choice, then by default.**

- `pools.backend`, private (§12): `"treehouse"` (default) or `"canopy"`. The journal records which pool made each
  lease, and a lease is always returned through that pool, so switching with runs in flight is safe.
- Switching to canopy, `canopy workspace sync` moves each idle treehouse slot into `pools/` with `git worktree move`,
  keeping its ignored files. Switching back costs only warm caches: treehouse makes fresh slots and sync removes
  canopy's idle ones.
- `post_create` does not run under canopy's pool; the operator's guide says how to move a hook to `runtime.setup_cmd`
  (§9).
- Before the week starts, the live checks below (S45 to S52) run on the toy workspace (TOY_REPOS),
  so the week is not the first time canopy's pool leases, resets, reuses, seeds, and returns slots in real
  repositories, with real workers and processes. A check that fails is an issue, fixed before the week.
- Check, live, before the default changes: a week on `"canopy"` in which a Bazel or `node_modules` cache in a reused
  slot survives, no slot is left leased without a live run, and one switch back and forward with a run in flight
  loses nothing. Then the default becomes `"canopy"`, in its own PR.

**Stage 4, treehouse removed,** once a tagged release has shipped with `"canopy"` as the default.

- Goes: treehouse's implementation, `pools.backend` (a config still setting it is warned about, then ignored), the
  fake and its fixture, `make treehouse` and the CI job, README's install step, and the mock's pool hashes.
- Stays: finishing the move without treehouse, for a workspace that skipped the release where sync moved its slots
  (DESIGN §18, Upgrading past treehouse; proposed, #813). A lease the journal says treehouse made is returned by
  canopy's own forced return of that worktree (its processes ended, reset to its base, ignored files kept), with no
  treehouse call; a return that fails is logged and leaves the worktree for sync, so no tick fails on one. Sync finds
  each worktree of a clone under `.treehouse/` with `git worktree list` and moves it into `pools/` as stage 3's switch
  does, what treehouse seeded in it recorded as seeded; one a running run or review holds waits, and one with changes,
  a process in it, or a damaged link stays, and sync says so and exits 1. `.treehouse/` goes once it holds no
  worktree. `'treehouse'` stays a value of the journal's lease columns.
- Test: a scenario that upgrades. A journal from the release before holds a running run's `'treehouse'` lease whose
  `_run` is gone, a running run's and a running review's that are live, and a finished run's; real worktrees under
  `.treehouse/` hold an ignored cache and a seeded file, one with changes, one with a process in it, and one with a
  damaged link; the config still sets `pools.backend = "treehouse"`; and no `treehouse` is on `PATH`. Expect the tick
  to end ok, warning about the key, with the dead run closed `crashed` and its slot reset in place; sync to move the
  idle worktrees with their caches (same inode), keep the rest, and exit 1; once the runs end and the worktrees are
  cleaned, a second sync to move the rest, remove `.treehouse/`, and exit 0; and the next lease to reuse a moved slot,
  seeding it afresh with no quarantine. A forced return that fails, its process outliving its signals, leaves a tick
  that ends ok.
- Check, live: S53 (below) on the toy workspace, an upgrade from the release before with treehouse slots and leases
  left over (the M45 test plan's phase F), before the stage's last PR merges.
- Docs: D002 (rewritten as settled), D033's last `Rejected` line, D066's first bullet, DESIGN §6, §8, §9, §18, §22,
  and §24, REQUIREMENTS R2, README, GETTING_STARTED, PRIOR_ART, TRUST_MODEL, and where the web UI's guide and the
  worktrees API's descriptions name treehouse.

Open: whether a seeded symlink is copied as a link (treehouse writes its target text into a regular file), checked
against TRUST_MODEL T4; whether sync warms a new slot (what `post_create` did for M17) or the first run's `setup_cmd`
is enough.

**Live checks on the toy workspace.** Moved here from SCENARIOS (2026-10-22), keeping their numbers: canopy's own
pool (DESIGN §18) doing treehouse's work on the toy workspace (`TOY_REPOS.md`): leasing, resetting, reusing, seeding,
and returning slots for real workers, with real processes in them. The contract suite holds it to the same guarantees
with throwaway repositories and fake runs. Run these before stage 3's live week, and
again after a change to `core/pool.py`, `canopy workspace sync`, or how reconcile returns leases.

Run them in order, as the kit's `toycanopy` from the workspace root, starting under `pools.backend = "treehouse"`
with `capacity.slots_per_repo = 2` synced. S52 leaves slots no command can release yet (#811), so it goes last. A run
is a small toy-calc issue (the TOY_REPOS catalog's S8 or S16), started with `canopy start KEY` and dispatched by
`canopy tick`; most steps end it with `canopy stop --now KEY` once they have seen what they need. First, give
toy-calc's clone an ignored cache and a file to seed:

1. `printf 'cache/\n*.local\n' >> repos/toy-calc/.git/info/exclude`. Every slot shares the clone's git directory, so
   both are ignored in every slot.
2. `echo v1 > repos/toy-calc/settings.local`.
3. `echo '*.local' > ~/canopy-toys/pools.include`, and `paths.worktree_include = "~/canopy-toys/pools.include"` in
   the toy user config.

Where to look: each slot's status and holder on the web UI's worktrees page (`canopy loop --defer 600` serves it and
waits ten hours before its first tick; restart it after a config change); the pool's rows,
`sqlite3 -readonly .canopy/canopy.db 'SELECT name, path, lease_holder, base, seeded FROM slots'`; the pool that made
each run's lease, `SELECT run_id, slot_path, pool FROM run_slots`; and the log, `.canopy/canopy.log`.

- **S45. Switching pools, and back** (M45).
  1. Under treehouse, give the toy treehouse config (`~/canopy-toys/config/treehouse/config.toml`) a hook,
     `[hooks] post_create = ["mkdir -p cache && date >> cache/hook-ran"]`. In each idle slot of toy-calc's pool, write
     `cache/warm.bin` and note its inode: `ls -i .treehouse/*/*/toy-calc/cache/warm.bin`.
  2. Set `pools.backend = "canopy"` in the toy user config and run `canopy workspace sync --dry-run`. Expect
     `toy-calc: to move: 2 idle treehouse slots into pools/`, the same for each other repository, and nothing changed
     on disk, with `toy-calc: slots: 2 of 2`: the dry run counts the slots its move brings in, as the real sync does.
  3. `canopy workspace sync`. Expect `toy-calc: moved: moved 2 of 2 idle treehouse slots into pools/`, then
     `toy-calc: slots: 2 of 2`, and exit 0. The slots are `pools/toy-calc/1/toy-calc` and `pools/toy-calc/2/toy-calc`,
     `git -C repos/toy-calc worktree list` names them, each has a row with no holder, and
     `ls -i pools/toy-calc/*/toy-calc/cache/warm.bin` prints step 1's inodes.
  4. Move the hook to `runtime.setup_cmd = "sh -c 'mkdir -p cache && date >> cache/setup-ran || true'"` (BAZEL.md,
     section 3), and start a run. Expect its lease from canopy's pool (`run_slots.pool` is `canopy`) on a moved slot,
     its `cache/warm.bin` at the same inode, `cache/hook-ran` unchanged, and one new line in `cache/setup-ran` before
     the worker starts. Stop it: the run ends `stopped` and its slot has no holder.
  5. Set `"treehouse"` again and sync. Expect `toy-calc: removed: removed 2 of 2 idle slots of canopy's pool`, then
     `toy-calc: slots: 2 of 2, made 2` under `.treehouse/`: fresh slots with no `cache/warm.bin`, which is all
     switching back costs. Set `"canopy"` and sync again for the checks below: `moved 2 of 2`.
- **S46. A run's slot, reset and reused** (M45).
  1. Write `cache/warm.bin` in each idle slot of `pools/toy-calc/` and note the inodes. Start a run. Expect its slot
     held by `canopy:KEY`, with `settings.local` in it reading `v1` and listed in its row's `seeded`.
  2. While the worker runs, in its slot: `echo stray > stray.txt`, `git commit --quiet --allow-empty -m stray`, and
     `date > cache/during.bin`. Stop the run. Expect, once it is `stopped`, the slot with no holder; `git status
     --porcelain` in it printing nothing; HEAD at `origin/main` (`git rev-parse HEAD origin/main` prints one commit
     twice), the stray commit gone from `git log`; `stray.txt` and `settings.local` gone, and `seeded` `[]`; and
     `cache/warm.bin`, at its inode, and `cache/during.bin` still there.
  3. `echo v2 > repos/toy-calc/settings.local`, then `canopy start KEY` and `canopy tick` again. Expect a reused slot,
     no new directory under `pools/toy-calc/`, with `settings.local` reading `v2` and the caches as they were. Let this
     run end on its own, with its PR: its slot is reset as in step 2, the worker's commits gone from it.
- **S47. A switch with a run in flight, both ways** (M45). A lease goes back to the pool that made it.
  1. Under treehouse, start a run. While its worker runs, set `"canopy"` and sync. Expect `moved 1 of 1 idle
     treehouse slots into pools/`, no slot made in place of the run's (`slots: 1 of 2; 1 left in treehouse's pool,
     moved in by a later sync`), exit 0, and the run's slot left in `.treehouse/`.
  2. `canopy tick` while it runs. Expect no `canopy lease with no running worker; returned` line for its slot in the
     log, and the run still running in `canopy status`.
  3. Let it end, or stop it. Expect its `run_slots` row to say `treehouse`, and the slot `available` in
     `treehouse status --json`, run in `repos/toy-calc` with `TREEHOUSE_ROOT` the workspace root.
  4. Sync. Expect it to move that slot, now idle, its caches with it: `moved 1 of 1 idle treehouse slots into
     pools/`, then `slots: 2 of 2`, and exit 0. `.treehouse/` holds no slot of toy-calc's.
  5. The other way: start a run under canopy, set `"treehouse"` while it runs, and sync. Expect `removed 1 of 1 idle
     slots of canopy's pool`, the run's slot left in `pools/`, and treehouse's pool made up to its size. When the run
     ends, its slot goes back to canopy's pool, its row with no holder, and the next sync removes it (`removed 1 of
     1`). Set `"canopy"` and sync before S48.
- **S48. Processes in a slot** (M45). canopy's pool reads them from `/proc` on Linux and with `lsof` on macOS: run
  steps 1 and 2 on both.
  1. In another terminal, `cd` into an idle slot and leave the shell there. Expect the slot `in-use` on the worktrees
     page, naming the shell; a run started now leases another slot. Stop it, and leave the slot.
  2. Start a run. While it runs, from a shell outside its slot, start two processes in it:
     `(cd SLOT && exec sleep 3601) &` and `(cd SLOT && trap '' TERM && exec sleep 3602) &`. Stop the run. Expect both
     gone once it ends (`pgrep -f 'sleep 360'` prints nothing), the second by SIGKILL two seconds after SIGTERM, and
     the slot returned. A run that ends on its own ends them the same way.
  3. On macOS, put an `lsof` that exits 1 first on canopy's `PATH` and start a run. Expect every idle slot read as
     `unverified`, so busy: the dispatch is refused `no_slot` (`2 of its slots are busy, and capacity declares 2 for
     this pool`), and no slot is reset.
- **S49. A crash, and slots the journal does not match** (M45, DESIGN §18's Recovery).
  1. Start a run, and while its worker runs, `kill -9` its `_run`
     (`sqlite3 -readonly .canopy/canopy.db "SELECT pid FROM runs WHERE status = 'running'"`). Expect the worker to go
     on until the next `canopy tick`, which kills it, closes the run `crashed`, and returns its slot to canopy's pool:
     the log's line for the closed run lists the slot `returned`, and the slot is reset as in S46 step 2.
  2. Set `[capacity.repo_slots] toy-calc = 3` and, before syncing, make a worktree where slot 3 goes, with a cache in
     it: `git -C repos/toy-calc worktree add --detach "$PWD/pools/toy-calc/3/toy-calc" origin/main`, then
     `mkdir pools/toy-calc/3/toy-calc/cache && date > pools/toy-calc/3/toy-calc/cache/warm.bin`. Sync. Expect
     `slots: 3 of 3, made 1`, with the worktree adopted as slot 3 (a row for its path), not made again: its
     `cache/warm.bin` keeps its inode.
  3. `rm -rf pools/toy-calc/3`. Expect slot 3 `damaged` on the worktrees page while its row lasts. A sync alone sees
     `3 of 3` and leases nothing; start a run and stop it: that lease forgets the row. Sync again: `slots: 3 of 3,
     made 1`, a new slot 3.
  4. Damage an idle slot's git link: save its `.git` file, write `gitdir: /tmp/nowhere` in its place, and
     `touch mine.txt` in the slot. Expect it `damaged`; a run leases another slot, never this one; with the size
     lowered to 2, sync removes an idle slot and leaves this one; and `mine.txt` still there after each. Put the saved
     `.git` file back.
- **S50. Size and trim** (M45).
  1. With `toy-calc = 3`, `canopy workspace sync --dry-run`: `toy-calc: slots: 2 of 3, would make 1`. Sync: `slots: 3
     of 3, made 1`, and no row left held by `canopy-sync`.
  2. `touch stray.txt` in each slot, and start a run. Expect the dispatch refused `no_slot`, `toy-calc: 3 of its slots
     are busy, and capacity declares 3 for this pool`, and no fourth slot. Remove the files.
  3. Commit in the highest-numbered slot (`git commit --quiet --allow-empty -m unmerged`), set `toy-calc = 1`, and
     sync. Expect `toy-calc: slots: 1 of 1, removed` naming the other two, highest first, and the slot with the
     commit kept, as not merged into `origin/main`. Detach it at `origin/main`, set `toy-calc = 2`, and sync: `slots:
     2 of 2, made 1`, the new slot numbered after the highest left.
- **S51. Reviews, joint runs, and stacked runs** (M45). Step 2 needs toy-api and toy-web (TOY_REPOS, Order of work).
  1. `canopy start PR --review` on an open toy-calc PR, and tick. Expect its slot from canopy's pool, held by
     `canopy:review:ID`, its `review_runs` row's `pool` `canopy`, and the slot with no holder once the review ends. On
     another PR, `kill -9` the `_review` (`review_runs.pid`) while it runs: the next tick closes it `crashed` and
     returns its slot.
  2. Set `[capacity.repo_slots] toy-web = 0`, `canopy start` S14's issue, and tick. Expect the joint dispatch refused
     `no_slot` naming toy-web, and no slot of toy-api's left leased. Remove the entry and tick again: one slot leased
     in each of `pools/toy-api/` and `pools/toy-web/`, both `canopy` in `run_slots`, and `desks/KEY/` holding a link
     to each; once the run ends, both slots with no holder and the desk gone.
  3. S12's pair, the second stacked on the first. Expect the second's run to lease from canopy's pool on the default
     branch (its row's `base` empty) and `_run` to check out the first's branch in the slot; once returned, the slot
     is at the default branch's tip and the next lease reuses it.
- **S52. Seeding's edge cases** (M45, DESIGN §9). Set `toy-calc = 4` and sync first, so slots stay free.
  1. `ln -s settings.local repos/toy-calc/link.local` and `ln -s /etc/hosts repos/toy-calc/hosts.local`, then start a
     run. Expect `link.local` and `hosts.local` in its slot as regular files (`ls -l`) holding `settings.local` and
     `/etc/hosts`, the links' targets, and all three in its row's `seeded`. Whether a link should stay a link is M45's
     open question: note what you see. Stop it: all three gone from the slot.
  2. In the idle slot the next lease takes, the lowest-numbered one, `echo mine > settings.local`, and start a run.
     Expect the dispatch refused `no_slot`, `failed to seed SLOT: settings.local: file exists`; the slot held by
     `quarantined: worktree seeding failed`, its `settings.local` still `mine`; and the next run leasing another slot.
     A quarantined slot counts as busy and is never reused, and sync leaves it; no command releases it until #811.
  3. In the next idle slot, `ln -s /tmp/outside.local settings.local`, and start a run. Expect the same quarantine and
     no `/tmp/outside.local`: seeding never writes through a link in the slot.
  4. Point `paths.worktree_include` at a path with no file, and start a run. Expect `no_slot` naming the include file
     (`failed to read include file`), with no slot leased, reset, or quarantined. Put the setting back.
- **S53. Upgrading past treehouse** (M45 stage 4, DESIGN §18's Upgrading past treehouse). Run it once stage 4 is
  built, on a fresh toy workspace with this group's first three steps done, not after S45 to S52: it starts on the
  release before, under treehouse, with `toy-calc = 3` synced and `cache/warm.bin` written in each slot of
  `.treehouse/`, its inodes noted.
  1. Start run A and `kill -9` its `_run`. Start run B and leave its worker working. In the idle slot,
     `touch stray.txt`.
  2. Install the stage 4 build with `uv tool install`, take `treehouse` off `PATH`, and leave `pools.backend =
     "treehouse"` set. `canopy tick`. Expect a warning that `pools.backend` is ignored and the tick ending ok; A
     closed `crashed`, its slot still under `.treehouse/`, `git status --porcelain` in it printing nothing, HEAD at
     its base, and `cache/warm.bin` at its inode; and no `canopy lease with no running worker` line for B's slot.
  3. `canopy workspace sync --dry-run`: A's slot to move, B's waiting, the idle one kept for its changes, nothing
     changed on disk. `canopy workspace sync`: A's slot moved into `pools/toy-calc/`, its cache at the same inode and
     its row's `seeded` naming `settings.local`; B's slot waiting; the idle one kept, named with `stray.txt`; exit 1.
  4. Remove `stray.txt`, and `canopy stop --now` B. Expect its slot returned in place, as A's was. Sync: both moved,
     `.treehouse/` gone, `slots: 3 of 3`, exit 0.
  5. Start a run. Expect it to reuse a moved slot, `settings.local` reading `v1`, no quarantine, and `cache/warm.bin`
     at its first inode. Remove `pools.backend` from the config: the warning stops.

Accept: each stage's check, in order. Then `make install-check` passes with no `treehouse` on `PATH`, and a
fresh install from README on a machine with no Go runs a day of `canopy loop`.

Status: in progress. Stage 1 passed its check 2026-10-16: the contract suite passes against the fake, and against real
treehouse at the pinned commit in CI on Linux and macOS; CI has run it on Linux only since 2026-10-17, at the
operator's request. Stage 2 is built: canopy's pool passes every contract case, and
reconcile's shadow logs `pool_shadow_mismatch`; its check, a week of `canopy loop` with the shadow on, is the
operator's. Stage 3's choice is built too, ahead of stage 2's check at the operator's request (2026-10-16):
`pools.backend` picks the pool, each lease goes back to the pool the journal says made it, and sync moves idle slots
across on a switch. A slot a seeding collision quarantines is freed by the operator with `canopy workspace release`,
in either pool (#811). The default stays `"treehouse"` until stage 3's live check passes.
