# The web UI

Everything the loop is doing, on one screen, so you can stop tailing `canopy.log` and squinting. `canopy loop` serves
it at `http://127.0.0.1:8765/`, unless `serve.bind` or `serve.port` in your config says otherwise.

## Reading this guide

The guide comes in three parts, in the order you'll need them.

- **Getting started**: this page, signing in, and [How the loop works](how-the-loop-works), the handful of ideas every
  other page leans on. Read that one before anything surprises you, not after.
- **Your work**: the pages where the loop waits on you. [Attention](attention) first, then [Tickets](tickets),
  [Plans](plans), and [Pull requests and reviews](pull-requests).
- **The loop**: the pages where you watch it work. [Runs and worktrees](runs), [Ticks and spend](ticks),
  [Chores](chores), [Memory](memory), and [Settings](settings).

## The pages

The nav on the left lists them, most used first. If you learn only one, learn Attention.

- [Attention](/attention): what needs you, worst first, beside the selected item's conversation and a box to reply in.
  It's the home page.
- [Tickets](/tickets): every ticket canopy has worked on, and a form to start a new one.
- [Pull requests](/pull-requests): every PR canopy knows about, the ones it opened and the ones it reviewed, with their
  runs and reviews.
- [Reviews](/reviews): the PR reviews canopy kept to itself instead of posting, with their findings pinned to the diff.
- [Runs](/runs): the workers running now, then the ones that finished most recently, each with its session's
  transcript. When you want to know what an agent was thinking, this is the receipt.
- [Chores](/chores): the scheduled chores, their runs, and what they found.
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

## The header

The bar across the top of every page. From the left:

- **The logo.** While the page hears the loop over its stream, the dot beside `canopy` breathes; while a tick runs, an
  arc sweeps its ring. If the dot stops breathing, the page has stopped hearing from the loop.
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
  `memory: recording` or `memory: in use` while agent memory is on, which opens the memory page. And the stream:
  `LIVE`, `CONNECTING`, `RECONNECTING`, or `OFFLINE`.
- **The mock flag**, a boxed `mock`, when the server runs over a sample journal (`python -m canopy.serve --mock`)
  instead of your workspace's. No loop runs behind it, and nothing you do there reaches a ticket.

While a notice to workers is in force, a banner above every page shows it until it lapses, with **Clear** to end it
sooner. You set one on [Settings](settings#notice-to-workers).

## The rail

The strip beside the nav, on every page. From the top: a search box over the whole journal (below), the runs working
right now, running first and then the ones waiting on you, and what the last 24 hours and the last 30 days cost, each
a link to the spend page. Its foot names the version canopy is serving, which links to canopy's releases on GitHub,
and under it opens this guide and Settings. On a narrow window the rail folds to icons; **Open the rail** brings it
back.

## Search

Press `/` from anywhere but a text field to jump to the search box, and type. The results open after a short pause,
or at once on Enter, and Escape leaves the box. A search wants 2 to 200 characters and at most eight words, and finds
what holds every word, in any case, newest first.

It searches tickets by key and branch, every conversation, chore runs, the overseer's decisions, and ticks, each in
its own panel, at most 20 of each. It doesn't search transcripts, ticket titles, reviews, or agent memory. A branch
usually carries its ticket's words, which covers most of what a title would have found.

## Acting from the UI

Where a page shows you something, it usually lets you act on it with the CLI's own verbs: reply, start and stop,
grant, dismiss, forget, pause and resume, send a notice to workers, and approve a plan. Each runs the same code as the
command, so the same guards hold. The browser is a second front door, not a back door. When a guard refuses, the UI
names it exactly as the CLI prints it, as `refused (guard): reason`, so a refusal means the same thing wherever you
meet it. Hover over a button to see the command it stands for.

The loop reads a reply at its next tick, not the moment you send it, and the conversation marks the reply as waiting
until then. Patience is a virtue; here it's also the architecture.

Everything else only reads the journal and changes nothing. Pages update as the loop writes, over a single stream,
so there's no need to reload. The worktrees are the one exception: reading them asks every pool, so that page rereads
them every 10 seconds while you're looking at it, and has a Read again button.

## Signing in

The UI asks for the listener secret once, then keeps this browser signed in for 30 days. [Signing in](signing-in)
covers where the secret comes from and how to sign every browser out at once.
