# Checklists

Your rules for a repository that no linter checks, asked of a worker's diff before it pushes, with each answer kept so
you can tell which rules earn their place. This page covers writing a list, what a worker does with it, and reading
what comes back.

## Why ask

Your workers already read the repository's `AGENTS.md` and your standing instructions, and they still miss the rules
your team keeps tripping on: the most general parameter type, the doc comment in the house style, the companion file a
migration needs. A rule among forty, read once at the top of a long run, loses to everything the run reads after it.
Asked one plain question about one finished diff, "does this do X?", an agent answers reliably.

So canopy asks at the moment it matters: when the worker's diff is whole and before anything is pushed, so a fix costs
no CI run. A reviewer who keeps writing the same comment is a checklist item that hasn't been written down yet.

## Writing a list

Point `paths.checklists` in your own config at a directory, and put one file in it per repository you want asked,
named for the repository as the workspace map names it: `api.md` for `api`. A repository with no file is never asked,
so you can start with the one whose reviews annoy you most. The key is yours alone: a list is instructions in every run
it reaches, so the shared workspace file can't set it, and canopy refuses to start if it does.

Each item opens with a `## <id>` heading, then two optional lines, then the rule in plain words:

```markdown
## general-types
paths: src/**/*.py

A parameter takes the most general type its body needs: `Iterable` for one pass, `Mapping` for a dict it only reads.
Passes: `def total(xs: Iterable[int])` over a body that loops once. Fails: `def total(xs: list[int])` over the same.

## migration-companion
paths: migrations/
severity: major

A new migration has its companion under `tests/canopy/core/migrations/`, of the same number, opening with the
migration's sha256. Passes: both files in the diff. Fails: a migration alone.
```

- **The id** is a word of letters, digits, `.`, `_`, and `-`, unique in the list. It's how the worker's answer names
  the item, so renaming one starts its count over.
- **`paths:`** lists the paths the item is about, separated by commas, from the repository's root: `docs/`, or a
  pattern such as `services/*/migrations/` or `**/OWNERS`, with `*` and `?` inside a part and `**` only as a whole
  part. With no `paths:` line, the item is about every path.
- **`severity:`** is `blocking`, `major`, or `minor`, the default. The reminder doesn't use it; it's there for a review
  that asks the same list of a PR, which canopy doesn't run yet.
- **The rule** says what passes and what fails, ideally with one example of each. A rule a worker has to guess at gets
  guesses for answers.

Ten to fifteen items is plenty. A longer list is usually two lists, or a list with a linter hiding in it: anything a
machine can check belongs in the linter, which never gets tired of saying so.

A file holds at most 16 KiB of UTF-8, and nothing before its first heading. Like a [persona](personas), it may not
hold a character that hides text, such as a zero-width space, since it reaches every run in its repository.

## When a list can't be read

A list canopy can't use refuses the run, as `bad_prompt`, rather than running it without the list. The refusal names
the file and what's wrong with it, such as text before the first heading, an item with no rule, or an id used twice.

The list is read again for every run, so a fixed file counts from the next one, with no reload. A run already going
keeps the list it started with, and its answers are held to that one.

## The held push

Workers that may push hear the list: `implement` and `resume` runs, on public and private tickets alike, and a
[task's run](tasks#a-tasks-run). The overseer, a planner, a reviewer, and a chore never do.

canopy's own `pre-push` hook, which a worker's git already runs before the repository's, holds the worker's first
push. It prints `[canopy] Push held, not rejected: nothing was sent.` and the repository's list, asks the worker to
diff the branch against its base, hold each item to the diff, and commit a fix for each that fails, and then fails, so
git sends nothing. The worker's next push goes through, with the repository's own `pre-push` hook run as usual. So a
worker is held once, never kept from pushing.

- It holds only a push with something to send, from whatever ran it: a script, `make`, or the worker typing `git push`.
- A push more than half an hour after the hold, from the same run, is held again: a lot can change in a long stretch of
  work.
- In the last stretch before a run's [timeout](how-the-loop-works#runs), it holds nothing. It prints the list, lets
  the push through, and asks for any fix in a push after it, since a held push that late risks a run that ends with
  nothing pushed at all.
- A run across several repositories is held in each, with that repository's own list.

It's a reminder, not a guard: `git push --no-verify` skips it, as it skips every hook. The worker's prompt says a held
push is to be pushed again, unlike a push the remote rejects, which a worker still never retries.

## The answers

The worker answers every item in its result, under its repository:

- **pass**: the diff already held to it.
- **fixed**: it didn't, and the worker committed the fix.
- **held**: it doesn't, and the worker left it so, with its reason in a sentence or two.
- **n/a**: the diff touches nothing the item is about.

An item the result leaves out is recorded **unanswered**, however the run ended, so a run that ended without a result
counts every item so. An answer to an item or a repository the run's lists don't hold is dropped.

No answer raises an attention item, `held` included: a person still reviews the PR, and a held item is the worker's
case made in advance, on the run for that person to read. Each run's answers are in the **Checklist** panel of
[its page](runs#a-runs-page), or [a task's run's](tasks#a-tasks-run), and `canopy show run:ID` or `canopy show task:N`
prints them.

## Tuning the list

The [checklist page](reports#the-checklist-page) under Reports counts the answers per repository and item, over 7, 14,
or 30 days, and applies the advice below for you: an item it would drop says `drop?`, one to argue about says `argue`.
`canopy checklist --days 14` prints the same counts, `--repo NAME` keeps one repository's list, and `--json` gives you
the numbers to do your own arithmetic.

- An item that's mostly **n/a** is about too little, or its `paths:` are too wide. Narrow it, or drop it.
- An item that's never anything but **pass** is a rule your workers keep without being asked, and every reminded run
  pays tokens to agree with it. Drop it, and keep it in `AGENTS.md`.
- An item that's often **held** is a disagreement. Read the reasons (the page's **held** count lists the runs and what
  each said), then take it up with whoever wrote the rule: one of you is wrong, and the list should say which.
- A lot of **unanswered** is mostly runs that never pushed, so were never held. canopy counts every item of a run it
  gave a list to, pushed or not, and errs toward too many.

A list is worth its tokens when its items get **fixed**: each one is a review comment nobody had to write, and a CI run
nobody had to wait for.
