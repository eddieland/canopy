# M61. One-off tasks

REQUIREMENTS R25, DESIGN §36, §8, §14, §18, §20, and §22, TRUST_MODEL T1, T3, and T6. Asked for by the operator
(2026-10-21): submit one-off private tasks that belong to no ticket, for ad-hoc exploration and for planning the tickets
that should follow, whose branches are throwaway quality and get a separate quality pass. The operator settled four
points the same day: a task runs in a worktree and may push a branch; the next tick starts it in code, without the
overseer; it may open a draft PR; and it may file tickets with no queue label.

- **Stage 1, a task runs.** `canopy task submit TEXT` (`-` reads stdin, `--repo` names the repository, required when the
  workspace has several, and `--project` the tracker project its tickets go in, none by default), `canopy task list`,
  and `canopy show task:N`, with each run's branch and head commit; refused inside a tick or any run (`inside_run`). A
  `tasks` table (text, repository, project, submitted, stopped) and a `task_runs` table of their own, rather than
  `runs`, whose ticket and tick a task has neither; `task:N` joins the subjects `conversation.parse_ref` knows.
  Reconcile closes a task run whose process died, as it closes a worker's, and returns its slot. Spend and health count
  task runs as a kind of their own, and a task run's report and question are messages that name their run. The tick
  starts queued tasks after reconcile and before the overseer, oldest first, under the dispatch lock: one run per task,
  `capacity.max_tasks` (default 1, shared, may only be lowered) within `capacity.max_workers`, which counts task runs
  with worker and review runs. A dry tick starts none. `canopy _task ID` leases a slot as `canopy:task:<N>`, checks out
  the task's branch, or the base before one is pushed, at a detached HEAD, runs `runtime.private_worker_cmd` with
  `.agents/prompts/task.md`, parses the result line, verifies the push of `<branch_prefix>task/N` as `_ensure_pushed`
  does, never with force whatever `trust.rebase` says (`unpushed` when it cannot), records the pushed head commit, and
  returns the slot. Whatever reads canopy's branches (the GitHub connector, the overseer's state block, garbage
  collection) leaves `task/` branches and their PRs out of every ticket's work. The state block's capacity counts task
  runs in `running`, so the overseer plans around the slots they hold and sees nothing else of a task. The prompt names
  that branch and says to push only it, to open one PR, as a draft, only when the task's text asks, and to write nothing
  to any existing ticket; Stage 3 lets it file new ones. A submission ends the loop's wait. `canopy stop task:N` ends a
  running run as `stop` ends a ticket's and drops a queued one.
- **Stage 2, the conversation.** `canopy reply task:N` queues the next run, which continues the branch, with the
  operator's messages as instructions and earlier summaries as data, and ends the loop's wait. A `blocked` run's
  question is a worker message, and raises `awaiting_reply` until a reply. A run's end is a `task.ended` event, in a
  `tasks` group of its own (§20), with its summary, its question when `blocked`, its branch and pushed head commit, and
  its PR; no sink takes the group unless the operator lists it, and the `awaiting_reply` item names the task, not the
  question.
- **Stage 3, what a task leaves.** The report: `.canopy-task-report.md` at the slot's root, excluded from git, copied
  to `<state_dir>/tasks/<N>/<run>.md` before the slot is returned, as plans are (§25), shown by `canopy show task:N`,
  and copied into the next run's slot as a plan is. Tickets: the prompt lets the worker file them only with
  `--project`, and only there. The result's `created`, at most `policy.max_follow_ups`, is recorded against the task,
  each key's text checked only (D003), and named in `task.ended`. A key outside the project, as `follow_ups` reads a
  key's project, or any key from a task with no project, is not recorded and raises `task_ticket_unrecorded`, as
  `follow_up_unrecorded` does for a ticket.
- **Later, not built here.** Tasks in the web UI; a task across several repositories. Not planned: promoting a task to
  a ticket. The loop never adopts a task's branch; a ticket uses it by naming it, and its worker reads it as any branch.
- **TRUST_MODEL**, in Stage 1's PR: T1 (a task's text and replies are the operator's, through the operator's channels
  only; a report is data), T3 (`max_tasks`, one run per task, no retry), T6 (a task's worker is the private worker,
  with its own branch, a PR for it, and unlabeled tickets; a draft PR is the prompt's rule, not a guard). Its §6 list
  keeps every line: a task pushes only under `trust.branch_prefix`, and merges and approves nothing.
- Tests with the fakes: a submit refused inside a run; a queued task started by the next tick and not by a dry one, held
  by `max_tasks` and by `max_workers` and started by the tick after; its worker's prompt carries the text; a pushed
  branch recorded with its head commit, an unpushed one `unpushed`; no forced push under `trust.rebase`; the slot
  returned; stop of a running and of a queued task; a reply's run continuing the branch; `awaiting_reply` raised and
  cleared; the report kept and shown; `created` keys recorded and capped; a key outside the project, or from a task with
  none, unrecorded and raising its item; no journal row a task writes names a ticket; `task.ended` reaching only a sink
  that lists `tasks`.

Accept: on the operator's workspace, an exploring task that pushes a branch and opens a draft PR, and a planning task,
submitted with `--project`, that files two unlabeled tickets there and leaves a report; each shown by
`canopy show task:N`, and neither touching any existing ticket.

Status: in progress. Designed 2026-10-21 (DESIGN §36). Stage 1 built 2026-10-21: `canopy task submit`, `task list`,
`show task:N`, and `stop task:N [--now]`; the `tasks` and `task_runs` tables; the tick starting queued tasks in code
under `capacity.max_tasks`; `canopy _task` running the private worker on `<branch_prefix>task/N`, never forced; task
runs reconciled, counted by capacity, spend, and health; TRUST_MODEL T1, T3, and T6. The tick leases a task's slot under
the dispatch lock, as a review's is, so a pool with no free slot leaves the task queued rather than failing its one
run. Its live check, an exploring task that pushes a branch and opens a draft PR, waits on the operator.
