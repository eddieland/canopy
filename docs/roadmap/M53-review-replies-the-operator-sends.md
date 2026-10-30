# M53. Review replies the operator sends

REQUIREMENTS R20, DESIGN §21, §22, and §29, TRUST_MODEL T1, T2, T5, T6, and T8, D003, D069. Needs M32. Under
`trust.review_replies = "approve"`, the default, a worker pushes and posts no comment but drafts its replies; canopy reads
the PR's review threads itself through its own GitHub programs (`packages/canopy-github`), and the operator edits,
drops, sends, or stages the drafts from the PR's page or `canopy draft`, each sent verbatim and unmarked in one comment
review and known afterwards by its comment id.

Status: done 2026-10-29.
Learned: closed by the operator on real use, sending drafts on real PRs, before the Accept's live check ran; what daily
use does not show is SCENARIOS S68. Staging, which opens a PR's drafts as a pending review the operator submits on
GitHub, was asked for while it was built (S54).
Next: M54's feedback plans and M43's reviews build on its reader, threads view, ids, and drafts; M36 grows the reader
into the whole connector, and M37 checks in code that a comment the operator sent is never a review item.
