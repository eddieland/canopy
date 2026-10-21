# One-off tasks

Part of the canopy design, normative like all of it: work the operator hands canopy in their own words, about no
ticket. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [The overseer
reads the journal](READING_THE_JOURNAL.md).

## 36. One-off tasks

Designed, not built (ROADMAP M61).

A **task** is one-off work the operator submits in canopy, in their own words, about no ticket: exploring a question in
the code, trying an approach, or planning the tickets that should follow. A worker runs it once in a worktree of one
repository. What it leaves is a report, a branch, and perhaps a draft PR and some tickets, all of throwaway quality
until the operator gives them a pass of their own. A task is private like a started ticket (§22): its conversation
never touches the tracker. It is neither a ticket, which a label or a start authorizes and the loop drives to a PR, nor
a chore (§19), which recurs, reads only, and reports findings.

### Submitting

The operator submits a task's text, naming the repository when the workspace has more than one; `task:N` names it
afterwards (D075). The submission is the authorization: only the operator's channels write it, refused inside a tick or
any agent's run (TRUST_MODEL T1), and its text is the operator's instruction. A task never reaches the overseer, which
neither sees its text nor decides whether it runs, so no tracker or PR text can start, steer, or stop one.

### Starting

A submitted task waits for the next tick, which starts it in code, before the overseer runs, oldest first; a dry run
starts nothing (D036). Guards in code hold it (§4): one run per task at a time, and task runs count against
`capacity.max_workers` with everything else, of which `capacity.max_tasks` may be tasks, so tickets are not starved. A
task the guards hold waits, rather than being refused; the operator's submission or reply ends the loop's wait (§22).
Each run follows an operator's word, so a task never retries: a run that fails stays failed until the operator replies.

### The run

A task's run leases a slot in its repository's pool (§18), starts from the base branch, and runs the private worker's
definition (§22) with a prompt of its own: the operator's text and replies as instructions, earlier runs' reports as
data, and the result contract. canopy names its branch, `<branch_prefix>task/N`, a shape no ticket's branch can take
(§8), so nothing that reads canopy's branches mistakes it for a ticket's work; push verification (§8) holds the run to
it as to a ticket's. A run that commits nothing pushes nothing, and that is not a failure.

- It may open one PR for its branch, a draft by its prompt. canopy never drives it: no `resume`, no CI fix, no review
  reply. It is the operator's PR like any other, so it is reviewed only when `review.query` or a request names it
  (§21), which is one way to give it its pass.
- It may file tickets where the operator's text says, with no queue label, as follow-ups are filed (§18), at most
  `policy.max_follow_ups` per run. They authorize nothing; canopy records their keys against the task, checking only
  their text (D003), and the operator labels or starts the ones worth working.
- It may leave a report, a markdown file at the slot's root, excluded from git. canopy keeps it as it keeps a plan
  (§25): an operator-only file in the state directory, never read through a link, never sent anywhere. The result
  line's summary stays short; the report holds what a planning or exploring task found.

Result contract, the last line of its text (§13), validated (D026); anything else is `unknown`:

```json
{"status":"done|blocked|failed","summary":"...","question":"<only when blocked>","branch":"<only when pushed>","prs":["..."],"created":["..."]}
```

### The conversation

A reply to a task (§22) queues its next run, which continues its branch, or starts one if none was pushed. A `blocked`
run's question raises `awaiting_reply` (§14) until the operator replies. Stopping a task ends its run as `canopy stop`
ends a ticket's, and drops what was queued; it is never deleted, so its runs, report, and spend stay to read. Each run
that ends is a `task.ended` event (§20) with its summary, its question when `blocked`, and its branch and PR, never
its report.

### Trust model changes

The PR that builds it proposes them: T1 (a task's text and replies are the operator's, written only through the
operator's channels; its reports are data), T3 (`capacity.max_tasks`, one run per task, one run per operator word),
and T6 (a task's worker is the private worker, which may also open a PR for its own branch and file unlabeled tickets
where its text says; the PR's draft state is the prompt's rule, not a guard, and, as on a private ticket, only its
create tool writes to the tracker, which on GitHub also edits issues).

### Open

- A task across several repositories, in a desk (§18), when one asks for it.
- Promoting a task to a ticket, carrying its branch, so the loop drives it from there.
- Tasks in the web UI: submitting, replying, and reading the report.
