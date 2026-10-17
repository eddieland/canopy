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

- **Schedule**: how often it may run, the hours it may start in, and its `when`, the words you gave the overseer for
  when it's worth running.
- **Open findings**: what its latest ok run found. Each finding also reaches the attention list.
- **Notes**: what you've told its runs. More on these below.
- **Runs**: every run, with its status, how many findings it had, its cost, and its summary. A run's page has its
  transcript, as a worker's does.
- **Spend**: its runs' cost over the last 24 hours and 30 days, average and worst included.

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

## Notes to a chore

A note is an instruction to the chore's next runs, such as a finding to leave out or a place to look harder. Write one
in **Notes** and press **Add note**, or your send key; it's `canopy reply chore:NAME`. Every run reads the latest ten,
oldest first, and a later note wins over an earlier one. A note no run has read yet is marked `waiting for the next
run`.

Nothing deletes a note. To take one back, write a newer one that says so. Notes never reach the overseer or the
attention list: they shape what the chore looks for, not when it runs.
