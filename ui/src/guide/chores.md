# Chores

A chore is a scheduled task with an agent's judgment in it. You write, in plain language, what to look at and what
counts as a problem; on a schedule, an agent goes and looks, decides what matters, and puts each problem it finds on
the attention list with a link. A cron job can tell you a check went red. A chore can tell you it's the same flaky
test as Tuesday, that three PRs are failing for one reason, and which of forty Sentry issues is worth your morning.

## What a chore can do

- **Read whatever its tools reach.** Under the agent canopy ships, that's your GitHub and tracker MCP servers' read
  tools: CI on main, other people's PRs, review queues, tickets. Give a chore an agent of its own and it can also run
  the read-only commands you allow it, such as `sentry issue list`, `pip-audit`, or canopy's own `canopy health`.
- **Judge, not just match.** Its prompt can say "a test that failed and passed on retry is flaky" or "skip anything
  someone is already assigned to", and it applies that the way a person would, with your [notes](#notes-to-a-chore)
  steering it from run to run.
- **Remember.** Each run sees what the last one said and which findings are still open, so a problem keeps one id and
  one attention item until it's fixed, then quietly goes away. It can also look further back,
  [below](#what-a-run-knows-of-the-last-ones).
- **Run when it's worth it.** You set how often it may run and in which hours; the overseer decides whether a due run
  is worth it, guided by a `when` line in your words, such as "skip it on weekends unless the last run found something".
  Without a `when` there's nothing to judge, so canopy starts it itself each time it's due, right after the overseer.

What it can't do is change anything. A chore edits no file, pushes no branch, posts no comment, and files no ticket;
the agent it runs under has no write tools. Its only output is its findings, and what to do about them is yours, or
a ticket's. That's deliberate: a chore reads text from people outside your queue, and an agent that reads strangers'
words shouldn't hold a pen. When you already know what to change, that's a ticket, not a chore.

Some chores canopy ships: `build-health` (red and flaky checks on main), `sentry-triage` (the errors nobody has
acted on), `canopy-health` (what keeps failing in canopy itself, and the setting to tune), and `memory-tickets` (what
workers learned that should become a ticket).
[examples/chores](https://github.com/eddieland/canopy/tree/main/examples/chores) has those and a few dozen more ideas,
from review queues to end-of-life runtimes.

## Setting one up

A chore runs about no ticket, so it gets no worktree and no branch. You define one as `[chores.NAME]` in
`.canopy/config.toml` (or `~/.config/canopy/config.toml`, for every workspace), with a prompt and how often it may run,
and set `capacity.max_chores` above 0. Open the prompt with a heading, `# Dependency advisories`: it's the chore's title
on Runs, under [Workspace](/workspace), and its runs' pages, as a ticket's title is a worker run's. The overseer decides
when a due chore runs, each tick, within the hours you allowed it. The schedule is a floor, not an alarm clock: "at most
every 120 minutes" means no sooner, not on the dot.

A chore runs on `runtime.models.chore` unless its table sets a `model` of its own, spelled the same way,
`provider/model@variant` included; canopy runs it on a copy of its chore agent made for that model. A chore whose
command runs an agent of your own can't take one: canopy doesn't write that agent's definition, so the model goes
there, and config refuses a `model` beside it rather than let two places disagree. [Settings](settings#models) shows
which model each chore ends up on, and each run's page names the one it asked for, then the one that served it.

You don't have to start from a blank page. `canopy chore install` lists the chores canopy ships, and
`canopy chore install NAME` copies one's prompt, its table, and the agent it runs if it comes with one into this
workspace, then says what's left to set up. The copies stay put when canopy is upgraded. The command owns them, though:
running it again puts the shipped version back over your edits. Steer an installed
chore with notes instead (below), which it leaves alone.

[Chores](/chores) lists each chore: whether it's running, how its latest run ended and when, when it's due, its open
findings and how many you dismissed, its schedule, and what its runs cost over the last day and month. While
`capacity.max_chores` is 0, the loop runs no chores and the list is empty, whatever you defined: a chore's page still
opens at `/chores/NAME`, and **Try now** still works there. To run one now instead of waiting for the overseer, use
**Try now** on its page, below.

## A chore's page

The line under its name says whether it's healthy: how its latest run ended and when it's next due, then its open
findings, if it has any (`last ok 4h ago, due in 1h · 1 open finding`). While a run works, it says that and still how
the last one ended, since the running one hasn't said anything yet.

- **Schedule**: how often it may run, then, if you set them, the hours it may start in and its `when`, the words you
  gave the overseer for when it's worth running. A chore that may start any time, whenever it's due, shows just the
  first.
- **Open findings**: what its latest ok run found, each with how long it's been open. Each finding also reaches the
  [attention list](attention#chore-items); one you dismissed stays here, marked `dismissed`, and the count beside the
  label names those apart from the open ones.
- **Runs**: every run, with its status, how many findings it had, its cost, its summary, and its session id and log
  path, each with a button that copies it. A run's page is laid out as [a worker's](runs#a-runs-page) is: its summary
  first, when it ran and for how long, what it spent and on which model, and its log, then its findings and its
  transcript, filling in while the run works, and the prompt it started from. Its chore is the link in the trail above
  the title.
- **Notes**: what you've told its runs. More on these below.
- **Spend**: its runs' cost over the last 24 hours and 30 days: how many runs, the total, the average, the 99th
  percentile, and the worst. Runs that reported no cost are counted as `unpriced`, so a cheap-looking month says how
  much of it nobody priced.

On a wide screen, the open findings and runs take the wide column, since that's where you act, and the schedule, notes,
and spend sit beside them.

A chore run that doesn't end ok reaches the [attention list](attention) as `chore failed`.

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
waits on one, but the box sits open under **Notes** all the same: write it and press **Add note**, or your send key;
it's `canopy reply chore:NAME`. Every run reads the latest ten, oldest first, and a later note wins over an earlier
one. A note no run has read yet is marked `waiting for the next run`. A chore with no notes follows its prompt file
alone, which is how most of them should spend most of their lives.

Nothing deletes a note. To take one back, write a newer one that says so. Notes never reach the overseer or the
attention list: they shape what the chore looks for, not when it runs.

## What a run knows of the last ones

Each run's prompt carries the previous run's summary and the open findings, so it reports a problem still there under
the same id. That's all it gets for free. When it wants more, say whether a flaky test came and went last week, it calls
its one canopy tool, `canopy_chore_history`, for the chore's runs and what each found, or for one run in full. A run
reads its own chore's history and no other's, and the overseer reads none. You can read it too, with
`canopy chore history NAME`: it's the **Runs** list with the details left in.

A chore with an agent definition of your own needs `"canopy_chore_history": allow` among its permissions to look back.
A chore's run also gets a second server, of canopy's own reports, for a chore that looks at canopy itself:
`canopy_reports_health`, `-spend`, `-decisions`, `-show-run`, `-show-chore`, `-config-show`, and `-agents`, and agent
memory's `canopy_reports_memory-lessons`, `-proposals`, and `-list`. Each says what its command prints, the JSON where
the command has `--json`; there's no page of a ticket, which holds its conversation. The agent canopy ships reads none
of them; yours allows the ones it needs, each by name, and needs no shell for them.
A sandboxed chore can't: the journal sits in the part of `.canopy/` its sandbox hides, so it makes do with its prompt.
