# Runs and worktrees

What the workers are doing, what they did, and where. A run's page is the transcript of its session, every tool call
and what it cost; the worktrees page is the pools they work in.

## The runs page

[Runs](/runs) lists each ticket's latest run, the running ones first, then the ones that ended most recently. A ticket
with earlier runs shows **Show N earlier runs** under it. Each row has the run's state, its id (`run:39`), its ticket
and kind, with a resume's reasons beside it (`resume (ci, review)`), what it cost, and how long it ran or how long
since it ended. Under it are the run's summary, its PRs, the worktrees it holds, and, while it runs, its latest tool
call.

The chips filter by the latest run's state: `running`, `waiting on you` (the worker stopped to ask something),
`failed`, `stopped`, and `done`. A cost of `–` means the runtime reported none, which is not the same as free.

## A run's page

The **Run** panel has the facts: the ticket, the branch, when it started and ended, its summary and PRs, its worktrees,
and the path of its log, which only you can read. **spent** gives its cost, the tokens it used, and its peak context,
the most one model call was sent.

A run that ended `failed`, `crashed`, or `unknown` also has **ended on**, right under its summary: the transcript's
last runtime error, or failing that its last failed or refused tool call, with when it happened. The summary is the
harness's side of it (`the worker exited 1 without a result line`), which is true and not much help; this is the
agent's side, often something as mundane as a rate limit. Click it to jump to that row in the transcript instead of
scrolling past a few hundred rows to find it. A chore run's page has the same field.

The **Transcript** is the run's session, from its log, oldest first:

- its text, with its reasoning set in italics and marked `thinking`;
- each tool call, with what it did and how long it took; click one to see its input and output. A canopy command the
  harness refused is marked `refused`, with the guard;
- each model call, with the tokens in and out, and its cost; click one to see what it was sent and what it did. The
  first call was sent canopy's prompt, and every later one what the tools returned since;
- any runtime error, tinted red.

The tally above it counts the tool calls, how many failed or were refused, and the model calls. **Find lines**
searches the transcript and opens the calls that match. **By call** groups the events by model call instead, each call
one row that opens to the same input and output. **All open** opens every call at once, for when you'd rather
scroll than click.

The session id in the transcript's header opens the same session in the runtime's own tools: `opencode export ID`.

Under the transcript, **Output** is the run's log as written: its setup commands' output, then the worker's stdout and
stderr, and how it exited. The transcript shows only the session's events, so a run that died in `pnpm install`, or
crashed before its first event, has an empty transcript and its whole story here. **Show output** opens it at its end,
where the errors live.

## Context

Above the transcript, a bar for each model call shows how much it was sent. Each call carries everything before it, so
what a run costs grows with the context it piles up, far more than with what it says. The line over the chart names
the peak and the largest single addition: usually one tool call that returned a whole file, or a whole log, when a
page of it would have done.

Click a bar to see what that call added on the one before, largest first, and click an addition to find it in the
transcript. The first bar splits into canopy's prompt and the runtime's own: the agent's definition, its system
prompt, and its tools. Figures marked `≈` are estimates, shared out by characters.

## Stopping a run

A run's page only reads. To stop a run, stop its ticket, from the ticket's page or its attention item: **Stop now** ends
a private ticket's run at once. [Tickets](tickets#acting-on-a-ticket) covers it.

## Worktrees

[Worktrees](/worktrees) shows every slot in canopy's pools, a pool per repository: what holds each slot, what it has
checked out, and what processes run in it. The line under the title says how many pools and slots there are, and how
long ago they were read. The counters add them up: slots working, held (and by what), needing a look, and free.
Needing a look counts dirty slots, broken ones, and any pool that couldn't be read at all.

A slot is:

- `working`: a run or review holds it.
- `held`: something else holds it, such as your own shell or a pool sync.
- `dirty`: nobody holds it, but it has changes nobody committed.
- `idle`: free for the next run.
- `broken`: the pool can't vouch for it; hover for the pool's own word, such as `damaged` or `unverified`.

The chips filter by state. A slot held by no running run is marked as such: the next tick returns it. A pool larger
than its declared size says so, and `canopy workspace sync` removes the idle slots over it.

A dirty slot is the one to look at. The pool never reuses it and counts it as busy, so it quietly shrinks the pool until
someone deals with it, and once the rest are busy the next lease is refused. Nothing in canopy cleans it for you,
since those changes might be the only copy of someone's afternoon: open the slot (its path is on its number), keep
what you need, and discard the rest.

A slot held by `quarantined: worktree seeding failed` needs a look too. A lease went to copy your seed files into it,
found one of them already there, and stopped rather than overwrite it. The pool holds the slot from then on, counted
as busy, and no tick will free it. Open the slot, deal with the file in the way, then run the `canopy workspace
release` command its note gives you. Release it without moving that file and the next lease that seeds it trips over
the same thing.

This page only reads, and it's the one page not kept current by the stream: it rereads the pools every 10 seconds
while you're looking, and **Read again** rereads them now. Each read checks every slot of every pool, and under
treehouse takes each pool's lock for a moment, which is why it doesn't do so constantly.
