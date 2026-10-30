# M46. Workers file follow-up tickets

REQUIREMENTS N3, DESIGN §18 (Follow-up tickets). An `implement` or `resume` worker, public or private, may file
follow-up tickets in its ticket's project, linked to it, with no labels; `_run` checks and records each it reports,
bounded by `policy.max_follow_ups` and one generation, and the run's close records `follow_ups.filed`. A follow-up is
a request: a human's label or `canopy start` authorizes it as any ticket (TRUST_MODEL T1, T3, T6; D123). Splitting
stopped being a run kind; a reply asking for a split is guidance to the ticket's next run.

Status: done 2026-10-29.
Learned: closed on real use, workers having filed useful follow-up tickets on the operator's work, before its Accept's
sink and dispatch checks ran, which are SCENARIOS S68. Filing as an attention item stood until the parent was done, so
it became an event (2026-10-20).
Next: still open, until real use shows one matters: a bound per ticket rather than per run, how long
`follow_up_unrecorded` stands, the parent's phase once a split request moved its work into follow-ups, and whether a
follow-up is a draft under `trust.review_replies = "approve"`.
