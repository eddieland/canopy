# Flaky CI

Part of the canopy design, normative like all of it: what happens to a CI failure the change did not cause.
Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Conversations](CONVERSATIONS.md). Next: [Sandboxed runs](SANDBOXING.md).

## 23. Flaky CI

Some failures are not the change's: a flaky test, a lost runner, a download that timed out. The `resume` for `ci` that
reads one (§8) changes nothing for it and does not rerun it. It reports `"flaky": true`, naming each such check and its
evidence in its summary. It says so only with evidence, and fixes a failure it is unsure of, since a fix attempt that
finds nothing costs less than a rerun that hides a regression. A failure in the check itself, or from a stacked
blocker's changes, is still `blocked`.

The worker's word reaches the overseer as one bit on the ticket's `last_run`, never its text (TRUST_MODEL T1). While
the same check run still fails, no newer than the `ci` cursor, the overseer records `flaky_rerun` (§14) naming the
check, where it would otherwise wait for a newer run that no push will start. The operator reruns the check, or says
with `canopy reply` that it is real. A rerun's checks are newer than the cursor: green ends the item, and red is
`ci_red` again, whose `resume` counts toward `max_resume_attempts` as every one does (D030). A steered worker can only
hold its own ticket's PR on the attention list, which a person reads before anything is rerun.

Rejected: a `triage-ci` run before each `resume` for `ci`, rerunning what it judged flaky. It took a run kind, an agent
definition, a prompt, a limit, and trust model changes for a rerun tool, to save one `resume` attempt per flake; the
`resume` worker reads the same failure with the change checked out, and judges it as well. Reruns stay a person's, so
no canopy prompt asks an agent to rerun a workflow the operator's `gh` can reach, a deploy's included.

### Open

- Whether a repository skill naming its known flaky tests should reach the `resume` prompt, once real use shows workers
  judging flakes wrong.
- Whether `flaky_rerun` moves into code with §37, which needs only the run's bit and the observed check.
