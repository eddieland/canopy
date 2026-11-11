# What a run changed

Part of the canopy design, normative like all of it: what a worker's or a task's run leaves of its push, the commits
its branch went from and to and the diff between them, kept for the operator. Sections are numbered across the whole
design; the [README](README.md) has the map. Previous: [Messages to running agents](MESSAGES.md).

## 45. What a run changed

A run's result says what its worker thinks it did; its branch on GitHub shows every commit anyone put there,
rewritten by each flaky kick (§23). Neither says what this run changed. This section makes that a journal fact, read
by the harness from the run's own slot as it ends and kept for the operator, who judges a run by its diff more than by
its summary.

### The record

As a worker's or a task's run ends, after its push and before a flaky kick rewrites the branch (§8 step 5), the harness
records, per slot: the commit origin's branch held when the run started, or the base's commit the run started from when
origin had no branch yet; the commit the run left on origin, or none, for a run that left no branch there; and the merge
base with its base branch as the slot last fetched it, since nothing here fetches. A joint run (§18) records one per
repository. The commits are the harness's own reads of origin and of the slot, never the agent's word. The rows are
never removed (§26): a later run, a kick, or the operator tells by them which commits were whose.

### The kept diffs

Beside the run's log, the harness keeps two diffs per slot, as a review keeps its one (§21, The diff): the run's own
change, from the commit it started from to the one it left, and the branch against its base, which §29 keeps for its
threads and which every run now keeps, with or without drafts. A slot the run left unpushed keeps the diff of the last
commit the run made there, found as the push check finds what a push left behind, marked as work not on origin, so what
it did can be read though its commits go with it, and a joint run's slot that pushed is not so marked; a `crashed` run,
in whose slots no git runs, keeps nothing. Each is kept then or never: the slot is returned, a kick may rewrite the
branch, and the run's objects are deleted with it. Best effort, as a kept diff is: the run needs none of it, a failure
is logged, and the journal says when a diff is missing. The diffs are the branch's text, untrusted, read and shown
within the bounds a review's diff has, every control character dropped, on a page and at the terminal alike, with
drivers and textconv off (D107), and removed with the run's other files, a task run's too, after `run_files_days` (§26).

### Where it shows

The operator reads what a run changed where they judge the run: on its page, a worker run's or a task run's, a joint
run's per repository, a summary first, since the page is opened far more often to see why a run ended than to read its
diff: the range and how many files and lines it touched, as git counted them at the run's end and the journal keeps,
with the run's own diff read only when asked for, and the stretches a checklist kept (§42) inside it, under its
answers; on its PR's page, which holds the branch against its base, whose threads sit on the kept diff of the latest
run that pushed, under every `trust.review_replies` setting (§29); and from the CLI, which prints a kept diff on
request. An `unpushed` run's diff is marked as work not on origin, and a diff that was not kept is said to be missing,
never shown as nothing. What each page draws is `ui/DESIGN.md`'s. Nothing here reaches the overseer's state block (§6)
or any agent's prompt: the reviewer and the planner read git themselves (§27).

### The commits

With the range, the harness records the commits in it, bounded, the newest kept and all of them counted: each one's
id, its subject, cut and every hidden character named as a tracker comment's is (§22), whether it carries canopy's
trailer and prefix and another co-author's, as the runtime's attribution is (TRUST_MODEL T5), and whether the harness's
fallback push, not the worker, put it on origin. The run shows them with its diff, and the PR its branch's history run
by run, with the flaky kicks between them (§23) and the harness's own pushes marked, so the operator reads who put what
on the branch without leaving canopy. The note §8 step 5 writes about a commit that lacks a mark stays, for the report.
A subject is the operator's alone: an agent reading the run is told how many commits there were.

### What holds it (TRUST_MODEL T1, T4, T5)

- The harness reads a slot as it already does after a worker under `approve`: commits alone, by its own git with
  hooks, the filesystem monitor, drivers, and textconv off (D107), at run end and never from a page; the commits'
  subjects and trailers are one more read of the same kind, bounded and cleaned as the diff is. Nothing here pushes,
  fetches, or touches a branch.
- A diff and a commit's subject are a worker's text, shown to the operator as text and put in no agent's prompt (T1).
- A run's commits and their marks are a row each, not only a note, which is what T5 promises told structurally.

### Rejected

- Reading the diff from GitHub when a page opens: the web UI asks GitHub nothing (§4 principle 5), and the harness
  holds no GitHub client (D003).
- Reading it from the pool when a page opens: the slot is returned, a kick may have rewritten the branch, the run's
  objects are gone, and a page read would take the pool's lock.
- The diffs in the journal rather than files beside the log: the journal stays small, and §26 already retires a run's
  files.
- A diff per commit: one per run is what the operator reads, and the commits are listed by name.
- A model's summary of the change: the run's own summary is that, and a diff is the fact under it.
- The working tree's uncommitted edits in an `unpushed` run's diff: the diff is of commits, so it reads as the push
  would have, and an edit the worker never committed was never its work's checkpoint (§4).

### Open

- Whether the kept range should serve a review's late findings (§21), which diff two commits of their own today.
- The files a run touched against its plan's steps (§25), in code, once the diff is kept.
- Whether reconcile keeps the range and the diff of a run it closes after `_run` was killed (§6 step 3), which today
  returns the slot and keeps nothing.
