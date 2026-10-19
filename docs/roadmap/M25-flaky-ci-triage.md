# M25. Flaky CI triage

REQUIREMENTS R14, DESIGN §23. Needs M3. Asked for by the operator (2026-10-09): a check that fails for a
reason the change did not cause sends a `resume` to change code that is not broken, and spends its attempts.

- TRUST_MODEL T1, T3, T6, T7, §6, and §7 as DESIGN §23 lists them.
- Config: `policy.max_triage_ci_attempts` (default 0), `runtime.triage_cmd`, `runtime.triage_timeout_minutes`,
  `runtime.triage_skill`.
- `canopy dispatch --kind triage-ci`: `triage_off`, one unit, no slot. `_run` runs it in the unit's primary clone after
  the shadowing check, validates the triage result, and records its report.
- `agents/canopy-ci-triage.md`. `canopy-worker` denies `gh run rerun`, `gh run cancel`, `gh run delete`, and
  `gh workflow`; `test_definitions.py` checks both.
- `prompts/ci-triage.md` and its private variant; the overseer prompt's triage rows and the state block's fields.
- §7, §8, §12, and §13 say what §23 changes in them, and §23 loses its "designed, not built" line.
- Tests with the fakes: `triage_off` under the default config; a dry-run tick that triages a new failure; a triage
  run's cwd is the primary clone and it leases nothing; a `flaky` result without reruns recorded `failed`; a `real`
  verdict followed by a `resume` for `ci`; the limit refusing the next triage; `resume` attempts not counting triages.

Accept: the tests above pass. Live: on a PR whose check fails for a reason the change did not cause, the loop reruns it
once and the PR goes green with no `resume` for it; on a PR with a real failure, the triage reports `real` and the
next tick's `resume` fixes it; a repository skill that names a flaky test is followed.

Status: deferred 2026-10-15. Until it is built, `ci_red` dispatches a `resume` for `ci` as DESIGN §7 says.
