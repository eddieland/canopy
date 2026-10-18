# Chores

Recurring work you define, beside the tickets: a check on your builds, a sweep for stale dependencies, anything an agent
can look at on a schedule and report on to the attention list.

## Chores

A chore is an agent run about no ticket: no worktree, no branch, no push. You define one as `[chores.NAME]` in your
own config, with a prompt and how often it may run, and set `capacity.max_chores` above 0. The overseer decides when a
due chore runs, each tick, within the hours you allowed it. The schedule is a floor, not an alarm clock: "at most
every 120 minutes" means no sooner, not on the dot.

[Chores](/chores) lists each chore: whether it's running, when it last ran ok, when it's due, its open findings, its
schedule, and what its runs cost over the last day and month. To run one now instead of waiting for the overseer, use
**Try now** on its page, below.

## A chore's page

The line under its name says whether it's healthy: how its latest run ended and when it's next due, then its open
findings, if it has any (`last ok 4h ago, due in 1h · 1 open finding`). While a run works, it says that and still how
the last one ended, since the running one hasn't said anything yet.

- **Schedule**: how often it may run, then, if you set them, the hours it may start in and its `when`, the words you
  gave the overseer for when it's worth running. A chore that may start any time, whenever it's due, shows just the
  first.
- **Open findings**: what its latest ok run found. Each finding also reaches the attention list.
- **Runs**: every run, with its status, how many findings it had, its cost, and its summary. A run's page has its
  transcript, as a worker's does, filling in while the run works.
- **Notes**: what you've told its runs. More on these below.
- **Spend**: its runs' cost over the last 24 hours and 30 days, average and worst included.

On a wide screen, the open findings and runs take the wide column, since that's where you act, and the schedule, notes,
and spend sit beside them.

A chore run that doesn't end ok reaches the attention list as `chore failed`.

## Trying a chore

**Try now**, at the foot of **Schedule**, runs the chore at once, as `canopy chore try NAME` does: a real run, recorded
like the overseer's, whatever its schedule, its hours, or `max_chores`. The run shows in **Runs** straight away, its
findings reach the attention list when it ends, and the next scheduled run counts from it. While a run of the chore is
going, the button waits. Each try costs what a run costs, so it's for when you want an answer now, not for asking
until you like the answer.

To try a prompt you're still writing without touching its open findings, run `canopy chore try NAME --no-record` from
your shell: it prints what the run found and records nothing.

## Dismissing a finding

A finding you've read and don't want to see again has **dismiss**, here and on its attention item. It keeps the
finding off the attention list until the chore stops reporting it; if the finding clears and later comes back, it's
listed again. **undo**, here, lists it again now. This is `canopy dismiss chore:NAME ID`.

## Capping the findings

A chore that reports forty findings has told you nothing you'll read. So each run lists at most five, the ones that
matter most, and only counts the rest; `max_findings` in its `[chores.NAME]` table changes that, up to 20. The count
shows as `not listed` beside **Open findings**, on each run, and in `attention.md`, so a short list never passes for
the whole one. canopy keeps the first five of a longer list itself, so say in the prompt which kind comes first. A
dismissed finding still takes one of the five; to make room, write the chore a note to leave it out.

A chore over its limit has a band at the top of its page saying by how much. It stays until a run fits under the
limit, which is the hint: either the chore is looking at too much, and a note can narrow it, or you really do want
more, and `max_findings` goes up. Either way, decide once, rather than skimming the same top five every morning.

## Notes to a chore

A note is an instruction to the chore's next runs, such as a finding to leave out or a place to look harder. Nothing
waits on one, so the box stays folded: open **Show a note for its next runs** in **Notes**, write it, and press **Add
note**, or your send key; it's `canopy reply chore:NAME`. Every run reads the latest ten, oldest first, and a later
note wins over an earlier one. A note no run has read yet is marked `waiting for the next run`. A chore with no notes
follows its prompt file alone, which is how most of them should spend most of their lives.

Nothing deletes a note. To take one back, write a newer one that says so. Notes never reach the overseer or the
attention list: they shape what the chore looks for, not when it runs.

## What a run knows of the last ones

Each run's prompt carries the previous run's summary and the open findings, so it reports a problem still there under
the same id. That's all it gets for free. When it wants more, say whether a flaky test came and went last week, it runs
`canopy chore history NAME` for the chore's runs and what each found, and `--run ID` for one in full. A run reads its
own chore's history and no other's, and the overseer reads none. You can run it too; it's the **Runs** list with the
details left in.

A chore with an agent definition of your own needs `"canopy chore history *": allow` among its bash rules to look back.
A sandboxed chore can't: the journal sits in the part of `.canopy/` its sandbox hides, so it makes do with its prompt.
