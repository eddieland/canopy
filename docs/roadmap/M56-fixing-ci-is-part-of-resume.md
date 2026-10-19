# M56. Fixing CI is part of resume

REQUIREMENTS R4, DESIGN §7 and §8, TRUST_MODEL T3, D030. Needs M3. Asked for by the operator (2026-10-17): `fix-ci`
should be a part of `resume`, one kind of worker for everything that comes back to a PR, so that a round of feedback is
one run and, with M54, one plan. Today a PR with a red check and a new review comment takes two runs, each with its own
prompt, cooldown, and attempt limit, and each pushing to the same branch. Designed in DESIGN §8 (One resume for what
comes back to a PR), which the PR that builds it folds into §7, §8, §10, and the other sections that name `fix-ci`.

- **One kind.** `ci_red` dispatches `resume --reason ci`, with the failed checks named in its context as fix-ci's are
  today. When the same tick sees review feedback, a reply, or a conflict on the unit, one `resume` takes all of it,
  with every reason and cursor, so the run fixes the build and answers the reviewers on one checkout and one push.
  `canopy dispatch --kind fix-ci` is refused (`bad_kind`) naming `resume --reason ci`, and the `fix-ci` value stays in
  `core/vocab.py` only to read old runs.
- **Reasons.** Every `resume` names why it runs, once or more: `ci`, `review`, `reply`, `conflict`, `no_pr`, and
  `retarget` (a stacked PR whose blocker merged), each the phase or step that sends it. They are recorded on the run, a
  closed vocabulary in `core/vocab.py`, and shown beside its kind. A `resume` with none, a reason on another kind, or a
  cursor without its reason (`ci`, `review` or `--review-run`, `comment` or `message`) is refused `bad_reason`.
- **One prompt.** `worker-resume.md` and its private variant gain fix-ci's section on reading a failed check and its
  log, under the reason `ci`, and `{{REASONS}}` names the run's; `worker-fix-ci.md` and its private variant go. While
  a prompt override of either fix-ci file exists, every `resume` is `bad_prompt`, naming the file and what to merge
  into the resume override, and records a `fix_ci_override` attention item on the unit.
- **One limit, higher.** `policy.max_resume_attempts` bounds every `resume` of a unit, whatever it was for, an old
  `fix-ci` run counted among them (D030: derived from `runs`, no reset), with its default raised to 6, more than today's
  two limits together (2 and 3), since one run now does what two did. The operator chose one simpler limit (2026-10-17),
  accepting that a PR that keeps going red can spend the attempts its reviewers would have had. Nothing is migrated:
  every run counts, and a unit's `fix-ci` grants count toward the new limit as its `resume` grants do, so a unit within
  the old defaults (at most 2 and 3, 5 together) is within 6 on upgrade, and one past them had grants that carry over.
  `policy.max_fix_ci_attempts` becomes a removed key, whose error says to raise `max_resume_attempts`, and `canopy grant
  KEY fix-ci` is refused naming `resume`. The cooldown stays, renamed `policy.ci_cooldown_minutes`
  (`fix_ci_cooldown_minutes` a removed key naming it): it holds a `resume` whose only reason is a failed check, so a red
  build still waits between attempts, and a `resume` with any other reason is not held. `notice_changed` refuses a
  `resume` with `ci` among its reasons.
- **Under M54.** With `policy.feedback_plan = "approve"`, a `resume` for a failed check alone waits on an approved plan
  like any other, so a CI fix that ran unattended as `fix-ci` now waits for the operator. That is intended: the
  operator asked for CI rounds to be planned too (2026-10-17). M55's triage, where it is on, can waive the plan for a
  trivial one. With feedback plans off, a red check sends its `resume` unattended, as `fix-ci` did.
- **What else changes.** M25's `triage-ci`, once built, comes before a `resume` for a failed check as it would have
  before `fix-ci`; M35's notice holds that `resume` as it held `fix-ci`; M38 moves `ci_red`'s `dispatch resume` into
  code under its own evidence rule; the overseer prompt's phase table and the web UI's kind chips and guide pages say
  `resume`, with its reasons beside it. Spend (M33) shows old `fix-ci` runs under their kind. A `resume` for CI alone
  gets the approved plan's copy (M44), as every `resume` does.
- TRUST_MODEL T3: one `resume` limit per unit in place of two, and the cooldown on CI-only runs.
- Tests with the fakes: a red check dispatches `resume --reason ci` with the checks named; a red check and a review
  comment in one tick make one run with both reasons; `--kind fix-ci` refused; each `bad_reason`; the one limit counting
  old `fix-ci` runs and every `resume`, with `fix-ci` grants; `canopy grant KEY fix-ci` refused; the removed keys'
  errors; a `fix-ci` prompt override refusing every `resume`, with its attention item; the cooldown holding a CI-only
  `resume` after a `resume` with `ci` or an old `fix-ci`, and not one with review feedback; the overseer's state block,
  a snapshot.

Accept: the tests above pass, and the design names `fix-ci` only as an old run's kind. Live: on one of the loop's PRs
with a red check and a new review comment from a trusted reviewer, the next tick sends one `resume` with reasons `ci`
and `review`, which fixes the check and addresses the comment in one push.

Status: in progress. Designed 2026-10-18 (DESIGN §8, One resume for what comes back to a PR). The open question on
reasons' names is settled there, with `retarget` added for a stacked PR whose blocker merged. Built 2026-10-18: the
tests above pass and the design names `fix-ci` only as an old run's kind; the live check waits on the operator
(SCENARIOS S43).
