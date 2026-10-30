# The operator's checklist

Part of the canopy design, normative like all of it: the operator's own list of rules no linter checks, asked of a
worker's diff before it is done, and of a PR by a second review when that is not enough. Sections are numbered across
the whole design; the [README](README.md) has the map. Previous: [Where a running agent stands](PROGRESS.md).

## 42. The operator's checklist

Proposed (REQUIREMENTS R27, ROADMAP M66). The checklist is the operator's list of rules a team holds and no linter
checks, each a question that can be asked of a diff, one list per repository, since a workspace's repositories differ
in language and team. canopy asks it at the moment it matters: when a worker's diff is whole and before it is pushed, as
a reminder in its own run, with the worker's answer to each item recorded. If that is not enough, or for PRs workers did
not write, a checklist review asks the same list of a PR at one commit, as a second review beside the adversarial one
(§21).

Why asked, rather than told: the worker's prompt already carries these rules, in the repository's docs and the
operator's standing instructions (§12), and workers miss them, as the adversarial reviewer does, which is asked for
defects and weighs a rule among the whole change. Asked one plain question of one diff, an agent answers it reliably.
A reminder is that question, put when the diff is whole and before CI is spent on it; a review is the same question put
by a run that did not write the code.

### The list

`paths.checklists` names the operator's directory of lists, private (T7), a file per mapped repository that has one, as
`paths.personas` holds a file per persona: it is instructions in every run it reaches, as `paths.worker_instructions`
is, so a shared workspace file can neither supply it nor choose one. A repository without a list is not asked, by
reminder or review. One item per heading: an id, the paths it is about, a severity the review alone uses (`minor` unless
the item says), and the rule in plain words with what passes and what fails. Each file is bounded, and refused with
hidden characters as a persona is (§31). A run whose list cannot be read is refused as `bad_prompt`, never run without
it. Rejected: the list read from the repository's checkout, a file of its own included, which a PR could rewrite and a
shared workspace cannot vouch for (T1, T7); the team's copy stays with its docs, and the operator's file is what runs.

### The reminder

Every worker run that pushes, public and private, `implement`, `resume`, and a task's, hears the list before its branch
goes up, so a fix costs no CI run: canopy's plugin (§33) holds the tool call that would push (`tool.execute.before`),
which does not run, and the call's error carries the list of each of the run's repositories, a joint run's all at once,
after a `[canopy]` line saying the push was held, not rejected, and asking the worker to diff each branch against its
base, hold each item to its repository's diff, commit what fails, answer each item in its result, and push again.
Nothing in a held call runs, so a commit chained before the push in the same command is held with it. The push after a
hold goes through, so a worker is held once and never kept from pushing: whether it held is kept in memory in the agent
process, as the clock keeps whether it warned (§33), and a new process starts a new stretch; a push after a long stretch
of work is held again. Near the deadline, in the clock's last stretch (§33), the plugin holds nothing, since a held push
then risks the run ending `unpushed`: it lets the push run and, once its result shows it went through, adds the list
there instead, asking for the fix pushed again, which D116 allows. So it does under a runtime version that does not hand
a hook's error to the agent as the call's result: there it holds nothing and reminds only after the push. A rejected
push is never reminded, since a worker never retries one (§8). The list reaches the run as the operator's answer to a
running agent's question does (§41): a file in the run's answers directory, which a sandboxed run may read and not
write, so the plugin still writes nothing and reads only what it is handed. The overseer, a planner, a reviewer, and a
chore hear none.

The worker's result line gains `checklist`: for each repository and item, `pass`, `fixed`, `held` with the reason, or
`n/a`, validated (D026). A reminded run whose result answers no item is recorded as unanswered, never refused: its push
is already made. The answers are the record the standing instructions lacked: the run's page shows them, and canopy
counts, per repository and item, how often it was reminded, passed, fixed, held, and left unanswered, so an item earns
its place or is dropped. No answer raises attention: a human reviewer still reads the PR, and a `held` item is on its
page for them.

What lets it run (TRUST_MODEL): a forged `[canopy]` line can only ask the agent to check its own diff against a list
it already holds, so it fails safe, as the clock's and the nudge's do (T1); nothing a worker does with it extends its
run (T3); the plugin reads one more file in a directory the harness made and writes nothing, and the one call it refuses
is a worker's push, once per stretch and never near the deadline, which only delays what the worker may do (T4).

### The review

Where the reminder is not enough, or for a PR no worker wrote, `checklist.review` turns on a checklist review: a commit
of a repository with a list owes one wherever it owes an adversarial review, the loop's own PRs under
`review.agent_prs`, `review.query`'s, and requests, and the same `review-run` starts each still owed, side by
side, as it starts a review in each persona (§31); the commit is reviewed once each has ended and the adversarial one is
`done`. Every guard of a review holds (§21), but the per-PR limit, which bounds the rounds between a worker and the
adversarial reviewer: the checklist review starts only on a commit that limit allows, and one that ends `failed` or
`unknown` is not started again on that commit (T3). It is a review run as any other: read-only, posting nothing (D114),
no persona, its definition allowing canopy's git tools and the `status` tool (§41) alone, on `runtime.models.checklist`.
Its result answers each item asked, `pass`, `fail` with each `path:line` and what fails the rule, or `n/a`; a result
that skips an item or answers one not asked is `unknown`. The harness makes the findings, each with the item's title and
severity, the operator's words, and from there they are any review's: a `resume` carries them with the adversarial
review's, trusted under `canopy:review` (D089), a dismissal is counted per item, a coworker's PR's keeps its own draft
(§34), and rebuttals and late findings are held as §21 holds them.

### Rejected

- The reminder after the push: the fix it asks for is a second push, and a second CI run, on most reminded runs.
- The reminder after each commit: a worker commits many times before its diff is whole, so it is asked of half a change,
  and again and again.
- A git `pre-push` hook: `core.hooksPath` would replace the repository's own hooks, and the hook keeps state in a
  checkout a sandboxed run writes; the plugin already sees the call and the clock.
- The list in `paths.worker_instructions` or `paths.reviewer_instructions`: the operator's already emphasize these
  rules, read once at the top of a long run and weighed against everything after; no record per item.
- A persona: voice and emphasis, which cannot narrow a run or a review, and the prompt comes first (§31).
- The review first: a run per commit, a slot, and a `resume` round trip, before the cheaper ask has been measured.
- One review run per item: as many leases per commit; one run asking each in turn keeps the focus.
- One list for the workspace: another repository's items are `n/a` noise in every answer, and keeping them apart by
  their paths grows one list past what a run can hold to a diff.
