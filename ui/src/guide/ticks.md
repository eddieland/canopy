# Ticks and spend

What the overseer decided each tick, and why, and what the whole loop costs. When the loop does something you didn't
expect, a tick's page is where you find out what it was thinking.

## The ticks page

[Ticks](/ticks) lists the latest 50 ticks, newest first: each one's status, how many decisions it recorded, what its
overseer cost in dollars, tokens, and peak context, and its summary. A `dry run` chip marks a tick from
`canopy tick --dry-run`, which plans and dispatches nothing. Before the first tick, the page says when one comes: after
`loop.interval_minutes`, or now, with **Tick now** right there in the sentence.

A tick reads `running` while it works, and ends:

- `ok`, the usual;
- `skipped`, when the overseer couldn't see the world, such as an MCP server that wasn't there. It still did the
  chores and whatever else needed nothing from the missing server, then left the attention list alone;
- `overseer failed`, when the overseer didn't finish its job, such as deciding about every ticket;
- `canopy unavailable`, when the overseer couldn't run canopy at all, so nothing was decided;
- `disk low`, when the disk had less free than `loop.min_free_disk_mib`, 2 GiB by default, so the overseer didn't run
  and started nothing;
- `reconcile failed`, when tidying up after the last tick went wrong;
- `error`, when something in canopy itself broke during the tick; its summary names what, such as a full disk;
- `abandoned`, when its process went away without closing it, and the next tick closed it for it.

## A tick's page

The line under the title says how the tick ended, how many decisions it recorded, and what woke it: the timer, your
reply, a run ending, **Tick now**, and so on. The **Tick** panel leads with its summary, then when it ran and for how
long, what it spent, the model its overseer ran on, and the version of canopy that ran it, laid out as a run's page
is. The version is the one to check when a decision looks like the work of a release you thought you'd upgraded past.

The buttons at the right of the title step to the tick before and after this one, dry runs included, so the ticks
around an old one are a click away rather than an edit to the URL. At either end the button stays, greyed out; on the
newest tick, the next one's button comes alive when the next tick starts. For the latest tick itself, the header's
readout is the shortcut.

**Decisions** lists what the overseer decided, in the order it decided, each with its subject, its action, and the
overseer's reasons in its own words. A `refused` action, in red, names the [guard](how-the-loop-works#guards) that held
it back; an `attention` action, in amber, is an item it put on your list. When you want to know why a ticket sat still,
its refusals are usually the answer.

Under them are the overseer's session, as a run's [Transcript](runs#a-runs-page) shows it, its session id in the
header; the **Prompt** canopy started it with, folded as a run's is; and its raw **Output**, stdout then stderr, under
the path of its file, opened with **Show output**. The transcript and the output fill in while the tick runs, so a
tick that seems stuck can be watched being stuck. A tick that kept no output file has no Output panel; the
transcript's header says why, once. **Pretty** lays each event out on its own lines. The output opens at its end,
where the errors are, since that's usually why you're reading it.

A tick keeps those files for 7 days by default, and one that didn't close `ok` keeps them as long as a run does, 30,
since those are the ones you come back to debug. After that your `[retention]` removes them, and the page says
`removed after 7 days` where they were; the decisions stay forever.

## The spend page

[Spend](/spend) shows what agent runs cost, as the runtime reported it, over the last **24 hours**, **7 days**, or **30
days**. The line under the title is the window at a glance, `$10.51 over 7 days · 2 tickets done`; hover the title for
what the page holds. The **Totals** split it by who spent it: the overseer, then the part of that its idle ticks spent,
then the workers, plans, chores, reviews, and dry runs. Beside them are the tickets the loop marked done in that window,
and what each cost on average, the overseer and chores included.

Each split has one name everywhere on the page, in the totals, the chart's legend, and the table: **overseer** is all
the overseer spent, idle ticks included, as `canopy spend` counts it, and **idle ticks** is the part of it that went
on deciding there was nothing to do. Hover a name for what it counts.

**By day** stacks each day's spend by the same split, with a table under it that also counts the tickets done that day.
A day runs midnight to midnight on the clock of the machine canopy runs on, so your evening's work lands on today and
not on a UTC tomorrow. The dearest day has its total printed over its bar, so you can read the scale without hovering;
hover any bar for that day's figures. A day that cost nothing is a flat line on the baseline, not a gap. Idle ticks sit
at the bottom of each bar, under the rest of the overseer's spend in a deeper shade of its color, and at real prices
they're a sliver beside a worker's run, so read their trend from the table. A window where nothing reported a cost says
so in one line rather than draw you an empty chart.

**24 hours** does the same by the hour: 24 clock hours ending with this one, so the newest bar fills in as the hour
goes. That's the window the rail's **24h** counter opens, for when you want to know what the last hour cost rather than
what the week did. The hour that started 24 hours ago is just outside it, so the total can read a little under the
rail's. Then:

- **By ticket** and **By pull request**: what each one's own runs cost. The overseer isn't shared out among them.
- **By model**: what the runs spent on each model, as their own sessions say, the dearest first. It opens on **all**,
  each model summed over every kind of run; the **kind** filter in its header narrows it to the overseer's, the
  workers', or any other kind the window has runs of. A run that switched models counts under both. Runs whose model
  canopy hasn't read yet sit last as **none**, with what they reported costing. Each run's session is read as it ends,
  and the loop reads the stragglers while it waits between ticks, so **none** is mostly runs from before canopy read
  models, and it shrinks while the loop idles. This is the table to read before and after you canary a model.
- **By tool**: which tools put the most into the runs' context, by the characters their calls returned, every kind
  summed or one kind's, with the same filter. Every later model call of the run reads those again, so a chatty tool
  costs more than once. The filters stay put when you switch the window, so you can watch the workers' `bash` habit
  across a month without picking it again.
- **Ticks by what they bought** and **Ticks by what woke them**: the ticks counted and costed by whether they were idle,
  and by their cause.
- **Idle ticks**: the newest of them, to open.

If a run reported no cost, the totals say how many, so a gap in the figures never passes for a quiet week.

## Idle ticks

A tick is idle when it started no work: it closed ok, dispatched no worker, review, or chore, and nothing reached the
journal since the tick before, no run ending and nothing from you. Waits, refusals, a ticket marked done, a comment
copied, or a new attention item don't count. The loop waits longer after each idle tick, so a quiet day costs little,
but a tick that starts nothing still pays for the overseer to read everything. The share of the overseer's spend that
went on idle ticks is the line under the totals. If it's high, a longer `loop.idle_max_minutes` is the knob.
