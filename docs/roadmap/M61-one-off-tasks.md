# M61. One-off tasks

REQUIREMENTS R25, DESIGN §36, TRUST_MODEL T1, T3, and T6. One-off private work the operator submits in their own
words, about no ticket (`canopy task submit`, `list`, `show task:N`, `stop task:N`): the tick starts a queued task in
code, without the overseer, under `capacity.max_tasks`; its run pushes only its own `task/` branch, never forced, and
may open a draft PR; `canopy reply task:N` runs it again on that branch with the conversation; and it leaves a report
canopy keeps and, with `--project`, unlabeled tickets there, recorded against the task.

Status: done 2026-11-11.
Learned: closed on the operator's own use, before the checks in Accept ran one by one. A task's branch, PR, report, and
filed tickets are what daily use shows; that a task writes to no existing ticket, opens its PR only as a draft, and
labels no ticket it files are the prompt's rules, not guards, and are SCENARIOS S77.
