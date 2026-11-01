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

With evidence of where the check failed, the worker also names its cause: `test`, a test of the repository that fails
now and then; `runner`, the machine the job ran on; or `service`, something the job reached over the network. Unsure,
it names none: a wrong cause sends the operator the wrong way, where none sends them to the log. It may add a line on
why, kept with the run's result. A cause outside the three is no cause, but is kept with the run as the worker said it
and told to the sinks, so a word the list lacks shows up rather than vanishing.

The worker's word reaches the overseer as one bit on the ticket's `last_run`, and its cause as a word of that closed
vocabulary, never its text or its line on why (TRUST_MODEL T1). The `flaky_rerun` item names the cause when the worker
gave one.

**Kicks.** With `trust.max_flaky_kicks` above 0 (private, off by default), `_run` reruns the checks itself: in each
repository where origin still has the branch where the run found it, it rebases the branch onto its base, making each
commit again, and pushes it with a lease on that head, the one forced push the key allows (TRUST_MODEL T1). The new
head's checks run, and `last_run`'s `kicked` names the repository, so the overseer waits for them. Each head a worker
or a person pushed gets that many kicks, counted in code: the chain of kicks back from origin's head, each recorded
before its push. A rebase that would drop what the branch holds, such as a merge commit's own changes, is no kick. A
branch out of kicks, or one that does not rebase cleanly, is left as it was, named in the run's note, and handled as
below. The harness kicks, never a worker: the worker's definition gains no force, and its judgment only starts a
`resume` the attempt limit counts.

Kicked or not, the run's close tells the sinks (`ci.flaky`, §20): the PR, what was kicked or why not, and the worker's
estimate of why the check is flaky, its line on why or else its summary, cut to one line, with its cause, as
`run.ended` carries a summary. Each kick pushed also tells them at once (`ci.kicked`, in the `loop` group sinks take by
default): the branch, the heads it replaced and pushed, and which of its kicks it was, so no forced push canopy makes
goes unheard.

Without a kick, while the same check run still fails, no newer than the `ci` cursor, the overseer records
`flaky_rerun` (§14) naming the check, where it would otherwise wait for a newer run that no push will start. The
operator reruns the check, or says with `canopy reply` that it is real. A rerun's checks, or a kick's, are newer than
the cursor: green ends the item, and red is `ci_red` again, whose `resume` counts toward `max_resume_attempts` as every
one does (D030). A steered worker can only hold its own ticket's PR on the attention list, which a person reads before
anything is rerun, or have it kicked as many times as the operator allowed.

Rejected: a `triage-ci` run before each `resume` for `ci`, rerunning what it judged flaky. It took a run kind, an agent
definition, a prompt, a limit, and trust model changes for a rerun tool, to save one `resume` attempt per flake; the
`resume` worker reads the same failure with the change checked out, and judges it as well. Rerunning a workflow
through the host's API stays a person's, so no canopy prompt asks an agent to rerun one the operator's `gh` can reach,
a deploy's included; a kick reruns only what a push to the PR's branch starts.

### Open

- Whether a repository skill naming its known flaky tests should reach the `resume` prompt, once real use shows workers
  judging flakes wrong.
- Whether `flaky_rerun` moves into code with §37, which needs only the run's bit and the observed check.
