# M61. One-off tasks

REQUIREMENTS R25, DESIGN §36, §8, §14, §18, §20, and §22, TRUST_MODEL T1, T3, and T6. Asked for by the operator
(2026-10-21): submit one-off private tasks that belong to no ticket, for ad-hoc exploration and for planning the tickets
that should follow, whose branches are throwaway quality and get a separate quality pass. The operator settled four
points the same day: a task runs in a worktree and may push a branch; the next tick starts it in code, without the
overseer; it may open a draft PR; and it may file tickets with no queue label.

- **Stage 1, a task runs.** `canopy task submit TEXT` (`-` reads stdin, `--repo` names the repository, required when
  the workspace has several), `canopy task list`, and `canopy show task:N`; refused inside a tick or any run
  (`inside_run`). A `tasks` table (text, repository, submitted, stopped) and a `task_runs` table of their own, rather
  than `runs`, whose ticket and tick a task has neither; `task:N` joins the subjects `conversation.parse_ref` knows.
  The tick starts queued tasks after reconcile and before the overseer, oldest first, under the dispatch lock: one run
  per task, `capacity.max_tasks` (default 1, shared, may only be lowered) within `capacity.max_workers`, which counts
  task runs with worker and review runs. A dry tick starts none. `canopy _task ID` leases a slot as
  `canopy:task:<N>`, checks out the base at a detached HEAD, runs `runtime.private_worker_cmd` with
  `.agents/prompts/task.md`, parses the result line, verifies the push of `<branch_prefix>task/N` as `_ensure_pushed`
  does (`unpushed` when it cannot), and returns the slot. Whatever reads canopy's branches (the GitHub connector, the
  overseer's state block, garbage collection) leaves `task/` branches and their PRs out of every ticket's work. The
  prompt says to push only that branch, to open at most one PR, as a draft, and to write nothing to any ticket.
  `canopy stop task:N` ends a running run as `stop` ends a ticket's and drops a queued one.
- **Stage 2, the conversation.** `canopy reply task:N` queues the next run, which continues the branch, with the
  operator's messages as instructions and earlier summaries as data. A `blocked` run's question is a worker message,
  and raises `awaiting_reply` until a reply. A run's end is a `task.ended` event (§20) with its summary.
- **Stage 3, what a task leaves.** The report: `.canopy-task-report.md` at the slot's root, excluded from git, copied
  to `<state_dir>/tasks/<N>/<run>.md` as plans are (§25), shown by `canopy show task:N`. Tickets: the result's
  `created`, at most `policy.max_follow_ups`, recorded against the task, each key's text checked only (D003), and
  named in `task.ended`.
- **Later, not built here.** Tasks in the web UI; a task across several repositories; promoting a task to a ticket.
- **TRUST_MODEL**, in Stage 1's PR: T1 (a task's text and replies are the operator's, through the operator's channels
  only; a report is data), T3 (`max_tasks`, one run per task, no retry), T6 (a task's worker is the private worker,
  with its own branch, a PR for it, and unlabeled tickets; a draft PR is the prompt's rule, not a guard). Its §6 list
  keeps every line: a task pushes only under `trust.branch_prefix`, and merges and approves nothing.
- Tests with the fakes: a submit refused inside a run; a queued task started by the next tick and not by a dry one,
  held by `max_tasks` and by `max_workers` and started by the tick after; its worker's prompt carries the text; a
  pushed branch recorded, an unpushed one `unpushed`; the slot returned; stop of a running and of a queued task; a
  reply's run continuing the branch; `awaiting_reply` raised and cleared; the report kept and shown; `created` keys
  recorded and capped.

Accept: on the operator's workspace, an exploring task that pushes a branch and opens a draft PR, and a planning task
that files two unlabeled tickets and leaves a report; each shown by `canopy show task:N`, and neither touching any
ticket.

Status: not started. Designed 2026-10-21 (DESIGN §36).
