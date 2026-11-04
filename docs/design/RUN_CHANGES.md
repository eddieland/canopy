# What a run changed

Part of the canopy design, normative like all of it: what a worker's or a task's run leaves of its push, the commits
its branch went from and to and the diff between them, kept for the operator. Sections are numbered across the whole
design; the [README](README.md) has the map. Previous: [Messages to running agents](MESSAGES.md).

## 45. What a run changed

Not yet built (ROADMAP M69); the code does not follow it until it is.

A run's result line says what its worker thinks it did; its branch on GitHub shows every commit anyone put there,
rewritten by each flaky kick (§23). Neither says what this run changed. This section makes that a journal fact, read
by the harness from the run's own slot as it ends and kept for the operator, who judges a run by its diff more than by
its summary.

### The record

As a worker's or a task's run ends, after its push and before a flaky kick rewrites the branch (§8 step 5), the harness
records, per slot: the commit origin's branch held when the run started, or the base's commit the run started from when
origin had no branch yet; the commit the run left on origin; and the merge base with its base branch at the end. A
joint run (§18) records one per repository. The commits are the harness's own reads of origin and of the slot, never
the agent's word. The rows are never removed (§26): a later run, a kick, or the operator tells by them which commits
were whose.

### The kept diffs

Beside the run's log, the harness keeps two diffs per slot, as a review keeps its one (§21, The diff): the run's own
change, from the commit it started from to the one it left, and the branch against its base, which §29 keeps for its
threads and which every run now keeps, with or without drafts. A run that ends `unpushed` keeps the diff of its slot's
HEAD, marked as work not on origin, so what it did can be read though its commits go with it; a `crashed` run, in whose
slots no git runs, keeps nothing. Each is kept then or never: the slot is returned, a kick may rewrite the branch, and
the run's objects are deleted with it. Best effort, as a kept diff is: the run needs none of it, a failure is logged,
and the journal says when a diff is missing. The diffs are the branch's text, untrusted, read and shown within the
bounds a review's diff has, with drivers and textconv off (D107), and removed with the run's other files after
`run_files_days` (§26).

### Where it shows

The run's page shows what the run changed, a panel per file as a review's page draws them, a joint run's per
repository, with the branch against its base a toggle away; an `unpushed` run's says its diff is of work not on origin,
and a run whose diff was not kept says so. A run shown a checklist shows each stretch it kept (§42) under its answers.
The PR's page shows its threads on the latest run's kept diff under every `trust.review_replies` setting (§29), and its
runs each with the commits they went from and to. A task run's page shows its diff as a worker run's does. `canopy
show` prints each repository's range and the kept diffs' paths, and prints the run's own change on request. Nothing
here reaches the overseer's state block (§6) or any agent's prompt: the reviewer and the planner read git themselves
(§27).

### The commits

With the range, the harness records the commits in it, bounded: each one's id, its subject, cut and every hidden
character named as a tracker comment's is (§22), whether it carries canopy's trailer and the runtime's (TRUST_MODEL
T5), and whether the harness's fallback push, not the worker, put it on origin. The run's page lists them under its
diff, and the PR's page lists its branch's history run by run, with the flaky kicks between them (§23) and the
harness's own pushes marked, so the operator reads who put what on the branch without leaving canopy. The note §8 step
5 writes about a commit that lacks a mark stays, for the report.

### What holds it (TRUST_MODEL T1, T4, T5)

- The harness reads nothing new from a slot: the reads already run there after a worker, with hooks, the filesystem
  monitor, drivers, and textconv off (D107), at run end and never from a page. Nothing here pushes, fetches, or touches
  a branch.
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

### Open

- Whether the kept range should serve a review's late findings (§21), which diff two commits of their own today.
- The files a run touched against its plan's steps (§25), in code, once the diff is kept.
