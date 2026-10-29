# M66. Checklist reviews

REQUIREMENTS R27, DESIGN §21, §31, §34, §41, and §42, TRUST_MODEL T1, T3, and T7. Asked for by the operator
(2026-10-29): the team keeps meeting the same nits, rules its architect asks for that `AGENTS.md` states and no linter
checks, and reviewers hold them only sometimes, canopy's adversarial reviewer among them. Asking an agent one plain
question, "does this change do X?", gets a reliable answer; a rule among forty in a prompt that asks for defects does
not. So: a second review of each commit, lighter than the adversarial one, that asks the operator's own list of
questions in turn and reports where the diff fails each (DESIGN §42).

Today the adversarial reviewer is told to look for defects, not style (§21, step 3), to report at most five minor
findings, and to hold the change to the repository's docs as one rule among the rest. The operator's standing
instructions (`paths.reviewer_instructions`) reach it as a paragraph, with the same weight. Neither records, per rule,
what was found and what the operator dismissed, so a rule cannot earn or lose its place. Three stages, in order, each
in its own PRs.

- **Stage 0, the first list.** The operator writes it, before stage 1 starts, from the rules review already holds by
  hand: `AGENTS.md`'s "No linter checks this, so review does" is one (the most general parameter type), newspaper
  order and `#:` doc comments are two more, and the architect's are the rest. Each item has an id, the paths it is
  about, and the rule with one example that passes and one that fails. Ten to fifteen items; a longer list is a sign
  two reviews are being asked for. Read by the operator as M60's stage 0 list was, since the list is what the review
  is.
- **Stage 1, the review.** `paths.review_checklist`, private, a Markdown file: one `## <id>` heading per item, an
  optional `severity:` line (`blocking`, `major`, or `minor`, the default) and an optional `paths:` line of globs
  compared as `high_impact_paths` are (§21), then the rule. Bounded at 16 KiB, refused with hidden characters as a
  persona is, and parsed by the harness for its ids, so a result can be held to them. A review run gains a kind,
  `adversarial` or `checklist`, a `core/vocab.py` enum with its `CHECK`; `canopy review run`, `canopy start URL
  --review`, and the state block treat the checklist review as one more review the commit is owed, as a persona's is,
  so the overseer's prompt changes by a line at most. A prompt, `checklist.md`, and a definition,
  `canopy-checklist.md`, each in `.agents/sizes.toml`: the definition is the reviewer's with every MCP server denied
  but canopy's git tools and the `status` tool, and no persona or standing instructions are rendered. The prompt
  carries the diff's range, the items whose paths the diff touches, and the previous checklist review of the PR with
  the worker's answers, as the reviewer's does. `runtime.models.checklist`, defaulting to the reviewer's model. The
  result contract in §42, validated; the harness builds each `fail`'s findings with the item's title and severity.
  `canopy review show` and the review's page show the items as a table, result and findings per item, and the reviews
  list marks the kind. The noise count (`canopy review noise`) gains the item as a dimension.
- **Stage 2, the list earns its items.** `review.eval_cases` take `kind = "checklist"` with an `item` and its
  `lines`, and `canopy review eval --checklist` scores each item: found, missed, false alarm. A week of real use
  goes in `MEASUREMENTS.md`: cost per checklist review beside the adversarial review of the same commits, and per
  item, findings, dismissals by reason, and fixes. An item mostly dismissed is reworded or dropped; the measurement
  says which.
- **Rejected:** the list as `paths.reviewer_instructions` (no per-item record, one paragraph against a whole change);
  a persona (it cannot narrow, §31); one run per item (as many leases per commit); the worker self-checking before
  it pushes (the operator's `paths.worker_instructions` already emphasize these rules, and workers miss them: the
  same context that wrote the code reads it); the list read from the repository (T1, T7); a run on its own without
  an adversarial review of the commit (nothing yet asks for it; the guards would need a source of their own).
- **TRUST_MODEL**, in the PR that builds stage 1: T7 (one more private path, listed with the others); T1 (the list is
  the operator's instructions, the diff is data, and the definition writes nothing anywhere, as the reviewer's); T3
  (one more run per reviewed commit, under review capacity, `max_workers`, and the daily limit, and not the per-PR
  limit, which stays what bounds the rounds).
- **Tests with the fakes:** a fake checklist reviewer that prints a configurable result; a tick with the list set
  starts both reviews of a commit, and the commit is reviewed once both are `done`; a result that skips an item or
  answers an unknown one is `unknown`; a `fail` becomes findings with the item's severity and title, and a `resume`
  carries them with the adversarial review's; a list the harness cannot read refuses `bad_prompt` and a list in the
  workspace file is a config error; a dry run starts nothing; an item case in `review eval`; the review page's
  snapshot. `test_layers.py`, `test_frozen.py`, `test_prompt_sizes.py`, and `core/test_db.py` and `test_records.py`
  for the kind.

Accept: Stage 0's list read by the operator, before stage 1 starts. Live, once built: a toy ticket's PR with a
deliberate hit on two items gets a checklist review beside its adversarial one, each finding on the right line under
its item's title, and the `resume` fixes both before the PR is `green_unreviewed`; a coworker's PR requested with the
list set gets a draft of the hits the operator publishes word for word; `canopy review eval --checklist` scores an item
case; and a week of real use is in `MEASUREMENTS.md` as stage 2 says.

Status: not started. Designed 2026-10-29 (DESIGN §42).
