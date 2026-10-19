# M13. Spend-paced loop

Every agent run canopy starts records its cost in dollars and tokens: worker, split, chore, and review runs and each
tick's overseer (with M15's session ids). The loop's per-tick block, `canopy tick`, `canopy status`, `canopy decisions`,
and the web UI's attention page (the last 24 hours and 30 days) and chores pages show it.

Status: done 2026-10-18.
Learned: closed on the operator's request with the cost recording in and the spend budget and pacing rule unbuilt; the
operator judged them unneeded once M36 to M39 run the overseer only when the journal leaves it something to judge. A
tick's cost is its overseer's alone, so a worker's is not counted against the tick that dispatched it. An
`overseer_cmd`, `review_cmd`, or chore `cmd` in a user file from before needs `--format json` added.
Next: the budget and the pacing rule move to the deferred list, with the trigger that would bring them back.
