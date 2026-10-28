# canopy scenarios

Live checks worth running through against real systems: the operator's queue, a real tracker and GitHub, the pinned
OpenCode. The fakes-based tests cover the harness's half of each, and a new one is told through the `scenario`
fixture (`tests/canopy/scenario_helpers.py`); these cover the half only a real run can, the model's judgment and the
runtime's permissions above all.

Most came from milestone acceptance criteria that were closed on real use rather than by a dedicated run (ROADMAP,
2026-10-13). Each names the milestone it came from, which says why the behavior exists. A scenario's number stays
with it; one retired is listed at the end and its number is not given out again.

A scenario earns its place by checking something that daily use would not show and the tests with the fakes cannot:
an OpenCode permission or output, a real system's behavior the fakes stand in for, a trust rule, or a model judgment
that needs a failure staged. One that real use exercises every day, one whose harness half is a guard the tests hold,
or one whose real half has been measured, is retired. An open milestone's checks that need a kit of steps live in its
file, not here.

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
- **S3. The private worker's wildcard deny** (M18). Confirmed in OpenCode's source (1.18.35), not in a run. Start a
  ticket privately and check that its worker can call the tracker's `tracker.read_tools` and is refused every other
  tool of the tracker's server, and the tracker CLIs in bash.
- **S65. The overseer's tools** (M48). Run a tick on the pinned OpenCode. Expect its transcript to show `canopy_*`
  tool calls and no `bash`, every duty met through them, and a worker it dispatches offered no `canopy_*` tool. After
  an upgrade, check too that code mode is still off (OpenCode 1's `OPENCODE_EXPERIMENTAL_CODE_MODE=false`, OpenCode
  2's entry `codemode: false`), that a tool call still waits as long as the entry's `timeout` (1), and that the
  overseer's first model call is sent the tools (2).
- **S44. The token split** (M33). Confirmed in OpenCode's source (1.19.3), not in a run. canopy's new tokens add a
  `step_finish`'s `output` and `reasoning` (`runtime/opencode/events.py`), which holds only while `output` leaves
  reasoning out. Check that OpenCode's `session.ts` still sets `output: outputTokens - reasoningTokens`; aide found the
  overlap differed in earlier releases (PRIOR_ART).
- **S38. A session's transcript, live and after** (M15, M27, taken on request 2026-10-15). While a worker runs under the
  pinned OpenCode, open its row on the runs page and its run's page. Expect its latest tool call on the row within
  seconds of the call ending, its cost moving at each model call, and its transcript growing as it goes, matching
  `opencode export <id>` (OpenCode 2's `opencode session export <id>`) for what it has done so far; and `canopy status`
  naming the same call. A row that shows nothing until the run ends means OpenCode is buffering its events, not
  printing them as they happen. Once it ends, and on a tick's page, expect the tool calls the export shows for the same
  session id, and, for a failed run, its runtime error.
- **S61. The clock** (M57). Give a worker a 5-minute `runtime.worker_timeout_minutes` and a toy ticket it cannot finish
  in that time, once unsandboxed and once under `canopy-sandbox`. Expect canopy's `[canopy]` line in its transcript in
  its last minute, after a built-in tool's output and first in an MCP tool's result, the longer wording once, and a push
  before the kill; and no `node_modules` or `package.json` written into the snapshot. Then run it in a repository with a
  `.opencode/` directory, sandboxed with the registry refused, and time the wait before the session starts. Record the
  times in `MEASUREMENTS.md`.
- **S65. The split** (#923). Confirmed against OpenCode's source (1.19.3), not in a run: the plugin finds where the
  environment starts by the lines `session/system.ts` writes. With S40's recorder, unsandboxed, run two workers in two
  slots, then two reviews, each pair within five minutes. Expect two system blocks in every request, the first the
  agent's body alone and equal across the pair, each with a breakpoint; and the second run's first call reading the
  tools and the body from the cache, writing only from the environment on. One system block means OpenCode changed those
  lines: the split leaves the prompt as it was. Record the tables in `MEASUREMENTS.md`. Then, over a week of real use,
  compare `canopy spend --json`'s first calls for the `workers`, `plans`, and `reviews` kinds on the snapshot with the
  split against the one before it: expect `cold_share` to fall where unsandboxed runs of one kind start within five
  minutes of each other, and no change otherwise, sandboxed runs' included. No fall at all means the split found no
  boundary, or such runs are too rare for it to pay.

## Before a release

- **S5. A second person installs from README** (M5). Someone who has not used canopy follows README's install steps
  without help, then runs it against a ticket of their own. Expect it to work in five steps; file their friction as
  issues.
- **S7. Slot setup in a Bazel repository** (M16, `docs/BAZEL.md`). With the recipe in `~/.bazelrc`, a personal
  `paths.worktree_include` that seeds a gitignored file, and a `setup_cmd` that runs `bazel fetch`, expect a real
  `implement` worker to find the seeded file in its slot and its `bazel test` to hit the disk cache another slot
  filled. A `setup_cmd` that exits 1 ends the run `crashed`, with no worker started and the slot returned. A slot's
  Bazel server exits once idle for `--max_idle_secs` after its run.

## Live checks

Run the ones in the area a change touches, or that rely on a prompt or guard it changes.

### A ticket's lifecycle

- **S43. A red check and a review comment, one run** (M56). On one of the loop's PRs with a red check and a new review
  comment from a trusted reviewer, expect the next tick to send one `resume` with reasons `ci` and `review`, shown as
  `resume (ci, review)` in `canopy status`, which fixes the check and addresses the comment in one push.
- **S63. A flaky check, left for a rerun** (M25). On one of the loop's PRs, make a check fail for a reason the change
  did not cause (a job that sleeps past its timeout on one run only, say). Expect the `resume` for `ci` to push nothing
  for it and end `done` with `flaky`, and the next tick to record `flaky_rerun` naming the check, not another `resume`.
  Rerun the check: green clears the item. On a PR whose failure is the change's, expect a fix and no `flaky`.
- **S66. A flaky check, kicked** (the operator's ask, 2026-10-28). With `trust.max_flaky_kicks = 1` and the check of
  S63 failing, expect the `resume` for `ci` to end `done` with `flaky`, its PR's branch rebased onto its base and
  pushed once, its checks running on the new head, and the next tick to `wait`, not record `flaky_rerun`. Fail the
  check once more: expect no second kick, and `flaky_rerun`. Check that branch protection accepted the leased push.
- **S12. Stacked tickets** (M4, M56). Two tickets, the second blocked by the first. Expect the second to wait, then be
  dispatched with `--base` on the first's branch once its PR is open and green. Then merge the first: expect a
  `resume (retarget)` for the second, without `--base`, that points its PR at the repository's base branch.

### Several repositories

- **S14. A joint run** (M7). A ticket that touches two repositories. Expect one run to open two PRs that link each
  other. Kill a joint run mid-way: the next tick returns all its slots.

### Private tickets and trust

- **S16. A private ticket** (M18). After S3, `canopy start` a real ticket. Expect its worker's question in
  `canopy status`, `canopy show`, and the web UI; answer it from the CLI; expect the PR to land for review and the
  ticket to show nothing canopy wrote.
- **S18. Untrusted and trusted reviewers** (M22). A review bot's comment on a loop PR waits as `untrusted_review` with
  no dispatch. A reply from the web UI resumes it, with the reply as the worker's instruction. A comment from someone in
  `trust.trusted_reviewers` resumes it without a reply.
- **S65. Limits and trust from the web UI** (M41). While `canopy loop` runs, change `capacity.slots_per_repo` and remove
  a trusted reviewer on the web UI's Settings, Limits and trust page. Expect the next tick to lease under the new size
  and its overseer's state block to carry the shorter list, and the workspace's private file, `.canopy/config.toml`, to
  keep its comments, with only those two values changed, and `~/.config/canopy/config.toml` untouched. Then try a
  count past its ceiling and adding a reviewer back by hand-crafting the request: expect each refused, naming its
  guard, and the files unchanged.

### Reviews

- **S54. Drafts staged, and submitted on GitHub** (M53). With drafts waiting on one of the loop's PRs, `canopy draft
  stage` two replies and the PR's comment. On GitHub, expect one pending review under your login holding both replies
  on their threads and the comment as its body, which a coworker cannot see; add a comment of your own to it and
  submit it from the PR's files page. Expect the next tick to settle both drafts `sent`, to dispatch nothing for them,
  and the body you submitted to be the one canopy staged.
- **S58. The reviewer and the planner read git through canopy's tools** (#1130). Review a stacked PR, and plan a
  ticket over two repositories, once unsandboxed and once with `canopy-sandbox` around `plan_cmd` and `review_cmd`.
  Expect `canopy show` of each run to list `canopy_git_*` among its tools, the transcripts to show the reviewer finding
  where the PR leaves its base and reading the diff from there, and the planner naming each repository with `repo`;
  no tool call fails for the server, and nothing in either checkout changes.
- **S64. A review's draft revised, published once, and staged** (M43). On a coworker's PR canopy reviewed on request,
  ask for a revision from the review's page with a note: expect the next tick to revise the draft at the reviewed
  commit, and its new version to follow the note. Publish it, then publish it again: expect the second refused. On a
  second PR, stage the draft: expect a pending review under your login holding that version on its lines, and
  `review_unsettled` on the attention list, until you submit it on GitHub and the next read records it published.

### Notifications and notices

- **S25. The Slack sink** (M10). On a real channel, one ticket's dispatch, its worker's question, and its PR each reach
  the channel once; an attention item is posted when it opens and when it resolves. Remove the webhook file: Slack
  fails for several ticks while another sink keeps delivering and reports `loop.sink_failing`; restore it and what
  was missed arrives in one message. A digest arrives on its interval, a quiet one included. With a bot token and
  `--threads`: the ticket's thread starts with a post naming it and its title, the dispatch and its question are
  replies in it and not in the channel, a chore's run starts its own thread the same way, and the next day's first post
  about the ticket starts a new one. Add
  `--broadcast blocked`: the next question is a reply also shown in the channel.
- **S37. A notice during a CI outage** (M35). During a CI outage, real or staged (a check that fails fetching a
  dependency), set a notice from the CLI (`canopy notice 'TEXT' --for 1h`) or the web UI's settings page. Expect the
  banner on every page and the line in `canopy status`; the next worker's summary to take the notice into account; the
  overseer to record `wait` for the `ci_red` unit whose check the outage failed, naming the notice, with no `resume`
  for it; once the notice lapses, `notice_rerun` on the attention list until the operator reruns the check, and no
  `resume` for it before that newer run; and the next worker's prompt after the lapse to have no notice section.

### Connectors

- **S56. Jira read by its connector** (M36). Put your email and an API token in `~/.config/canopy/jira-credentials`,
  one line `EMAIL:API_TOKEN`, mode 600, and add `[connect.sources.jira]` with `kind = "tracker"` and
  `cmd = "canopy-connect-jira --site <your site>"`. Run `canopy tick --dry-run`. Expect `canopy status` to name the
  source with an `ok` run; `observed_tickets` to hold every open ticket the query returns, each watched ticket's
  blockers, and a `needs-human` label's time from its changelog; and `observed_comments` each watched ticket's
  comments, authors as account ids, text as Jira shows it. Label a ticket the query returns past its first 100: expect
  it in the run's query result. Then `chmod 644` the file: expect the next run failed, naming the file, the
  observations kept.
- **S57. GitHub read by canopy's own reader** (M36). With `gh` logged in and no `[connect.sources]` of kind `vcs`,
  in a workspace whose map names a GitHub repository with a PR of the loop's open and a branch under
  `trust.branch_prefix` with none, set `review.query` and run `canopy tick --dry-run`. Expect `canopy status` to name
  `github` with an `ok` run; `observed_prs` the PR's labels and a `mergeable_state` GitHub's page agrees with;
  `observed_checks` every context at its head, check runs and commit statuses alike, with no combined status, past 100
  where a PR has more; `observed_branches` the branch; the run's review query result the PRs GitHub's search shows;
  and the derivation no longer counting the PR-less ticket stale for its branches. Point the map at a repository on
  a host `gh` is not logged in to: expect a `partial` run naming it, and the other repositories still read.

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
- **S40. What each agent's first request holds** (M34's prefix, taken on request 2026-10-17; #432). After an OpenCode
  upgrade, a new MCP server or toolset, or a change under `agents/`, record one short session of each agent
  `.agents/agents/` ships against a recorder on loopback and split its first request by source, as MEASUREMENTS'
  2026-10-17 section says (Re-measuring the first request), on the operator's machine with their MCP servers: the
  tracker's server has been in no run yet, and `split.py` gives each server's tools a row of their own. Run each agent
  as canopy does, with the operator's own HOME, so that the skills their home holds are listed as in a real run
  (2026-10-21 F52), and once more with `OPENCODE_DISABLE_EXTERNAL_SKILLS=1` for the rows that compare. Expect
  OpenCode's own prompt absent and the agent's body first; no schema for a tool a definition denies outright; and,
  against the latest such section (2026-10-21), a difference only where the change made one. A body the split cannot
  find means OpenCode moved it. Record the tables in `MEASUREMENTS.md`. After an OpenCode upgrade, record one agent
  twice more, in two directories, unsandboxed, and compare the two requests as 2026-10-19's second section did: expect
  them to share the tools and the body, which canopy's plugin splits from the rest (F50, S65), and nothing if it did
  not (F48). Sandboxed, expect them to share nothing: the shell tool names each run's own `TMPDIR`.
  Of the tracker's server, expect the overseer, the reviewer, and the chore sent only its read tools (Jira's 12 by
  default). Off a GitHub tracker, expect both workers and the planner sent none of GitHub's issue tools (`issue_read`,
  `issue_write`, `list_issues`, `search_issues`, `list_issue_types`, `list_issue_fields`, `get_label`; #436): about
  2.8k tokens less on each worker run and 1.8k on each plan (2026-10-21 F54), and every other tool as on 2026-10-21.
  Once M48 gives the overseer `canopy _mcp`, expect its eleven tools, about 2.3k tokens (F55), and `bash` gone if its
  rules deny it whole. Then let `canopy loop` run a week and expect no run or tick whose transcript shows a
  call to a tool it was not offered (`tool not found`).

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

Retired 2026-10-19. Split runs are gone, replaced by follow-ups (M46).

- **S2. The splitter's MCP name patterns** (M8). The splitter's definition is gone.
- **S15. A split on request** (M8). A reply asking for a split is now guidance to the ticket's next run.

Retired 2026-10-22, held to the stricter bar above. Daily use shows each, or the harness's half is a guard the tests
with the fakes hold.

- **S6. A workspace from clone URLs** (M17). Sizing, trimming, and dropping a repository are `canopy workspace sync`'s
  tests; canopy's own pool has M45's checks.
- **S8. Label to PR** (M2). Every ticket the loop takes; a killed worker is reconcile's tests.
- **S9. A failing check, to the limit** (M3, M56). The cooldown and the attempt limit are hard guards in code.
- **S10. A conflicted PR** (M3). Conflicts come up in daily use.
- **S11. A blocked question** (M3, M22). Workers ask in daily use; who may reply is a guard in code.
- **S13. One queue over two repositories** (M6). The operator's own workspace.
- **S19. A finding, resumed and re-reviewed** (M11). Daily use with `review.agent_prs` on.
- **S20. A review of your own PR** (M11). The reviewer's read-only checkout is S1's.
- **S21. A review killed, and the limit** (M11). Both are guards in code.
- **S22. A build-health chore over several days** (M9). Chores run in daily use; `every_minutes` is a guard in code.
- **S23. Answer a chore from the browser** (M23), **S36. A shadow review on its page** (M32), **S42. Try a chore from
  the browser** (M23), **S55. Memory's verbs from the web UI** (M52). Web UI pages, held by the Playwright specs and
  opened in daily use.
- **S24. The desktop sink** (M10). A configured sink fires in daily use.
- **S28. Served on loopback and a private address** (M20). The web UI is served in daily use.
- **S30. A session's transcript** (M15, M27). Folded into S38.
- **S32. Search** (M31). A slow search shows in daily use.
- **S35. Spend by what it bought** (M33). One module behind the command and the route makes them agree by
  construction.
- **S39. A coworker's PR, reviewed on request** (M42). Review requests come up in daily use; their endings are the
  overseer's commands, held by the tests.

Moved 2026-10-22 to the file of their open milestone, keeping their numbers.

- **S45 to S53. Worktree pools** (M45). Stage 3's and stage 4's checks on the toy workspace.
- **S59, S60, S62. What canopy keeps, and a week of passes** (M47). Stages 1 to 3's checks.

Retired 2026-10-23. The overseer has no shell; it mirrors through a tool (M48).

- **S4. A heredoc `canopy` command** (M19). No heredoc is left to admit: a comment's body is a field of the `mirror`
  tool.
