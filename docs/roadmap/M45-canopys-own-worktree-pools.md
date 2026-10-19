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
- Before the week starts, the Worktree pools live checks (SCENARIOS S45 to S52) run on the toy workspace (TOY_REPOS),
  so the week is not the first time canopy's pool leases, resets, reuses, seeds, and returns slots in real
  repositories, with real workers and processes. A check that fails is an issue, fixed before the week.
- Check, live, before the default changes: a week on `"canopy"` in which a Bazel or `node_modules` cache in a reused
  slot survives, no slot is left leased without a live run, and one switch back and forward with a run in flight
  loses nothing. Then the default becomes `"canopy"`, in its own PR.

**Stage 4, treehouse removed,** once a tagged release has shipped with `"canopy"` as the default.

- Goes: treehouse's implementation, `pools.backend` (a config still setting it is warned about, then ignored), the
  fake and its fixture, `make treehouse` and the CI job, README's install step, and the mock's pool hashes.
- Stays: finishing the move without treehouse, for a workspace that skipped the release where sync moved its slots.
  A lease the journal says treehouse made is returned by canopy's own forced return of that worktree (its processes
  ended, reset to its base, ignored files kept), with no treehouse call, so no tick fails on one. Sync finds each
  worktree of a clone under `.treehouse/` with `git worktree list` and moves it into `pools/` as stage 3's switch
  does; one with changes or a process in it stays, and sync says so and exits 1. `.treehouse/` goes once it holds no
  worktree. A test upgrades a journal and workspace with both left over.
- Docs: D002 (rewritten as settled), D033's last `Rejected` line, D066's first bullet, DESIGN §6, §8, §9, §18, §22,
  and §24, REQUIREMENTS R2, README, GETTING_STARTED, PRIOR_ART, TRUST_MODEL, and where the web UI's guide and the
  worktrees API's descriptions name treehouse.

Open: whether a seeded symlink is copied as a link (treehouse writes its target text into a regular file), checked
against TRUST_MODEL T4; whether sync warms a new slot (what `post_create` did for M17) or the first run's `setup_cmd`
is enough.

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
