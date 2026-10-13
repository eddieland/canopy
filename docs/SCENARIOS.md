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
- **S9. A failing check, to the limit** (M3). On a PR whose check fails, expect exactly one `fix-ci` attempt per
  cooldown window and an `attempt_limit` item at the limit, with no attempt after it.
- **S10. A conflicted PR** (M3). Make a PR conflict with its base. Expect `conflicted`, then a worker that merges the
  base to a clean PR.
- **S11. A blocked question** (M3, M22). Write a ticket that tells the worker to ask first. Expect one concrete question
  on the ticket and `needs-human`. A reply from an account not in `trust.authorized_repliers` does not resume it; an
  authorized one does, and so does `canopy reply` or the web UI's reply, with nothing of it on the ticket.
- **S12. Stacked tickets** (M4). Two tickets, the second blocked by the first. Expect the second to wait, then be
  dispatched with `--base` on the first's branch once its PR is open and green. Then merge the first and watch what
  happens to the second's PR: nothing in canopy checks it.

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
  checks pass; a finding goes back through `resume`, the new commit is reviewed again, and the ticket reaches
  `needs_reviewer`, with no review comment counted as a human's.
- **S20. A review of your own PR** (M11). With a `review.query` that matches a PR you wrote, expect one identified
  comment per new head commit and nothing else: no push, no ticket, no GitHub review.
- **S21. A review killed, and the limit** (M11). Kill a review run mid-way: the next tick returns its slot and raises
  `review_failed`. A PR at `policy.max_reviews_per_pr` gets no more reviews.

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

## The loop

- **S26. A watched session** (M12). `canopy loop` against the real queue for a working session. Expect each tick's
  block to be legible. Ctrl-C during a tick stops the loop when that tick ends; Ctrl-C during the wait stops it at
  once.
- **S27. An overnight loop** (M21). Leave `canopy loop` running overnight. Expect, in its output and log (`loop waits`
  lines), waits reaching `loop.idle_max_minutes` after a quiet evening, back at `loop.interval_minutes` within one tick
  of the first morning activity, and each run's end followed by a tick within a couple of minutes. Re-measure
  afterwards with MEASUREMENTS' prompt; M29 waits on the result.

## The web UI

- **S28. Served on loopback and a private address** (M20). `canopy loop` serves a real journal to a browser on
  loopback and on a private address; the worktrees page reads the real pools.
- **S29. Why a ticket was or was not dispatched** (M24). After a day of the loop, find in the browser why a ticket was
  or was not dispatched in a given tick; expect it to match `canopy decisions`.
- **S30. A session's transcript** (M15, M27). Open a worker run's page and a tick's page. Expect the tool calls
  `opencode export <id>` shows for the same session id, and, for a failed run, its runtime error.
