# M36. Connectors: the world observed into the journal, in shadow

DESIGN §30. Needs M28 and M34. Each tick, and `canopy loop` between ticks every `connect.every_minutes`, runs the
configured sources, deterministic programs speaking one JSON-lines contract, after reconcile; canopy validates and
bounds each line and records it as an observation (`observed_tickets`, `observed_comments`, `observed_prs`,
`observed_branches`, `observed_checks`), each run in `connector_runs`, raising `connector_failed` on a failure.
`loop/phases.py` derives §7's rows from the observations into `derivations`, its agreement with the overseer counted
in the loop's output; `canopy status` names each source and its age, and §26's pass prunes the per-tick tables. canopy
ships `canopy-connect-jira` (`packages/canopy-jira`) and `canopy-connect-github`, both the whole contract.

Status: done 2026-10-29.
Learned: closed by the operator on a few days of real use of both connectors, before its Accept's day of `canopy loop`
with the agreement and cost measured, which is SCENARIOS S68; reading Jira and GitHub live are S56 and S57. M37 was
started ahead of that measurement (2026-10-22) and settled the proposed tracker query run in code: the harness records
a fresh read's result as `canopy queried` would.
Next: M37's Accept still checks against the derivation as here, so S68 is run before it closes. Whether one failed
run raises `connector_failed` stays open (§30), M39 having settled that a poll's failure the tick's read clears raises
nothing.
