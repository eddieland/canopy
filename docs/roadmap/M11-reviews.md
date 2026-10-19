# M11. Reviews

A fresh reviewer per PR commit (DESIGN §21): guarded review runs in a slot, findings kept in the journal and posted
nowhere (D114), `resume --review-run`, and `canopy review show`.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the reviewer canary passed and PR #69 was reviewed live (2026-10-07), and
the other live checks are SCENARIOS S19 to S21. Review runs ending `unknown` within seconds were a plugin printing after
the result; since #218 an agent's result is the last line of its output that starts with `{`. Use added
`canopy dismiss` and `canopy grant URL review`.
Next: the next spend measurement confirms review runs no longer end `unknown` (MEASUREMENTS 2026-10-13 F18).
