# M25. Workers report flaky CI

REQUIREMENTS R14, DESIGN §23. Needs M56. Asked for by the operator (2026-10-09): a check that fails for a reason the
change did not cause sends a `resume` to change code that is not broken, and spends its attempts. First designed as a
`triage-ci` run that reran what it judged flaky, and deferred (2026-10-15); the operator reshaped it (2026-10-22): the
`resume` worker already reads the failure, so it only needs a way to say the failure is not the change's, and the rerun
stays a person's. DESIGN §23 says why the triage run was dropped.

- The worker result gains `flaky`, true when a `resume` for `ci` left a failed check a rerun would pass. The resume
  prompts say when (with evidence, and the change's to fix when unsure) and never to rerun it.
- The state block's `last_run` carries `flaky` for a `resume` for `ci` whose result says so, one bit and no text.
- The overseer records `flaky_rerun` for a `ci_red` failure no newer than the cursor whose run ended `done` with
  `flaky`, in place of waiting for a newer run; the operator skill lists it.
- Tests with the fakes: the result stored with `flaky`; `last_run` carrying it for a `resume` for `ci`, and not for
  another run that reports it.

Accept: the tests above pass. Live: SCENARIOS S63.

Status: in progress. Built 2026-10-22: the tests above pass. Live on the operator's workspace from 2026-10-22: 23
`resume` runs over 15 tickets ended `done` with `flaky`, and 11 tickets got `flaky_rerun` in place of another `resume`.
Left of SCENARIOS S63: that a rerun's green check ends the item, and why 4 of the 15 tickets got no `flaky_rerun`.
