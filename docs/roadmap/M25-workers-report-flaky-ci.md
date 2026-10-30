# M25. Workers report flaky CI

REQUIREMENTS R14, DESIGN §23. Asked for by the operator (2026-10-09), reshaped by them (2026-10-22): the `resume`
worker for a red check reports it `flaky` when the change did not cause it, `last_run` carries the bit, and the
overseer records `flaky_rerun` for the operator in place of another `resume`. No agent reruns CI.

Status: done 2026-10-30.
Learned: closed on the operator's real use from 2026-10-22, where 23 `resume` runs over 15 tickets ended `done` with
`flaky` and 11 of those tickets got `flaky_rerun` in place of another `resume`. Not checked live: that a rerun's green
check ends the item, which stays in SCENARIOS S63, and why the other 4 tickets got no `flaky_rerun`.
Next: if real use shows a `flaky` ticket sent back for another `resume`, the overseer's `flaky_rerun` rule is where to
look first.
