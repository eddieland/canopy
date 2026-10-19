# canopy scenarios

Live checks worth running through against real systems: the operator's queue, a real tracker and GitHub, the pinned
OpenCode. The fakes-based tests cover the harness's half of each, and a new one is told through the `scenario`
fixture (`tests/canopy/scenario_helpers.py`); these cover the half only a real run can, the model's judgment and the
runtime's permissions above all.

Most came from milestone acceptance criteria that were closed on real use rather than by a dedicated run (ROADMAP,
2026-10-13). Each names the milestone it came from, which says why the behavior exists. A scenario's number stays
with it; one retired is listed at the end and its number is not given out again.

A scenario earns its place by checking something that daily use would not show and the tests with the fakes cannot:
a permission, a judgment the operator rarely sees, a path that needs a failure staged, a real system other than the
tracker and GitHub. One that real use exercises every day, or whose real half has been measured, is retired.

They are grouped by when to run them: the canaries after an OpenCode upgrade, the release checks before a release, a
live check after a change to the area it names or the prompt and guards it relies on, and a measurement when its entry
says. A scenario that fails is a bug: file an issue with the tick id, and its decisions (`canopy decisions TICK`). A
run that measures something, such as spend or latency, goes in `MEASUREMENTS.md` as a dated section.

Toy repositories to run them against, apart from real work and cheap to reset, are planned in `TOY_REPOS.md`.

## Canaries

What canopy relies on in the pinned OpenCode: its permissions, its output, and how it streams. Run all of them after
any OpenCode upgrade, and before relying on a permission they check.

- **S1. The OpenCode canary** (M1, M7, M11, M16). `CANOPY_OPENCODE_CANARY=1 uv run pytest
  tests/canopy/test_opencode_canary.py`, with `CANOPY_OPENCODE_CANARY_MODEL` to pick a model. Expect every test to
  pass: denied tools refused, a repository's definition not loosening canopy's, a desk worker editing through its links
  and nothing beside them (with the workspace a plain directory and a git checkout), a reviewer reading only its
  checkout, and a worker refused Bazel's output base by its own path.
- **S2. The splitter's MCP name patterns** (M8). Not in the canary yet. Give `canopy-splitter` a ticket and check that
  OpenCode applies its name patterns to MCP tools: it can create and link tickets and comment on the parent, and is
  refused any other write tool.
- **S3. The private worker's wildcard deny** (M18). Confirmed in OpenCode's source (1.18.35), not in a run. Start a
  ticket privately and check that its worker can call the tracker's `tracker.read_tools` and is refused every other
  tool of the tracker's server, and the tracker CLIs in bash.
- **S4. A heredoc `canopy` command** (M19). Confirmed in OpenCode's source (1.18.35), not in a run. Check that the
  overseer's `canopy *` rule admits `canopy mirror` fed by a heredoc.
- **S44. The token split** (M33). Confirmed in OpenCode's source (1.19.3), not in a run. canopy's new tokens add a
  `step_finish`'s `output` and `reasoning` (`core/agent_output.py`), which holds only while `output` leaves reasoning
  out. Check that OpenCode's `session.ts` still sets `output: outputTokens - reasoningTokens`; aide found the overlap
  differed in earlier releases (PRIOR_ART).
- **S30. A session's transcript** (M15, M27). Open a worker run's page and a tick's page. Expect the tool calls
  `opencode export <id>` shows for the same session id, and, for a failed run, its runtime error.
- **S38. A running run, watched live** (M27, taken on request 2026-10-15). While a worker runs under the pinned
  OpenCode, open its row on the runs page and its run's page. Expect its latest tool call on the row within seconds of
  the call ending, its cost moving at each model call, and its transcript growing as it goes, matching
  `opencode export <id>` for what it has done so far; and `canopy status` naming the same call. A row that shows
  nothing until the run ends means OpenCode is buffering its events, not printing them as they happen.

## Before a release

- **S5. A second person installs from README** (M5). Someone who has not used canopy follows README's install steps
  without help, then runs it against a ticket of their own. Expect it to work in five steps; file their friction as
  issues.
- **S6. A workspace from clone URLs** (M17). In an empty directory, with `capacity.slots_per_repo` or
  `[capacity.repo_slots]` set, run `canopy init --workspace` with two real clone URLs. Expect both cloned, each pool
  at its size, and `post_create` run in the new slots during sync, not during the first run. Then:
  - lower a size and `canopy workspace sync`: idle slots are removed, never a leased one;
  - fill a pool and let the overseer dispatch into it: refused `no_slot`;
  - drop a repository from the map and sync: its clone and slots are removed, and a clone with an unpushed commit is
    kept and reported.
  treehouse's `max_trees` (16 by default) must be at least the largest declared size.
- **S7. Slot setup in a Bazel repository** (M16, `docs/BAZEL.md`). With the recipe in `~/.bazelrc`, a personal
  `paths.worktree_include` that seeds a gitignored file, and a `setup_cmd` that runs `bazel fetch`, expect a real
  `implement` worker to find the seeded file in its slot and its `bazel test` to hit the disk cache another slot
  filled. A `setup_cmd` that exits 1 ends the run `crashed`, with no worker started and the slot returned. A slot's
  Bazel server exits once idle for `--max_idle_secs` after its run.
- **S28. Served on loopback and a private address** (M20). `canopy loop` serves a real journal to a browser on
  loopback and on a private address; the worktrees page reads the real pools.

## Live checks

Run the ones in the area a change touches, or that rely on a prompt or guard it changes.

### A ticket's lifecycle

- **S8. Label to PR** (M2). Label a real ticket. Expect it to reach an open PR unattended, its slot returned, and a
  correct `runs` row. Kill the worker with SIGKILL mid-run: the next tick marks it `crashed` and returns the slot.
- **S9. A failing check, to the limit** (M3, M56). On a PR whose check fails, expect exactly one `resume --reason ci`
  per cooldown window and an `attempt_limit` item at the limit, with no attempt after it.
- **S43. A red check and a review comment, one run** (M56). On one of the loop's PRs with a red check and a new review
  comment from a trusted reviewer, expect the next tick to send one `resume` with reasons `ci` and `review`, shown as
  `resume (ci, review)` in `canopy status`, which fixes the check and addresses the comment in one push.
- **S10. A conflicted PR** (M3). Make a PR conflict with its base. Expect `conflicted`, then a worker that merges the
  base to a clean PR.
- **S11. A blocked question** (M3, M22). Write a ticket that tells the worker to ask first. Expect one concrete question
  on the ticket and `needs-human`. A reply from an account not in `trust.authorized_repliers` does not resume it; an
  authorized one does, and so does `canopy reply` or the web UI's reply, with nothing of it on the ticket.
- **S12. Stacked tickets** (M4, M56). Two tickets, the second blocked by the first. Expect the second to wait, then be
  dispatched with `--base` on the first's branch once its PR is open and green. Then merge the first: expect a
  `resume (retarget)` for the second, without `--base`, that points its PR at the repository's base branch.

### Several repositories

- **S13. One queue over two repositories** (M6). In a two-repository workspace, label one ticket in each. Expect both
  to reach open PRs from one queue, with every worktree under the workspace root.
- **S14. A joint run** (M7). A ticket that touches two repositories. Expect one run to open two PRs that link each
  other. Kill a joint run mid-way: the next tick returns all its slots.
- **S15. A split on request** (M8). After S2, on a ticket covering two repositories, an authorized replier asks for a
  split in a comment. Expect two linked children, the second blocked by the first, with no queue label on either, and
  nothing dispatched for them until you label them; then they are worked in order, one PR each.

### Private tickets and trust

- **S16. A private ticket** (M18). After S3, `canopy start` a real ticket. Expect its worker's question in
  `canopy status`, `canopy show`, and the web UI; answer it from the CLI; expect the PR to land for review and the
  ticket to show nothing canopy wrote.
- **S18. Untrusted and trusted reviewers** (M22). A review bot's comment on a loop PR waits as `untrusted_review` with
  no dispatch. A reply from the web UI resumes it, with the reply as the worker's instruction. A comment from someone in
  `trust.trusted_reviewers` resumes it without a reply.

### Reviews

- **S19. A finding, resumed and re-reviewed** (M11). With `review.agent_prs` on, a ticket's PR is reviewed once its
  checks pass; a finding goes back through `resume --review-run`, the new commit is reviewed again, and the ticket
  reaches `needs_reviewer`, with nothing of the review on the PR.
- **S20. A review of your own PR** (M11). With a `review.query` that matches a PR you wrote, expect one review per new
  head commit in `canopy review show` and nothing else: no comment, no push, no ticket, no GitHub review.
- **S21. A review killed, and the limit** (M11). Kill a review run mid-way: the next tick returns its slot and raises
  `review_failed`. A PR at `policy.max_reviews_per_pr` gets no more reviews.
- **S36. A shadow review on its page, and findings sent from it** (M32). With `review.agent_prs` on and
  `canopy:review` not in `trust.trusted_reviewers`, open a real review's page in the web UI beside its PR's diff on
  GitHub: expect each finding on the line it names, and the diff to match the PR's (a stacked PR also shows its base
  branch's commits). Dismiss one finding, tick another, and send it to a worker: expect the next tick to dispatch
  `resume --review-run` for that run, the worker to address the sent finding and leave the rest, and nothing of the
  review or the message on the PR or the ticket.
- **S39. A coworker's PR, reviewed on request** (M42). With no `review.query` and `review.agent_prs` off, ask for one
  coworker's open PR to be reviewed from the CLI (`canopy start URL --review`), and another, in a second repository of
  the workspace, from the web UI's reviews page. Expect each reviewed at its head, in its own repository, and
  its request to end `reviewed` (`canopy show URL`). Ask for one more on a PR that then merges before the next tick,
  and one on a PR in a repository the workspace does not have: expect the overseer's `canopy review end` to end them
  `merged` and `unknown_repo`. Nothing is posted on any PR.

### Chores and notifications

- **S22. A build-health chore over several days** (M9, `examples/chores/build-health.md`). Expect it never to start
  sooner than `every_minutes` after its previous run, and the `decisions` table to show the overseer following `when`.
  Each finding reaches the attention list, is notified once, and goes away after a run that no longer reports it. Kill
  a chore run mid-way: `crashed` with a `chore_failed` item. Delete the chore from the config: its items clear at the
  next tick.
- **S23. Answer a chore from the browser** (M23). Answer one of S22's findings from the web UI's attention list; expect
  the chore's next run's prompt to carry the note.
- **S42. Try a chore from the browser** (M23). With `canopy loop` running, press Try now on S22's chore's page. Expect
  its run in Runs at once, running, with no tick; the page to follow it to its end through the stream; its
  findings on the attention list; and the overseer's next run of it `not_due` counting from the try. Stop the loop
  while the try runs: the run goes on, and ends recorded.
- **S24. The desktop sink** (M10). Expect one ticket's blocked question and one attention item as desktop
  notifications, once each.
- **S25. The Slack sink** (M10). On a real channel, one ticket's dispatch, its worker's question, and its PR each reach
  the channel once; an attention item is posted when it opens and when it resolves. Remove the webhook file: Slack
  fails for several ticks while another sink keeps delivering and reports `loop.sink_failing`; restore it and what
  was missed arrives in one message. A digest arrives on its interval, a quiet one included. With a bot token and
  `--threads`: the dispatch starts the ticket's thread, its question is a reply also shown in the channel, a chore's
  run starts its own thread, and the next day's first post about the ticket starts a new one.

### Notices and search

- **S37. A notice during a CI outage** (M35). During a CI outage, real or staged (a check that fails fetching a
  dependency), set a notice from the CLI (`canopy notice 'TEXT' --for 1h`) or the web UI's settings page. Expect the
  banner on every page and the line in `canopy status`; the next worker's summary to take the notice into account; the
  overseer to record `wait` for the `ci_red` unit whose check the outage failed, naming the notice, with no `resume`
  for it; once the notice lapses, `notice_rerun` on the attention list until the operator reruns the check, and no
  `resume` for it before that newer run; and the next worker's prompt after the lapse to carry `None.` for the notice.
- **S32. Search** (M31). After a week of `canopy loop`, type into the web UI's search box a word of a ticket's title,
  then a phrase from a run's summary. Expect the ticket, by its branch, and the run's report among the hits, each
  opening the page that holds it. Then search for something nothing matches: expect the answer in under a second, and
  time `GET /search` in the browser's network tab. Over a quarter of a second is the cue to revisit FTS5 (DESIGN §22).

### Worktree pools

canopy's own pool (DESIGN §18, ROADMAP M45) doing treehouse's work on the toy workspace (`TOY_REPOS.md`): leasing,
resetting, reusing, seeding, and returning slots for real workers, with real processes in them. The contract suite
holds it to the same guarantees with throwaway repositories and fake runs. Run these before stage 3's live week, and
again after a change to `core/pool.py`, `canopy workspace sync`, or how reconcile returns leases.

Run them in order, as the kit's `toycanopy` from the workspace root, starting under `pools.backend = "treehouse"`
with `capacity.slots_per_repo = 2` synced. S52 leaves slots no command can release yet (#811), so it goes last. A run
is a small toy-calc issue (S8's or S16's), started with `canopy start KEY` and dispatched by `canopy tick`; most steps
end it with `canopy stop --now KEY` once they have seen what they need. First, give toy-calc's clone an ignored cache
and a file to seed:

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

## Measurements

Each records its numbers in `MEASUREMENTS.md`, as a dated section.

- **S27. An overnight loop** (M21). Leave `canopy loop` running overnight. Expect, in its output and log (`loop waits`
  lines), waits reaching `loop.idle_max_minutes` after a quiet evening, back at `loop.interval_minutes` within one tick
  of the first morning activity, and each run's end followed by a tick within a couple of minutes. Re-measure
  afterwards with MEASUREMENTS' prompt; M39 waits on the result.
- **S33. The overseer's prompt from the cache** (M34). Run two `canopy tick --dry-run` a minute apart, and read each
  tick's first model call from the journal: `SELECT id, tokens_first_call, tokens_first_cache_write, definitions_digest
  FROM ticks ORDER BY id DESC LIMIT 2` (DESIGN §13; the first `step_finish` event in `<state_dir>/ticks/<id>.log` holds
  the same). Expect the second tick's write near the state block's size, a few thousand tokens, and the rest of its
  first call, nearly all read from the cache, to hold the prompt, the provider skill, and the tools; the first tick,
  cold, writes them all. Over a longer stretch, `canopy spend --json`'s `first_calls` gives each snapshot's median first
  call and cold share. Run it after a change to the overseer's definition or prompt, or an OpenCode upgrade, which may
  change where OpenCode puts an agent's body. If the second tick's write still holds the prompt, M34's change did not
  take: file an issue. Record the numbers in `MEASUREMENTS.md`. M34's saving on a warm tick was measured on 2026-10-15
  (F23).
- **S34. Overseer reliability re-measured** (M28). After a working session of `canopy loop` against the real queue,
  re-measure with MEASUREMENTS' prompt (Re-measuring). Expect no tick that ran the overseer without a working
  `canopy` (each such tick closes `canopy_unavailable` with its attention item instead), no `overseer_failed` tick
  that recorded decisions, and every start from the web UI picked up within about a minute (`ticks.woken_by` is
  `starts`). Record the numbers in `MEASUREMENTS.md`.
- **S35. Spend by what it bought** (M33). After a day of `canopy loop` against the real queue, read idle ticks' share
  of the live overseer's spend from `canopy spend` and from the web UI's spend page, both over their default week, then
  from a query on the journal over the same UTC days: `SELECT sum(cost_usd) FILTER (WHERE idle = 1) / sum(cost_usd)
  FROM ticks WHERE dry_run = 0 AND status != 'running' AND started_at >= date('now', '-6 days')`, the ticks that ended,
  as the share counts. Expect all three to agree, and each day's total on the page to match the CLI's.
- **S40. What each agent's first request holds** (M34's prefix, taken on request 2026-10-17). After an OpenCode
  upgrade, a new MCP server or toolset, or a change under `agents/`, record one short session of each canopy agent
  against a recorder on loopback and split its first request by source, as MEASUREMENTS' 2026-10-17 section says
  (Re-measuring the first request), on the operator's machine with their MCP servers. Expect OpenCode's own prompt
  absent and the agent's body first; no schema for a tool a definition denies outright; and, against that section, a
  difference only where the change made one. A body the split cannot find means OpenCode moved it. Record the tables
  in `MEASUREMENTS.md`.

## Retired

Retired 2026-10-18. Daily use exercises each, and the tests with the fakes hold the harness's half.

- **S17. Mirrored comments** (M19). The overseer mirrors every ticket's new comments in daily use; the cost before and
  after was a one-time comparison of a change long shipped.
- **S26. A watched session** (M12). The loop is the operator's daily surface; Ctrl-C in each state is
  `tests/canopy/loop/test_loop.py`'s.
- **S29. Why a ticket was or was not dispatched** (M24). The web UI reads the same decisions `canopy decisions` prints.
- **S31. Reloading config** (M12). A reload, a closed terminal, and `nohup` are `tests/canopy/loop/test_loop.py`'s and
  `tests/canopy/infra/test_hangup.py`'s.
- **S41. A plan a week later** (M44). Plans are files canopy never removes (DESIGN §25), so a week changes nothing.
