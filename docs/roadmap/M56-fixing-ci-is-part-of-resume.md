# M56. Fixing CI is part of resume

REQUIREMENTS R4, DESIGN §7 and §8, TRUST_MODEL T3, D030. `fix-ci` folded into `resume`: every `resume` names its
reasons (`ci`, `review`, `reply`, `conflict`, `no_pr`, `retarget`), one run takes a unit's failed checks and its review
feedback on one checkout and one push, under one `policy.max_resume_attempts` (default 6) and a cooldown on a `resume`
for `ci` alone; `fix-ci` stays only as old runs' kind.

Status: done 2026-10-29.
Learned: closed on the operator's own workspace: no `fix-ci` run since 2026-10-19, and from 2026-10-23 to 2026-10-29,
14 `resume` runs carried both `ci` and `review`, 12 of them ending `done`; one fixed two causes of red checks, fixed one
review comment, and declined two, in one push. The reviewer was the operator's company's review bot, in
`trust.trusted_reviewers`, not a person.
