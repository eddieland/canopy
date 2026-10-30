# M66. The checklist, asked before the push

REQUIREMENTS R27, DESIGN §8, §12, §21, §31, §33, §41, and §42, TRUST_MODEL T1, T3, T4, and T7. Asked for by the
operator (2026-10-29): the team keeps meeting the same nits, rules its architect asks for that `AGENTS.md` states and
no linter checks, and reviewers hold them only sometimes, canopy's adversarial reviewer among them. The operator's
standing worker instructions already emphasize them, and workers still miss them. Asking an agent one plain question,
"does this diff do X?", gets a reliable answer; a rule among forty at the top of a long run does not. So canopy asks
the operator's list at the moment it matters, once the worker's diff is whole and before it pushes, so a fix costs no CI
run, in the worker's own run, and records each answer (DESIGN §42). A second review that asks the same list of a PR
waits on what that measures. The rules are a repository's, not the workspace's: a workspace maps repositories of
different languages and teams, so each has its own list, and one without a list is not asked (the operator, 2026-10-30).

Today a worker reads the rules once, in the repository's docs and `paths.worker_instructions`, and the adversarial
reviewer is told to look for defects, not style (§21, step 3). Neither records, per rule, what was held and what was
missed. Three stages, in order, each in its own PRs; stage 3 waits on stage 2's numbers.

- **Stage 0, the first list.** The operator writes it, for one repository, before stage 1 starts, from the rules review
  already holds by hand: `AGENTS.md`'s "No linter checks this, so review does" is one (the most general parameter type),
  newspaper order and `#:` doc comments are two more, and the architect's are the rest. Each item has an id, the paths
  it is about, and the rule with one example that passes and one that fails. Ten to fifteen items; a longer list is a
  sign two lists are being asked for. Read by the operator as M60's stage 0 list was, since the list is what the feature
  is.
- **Stage 1, the reminder.** `paths.checklists`, private, a directory of Markdown files as `paths.personas` is, one
  `<repo>.md` per mapped repository that has a list. Each file: one `## <id>` heading per item, an optional `paths:`
  line of globs compared as `high_impact_paths` are (§21), an optional `severity:` line stage 3 reads, then the rule.
  Each bounded at 16 KiB, refused with hidden characters as a persona is, and parsed by the harness for its ids, so a
  result can be held to them. Before a worker run that may push starts (`implement`, `resume`, public and private, and a
  task's), the harness writes the list of each of the run's repositories that has one to the run's answers directory
  (§41), where each slot's hook finds its own repository's, and points the worker's git at canopy's hooks even with no
  mark to add; a run none of whose repositories has a list gets no file and is never reminded. canopy's `pre-push`
  (`core/commit_hooks.py`) gains the hold, before it hands on to the repository's own: it reads the refs git hands it
  and hands them on, holds only a push with something to send, prints a `[canopy]` line saying the push was held, not
  rejected, and its repository's list, asking the worker to diff the branch against its base, hold each item to the
  diff, commit what fails, answer each item in `checklist` in its result, and push again, and exits non-zero. It marks
  the hold in the slot's own git directory with the time and `CANOPY_RUN_ID`: a push of the same run within a window
  goes through, one after it is held again, and a marker of another run, left in a slot it outlived, counts for nothing.
  In the clock's last stretch, by `CANOPY_DEADLINE`, it prints the list and lets the push through, asking for the fix
  pushed again (D116); so it does when it cannot write the marker, which would otherwise hold every push. The worker
  prompts gain a sentence saying a push may be held, that a held push is pushed again once the list is answered, unlike
  a rejected one, and what `checklist` holds; the result contract gains it, validated: per repository and item, `pass`,
  `fixed`, `held` with a `reason`, or `n/a`; an item or a repository the run's lists do not hold is dropped, and a
  reminded run with no `checklist` is recorded unanswered. `canopy show-run` and the run's page show the answers;
  `canopy checklist` (and a web UI view) counts per repository and item reminded, pass, fixed, held, and unanswered,
  over a period, and `--repo` narrows it to one. No attention item.
- **Stage 2, the measurement.** Two weeks of real use in `MEASUREMENTS.md`: per repository and item, the counts above,
  and the nits of that item that still reached a human reviewer's comment on canopy's PRs, counted by the operator
  from the PRs. An
  item mostly `n/a` or never failing is reworded or dropped; an item often `held` is argued with the architect. The
  measurement says whether stage 3 is needed, and for which items.
- **Stage 3, the review, if stage 2 says so.** `checklist.review = true` turns on a checklist review (§42, The review):
  a review run of a new kind, `adversarial` or `checklist`, a `core/vocab.py` enum with its `CHECK`, owed wherever an
  adversarial review is, on a PR whose repository has a list, and started by the same `canopy review run` and `canopy
  start URL --review`, as a persona's is, so the overseer's prompt changes by a line at most. A prompt, `checklist.md`,
  and a definition, `canopy-checklist.md`, each in `.agents/sizes.toml`: the reviewer's definition with every MCP server
  denied but canopy's git tools and the `status` tool, no persona, no standing instructions. The prompt carries the
  diff's range, the items of its repository's list whose paths the diff touches, and the previous checklist review of
  the PR with the worker's answers, as the reviewer's does. `runtime.models.checklist`, defaulting to the reviewer's
  model. The result per item in §42, validated; the harness builds each `fail`'s findings with the item's title and
  severity. `canopy review show` and the review's page show the items as a table; the noise count gains the repository's
  item as a dimension; `review.eval_cases` take `kind = "checklist"` with an `item` and its `lines`, scored by `canopy
  review eval --checklist`. The `TRUST_MODEL` lines for it: T7 (one more private key), T1 (the list is the operator's
  instructions, the diff is data, the definition writes nothing), T3 (one more run per reviewed commit under review
  capacity, `max_workers`, and the daily limit, not the per-PR limit, and not retried on a commit).
- **Rejected:** the reminder after the push alone (the fix it asks for is a second CI run); the plugin's hold (it sees a
  command's text, so a script's, `make`'s, or a joint run's `git -C` push goes unseen, a chained commit is lost with the
  call, and each OpenCode version needs its own code; MEASUREMENTS, 2026-10-30); after each commit (a diff not yet
  whole, asked again and again); the list as standing instructions (the operator's already emphasize these rules, and
  workers miss them; no record per item); a persona (it cannot narrow, §31); the review first (a run, a slot, and a
  `resume` per commit before the cheaper ask is measured); one review run per item (as many leases per commit); one list
  for the workspace (another repository's items are `n/a` noise, and keeping them apart by `paths:` grows one list past
  its bound); the list read from the repository's checkout, a file of its own included (T1, T7); a reminder to the
  adversarial reviewer (its prompt already holds the repository's rules as one input; the list's place there is the
  checklist review).
- **TRUST_MODEL**, in the PR that builds stage 1: T1 (a forged `[canopy]` line can only ask the agent to check its own
  diff against a list it already holds); T4 (canopy's hook reads one more file in the answers directory and writes one
  marker in the slot's own git directory, which a sandboxed run may write and nothing on the host reads; the push it
  holds is only delayed); T5 (canopy's hooks now reach a run with a list and no mark); T7 (one more private path, listed
  with the others); T3 (unchanged: nothing on a reminder extends a run or holds a slot).
- **Tests with the fakes:** the hook's own, against real git in a worktree slot, as `runs/test_commit_trailers.py` holds
  canopy's hooks: a push held and nothing sent, the list in git's output, a commit chained before it made; the push
  after it sent and the repository's own `pre-push` run with its refs; a push from a script held; nothing to send not
  held; a marker of another run, or past the window, holding again; the clock's last stretch printing the list and
  pushing; a joint run's slots each held with their own list; a missing or overlong file holding nothing; a marker it
  cannot write letting the push through with the list; and canopy's marks still on each commit. A fake worker that
  pushes is held, pushes again, and answers, and its answers show on the run; a result without `checklist` after a hold
  is recorded unanswered; an unknown item or repository is dropped; a run in a repository without a list gets no file
  and is not held; with trailer and prefix off, a run with a list is still held; a list the harness cannot read refuses
  `bad_prompt`, and a list in the workspace file is a config error; the overseer, a planner, a reviewer, and a chore get
  no file; a sandboxed run reads the file and writes the marker, and cannot write the file (the sandbox's tests); the
  counts per repository and item; `test_prompt_sizes.py` for the prompts, `test_frozen.py` for the answer type, and
  `core/test_db.py` and `test_records.py` for where the answers are kept.

Accept: Stage 0's list read by the operator, before stage 1 starts. Live, once stage 1 is built: a worker on a toy
ticket with a deliberate hit on two items has its push held, as its transcript shows, fixes both, and pushes once, so
its branch's CI runs once, and its run's page shows `fixed` on those and `pass` or `n/a` on the rest, before the PR is
`green_unreviewed`; a sandboxed worker the same; a joint run's worker held in each repository with that repository's
list; a worker in a repository without a list is not held; and two weeks of real use are in `MEASUREMENTS.md` as stage 2
says, with the operator's call on stage 3 recorded on the `Status:` line.

Status: not started. Designed 2026-10-29 (DESIGN §42); the operator chose the reminder over the review as the first
stage the same day, on the evidence that standing instructions already emphasize these rules and workers miss them.
Made a list per repository 2026-10-30, at the operator's ask, and the reminder held before the push the same day, so a
fix costs no CI run. The operator put the hold in canopy's own `pre-push` hook, not the plugin, the same day, on
MEASUREMENTS "2026-10-30: where M66's checklist can hold a worker's push".
