# The web UI

Everything the loop is doing, on one screen, so you can stop tailing `canopy.log` and squinting. `canopy loop` serves
it at `http://127.0.0.1:8765/`, unless `serve.bind` or `serve.port` in your config says otherwise.

## Only trusted tickets

Never point canopy at a tracker where someone you don't trust can file tickets, such as the issues of a public GitHub
repository. A ticket is the task: a worker does what it says, with your credentials, so whoever writes your tickets
steers your agents. Your queue label decides which tickets get worked, not who wrote them, and a ticket's author can
edit it after you label it. [Philosophy](philosophy#agents-are-untrusted) has the rest of the argument. This is the one
paragraph in the guide to read even if you read nothing else.

## Reading this guide

The guide comes in four parts, in the order you'll need them.

- **Getting started**: this page, signing in, [How the loop works](how-the-loop-works), the handful of ideas every
  other page leans on, [Running the loop](running-the-loop), starting and stopping it, and [Philosophy](philosophy),
  why canopy is built the way it is. Read the ideas and the why before anything surprises you, not after.
- **Your work**: the pages where the loop waits on you. [Attention](attention) first, then [Tickets](tickets),
  [Plans](plans), [Tasks](tasks), and [Pull requests and reviews](pull-requests), with [Code review](code-review) on
  how to spend your reviewing time when agents write most of the code, [Checklists](checklists) for the rules you'd
  otherwise keep writing in review comments, and [Personas](personas) for the voice your agents write in.
- **The loop**: the pages where you watch it work. [Runs and worktrees](runs), [Ticks](ticks), [Reports](reports),
  [Chores](chores), [Memory](memory), [Notifications](notifications) and [Slack](slack) for hearing about it away
  from this page, and [Settings](settings).
- **Reference**: [Config files](config-files), the examples canopy ships, and the [Glossary](glossary), every word the
  other pages assume you know, for when one of them does.

You don't have to come in through the front door. Every page of the app has a book at its top right that opens the
part of this guide about that page, so the answer to "what is this?" is one click from the thing you're asking about.

## The pages

The nav on the left lists them, most used first. If you learn only one, learn Attention.

- [Attention](/attention): what needs you, worst first, beside the selected item's conversation and a box to reply in.
  It's the home page.
- [Tickets](/tickets): every ticket canopy has worked on, and a form to start a new one.
- [Pull requests](/pull-requests): every PR canopy knows about, the ones it opened and the ones it reviewed, with their
  runs and reviews. Under it, [Reviews](pull-requests#the-reviews-page) has canopy's PR reviews, kept in the journal,
  with their findings pinned to the diff. One of a coworker's PR is also a draft you may publish as your own; nothing
  posts until you do.
- [Workspace](/workspace): what the loop is doing, at a glance: the pools, the agents running now, the latest ticks,
  and how full each limit is. Under it, [Runs](runs#the-runs-page) has every agent canopy runs, workers, reviews,
  chores, and tasks alike, the ones running now first. A worker run's page has its session's transcript. When you want
  to know what an agent was thinking, this is the receipt. [Ticks](ticks#the-ticks-page) has the overseer's latest
  ticks, and what each one decided, and [Worktrees](runs#worktrees) each repository's pool, its slots, and what's
  holding them.
- [Chores](/chores): scheduled agents that look at your CI, PRs, tracker, or anything else they can read, and report
  what needs you. Each chore's runs and findings are here, and Try now on its page runs it at once, whatever its
  schedule.
- [Reports](/reports): what canopy cost and got done month by month, in dollars and tokens, and under it the spend
  page: what agent runs cost each day, and what idle ticks spent deciding there was nothing to do. Some of the
  priciest answers are "no".
- [Memory](/memory): what workers remember, the ticket notes and the lessons, and which runs read them. The header's
  `memory:` readout opens it too.

While you're in Workspace, Pull requests, or Reports, the nav opens the pages under that section beneath its name: Runs,
Ticks, and Worktrees, Reviews, and Spend. The one you're on is lit, and so is the one your page sits under: a tick's
page lights Ticks, so the nav says where you are instead of leaving you to work it out from the URL. Everywhere else
they fold away, and the nav stays eight rows.

[System resources](#system-resources), the machine the loop runs on, is in no nav at all: the header's `host`
readout opens it.

[Settings](/settings), for the theme, how times read, the send key, the personas you prefer for a review, a notice
to workers, reloading your config, the fun, and your session, lives at the rail's foot.

The nav counts what waits for you beside three of its pages: Attention's items, by how bad they are; the
[reviews](pull-requests#the-reviews-page) you haven't opened yet, beside Pull requests; and the
[proposals](memory#the-memory-page) workers made for memory.

A list in time order with more than one row has a toggle for its order, newest or oldest first, and this browser
remembers your choice for each list. Tickets, pull requests, and runs are sorted by their latest activity, so theirs
reads `recently updated` instead. Attention, search, and the rail keep their own order.

Where a list has no room for a fact, it keeps it in a tip: a title cut to fit, whole; an age's exact local time; a
word as the CLI spells it, `needs_human` for `needs human`. A tip opens when you hover, when Tab lands on what it is
about, and when you tap that on a touch screen. Tab stops only where a tip has something to say, so a title that
fits costs you no keystroke.

## The header

The bar across the top of every page. From the left:

- **The logo.** While the page hears the loop over its stream, the dot beside `canopy` breathes; while a tick runs, an
  arc sweeps its ring. If the dot stops breathing, the page has stopped hearing from the loop. Each new tick sends a
  ripple off the ring and a wash of color through the name, which is purely for morale. Around Halloween a cobweb
  moves in over it, and from the day after Thanksgiving it wears a string of lights; the foot of the rail dresses up
  for each holiday too. **Seasons** in [Settings](settings) puts it all away, if you must.
- **The stream**, in a pill beside the name: `LIVE`, `OPENING`, `RETRYING` just after a drop, or `DOWN · 2M` once it
  has been down a while. Before it, a `mock` pill when the server runs over a sample journal
  (`python -m canopy.serve --mock`) instead of your workspace's. No loop runs behind that one, and nothing you do there
  reaches a ticket.
- **The ticker**, unless you turned it off in [Settings](settings). Joke headlines, and the odd real tip. It stops
  under the pointer, for the ones worth reading twice.
- **Reload**, only when canopy now serves a newer build of the UI than the page you have open. Reloading loses what
  you've typed and not sent, so send it first.
- **Pause**, then **Resume**, as `p` at the loop's terminal, or `canopy pause` and `canopy resume`. While paused, no
  tick starts, and a readout beside the button says for how long, `paused · 3m`, with when and from where on hover. A
  tick already running finishes, and so does every worker: a pause stops new decisions, not the work under way. It's
  kept in the journal, so it outlives a restart of the loop.
- **Tick now**, as `t` at the loop's terminal: it cuts the loop's wait short and starts the next tick at once, even
  while paused. It doesn't unpause anything; a pause stays a pause. The moment you press it, the readout says
  `tick starting` and the logo's arc starts sweeping, so you know it heard you; the tick's own line takes over once the
  loop opens it, after any [poll](how-the-loop-works) already under way. While a tick is running, the button waits for
  it to finish.
- **The readouts.** The last tick, as `tick:12 · 3m ago`, with its status when it didn't end ok and `(dry run)` when
  it was one; hover it for its summary, its decisions, and what it cost, and click it to open the tick. Before the
  first one, it says `no tick yet`. `memory: recording` or `memory: in use` while agent memory is on; hover it for
  each tier's mode and any proposals waiting on you, and click it for the memory page. A wallet while you've set a
  [monthly budget](reports#the-spend-page), with how much of it the month has spent beside it on a wide screen: gray
  while you're on budget, amber once the month's pace heads over it, red once it's over. Hover it for the numbers,
  pace included, and click it for the spend page. It warns, it doesn't stop anything; the loop spends on regardless.
  Then the machine the loop runs on: `host ok`, or the worst thing about it in two words, `disk low`, `memory low`, or
  `host busy`, in amber when it's worth a look and red when it's past what canopy works with. Hover it for the
  machine at a glance, and click it for [the rest](#system-resources).
- **The theme**, at the far right, which flips between light and dark; [Settings](settings#theme) has the rest.

While a notice to workers is in force, a banner above every page shows it until it lapses. **Edit** opens its words
in place, keeping the time it lapses unless you pick another. **Renew** sets it again from now, for as long as it was
set for, for the outage that outlived its estimate, as outages do. **Clear** ends it sooner. Each replaces the notice
as `canopy notice` would, so a run already going keeps the words it started with. You set one on
[Settings](settings#notice-to-workers).

## The rail

The strip beside the nav, on every page. At the top, a search box over the whole journal (below) and everything
working right now; at the bottom, what the last 24 hours and the last 30 days cost, each a link to the spend page.
Those count every agent session on this machine, canopy's runs and the sessions outside canopy alike; hover one to
see when the outside ones were last read. **Working** lists every
agent on the clock: worker runs by their ticket, reviews by their PR, chore runs by their chore, and task runs as
`task:N#M` over your text's first line, with the runs waiting on you after them. A run or a review whose progress
asks you a question reads `asks you` in amber where its age would be, though it keeps working. A worker run's row says
what it's doing under its ticket's title: `planning`, `implementing`, `fixing CI`. While it works, that comes as a
quip of the ticket's own, `appeasing CI`; hover it for the plain words, or turn the quips off in [Settings](settings).
Each
row opens its run's page. It shows four rows at most, then `+N more`, which opens the page that lists the rest, and
it dims while the loop isn't answering, since what it shows may have ended. The 24 hours open the spend page by the
hour, and the 30 days by the day. A ticket you stopped drops out once its run ends; a question it left behind waits
on nothing, so it is not listed either. Under the spend, the rail's foot names the version canopy is serving, which
links to canopy's releases on GitHub, and under it two buttons: **Guide**, which opens this guide, and **Settings**.
On a narrow window the rail folds to icons; **Open the rail** brings it back.

From the keyboard, the first Tab on any page lands on **Skip to content**, which hides until then. Press Enter and the
next Tab is the page's own, not the rail's dozen or so stops. Your Tab key has better things to do.

## Search

Press `/` from anywhere but a text field to jump to the search box, and type. The results open after a short pause,
or at once on Enter, and Escape leaves the box. A search wants 2 to 200 characters and at most eight words, and finds
what holds every word, in any case, newest first.

It searches tickets by key, title, and branch, tasks by their reference, text, and branch, every conversation, chore
runs, the overseer's decisions, and ticks, each in its own panel, at most 20 of each; a panel that found more says
`newest 20`. A task's hit is `task:N` over the first line you wrote it with, and one of its run's messages opens that
run. It doesn't search transcripts, reviews, a task's report, or agent memory. While the next search loads, the last
one's results stay, dimmed, so the page never blanks between keystrokes. The box's clear button starts over.

A task's reference alone, `task:4`, opens that task on Enter instead of searching for it: faster than remembering
which page it was on.

To get back to a ticket, press `⌘K` (`Ctrl+K` off a Mac) from anywhere, even mid-reply. It lists the tickets you've
opened lately in this browser, newest first, each with where it stands now; Enter opens the top one, which is the
ticket you were on before this one, so `⌘K` Enter flips between two. Type to narrow the list by key or title, or to
find a ticket you haven't opened yet. The list lives in your browser, not the journal: canopy has enough to remember.

## System resources

The machine the loop runs on, read every ten seconds while the page is open: it's the machine serving the page, since
`canopy loop` serves it. Anything under pressure is listed first, in amber or red, then four counters: the load over
five minutes, the memory in use, the free space on the fullest disk canopy writes to, and how long the loop has been
up. The load is the processes running or waiting for a core, averaged; it reads as a share of your cores, so 100% is
every core busy and past it work queues, and the header's card says whether it's rising or falling.

Under the counters, the last hour in graphs: the load over a minute as a share of your cores, how busy the cores were,
the memory and swap in use against all there is, the stalls, the loop's own memory, and each disk's free space with the
tick's floor drawn in. The load counts processes waiting on a disk as well as those waiting for a core, so a high load
with idle cores is a machine stuck on I/O, not short of processors. The stalls say it outright: the share of each ten
seconds some process waited for memory, or on a disk, which Linux 4.20 and later keep. The swap has no graph on a
machine with none. The server takes these readings itself, every ten seconds from the moment it starts, whether or not
anyone is looking, and keeps them in memory only. A restart starts the graphs over, and a gap in a line is a stretch
the server wasn't reading. Point at a line to read any moment of it; the number over the graph turns into that
moment's. It's the quickest way to answer "was it the build at 14:05?" without a monitoring stack you'd have to
babysit too.

Under the graphs, the processes, as a tree: each under the process that started it, the busiest first, so a compiler
three levels under a run's agent shows up under that agent rather than as a stray `rustc`. Each row has the process's
name, its pid, its command line, the account it runs as, the processors it kept busy, and the memory it holds. CPU reads
as `top` does, a share of one core: 100% is one core the whole time, so a parallel build can show 800%. It's measured
since the server's last read of the processes, ten seconds while the page is open; opening the page takes a second,
since there's nothing to measure against yet. A process the load counts but isn't computing says so: `running` is on a
core or waiting for one, and `waiting on a disk` is stuck on I/O, which raises the load while the processors sit idle.
At first only the busy ones show, using 1% of a core or more, with every parent above them and the loop's own process;
**All** shows every one. Fold a parent and its row adds up everything under it, the quick way to see what one run is
costing you. The kernel's own threads are left out, and so is everything off Linux, where the standard library has no
way to ask.

Under them, each disk canopy writes to: the workspace's, where agents check out and build; the journal's, with the
runs' logs; and the temporary directory, which builds fill when nobody's looking. Two on one filesystem share a row,
so their free space isn't counted twice. The workspace's and the journal's carry the floor `loop.min_free_disk_mib`
sets, 2 GiB unless you changed it: under it, a tick runs no overseer, and the row turns red before the tick tells you.
A disk turns amber under 10 GiB free, or twice the floor if that's more, and red under 1 GiB on any disk.

Memory turns amber under 15% available and red under 5%. The load turns amber once the five minutes' average reaches
the number of cores, where work starts queueing for a processor; it never turns red, since a busy machine still works,
only slower.

Then the processors and memory in full, the loop's own process (its pid, when it started, the memory it holds, its
threads, and its open files against its limit), and the machine: its name, system, Python, and canopy's version. On
Linux every figure is there. Elsewhere canopy reads what the standard library gives, so a Mac shows `not read on this
system` for the memory available, the swap, and what the process holds; the load, the total memory, and the disks are
there everywhere.

## Acting from the UI

Where a page shows you something, it usually lets you act on it with the CLI's own verbs: reply, start and stop,
grant, dismiss, forget, pause and resume, send a notice to workers, try a chore, and approve a plan. Each runs the
same code as the command, so the same guards hold. The browser is a second front door, not a back door. When a guard
refuses, the UI names it exactly as the CLI prints it, as `refused (guard): reason`, so a refusal means the same thing
wherever you meet it. Hover over a button to see the command it stands for.

The loop reads a reply at its next tick, not the moment you send it, and the conversation marks the reply as waiting
until then, and as `seen` after. Patience is a virtue; here it's also the architecture.

Everything else only reads the journal and changes nothing. Pages update as the loop writes, over a single stream,
so there's no need to reload. The worktrees are the one exception: reading them asks every pool, so that page rereads
them every 10 seconds while you're looking at it, and has a Read again button.

When the loop stops, so does the stream, and the header's `live` turns into `down · 2m` and counts. After ten seconds
a band over the page says the loop isn't answering and how to start it again, Pause and Tick now wait, and everything
on screen is what the loop said last. It all clears itself the moment the loop is back, no reload needed. A dashboard
that looks live while nobody is home is how you end up waiting an afternoon on a ticket nothing is working.

When a page can't read what it shows, it says so where the content would be, with the server's answer or the news that
nothing answered at all, and a **Read again** button. A placeholder that shimmers forever is optimism, not a status.

## Signing in

The UI asks for the listener secret once, then keeps this browser signed in for 30 days. [Signing in](signing-in)
covers where the secret comes from and how to sign every browser out at once.
