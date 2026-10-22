# M43. Publishing a review on someone else's PR

A review of a PR the loop does not own makes a draft, versioned in the journal, that the operator edits by hand or has
an agent revise on a note, then publishes or stages from the CLI or the review's page: canopy posts that version
verbatim, through `canopy-post-github`, as one comment review on the reviewed commit, approving nothing. D114 changed
from "posts nothing" to "posts nothing the operator has not approved, word for word" (DESIGN §34; TRUST_MODEL §6, T1,
T3, T5, T6, T8).

Status: done 2026-10-22.
Learned: closed on real use, the operator having published edited reviews on coworkers' PRs, before its Accept's
revision, second publish, and staging checks ran, which are SCENARIOS S64. Built, it worked but read as added onto
canopy's own reviews; a design critique (2026-10-22) led to #1260 to #1272, which gave the draft its page, its state
in the lists and the attention list, and M53's way of publishing.
