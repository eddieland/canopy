# Ticks and spend

What the overseer decided each tick, and why, and what the whole loop costs. When the loop does something you didn't
expect, a tick's page is where you find out what it was thinking.

## The ticks page

[Ticks](/ticks) lists the latest 50 ticks, newest first: each one's status, how many decisions it recorded, what its
overseer cost in dollars, tokens, and peak context, and its summary. A `dry run` chip marks a tick from
`canopy tick --dry-run`, which plans and dispatches nothing.

A tick ends:

- `ok`, the usual;
- `skipped`, when the overseer couldn't see the world, such as an MCP server that wasn't there;
- `overseer failed`, when the overseer didn't finish its job, such as deciding about every ticket;
- `canopy unavailable`, when the overseer couldn't run canopy at all, so nothing was decided;
- `reconcile failed`, when tidying up after the last tick went wrong;
- `abandoned`, when its process went away without closing it, and the next tick closed it for it.

## A tick's page

The **Tick** panel says when it started and ended, its summary, its overseer's session, what it spent, and the path of
its output. The line under the title says what woke it: the timer, your reply, a run ending, **Tick now**, and so on.

**Decisions** lists what the overseer decided, in the order it decided, each with its subject, its action, and the
overseer's reasons in its own words. A `refused` action, in red, names the guard that held it back; an `attention`
action, in amber, is an item it put on your list. When you want to know why a ticket sat still, its refusals are
usually the answer.

Under them are the overseer's session, as a run's [Transcript](runs#a-runs-page) shows it, and its raw **Output**,
stdout then stderr, opened with **Show output**. **Pretty** lays each event out on its own lines. The output opens at
its end, where the errors are, since that's usually why you're reading it.

## The spend page

[Spend](/spend) shows what agent runs cost, as the runtime reported it, over the last **7 days** or **30 days**. The
**Totals** split it by who spent it: the overseer, with its idle ticks apart, the workers, chores, reviews, and dry
runs. Beside them are the tickets the loop marked done in that window, and what each cost on average, the overseer and
chores included.

**By day** stacks each UTC day's spend by the same split, with a table under it. Then:

- **By ticket** and **By pull request**: what each one's own runs cost. The overseer isn't shared out among them.
- **By tool**: which tools put the most into the runs' context, by the characters their calls returned. Every later
  model call of the run reads those again, so a chatty tool costs more than once.
- **Ticks by what they bought** and **Ticks by what woke them**: the ticks counted and costed by whether they were idle,
  and by their cause.
- **Idle ticks**: the newest of them, to open.

If a run reported no cost, the totals say how many, so a gap in the figures never passes for a quiet week.

## Idle ticks

A tick is idle when it found nothing new: it closed ok, decided only waits, skips, and refusals that lift by
themselves, changed no phase and no attention item, and nothing reached the journal since the tick before. The loop
waits longer after each idle tick, so a quiet day costs little, but a tick that decides nothing still pays for the
overseer to read everything. The share of the overseer's spend that went on idle ticks is the line under the totals.
If it's high, a longer `loop.idle_max_minutes` is the knob.
