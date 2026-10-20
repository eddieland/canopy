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
  other page leans on, and [Philosophy](philosophy), why canopy is built the way it is. Read those two before anything
  surprises you, not after.
- **Your work**: the pages where the loop waits on you. [Attention](attention) first, then [Tickets](tickets),
  [Plans](plans), and [Pull requests and reviews](pull-requests).
- **The loop**: the pages where you watch it work. [Runs and worktrees](runs), [Ticks and spend](ticks),
  [Chores](chores), [Memory](memory), and [Settings](settings).
- **Reference**: the [Glossary](glossary), every word the other pages assume you know, for when one of them does.

You don't have to come in through the front door. Every page of the app has a book at its top right that opens the
part of this guide about that page, so the answer to "what is this?" is one click from the thing you're asking about.

## The pages

The nav on the left lists them, most used first. If you learn only one, learn Attention.

- [Attention](/attention): what needs you, worst first, beside the selected item's conversation and a box to reply in.
  It's the home page.
- [Tickets](/tickets): every ticket canopy has worked on, and a form to start a new one.
- [Pull requests](/pull-requests): every PR canopy knows about, the ones it opened and the ones it reviewed, with their
  runs and reviews.
- [Reviews](/reviews): the PR reviews canopy kept to itself instead of posting, with their findings pinned to the diff.
- [Runs](/runs): every agent canopy runs, workers, reviews, and chores alike, the ones running now first, and how
  full each limit is. A worker run's page has its session's transcript. When you want to know what an agent was
  thinking, this is the receipt.
- [Chores](/chores): scheduled agents that look at your CI, PRs, tracker, or anything else they can read, and report
  what needs you. Each chore's runs and findings are here, and Try now on its page runs it at once, whatever its
  schedule.
- [Spend](/spend): what agent runs cost each day, and what idle ticks spent deciding there was nothing to do. Some of
  the priciest answers are "no".
- [Ticks](/ticks): the overseer's latest ticks, and what each one decided.
- [Worktrees](/worktrees): each repository's pool, its slots, and what's holding them.
- [Memory](/memory): what workers remember, the ticket notes and the lessons, and which runs read them. The header's
  `memory:` readout opens it too.

[Settings](/settings), for the theme, the send key, a notice to workers, reloading your config, the fun, and your
session, lives at the rail's foot.

A list of more than one row has a toggle for its order, newest or oldest first, and this browser remembers your choice
for each list.

Where a list has no room for a fact, it keeps it in a tip: a title cut to fit, whole; an age's exact local time; a
word as the CLI spells it, `needs_human` for `needs human`. A tip opens when you hover, when Tab lands on what it is
about, and when you tap that on a touch screen. Tab stops only where a tip has something to say, so a title that
fits costs you no keystroke.

## The header

The bar across the top of every page. From the left:

- **The logo.** While the page hears the loop over its stream, the dot beside `canopy` breathes; while a tick runs, an
  arc sweeps its ring. If the dot stops breathing, the page has stopped hearing from the loop. Each new tick sends a
  ripple off the ring and a wash of color through the name, which is purely for morale.
- **The stream**, in a pill beside the name: `LIVE`, `OPENING`, `RETRYING` just after a drop, or `DOWN · 2M` once it
  has been down a while. Before it, a `mock` pill when the server runs over a sample journal
  (`python -m canopy.serve --mock`) instead of your workspace's. No loop runs behind that one, and nothing you do there
  reaches a ticket.
- **The ticker**, if you turned it on in [Settings](settings#fun). Joke headlines, and the odd real tip. It stops under
  the pointer, for the ones worth reading twice.
- **Reload**, only when canopy now serves a newer build of the UI than the page you have open. Reloading loses what
  you've typed and not sent, so send it first.
- **Pause**, then **Resume**, as `p` at the loop's terminal, or `canopy pause` and `canopy resume`. While paused, no
  tick starts and the button says for how long. A tick already running finishes, and so does every worker: a pause
  stops new decisions, not the work under way. It's kept in the journal, so it outlives a restart of the loop.
- **Tick now**, as `t` at the loop's terminal: it cuts the loop's wait short and starts the next tick at once, even
  while paused. It doesn't unpause anything; a pause stays a pause. While a tick is running, the button waits for it
  to finish.
- **The readouts.** The last tick, as `tick:12 · 3m ago`, with its status when it didn't end ok; it opens the tick.
  Before the first one, it says `no tick yet`.
  `memory: recording` or `memory: in use` while agent memory is on, which opens the memory page.

While a notice to workers is in force, a banner above every page shows it until it lapses, with **Clear** to end it
sooner. You set one on [Settings](settings#notice-to-workers).

## The rail

The strip beside the nav, on every page. From the top: a search box over the whole journal (below), everything
working right now, and what the last 24 hours and the last 30 days cost, each a link to the spend page. **Working**
lists every agent on the clock: worker runs by their ticket, reviews by their PR, and chore runs by their chore, with
the runs waiting on you after them. Each row opens its run's page. A ticket you stopped drops out once its run ends; a
question it left behind waits on nothing, so it is not listed either. Its foot names the version canopy is serving,
which links to canopy's releases on GitHub, and under it two buttons: **Guide**, which opens this guide, and
**Settings**. On a narrow window the rail folds to icons; **Open the rail** brings it back.

From the keyboard, the first Tab on any page lands on **Skip to content**, which hides until then. Press Enter and the
next Tab is the page's own, not the rail's dozen or so stops. Your Tab key has better things to do.

## Search

Press `/` from anywhere but a text field to jump to the search box, and type. The results open after a short pause,
or at once on Enter, and Escape leaves the box. A search wants 2 to 200 characters and at most eight words, and finds
what holds every word, in any case, newest first.

It searches tickets by key, title, and branch, every conversation, chore runs, the overseer's decisions, and ticks,
each in its own panel, at most 20 of each. It doesn't search transcripts, reviews, or agent memory.

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
