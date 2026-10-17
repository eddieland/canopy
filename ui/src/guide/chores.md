# Chores and memory

Two things the loop does beside its tickets. A chore is recurring work you define, such as a check on your builds,
that reports what it finds to the attention list. Memory is what workers learn on one run and carry to the next.

## Chores

A chore is an agent run about no ticket: no worktree, no branch, no push. You define one as `[chores.NAME]` in your
own config, with a prompt and how often it may run, and set `capacity.max_chores` above 0. The overseer decides when a
due chore runs, each tick, within the hours you allowed it. The schedule is a floor, not an alarm clock: "at most
every 120 minutes" means no sooner, not on the dot.

[Chores](/chores) lists each chore: whether it's running, when it last ran ok, when it's due, its open findings, its
schedule, and what its runs cost over the last day and month. There's no button to run one now; `canopy chore try NAME`
does that from your shell.

## A chore's page

- **Schedule**: how often it may run, the hours it may start in, and its `when`, the words you gave the overseer for
  when it's worth running.
- **Open findings**: what its latest ok run found. Each finding also reaches the attention list.
- **Notes**: what you've told its runs. More on these below.
- **Runs**: every run, with its status, how many findings it had, its cost, and its summary. A run's page has its
  transcript, as a worker's does.
- **Spend**: its runs' cost over the last 24 hours and 30 days, average and worst included.

A chore run that doesn't end ok reaches the attention list as `chore failed`.

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

## Memory

Memory comes in two tiers, each with a mode you set under `[memory]` in your config: `off`, `record`, or `use`, which
the UI calls off, recording, and in use.

- **Ticket notes**: a ticket's runs write them as they end, and only that ticket's later runs read them: what one
  worker learned about the ticket, left for the next.
- **Lessons**: workers propose them, and only the ones you promote reach other tickets' runs. A promoted lesson is
  read by every worker in the workspace, which is exactly why a proposal waits for you.

[Memory](/memory), in the nav, lists the ticket notes in force and the lessons, with the proposals waiting on you,
and the exact text every run is served from your lessons, or would be once they're in use. While either tier is on,
the header shows `memory: recording` or `memory: in use`, which opens it too. A ticket's page shows its own notes,
and a run's page what it wrote and read.

Recording without using is a good way to start: you see what workers would remember before any of it reaches a
prompt.

## Promoting a lesson

The memory page only reads. Promoting, rejecting, renewing, and forgetting are `canopy memory`'s, in your shell:
`canopy memory promote ID` promotes a proposal, or a ticket's note, with `--text` to put it in your own words. A new
proposal reaches your attention list, and so does a lesson that's due for review or that a run reported wrong.
