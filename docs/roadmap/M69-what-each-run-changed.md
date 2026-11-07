# M69. What each run changed, kept and shown

DESIGN §8, §21, §22, §23, §26, §29, §36, §42, and §45, TRUST_MODEL T1, T4, and T5. Asked for by the operator
(2026-11-04): richer git integration, around tracking and showing diffs. Today canopy knows a run by its branch and its
result line, and a task's run by the head it left too (§36). Which commit the branch was at when the run started, which
it left on origin, and what changed between them is not in the journal; the operator reads it on GitHub, where a
`resume`'s fix is lost among the branch's commits and a flaky kick (§23) has rewritten them. A diff is kept in three
places, each for one reader: a review keeps the reviewed commit against its base for its findings (§21, The diff); a
worker's run keeps its branch against its base only under `trust.review_replies = approve`, for the threads its drafts
answer (§29); and, with #2071, a run shown a checklist keeps the diff of what it pushed after the list (§42), which no
page shows yet. The run's own change, what this run did to the branch, is kept nowhere, and a run that ends `unpushed`
takes its work with it when its object directory goes.

This milestone makes a run's change a journal fact, kept for every worker's and task's run, and shows it where the
operator judges the run: its page, its PR's, and the CLI. Four stages, in order, each in its own PRs; stage 4 waits for
its own go-ahead.

- **Stage 1, the record.** As a worker's or a task's run ends (§8 step 5, after the push and before a flaky kick
  rewrites the branch), `_run` and `_task` record, per slot, the commit origin's branch held when the run started, or
  the base's commit the run started from when origin had no branch, the commit the run left on origin, and the merge
  base with its base branch as the slot last fetched it, since nothing here fetches; and keep two diffs beside the run's
  log, as a review keeps its one: the run's own change, from the first commit to the second, and the branch against its
  base, which §29 keeps under `approve` today and is from now on kept for every run, with or without drafts. A joint run
  records and keeps one set per repository. A slot the run left unpushed keeps the diff of the last commit the run made
  there, found as the push check finds the commits a push left behind, marked as work not on origin, so what it did can
  still be read, though its commits are gone with it; a joint run's slot that pushed is not so marked, whatever the
  run's status; a `crashed` run, in whose slots no git runs (§8 step 5), keeps nothing. Best effort throughout, as a
  kept diff is: the run needs none of it, a failure is logged, and the journal says when a diff is missing. The commits
  are the harness's own reads of origin, never the agent's word, and the diffs are read and shown within `review_diff`'s
  bounds. `canopy show run:ID` and `show task:N` print each repository's range as short commits and the kept diffs'
  paths; `--diff` prints the run's own change, for a pager. Garbage collection removes the files after `run_files_days`
  with the run's others (§26), a task run's files, which the pass leaves alone today, joining it, and the rows never:
  the range is how a later run, a kick, or the operator tells which commits were whose.
- **Stage 2, shown.** The run's page gets a Diff panel of what the run changed, drawn by the diff panels a review's page
  has (`DiffPanels`, D121), a joint run's one per repository, with a toggle to the branch against its base; an
  `unpushed` run's says its diff is of work not on origin, and a run whose diff was not kept says so rather than showing
  nothing. A run shown a checklist shows each kept stretch (#2071) under its Checklist panel, the diff of what it pushed
  after the list, so the answers and the fix are read together. The PR's page shows its threads on the kept diff of the
  latest run that pushed under every `trust.review_replies` setting, not only `approve`, since the diff is now always
  there, and its runs list says each run's range. A task run's page shows its diff as a worker run's does. The ticket's
  page runs list says each run's range in short commits, linking to the run. The CLI's surface is `canopy show`, above.
  Guide pages: runs, pull requests, checklists, and tasks; screenshots of the run's and the PR's page.
- **Stage 3, the commits.** As stage 1 records the range, the run also records the commits in it, from `git log` of the
  two, bounded: each one's id, its subject, cut and every hidden character named as a tracker comment's is (§22),
  whether it carries canopy's trailer and the runtime's (T5), and whether the harness's fallback push, not the worker,
  put it on origin. The note §8 step 5 writes about a commit without a mark becomes a column on the commit, and the note
  stays for the report. The run's page lists them under its Diff panel, each linked to its page on GitHub by the PR's
  URL, never a raw link (D113); the PR's page, in the runs list, becomes the branch's history: each run's commits, in
  order, with the flaky kicks between them (§23, `from_head` to `to_head`) and the harness's own pushes marked, so the
  operator reads who put what on the branch without leaving canopy. `canopy show run:ID` lists them too. The subjects
  are a worker's text, shown to the operator as text and given to no agent (T1).
- **Stage 4, the files against the plan (its own go-ahead).** With a run's diff kept, the files it touched are known in
  code: #1868's first step holds them to the files the ticket's approved plan names in its steps (§25), and the run's
  page says which files no step named and which steps touched nothing. No model, no attention item until real use asks
  for one. The operator decides whether to build this once stages 1 to 3 have been in real use.
- **What stays as it is.** The overseer's state block carries none of this (§6's cache, T1): a diff is for the operator,
  and the reviewer and the planner read git themselves through canopy's tools (§27). A review's kept diff and its
  findings' anchors are unchanged, and so is the diff of two commits that places a late finding (§21), which the kept
  range may serve later. The `vcs` source still observes no diff (§30). Nothing here pushes, fetches, or touches a
  branch: every read is of commits the run's slot already holds, at run end, with the harness's flags (D107).
- **Rejected:** reading the diff from GitHub when a page opens (principle 5: the web UI asks GitHub nothing, and the
  harness holds no GitHub client, D003); reading it from the pool at page open (the slot is returned, a kick may have
  rewritten the branch, the run's objects are deleted with it, and a page read would take the pool's lock, as only the
  worktrees page does today); the diffs in the journal rather than files beside the log (the journal stays small, and
  §26 already retires a run's files); a diff per commit (one per run is what the operator reads, and stage 3's list
  names the commits); a model's summary of the change (the run's own summary is that, and a diff is the fact under it);
  a page of the repository's history (canopy's record is the loop's own work, not the repository's).
- **Design and TRUST_MODEL.** DESIGN §45 states the promise, written ahead of the code: the range, the commits, and the
  kept diffs, which the pages rely on; stage 1's PR changes it only where the build makes it. In that PR, §29's sentence
  that keeps a diff under `approve` changes to say every run keeps one; §42's sentence on the stretch diff names where
  it shows; §36's sentence on the head a task's run leaves names §45 for its range and diffs; §26's table row for a
  run's files grows by the new ones, and a task run's files, which the table lacks today, get a row. No decision entry:
  nothing here spans the codebase or moves the trust boundary. TRUST_MODEL, in stage 1's PR: T4 (the harness reads
  nothing new from a slot: `rev-parse`, `merge-base`, and `diff` already run there after a worker under `approve`, with
  hooks and drivers off, D107; stage 3 adds `log`, read the same way); T1 (a diff and a commit's subject are a worker's
  text, shown to the operator as text, never put in an agent's prompt); T5 (unchanged in what it promises, and a run's
  commits and their marks are now a row each, not only a note).
- **Tests with the fakes**, against real git in a worktree slot, as `runs/test_checklist_hold.py` holds the hooks: an
  `implement` that pushes records the base's commit, origin's head, and the merge base, with both diffs kept; a `resume`
  records origin's previous head as its start, and its own diff holds the fix alone; a joint run records one row and one
  set of diffs per repository; a task run the same; an `unpushed` run keeps its slot's diff, marked, also when it moved
  HEAD back off its commits, and a joint run with one push refused marks that repository's alone; a `crashed` run keeps
  nothing and the journal says so; a run under `approve` keeps what it did before, and its threads still anchor; a run
  whose push a flaky kick follows keeps its diff from before the kick; stage 3's commits carry the marks git added and
  name one committed around the hooks; the diff files go with `run_files_days` and the rows stay; `core/test_db.py` and
  `test_records.py` for the migration and row types, `test_frozen.py` for the kept range's type, `test_layers.py` for
  the new module; a snapshot of `canopy show run:ID`; the web UI's unit tests for the Diff panel's states, the PR page's
  diff without `approve`, and a stretch under its checklist item.

Accept: Live, once stage 2 is built: a worker on a toy ticket has its run's page show the diff it pushed, the same
change GitHub's compare of the two commits shows; a `resume` for a review comment on it shows only the fix; a joint run
shows each repository's; a worker held by a checklist shows the stretch under its answers; the PR's page shows its
threads on the diff with `trust.review_replies = post`; and after a flaky kick the run's diff still reads. A week of
real use in `MEASUREMENTS.md`: the disk the kept diffs take per run and per day, how many runs kept none and why, and
the operator's word on whether the run's page replaced GitHub's compare for judging a run. Stage 3, once built: the PR's
page lists the branch's commits run by run, kicks between them, matching `git log` of the branch.

Status: in progress. Stage 1 built 2026-11-06 against the fakes: `_run` and `_task` record a `run_changes` row per
slot after the push check and before a kick, keep `<id>.<repo>.change.diff` and the branch's `<id>.<repo>.diff` with its
head for every run, mark an unpushed slot's last commit, record a crashed run's row as having read nothing, and print
it all in `canopy show run:ID` and `task:N`, with `--diff` for the run's own change; garbage collection takes the new
files with the run's others, a task run's too, and a checklist's stretches, which a pass had removed as unrecorded.
Chosen conservatively, for the operator to change: the branch's diff is still the one file §29's PR page reads, so a
PR's page under `post` shows its threads on it from now on; a run reconcile closes, and a plan run, records nothing; a
run that crashes after its slots were read is recorded as having read nothing, its kept files left to garbage
collection; `task:N --diff` prints the newest of its runs that recorded one. Stage 2 in part, 2026-11-07, against the
fakes: a worker run's page, and a task run's, has a Diff panel per repository after its checklist, the run's own change
in `DiffPanels` with a toggle to the branch against its base, an unpushed slot's marked as work not on origin, a diff
not kept saying why or that retention removed it, and an ended run of a kind that records saying it recorded nothing;
a ticket's runs list names each run's range in short commits, linking to the run (the stretches under the checklist
came 2026-11-06). Both diffs are sent with the page, each within `review_diff`'s bounds; the mock's runs 39, 40, and
37 and task 1's run show the states, so the screenshots of `workspace/runs/39` and `tasks/1/runs/1` are to be taken
again. Left for a follow-up: the PR's page, its threads on the kept diff under every `trust.review_replies` setting and
each run's range in its runs list, and its guide page.
