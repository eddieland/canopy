# Checklist reviews

Part of the canopy design, normative like all of it: a second, narrower review that asks the operator's own questions
of a change, one at a time. Sections are numbered across the whole design; the [README](README.md) has the map.
Previous: [Where a running agent stands](CARDS.md).

## 42. Checklist reviews

Proposed (REQUIREMENTS R27, ROADMAP M66). A checklist review asks the operator's list of questions of one PR at one
commit, each in turn, and reports which the change fails and where. It is the second review of a commit, beside the
adversarial one (§21), and nothing else about it is new: a review run, read-only, posting nothing (D114), its findings
going where any review's go.

Why a second review rather than more instructions to the first: the adversarial reviewer is asked for defects, not
style, and weighs any rule it is given against the whole change, so a rule the team holds and no linter checks is held
only sometimes. Asked one plain question of one diff, an agent answers it reliably. The list is those questions, and
the review is lighter for it: it reads the diff and what the questions need, not the PR's discussion or the ticket; it
has no persona, since it writes verdicts and not prose; and it may run on a cheaper model, `runtime.models.checklist`.

### The list

`paths.review_checklist` names the operator's file, private (T7): it is instructions in every review it reaches, as
`paths.reviewer_instructions` is, so a shared workspace file can neither supply it nor choose one. One item per
heading: an id, a severity (`minor` unless the item says), the paths it applies to, and the rule in plain words with
what passes and what fails. The file is bounded, and refused with hidden characters as a persona is (§31). A review
whose list cannot be read is refused as `bad_prompt`, never run without it. Rejected: the list read from the
repository's checkout, which a PR could rewrite and a shared workspace cannot vouch for (T1, T7); the team's copy stays
with its docs, and the operator's file is what runs.

### Running one

A commit owes a checklist review wherever it owes an adversarial one: the loop's own PRs under `review.agent_prs`,
`review.query`'s, and requests. The same `canopy review run` starts each still owed, side by side, as it starts a
review in each persona (§31), and the commit is reviewed once each has ended and the adversarial one is `done`; the
state block names what a commit is still owed. Every guard of a review holds (§21): review capacity, `max_workers`,
the daily limit, the settle time, a dry run, and a commit already `done`. It does not count against the per-PR
limit, which bounds the rounds between a worker and the adversarial reviewer, and it starts only on a commit that
limit allows. One that ends
`failed` or `unknown` is not started again on that commit: the commit owes nothing more of it and is reviewed on the
adversarial review alone, with `review_failed` raised as for any review, so a list a model cannot answer costs one run
per commit, not one per tick (T3). Its definition allows canopy's git tools and the card (§41) and nothing else: no
tracker, no GitHub, so each question is answered from the code. The prompt names the items whose paths the diff
touches, in order, and asks each of the diff alone: a line the change did not touch fails nothing.

Result contract, the last line of its text, validated (D026); anything else is `unknown`, and so is a result that
skips an item asked or answers one not asked:

```json
{"status":"done|failed","summary":"one line",
 "items":[{"id":"the item's id","result":"pass|fail|n/a",
           "findings":[{"location":"path:line","detail":"what fails the rule, and the smallest change meeting it"}]}]}
```

A `fail` carries at least one finding; `pass` and `n/a` carry none and are kept, so the operator sees what was asked
and what held. The harness makes the findings: one per location, its severity the item's and its title the item's
heading, the operator's words, so the reviewer chooses neither; its detail the reviewer's. `verdict` is `findings`
exactly when an item fails. From there it is any review's: a `resume` carries them with the adversarial review's,
trusted under `canopy:review` (D089); a dismissal says why and is counted per item, so an item mostly dismissed shows
itself; a coworker's PR's keeps its own draft (§34); a rebuttal and a late finding are held as §21 holds them, the
previous checklist review and the worker's answers carried as data. `canopy review eval` scores the list on cases that
name an item and its lines, so an item is kept on what it finds.

### Rejected

- The list in `paths.reviewer_instructions`: one paragraph in a prompt that asks for defects and caps minor findings,
  weighed against the whole change, with no record per item.
- A persona: voice and emphasis, which cannot narrow a review, and the prompt comes first (§31).
- One run per item: more focused, and as many slots and leases per commit; one run asking each question in turn keeps
  the focus, and its card shows the item it is on.
- The worker checking its own diff against the list before pushing: the author's blind spots, which a fresh run is for
  (§21). Revisit, as a cheaper first pass, once the list has measured which items workers get wrong.
