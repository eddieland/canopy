# canopy scenarios

Live checks worth running through against real systems: the operator's queue, a real tracker and GitHub, the pinned
OpenCode. The fakes-based tests cover the harness's half of each; these cover the half only a real run can, the
model's judgment and the runtime's permissions above all.

Most came from milestone acceptance criteria that were closed on real use rather than by a dedicated run (ROADMAP,
2026-10-13). Each names the milestone it came from, which says why the behavior exists.

Run the ones that touch what changed: the canaries after an OpenCode upgrade, a lifecycle scenario after a change to
the prompt or the guards it relies on, the install scenarios before a release. A scenario that fails is a bug: file an
issue with the tick id, and its decisions (`canopy decisions TICK`). A run that measures something, such as spend or
latency, goes in `MEASUREMENTS.md` as a dated section.

Toy repositories to run them against, apart from real work and cheap to reset, are planned in `TOY_REPOS.md`.

## Canaries

Opt-in tests that run a real model under the pinned OpenCode. Run all of them after any OpenCode upgrade, and before
relying on a permission they check.

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

## Install and setup

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

## A ticket's lifecycle

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
- **S12. Stacked tickets** (M4). Two tickets, the second blocked by the first. Expect the second to wait, then be
  dispatched with `--base` on the first's branch once its PR is open and green. Then merge the first and watch what
  happens to the second's PR: nothing in canopy checks it.
- **S41. A plan a week later** (M44). A week after a ticket's plan was approved and implemented, open the ticket's
  page. Expect every plan it had still there, the approved one marked, with its comments.

## Several repositories

- **S13. One queue over two repositories** (M6). In a two-repository workspace, label one ticket in each. Expect both
  to reach open PRs from one queue, with every worktree under the workspace root.
- **S14. A joint run** (M7). A ticket that touches two repositories. Expect one run to open two PRs that link each
  other. Kill a joint run mid-way: the next tick returns all its slots.
- **S15. A split on request** (M8). After S2, on a ticket covering two repositories, an authorized replier asks for a
  split in a comment. Expect two linked children, the second blocked by the first, with no queue label on either, and
  nothing dispatched for them until you label them; then they are worked in order, one PR each.

## Private tickets and the conversation

- **S16. A private ticket** (M18). After S3, `canopy start` a real ticket. Expect its worker's question in
  `canopy status`, `canopy show`, and the web UI; answer it from the CLI; expect the PR to land for review and the
  ticket to show nothing canopy wrote.
- **S17. Mirrored comments** (M19). Over a working session, expect each new tracker comment mirrored into the journal
  once (`canopy show REF`), and compare a tick's cost before and after mirroring.
- **S18. Untrusted and trusted reviewers** (M22). A review bot's comment on a loop PR waits as `untrusted_review` with
  no dispatch. A reply from the web UI resumes it, with the reply as the worker's instruction. A comment from someone in
  `trust.trusted_reviewers` resumes it without a reply.

## Reviews

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
  the workspace, from the web UI's pull requests page. Expect each reviewed at its head, in its own repository, and
  its request to end `reviewed` (`canopy show URL`). Ask for one more on a PR that then merges before the next tick,
  and one on a PR in a repository the workspace does not have: expect the overseer's `canopy review end` to end them
  `merged` and `unknown_repo`. Nothing is posted on any PR.

## Chores and notifications

- **S22. A build-health chore over several days** (M9, `examples/chores/build-health.md`). Expect it never to start
  sooner than `every_minutes` after its previous run, and the `decisions` table to show the overseer following `when`.
  Each finding reaches the attention list, is notified once, and goes away after a run that no longer reports it. Kill
  a chore run mid-way: `crashed` with a `chore_failed` item. Delete the chore from the config: its items clear at the
  next tick.
- **S23. Answer a chore from the browser** (M23). Answer one of S22's findings from the web UI's attention list; expect
  the chore's next run's prompt to carry the note.
- **S24. The desktop sink** (M10). Expect one ticket's blocked question and one attention item as desktop
  notifications, once each.
- **S25. The Slack sink** (M10). On a real channel, one ticket's dispatch, its worker's question, and its PR each reach
  the channel once; an attention item is posted when it opens and when it resolves. Remove the webhook file: Slack
  fails for several ticks while another sink keeps delivering and reports `loop.sink_failing`; restore it and what
  was missed arrives in one message. A digest arrives on its interval, a quiet one included.
- **S42. Try a chore from the browser** (M23). With `canopy loop` running, press Try now on S22's chore's page. Expect
  its run in Runs at once, running, with no tick; the page to follow it to its end through the stream; its
  findings on the attention list; and the overseer's next run of it `not_due` counting from the try. Stop the loop
  while the try runs: the run goes on, and ends recorded.

## The loop

- **S26. A watched session** (M12). `canopy loop` against the real queue for a working session. Expect each tick's
  block to be legible. Ctrl-C during a tick stops the loop when that tick ends; Ctrl-C during the wait stops it at
  once.
- **S27. An overnight loop** (M21). Leave `canopy loop` running overnight. Expect, in its output and log (`loop waits`
  lines), waits reaching `loop.idle_max_minutes` after a quiet evening, back at `loop.interval_minutes` within one tick
  of the first morning activity, and each run's end followed by a tick within a couple of minutes. Re-measure
  afterwards with MEASUREMENTS' prompt; M39 waits on the result.
- **S31. Reloading config** (M12). With `canopy loop` running in a terminal, change `capacity.max_workers` and
  `kill -HUP` the loop during a tick, then press Reload on the web UI's settings page during the wait. Expect each tick
  to finish first, `config reloaded  capacity.max_workers changed` under it, and the next tick's footer to count to the
  new limit. Then close the terminal window: expect the loop gone, as before. Under `nohup`, expect it to outlive the
  window and still reload on `kill -HUP`.
- **S33. The overseer's prompt from the cache** (M34). Run two `canopy tick --dry-run` a minute apart, and read each
  tick's first model call from the journal: `SELECT id, tokens_first_call, tokens_first_cache_write, definitions_digest
  FROM ticks ORDER BY id DESC LIMIT 2` (DESIGN §13; the first `step_finish` event in `<state_dir>/ticks/<id>.log` holds
  the same). Expect the second tick's write near the state block's size, a few thousand tokens, and the rest of its
  first call, nearly all read from the cache, to hold the prompt, the provider skill, and the tools; the first tick,
  cold, writes them all. Over a longer stretch, `canopy spend --json`'s `first_calls` gives each snapshot's median first
  call and cold share. Run it after a change to the overseer's definition or prompt, or an OpenCode upgrade, which may
  change where OpenCode puts an agent's body. Then, after a working session of `canopy loop`, re-measure with
  MEASUREMENTS' prompt: expect the median tick that starts within the cache's lifetime of the one before at least 15%
  cheaper than on 2026-10-13 at the same price, with no change in what the ticks decided. If the second tick's write
  still holds the prompt, M34's change did not take: file an issue. Record the numbers in `MEASUREMENTS.md`.
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
- **S37. A notice during a CI outage** (M35). During a CI outage, real or staged (a check that fails fetching a
  dependency), set a notice from the CLI (`canopy notice 'TEXT' --for 1h`) or the web UI's settings page. Expect the
  banner on every page and the line in `canopy status`; the next worker's summary to take the notice into account; the
  overseer to record `wait` for the `ci_red` unit whose check the outage failed, naming the notice, with no `resume`
  for it; once the notice lapses, `notice_rerun` on the attention list until the operator reruns the check, and no
  `resume` for it before that newer run; and the next worker's prompt after the lapse to carry `None.` for the notice.
- **S40. What each agent's first request holds** (M34's prefix, taken on request 2026-10-17). After an OpenCode
  upgrade, a new MCP server or toolset, or a change under `agents/`, record one short session of each canopy agent
  against a recorder on loopback and split its first request by source, as MEASUREMENTS' 2026-10-17 section says
  (Re-measuring the first request), on the operator's machine with their MCP servers. Expect OpenCode's own prompt
  absent and the agent's body first; no schema for a tool a definition denies outright; and, against that section, a
  difference only where the change made one. A body the split cannot find means OpenCode moved it. Record the tables
  in `MEASUREMENTS.md`.

## The web UI

- **S28. Served on loopback and a private address** (M20). `canopy loop` serves a real journal to a browser on
  loopback and on a private address; the worktrees page reads the real pools.
- **S29. Why a ticket was or was not dispatched** (M24). After a day of the loop, find in the browser why a ticket was
  or was not dispatched in a given tick; expect it to match `canopy decisions`.
- **S30. A session's transcript** (M15, M27). Open a worker run's page and a tick's page. Expect the tool calls
  `opencode export <id>` shows for the same session id, and, for a failed run, its runtime error.
- **S38. A running run, watched live** (M27, taken on request 2026-10-15). While a worker runs under the pinned
  OpenCode, open its row on the runs page and its run's page. Expect its latest tool call on the row within seconds of
  the call ending, its cost moving at each model call, and its transcript growing as it goes, matching
  `opencode export <id>` for what it has done so far; and `canopy status` naming the same call. A row that shows
  nothing until the run ends means OpenCode is buffering its events, not printing them as they happen.
- **S32. Search** (M31). After a week of `canopy loop`, type into the web UI's search box a word of a ticket's title,
  then a phrase from a run's summary. Expect the ticket, by its branch, and the run's report among the hits, each
  opening the page that holds it. Then search for something nothing matches: expect the answer in under a second, and
  time `GET /search` in the browser's network tab. Over a quarter of a second is the cue to revisit FTS5 (DESIGN §22).
