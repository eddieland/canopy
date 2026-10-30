# Reports

What canopy cost and what it got done, month by month, and what agent runs cost each day. Every dollar and token here
is what the agent runtime reported, so if a runtime under-reports, so does this page. It is a mirror, not an audit.

## The reports page

[Reports](/reports) puts the calendar months side by side, a year of them by default; **6 months** and **24 months**
narrow or widen it. A month runs midnight to midnight on the clock of the machine canopy runs on, like the spend
page's days. The line under the title is the month so far: what it cost, the tickets it landed, and its PRs.

**Month by month** is the bill, the whole of it: canopy's runs and the sessions outside canopy alike, so a month you
spent pairing with an agent by hand doesn't pass for a cheap one. For each month: what it **spent**, with a bar against
the dearest month so the trend reads at a glance; its **runs**, a tick each for the overseer; the tokens the models were
**sent** and **wrote**; the **cache hit**, the share of what was sent that came from the cache; the tickets **landed**
and **closed**; the **PRs** a run first named in it; and the cost **per landed** ticket, the overseer and chores
included, but not your own sessions, which landed nothing canopy knows of. A cache hit that drops from one month to the
next is the first place to look when the bill grows and the work didn't: a changed prompt or a new tool list can turn
every run cold.

**Delivery** is what the months got done, as a median per landed ticket:

- **iterations**: the worker runs, implement and resume, a ticket took before it landed. One means the first attempt
  shipped; five means somebody had opinions.
- **PR comments**: comments on its PRs from people other than the PR's author. canopy posts as you, the author, so its
  own replies and reviews never count as feedback it received. Bots are left out too.
- **to land**: from its first worker run to the tick that marked it done. canopy doesn't keep GitHub's merge time, so
  the tick that saw the merge stands in, which can add up to one tick's wait.
- **review wait**: from the end of its first worker run that ended done, when the PR was ready, to the first review
  after it. canopy keeps no history of a ticket's phases, so this is the closest honest proxy for time spent waiting on
  a reviewer. A ticket nobody reviewed has none, and isn't counted.

Click a month to see it in detail below; the page opens on the latest.

**By kind** splits the month by who spent it, the same kinds as the spend page: the overseer, dry runs included, then
workers, plans, chores, reviews, and your tasks, each with its runs, cost, tokens, and cache hit. Under them, **outside
canopy** is the runtime's sessions none of canopy's runs started, counted in sessions, not runs: yours, and another
workspace's canopy, as of when `canopy loop` last read them (hover it for when). **By model** is what each model's
replies cost over every kind of run, the dearest first, with the runs canopy hasn't read a model for yet last as
**none**.

**Landed** lists the month's tickets the loop marked done as merged, the latest first, with each one's iterations, PR
comments, reviews (the ones that asked for changes in brackets), time to land, review wait, and what its own runs cost.
A ticket closed without a merge is counted in **closed** above, not here.

## The spend page

The spend page, which **Spend by day** on [Reports](/reports) opens, as do the rail's counters, shows what agent runs
cost, as the runtime reported it, over the last **24 hours**, **7 days**, or **30 days**. The line under the title is
the window at a glance, `$10.51 over 7 days · 2 tickets done`; hover the title for what the page holds.

**This month** sits on top whatever the window, and tracks the calendar month so far against the monthly budget you set
under [Limits and trust](settings#limits-and-trust): what it spent of the budget, and what the month will cost if the
rest of it spends like the start did. Spent means every agent session on this machine, not just canopy's: the line
under it splits the month into canopy's runs and the sessions outside canopy, the ones you ran by hand, as of when
`canopy loop` last read the runtime's record. It reads it between ticks, so with the loop stopped your own sessions
wait to be counted, and the month can look thriftier than it is. The bar fills with the budget spent, and the mark
across it is how far through the month you are, so a bar past its mark is spending faster than the budget allows. It
reads **On budget**, then **Headed over** once the pace passes the budget, then **Over budget**, and the wallet in the
[header](overview#the-header) wears the same in its color on every page, so you needn't come here to check. The pace
waits for the month's first day to end, since one morning's runs would otherwise forecast something dramatic. Nothing
stops at the budget: it's a number to watch, not a brake. A [sink](slack#choosing-what-it-hears) that takes `loop`
events hears once when the month reaches it, and again only if you raise the budget and the month reaches that too. The
message splits the month the same way, canopy's runs and outside canopy, and says when your own sessions were last
read.

Want a heads-up before the bill, not after? Add alerts at other percentages of the budget, `50, 80` say, or `150` for
when the month really gets away from you. Each is sent once a month, as the spend reaches it, and the ones short of the
budget show as ticks under the bar. A month that jumps past several at once hears about the highest one, because one
message saying 80% beats two saying 50% and then 80%. The 100% alert always goes out. With no budget set, the panel says
where to set one.

The **Totals** split it by who spent it: the overseer, then the part of that its idle ticks spent, then the workers,
plans, chores, reviews, your one-off tasks, and dry runs, and last **outside canopy**, the sessions none of canopy's
runs started. The total counts them all. Beside them are the tickets the loop marked done in that window, and what each
cost on average, the overseer and chores included and your own sessions not, since they landed nothing canopy knows
of.

Each split has one name everywhere on the page, in the totals, the chart's legend, and the table: **overseer** is all
the overseer spent, idle ticks included, as `canopy spend` counts it, and **idle ticks** is the part of it that went
on deciding there was nothing to do. Hover a name for what it counts.

**By day** stacks each day's spend by the same split, with a table under it that also counts the tickets done that day.
A day runs midnight to midnight on the clock of the machine canopy runs on, so your evening's work lands on today and
not on a UTC tomorrow. The dearest day has its total printed over its bar, so you can read the scale without hovering;
hover any bar for that day's figures. A day that cost nothing is a flat line on the baseline, not a gap. Idle ticks sit
at the bottom of each bar, under the rest of the overseer's spend in a deeper shade of its color, and at real prices
they're a sliver beside a worker's run, so read their trend from the table. The sessions outside canopy sit on top, no
part of canopy's work but very much part of the bill. A window where nothing reported a cost says
so in one line rather than draw you an empty chart.

**24 hours** does the same by the hour: 24 clock hours ending with this one, so the newest bar fills in as the hour
goes. That's the window the rail's **24h** counter opens, for when you want to know what the last hour cost rather than
what the week did. The hour that started 24 hours ago is just outside it, so the total can read a little under the
rail's. Then:

- **By ticket** and **By pull request**: what each one's own runs cost. The overseer isn't shared out among them.
- **By model**: what the runs spent on each model, as their own sessions say, the dearest first. It opens on **all**,
  each model summed over every kind of run; the **kind** filter in its header narrows it to the overseer's, the
  workers', or any other kind the window has runs of. A run that switched models counts under both, with its share
  of the cost under each, so the runs column won't add up to the kind's. **per run** is what a model spent over its
  runs, which is how you compare a model that ran twice with one that ran twenty times. Runs whose model canopy
  hasn't read yet sit last as **none**, with what they reported costing, and the header says how much of the table
  that is (`43% not yet attributed`), since a big **none** quietly flatters every model above it. Each run's session
  is read as it ends, and the loop reads the stragglers while it waits between ticks, so **none** is mostly runs from
  before canopy read models, and it shrinks while the loop idles. Click a model to see [its runs](runs#the-runs-page),
  of the kind the table shows, or of every kind under **all**. The overseer's models aren't links: the runs page lists
  ticks apart, under Ticks, and not by model. This is the table to read before and after you change a model in your
  config, which moves the whole workspace. To try one on a single ticket first, read that ticket's line instead
  ([Choosing a model](tickets#choosing-a-model)): its link opens this table narrowed to the ticket, its key in the
  header, on its **workers** rather than **all**, so the reviewer's model doesn't mix in. Each row then counts the
  ticket's own runs and adds **workspace per run**, what every run of that kind on that model cost each, the ticket's
  included. **all** brings its plan and review runs back, and **every ticket** drops the ticket again. Only this table
  narrows: the rest of the page is still the whole workspace's.
- **By tool**: which tools put the most into the runs' context, by the characters their calls returned, every kind
  summed or one kind's, with the same filter. Every later model call of the run reads those again, so a chatty tool
  costs more than once. The filters stay put when you switch the window, so you can watch the workers' `bash` habit
  across a month without picking it again.
- **First calls by week**: how much of each kind's first model call the cache served, a bar per week, Monday to
  Sunday on canopy's clock. That first call carries the prefix every run of the kind starts with, so a warm cache
  makes it cheap, and a bar that drops is a prefix the cache no longer recognizes. The usual suspects get a rule
  before their week and a line under the chart: a runtime version, or a definitions snapshot (canopy's prompts and
  agent definitions, as a run loaded them), that the week's runs used and the week before's did not. A dip with no
  rule beside it is your cue to look elsewhere. Pick the kind in the header, then **all runs**, one chore, or one
  model under it; runs that more than one model served stay in **all runs**. The table holds each week's runs and
  median first call. The 7 days hold one or two weeks, which is not much of a trend, so pick **30 days**; it's what
  `canopy spend --days 30` prints, by week.
- **Every session**: every session the runtime keeps that started in the window, in any directory: **canopy's
  runs**, a subagent's counted with the session it ran for, and **outside canopy**, then where those ran, the
  costliest directory first. Another workspace's canopy counts as outside, since its runs are in another journal. The
  header says when `canopy loop` last read the runtime's record; it reads it between ticks, so with the loop stopped,
  the list waits.
- **Ticks by what they bought** and **Ticks by what woke them**: the ticks counted and costed by whether they were idle,
  and by their cause. The **no overseer** column counts the ones that ran no overseer, because nothing was left for it
  or the tick halted first. They cost nothing and count as nothing, never as a run that forgot to report its cost, so
  what idle ticks spent is only the overseer runs that bought nothing.
- **Idle ticks**: the newest of them, to open.

If a run reported no cost, the totals say how many, so a gap in the figures never passes for a quiet week.
