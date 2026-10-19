# M9. Chores

Recurring runs the operator defines and the overseer schedules (DESIGN §19): `[chores.<name>]`, `chore_runs`,
`canopy chore run`, `wait`, and `try`, and findings on the attention list.

Status: done 2026-10-13.
Learned: closed on the operator's real use; several days of a build-health chore are SCENARIOS S22. A chore's `days`
and `hours` became a guard in code. Use added `canopy chore try` and `canopy reply chore:NAME`.
