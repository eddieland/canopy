# Reports

What canopy cost and what it got done, month by month, what agent runs cost each day, and how they ended. Every
dollar and token here is what the agent runtime reported, so if a runtime under-reports, so does this page. It is a
mirror, not an audit. Beside them, the checklist page counts how workers answered your checklists, item by item, the
CI page says which checks fail, the Reviews page says who reviews canopy's PRs and how soon, and the Plans page says
how you approve plans and what their PRs needed after.

Every report keeps its window in the same place, at the top right beside its title, so changing it from the bottom of
a long page is one scroll up rather than a hunt. A column name with a dotted underline has more to say about what it
counts: hover it, tab to it, or tap it. A chart's numbers are under it too, folded: **Show 7 days as a table** opens
them, and a screen reader reads them whether or not you do.

A report's headline figures each say how they moved since the window before it, as many days or hours ending where
this one starts: `+3 on the 7 days before`. A move the wrong way, more failures or a slower first review, is in red.
Spend never is: whether more of it bought enough is your call, not the page's.

## The reports page

[Reports](/reports) opens on a card for each report under it: **Spend**, **Checklist**, **Health**, **CI**,
**Reviews**, and **Plans**, each with that page's own line for the last 30 days (`3 of 46 runs failed over 30 days`)
and, where the page draws one, a small line of its days, so a bad week shows before you open anything. Click a card for
its page on those 30 days; hover it for what the page holds.

Under the cards, the calendar months sit side by side. The page opens on the months since the first one with anything
in it, a year at most, and the panel says from when (`since April 2026`), so a workspace that's a few months old isn't
padded out with a year of zeros. **6 months**, **12 months**, and **24 months** in the header draw that many whole,
empty ones included, and pressing the one that's on goes back to fitting. A month runs midnight to midnight on the
clock of the machine canopy runs on, like the spend page's days. The line under the title is the month so far: what it
cost, the tickets it landed, its PRs, and what the month before cost, for the comparison you were about to make anyway.

**Month by month** is the bill, the whole of it: canopy's runs and the sessions outside canopy alike, so a month you
spent pairing with an agent by hand doesn't pass for a cheap one. It's the spend page's chart a month to a bar: each
month stacked by kind in the same colors, the sessions outside canopy on top, the dearest month's total over its bar,
and the month you're looking at shaded. Click a bar to look at that month. The table folded under it has, for each
month: what it **spent**, with how that moved on the month before on hover; its **runs**, a tick each for the overseer;
the tokens the models were **sent** and **wrote**; the **cache hit**, the share of what was sent that came from the
cache; the tickets **landed** and **closed**; the **PRs** a run first named in it; and the cost **per landed** ticket,
the overseer and chores included, but not your own sessions, which landed nothing canopy knows of, against the month
before on hover too. A cache hit that drops from one month to the next is the first place to look when the bill grows
and the work didn't: a changed prompt or a new tool list can turn every run cold.

**Delivery** is what the months got done, as a median per landed ticket. Each median is drawn across the months over
the table, the latest month's figure beside its name, so a review wait creeping up reads as a line going the wrong way
rather than a column of numbers you have to remember. Hover a point for its month:

- **iterations**: the worker runs, implement and resume, a ticket took before it landed. One means the first attempt
  shipped; five means somebody had opinions.
- **PR comments**: comments on its PRs from people other than the PR's author. canopy posts as you, the author, so its
  own replies and reviews never count as feedback it received. Bots are left out too.
- **to land**: from its first worker run to its PR's merge, on GitHub's clock. A PR canopy read before it kept
  GitHub's times has no merge time, so the tick that marked the ticket done stands in, which can add up to one tick's
  wait.
- **review wait**: from when its PR started waiting on a reviewer to the first review after that, on GitHub's clock:
  the first review asked for once the PR was ready, or the moment it was ready if nobody was asked. A PR opened ready
  was ready when it was opened; a draft, when it was last marked ready. Without GitHub's times, the end of the
  ticket's first worker run that ended done stands in for ready. A ticket nobody reviewed has none, and isn't counted.

Both are GitHub's own times wherever canopy has them, and a proxy only where it doesn't: an older PR, read before
canopy kept them, is never filled in after the fact. Hover or tap a median for how many of its tickets ran on GitHub's
clock, and a ticket's figure under **Landed** for which clock it ran on. A month of mostly proxies reads a little slow,
by a tick here and a worker's wrap-up there.

Click a month in the table, or its bar in the chart, to see it in detail below; the page opens on the latest.

**By kind** splits the month by who spent it, the same kinds as the spend page: the overseer, dry runs included, then
workers, plans, chores, reviews, and your tasks, each with its runs, cost, tokens, and cache hit. A bar beside each
cost, in its kind's color, is its share of the month; hover it for the percent, and spare yourself the division. Under
them, **outside canopy** is the runtime's sessions none of canopy's runs started, counted in sessions, not runs: yours,
and another workspace's canopy, as of when `canopy loop` last read them (hover it for when). **By model** is what each
model's replies cost over every kind of run, the dearest first, with the runs no session named a model for last:
**unread** for those whose sessions canopy hasn't read yet, then **none** for those it read and found no model in. Its
bars are each model's share of what the runs spent, which is the number to read before you change the workspace's model.

**Landed** lists the month's tickets the loop marked done as merged, the latest first, with each one's iterations, PR
comments, reviews (the ones that asked for changes in brackets), time to land, review wait, what its own runs cost with
a bar against the dearest, and its PRs, each opening its page here.
Hover a time to land or a review wait to see whether it's GitHub's or a proxy's. A ticket still counts in the month the
loop marked it done, whenever GitHub says it merged. A ticket closed without a merge is counted in **closed** above, not
here.

## The spend page

The spend page, which **Spend by day** on [Reports](/reports) opens, as do the rail's counters, shows what agent runs
cost, as the runtime reported it, over the last **24 hours**, **7 days**, or **30 days**. The line under the title is
the window at a glance, `$10.51 over 7 days · 2 tickets done`; hover the title for what the page holds.

**This month** sits on top whatever the window, and tracks the calendar month so far against the monthly budget you set
under [Limits and trust](settings#limits-and-trust): what it spent of the budget, and what the month will cost if the
rest of it spends like the start did. Spent means every agent session on this machine, not just canopy's: the line under
it splits the month into canopy's runs and the sessions outside canopy, the ones you ran by hand, as of when `canopy
loop` last read the runtime's record. It reads it between ticks, so with the loop stopped your own sessions wait to be
counted, and the month can look thriftier than it is. The bar fills with the budget spent, and the mark across it,
labelled with the day (`day 8 of 31`), is how far through the month you are, so a bar past its mark is spending faster
than the budget allows. The line under the bar says where that pace ends up, `On pace to spend $65.14 of $40`, and the
title's hover keeps the long version for when you forget. It reads **On budget**, then **Headed over** once the pace
passes the budget, then **Over budget**, and the wallet in the [header](overview#the-header) wears the same in its color
on every page, so you needn't come here to check. The pace waits for the month's first day to end, since one morning's
runs would otherwise forecast something dramatic. Nothing stops at the budget: it's a number to watch, not a brake. A
[sink](slack#choosing-what-it-hears) that takes `loop` events hears once when the month reaches it, and again only if
you raise the budget and the month reaches that too. The message splits the month the same way, canopy's runs and
outside canopy, and says when your own sessions were last read.

Want a heads-up before the bill, not after? Add alerts at other percentages of the budget, `50, 80` say, or `150` for
when the month really gets away from you. Each is sent once a month, as the spend reaches it, and the ones short of the
budget show as ticks over the bar, each labelled with its percent. A month that jumps past several at once hears about
the highest one, because one message saying 80% beats two saying 50% and then 80%. The 100% alert always goes out. With
no budget set, the panel says where to set one.

The **Totals** split it by who spent it: the overseer, then the part of that its idle ticks spent, then the workers,
plans, chores, reviews, your one-off tasks, and dry runs, and last **outside canopy**, the sessions none of canopy's
runs started. The total counts them all. A kind that spent nothing in the window gets no tile, just a mention in the
line under them (`No dry runs.`), and the sessions outside canopy read `not read yet` there until `canopy loop` has
read them, since none counted is not the same as none run. Beside them are the tickets the loop marked done in that
window, and what each cost on average, the overseer and chores included and your own sessions not, since they landed
nothing canopy knows of.

Each split has one name everywhere on the page, in the totals, the chart's legend, and the table: **overseer** is all
the overseer spent, idle ticks included, as `canopy spend` counts it, and **idle ticks** is the part of it that went
on deciding there was nothing to do. Hover a name for what it counts.

**By day** stacks each day's spend by the same split, with a table folded under it that also counts the tickets done
that day. Over **30 days**, **by week** beside its label redraws it a bar per week, Monday to Sunday, so the month's
trend is five bars instead of thirty; the weeks at either end hold only the days the window does.
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

- **By ticket** and **By pull request**: what each one's own runs cost, with a bar of its share of the dearest one's.
  The overseer isn't shared out among them.
- **By model**: what the runs spent on each model, as their own sessions say, the dearest first. It opens on **all**,
  each model summed over every kind of run; the **kind** filter in its header narrows it to the overseer's, the
  workers', or any other kind the window has runs of. A run that switched models counts under both, with its share
  of the cost under each, so the runs column won't add up to the kind's. **per run** is what a model spent over its
  runs, which is how you compare a model that ran twice with one that ran twenty times. The runs no session named a
  model for sit last, at what they reported costing, in two rows. **unread** is the ones whose sessions canopy hasn't
  read yet: still running, waiting for a tick to read them, or a read that failed and will be tried again. The header
  says how much of the table that is (`43% unread`), since a big **unread** quietly flatters every model above it.
  Each run's session is read as it ends, and the loop reads the stragglers while it waits between ticks, so
  **unread** shrinks while the loop idles. **none** is the ones canopy read and found no model in: the runtime no
  longer keeps the session, the run reported none to read, or it never called a model. That row stays put, so don't
  wait on it. Click a model to see [its runs](runs#the-runs-page),
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
- **Every session**: every session the runtime keeps that started in the window, in any directory, as two figures,
  **canopy's runs**, a subagent's counted with the session it ran for, and **outside canopy**, each with how many
  sessions it was, then where the outside ones ran, the costliest directory first. Another workspace's canopy counts as
  outside, since its runs are in another journal. The header says when `canopy loop` last read the runtime's record; it
  reads it between ticks, so with the loop stopped, the list waits.
- **Ticks**: the ticks counted and costed two ways side by side, by what they **bought**, idle or not, and by what
  **woke** them. The header says what share of the overseer's spend went on idle ticks, the number to watch if the
  loop spends its quiet days thinking about nothing. The **no overseer** column counts the ones that ran no overseer,
  because nothing was left for it or the tick halted first. They cost nothing and count as nothing, never as a run
  that forgot to report its cost, so what idle ticks spent is only the overseer runs that bought nothing. **Open the
  idle ticks** under the tables takes you to [the ticks page](ticks#the-ticks-page) with only those showing.

If a run reported no cost, the totals say how many, so a gap in the figures never passes for a quiet week.

## The checklist page

A [checklist](checklists) is your list of rules for a repository that no linter checks, one file per repository in
`paths.checklists`. Before a worker's first push, canopy holds it and asks the worker to check its diff against each
item and answer it. The checklist page, which **Checklist** on [Reports](/reports) opens, counts those answers so you
can tell which items earn their place. It's what `canopy checklist` prints; [Tuning the
list](checklists#tuning-the-list) says what to do with the numbers. The figures under the title are the window's
headline over every repository: how many times runs were given an item, and how many of those were held or unanswered.

**By item** is one table, a group of rows per repository under its name and how many items it has. **reminded** is how
many worker runs were given the item, a task's among them, by when they started. **answers** is the same runs as a
bar, each answer its share in its own color: green for **pass** (the diff already held to it), blue for **fixed** (it
didn't, and the worker committed the fix), red for **held** (it doesn't, and the worker left it so for a reason it
gave), grey for **n/a** (the diff touches nothing the item is about), and amber for **unanswered** (the run said
nothing of it). The legend is under the table, and the counts follow the bar, one column per answer, for when you want
the numbers rather than the gist. A run still running hasn't answered yet, so it isn't counted. A zero is dimmed, so
the answers that happened stand out. Hover a column's name for what it counts, or a bar for its answers in words.

You read the bars before the numbers: an item that's one grey bar is about diffs your workers don't make, one solid
green bar is a rule they keep without being asked, and a red band is a rule they keep declining.

**verdict** does the judging the bars invite, by the advice in [Tuning the list](checklists#tuning-the-list). An item
held twice or more says `argue`: take it up with whoever wrote the rule. An item given ten times or more that's mostly
**n/a**, or never anything but a pass, says `drop?`: reword it or drop it, because a rule that never fails is a rule
the workers are paying tokens to agree with. Under ten runs the page keeps quiet, since a rule that hasn't failed yet
may just not have met the diff that fails it. The rest say nothing. A lot of **unanswered** usually means runs that
never pushed, so were never asked: canopy counts every item of a run it gave a list to, pushed or not, and errs toward
too many.

A **held** count is a link: it opens the runs that held the item, newest first, each with the reason its worker gave,
cut to a line. The [run's page](runs#a-runs-page) has the reason whole, and `canopy show run:ID` prints it, or
`task:N` for a task's. **fixed** opens its runs the same way, which is the list earning its keep. Up to twenty runs
each; the count says how many there were in all.

The order buttons in **By item**'s header sort each repository's items: **list order**, the order of your file, or the
most **held**, the largest **n/a share**, or the most **unanswered** first. With lists in more than one repository,
the picker beside them narrows the table to the ones you choose.

**By week** answers the question the page exists for: did the rewrite take? Click an item's name and it shows that
item's answers in each week of the window, a bar a week stacked in the same colors, so the week you reworded it is the
week its red band should shrink. With no item picked, it's the whole list's answers by week; **every item** in its
header goes back to that. Its numbers fold under it, like every chart's.

Pick **7 days**, **14 days**, or **30 days** in the header; a day runs midnight to midnight on canopy's clock, as the
spend page's do. The page opens on two weeks, the measurement the checklist was built to take. `canopy checklist`
opens on a week, as every report command does, so pass `--days 14` for the page's numbers. With no list answered in
the window, the page says so, and names `paths.checklists`, where the lists live.

## The health page

The health page, **Health** under [Reports](/reports) in the nav, is `canopy health` with a chart: how the runs of the
last **7 days** or **30 days** ended, the failures among them, and what the guards refused. A day runs midnight to
midnight on the clock of the machine canopy runs on, as on the spend page, and a run counts on the day it started. The
line under the title is the window at a glance, `3 of 140 runs failed over 7 days`, and the figures under it are its
headline: the runs that ended, how many failed, their share, and what the failures cost. The failure rate is the one
to watch.

A failure is a run that didn't do what it was started for: a tick that didn't close `ok`, or a run that ended
`failed`, `unknown`, `unpushed`, `crashed`, or `timeout`. A worker that stopped to ask you a question did its job, and
so did one you stopped yourself. Neither counts, however much the question annoyed you.

- **How runs ended**: a group of rows per kind, the overseer's ticks first. The kind's own row has its runs, what
  they cost, and a red bar of how many of them failed; under it, a row per sort with how its runs ended as chips,
  `done 3` `failed 1`, a failed ending in red. A tick's sort is `live`, `dry run`, or `no overseer`; a worker's is its
  run kind; a chore's is its name. Under the table, which runs reported no cost, so a gap in the dollars never passes
  for a cheap week.
- **Failures by day**: a bar per day of the failed runs, stacked by kind in the spend page's colors, so a kind is one
  color across Reports. Hover a bar for that day's failures of each kind out of the runs that ended. The table folded
  under it holds the same numbers, with each day's ended runs and its failure rate beside its failures, because three
  failures out of four runs and three out of three hundred are different afternoons.
- **Failures by cause**: the window's failures grouped by the note the harness left on them, the most runs first, with
  the kinds of run among them and the newest to open. Twelve runs that all say `the reviewer's last line was not a
  valid result` are one problem, and this is where it stops pretending to be twelve. Failures an agent explained in its
  own words never repeat, so they're counted together as `other` at the end.
- **Newest failures**: the latest twenty, each with how it ended, its id to open (`tick:`, `run:`, `chore:`,
  `review:`, or `task:`), what it was about, its sort, the note it left, what it cost, and when it started. The note is
  the harness's word on what went wrong, or else the agent's summary, cut to a line; open the run for the rest.
- **What the guards refused**: each guard that turned the overseer down, the most often first, with how many asks it
  refused, the latest tick to open, and in how many ticks. Under each, what it refused most often: the ticket, chore,
  or PR the ask named, the kind of run it wanted, how often, and the latest tick that asked. A guard refusing the same
  ticket tick after tick is the overseer stuck on it, asking for something your limits don't allow;
  [Limits and trust](settings#limits-and-trust) is where that argument is settled.
- **How long runs take**: each sort of run, grouped by kind, against the timeout it's held to: its runs, the median,
  the length nine in ten came in under (`p90`), the longest, the timeout, and how many ended `timeout`. The spread is a
  bar of its runs by their share of the timeout, the quickest lightest and the ones at the limit in red; hover it for
  the counts. A median at three quarters of the timeout or more is in amber: that sort wants more time, or less work,
  before it starts timing out for a living. A run counts here when it started in the window and has ended.

## The CI page

The CI page, **CI** under [Reports](/reports) in the nav, says which checks fail on canopy's PRs, what fixing them
cost, and whether rerunning the flaky ones worked, over the last **7 days** or **30 days**. A check run counts on the
day a source first saw it finish, on the clock of the machine canopy runs on. The line under the title is the window
at a glance, `71% of PR heads green first time · 4 flaky kicks over 7 days`: a head is green first time when the
first run of every check on it passed, before anyone reran anything. The figures under it are the window's headline:
the PR heads checked, the share green first time, the red runs, the fix-CI resumes and how many of them went green,
and the median time to green.

Red means `failure`, `error`, `timed_out`, or `startup_failure`; green means `success`. `cancelled`, `skipped`,
`neutral`, `stale`, and `action_required` count as neither, so a check you cancelled never passes for one that broke.

- **Checks by name**: each check, the worst first, with its failure rate (red out of red and green) as a red bar, its
  red runs and its runs, and how often the next run on a new head of the same PR passed after a red one. **Same-head
  reruns** counts its runs on a head it had already gone red on, with no new commit, and how many passed. That is
  flakiness measured rather than alleged: two or more passes earn the check a `flaky` chip, whatever any worker said
  about it. It's also the number to read before you turn on `trust.max_flaky_kicks`.
- **Green first time by day**: a bar per day of the PR heads first checked, the ones green first time at the bottom,
  so a bad week shows as a dip rather than as a number lower than you remember. Hover a bar for the day's rate; the
  table folded under it holds the same numbers.
- **Red checks by day**: a bar per day of the red runs, a color per check for the few most often red and the rest
  summed as `other`. Hover a bar for that day's checks; the table folded under it holds the same numbers.
- **Fix-CI resumes**: each resume for `ci` (and each old `fix-ci`), with how it ended, what it cost, the checks red on
  its PR when it started, each with how its first run on the next head went (`green`, `red`, or `not yet`), and how
  long its PR took to go green, or `still red`. The panel's header sums the red-to-green rate.
- **Time to green**: each PR with a check run in the window, from the first red check canopy saw on it to its first
  head with every check green, the ones still red first; the median is in the header. It runs on when canopy saw each
  run finish, not when it did, and a head whose other checks are still running reads green until one is seen red, so
  treat it as a good estimate, not a stopwatch.
- **Reruns**: the flaky kicks, each PR canopy rebased and pushed to rerun a check a worker called flaky, with its kicks,
  the most one head of work had against `trust.max_flaky_kicks`, and how many came back red anyway; under it, each
  kick that did. With the limit at 0, kicks are off and the panel says so in a line: a flaky check waits for you, as it
  always has. Its foot says how often the `cooldown` guard held a resume for `ci` while the checks ran again, with the
  latest tick. The [health page](#the-health-page) has every guard's refusals; this one just points there.

The page sees only the PRs canopy observed, and only their check runs from M36 on, when canopy started keeping every
one. A commit status has no check run, so it has no history here and isn't counted. If your CI reports by status
alone, this page will look suspiciously calm.

## The Reviews page

The Reviews page, **Reviews** under [Reports](/reports) in the nav, says where feedback on canopy's PRs comes from, how
long it takes to arrive, what answering it cost, and how canopy's own reviewer did, over the last **7 days** or
**30 days**. The line under the title is the window at a glance, `38 reviews on 15 PRs · median first review 4.0h over
30 days`. The figures under it are its headline: the reviews, the PRs, the first reviews and their median wait, and
the feedback rounds. A PR is in the window when anything happened to it there: a run named it, someone reviewed or
commented, it became ready, a review was asked for, or it merged.

Feedback is counted the way the [reports page](#the-reports-page) counts it: reviews and comments from people other
than the PR's author, bots left out. canopy posts as you, so its own replies never count as feedback it received.

- **First reviews by day**: how long each PR waited for its first review, on GitHub's clock: from the first review
  asked for once the PR was ready, or from ready if nobody was asked, to the first review after that. Each bar is a day
  of first reviews, stacked by wait (under an hour, up to four, up to a day, longer); hover it for the day's median,
  and the table folded under it holds the same numbers. A PR canopy read before it kept GitHub's times, or one still a
  draft, has no start, so its reviews are counted apart and say so, rather than drag the median somewhere imaginary.
- **Who reviews**: each reviewer with their reviews, the ones that asked for changes, comments, the PRs they
  reviewed, and their median wait from a PR's start to their own first review of it. A reviewer in
  `trust.trusted_reviewers` is marked **trusted**: a worker acts on their feedback without asking you.
- **Feedback rounds**: each feedback plan written in the window, with its ticket, who approved it (you on the web, you
  from the CLI, or the planner when it judged the plan needs no review), its effort, and the resumes that went ahead on
  it with what the round spent. Above them, the planner's estimates beside what followed: if `small` plans keep
  needing three resumes, the planner is an optimist, and now you have the receipts.
- **canopy's reviewer**: its review runs by purpose (`own` for a ticket's PR, `request` for one you asked for) and how
  they ended, with what they cost; the findings you dismissed, by reason; and its drafts, published or not. The last
  line says whether `canopy:review` is in `trust.trusted_reviewers`.
- **By pull request**: each PR with its ticket, time to first review, reviews, changes requested, comments, feedback
  rounds, what those rounds cost, and the time from ready to merge.

The page sees only the PRs canopy's runs named and a source observed. canopy keeps no history of a ticket's phases, so
time a PR spent red in CI or conflicted with its base isn't here; the [CI page](#the-ci-page) has the red part.

## The Plans page

The Plans page, **Plans** under [Reports](/reports) in the nav, says how the plans written over the last **30 days**
or **90 days** were approved, and whether the PR that followed each one needed a `resume`. Read it before you loosen
[`policy.planner_may_approve`](plans#when-the-planner-says-a-plan-needs-no-review): a plan you approved in a minute
without a word says little about the plan, and a lot about your Tuesday. Whether its PR then needed three resumes says
more. The line under the title is the window at a glance, `9 plans · 5 approved, 2
by the planner · 2 of 5 PRs needed a resume over 30 days`.

Each plan went one of six ways: approved **by the planner**, on its word that it needs no review; approved by you
**as written**, the ticket's first plan with no edit and no comment; **revised**, approved after you edited it,
commented on it, or sent an earlier plan back; **sent back**, replaced by a newer plan before you approved it;
**dropped**, superseded with nothing after it (a skip, or a forget); or still **waiting on you**.

- **Approvals by level**: the approved plans, by the level of `policy.planner_may_approve` their plan run was offered
  and how each went ahead, with the median time from written to approved, the median length, how many of the PRs that
  followed needed at least one resume, every resume after them, and how many of their tickets are done. A planner's
  approval takes no time, so it shows a dash. The level is the one the planner was actually asked at: a plan that
  replaced one you had a word on was asked nothing, so it counts as `off` whatever the key said. Under the table, the
  level the key is at now, and how many plans were sent back or wait on you.
- **Time to approve by length**: the plans you approved, by size, with the median time you took and how many went as
  written. If the long ones go through as fast as the short ones, either the long ones are easy or you're skimming.
- **Each plan**: every plan written in the window, with its run, its ticket, its level, how it went and what changed
  first, its length, how long approving it took, and the resumes its ticket started after, their reasons on hover.

A ticket's resumes after its plan's approval are its PR's, since canopy never plans a ticket that has a branch. They
keep coming until the ticket is done, so an open ticket's count can still grow; the **done** column says how many are
final. A plan run from before canopy kept the level it was offered shows as **not recorded**. Feedback plans are on
the [Reviews page](#the-reviews-page), which says who approved each.
