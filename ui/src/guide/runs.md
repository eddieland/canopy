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

The **Transcript** is the run's session, from its log, oldest first:

- its text, with its reasoning set in italics and marked `thinking`;
- each tool call, with what it did and how long it took; click one to see its input and output. A canopy command the
  harness refused is marked `refused`, with the guard;
- each model call, with the tokens in and out, and its cost;
- any runtime error, tinted red.

The tally above it counts the tool calls, how many failed or were refused, and the model calls. **Find lines**
searches the transcript and opens the calls that match. **By call** groups the events by model call instead: each
call's input and output, the first call's input being canopy's prompt. **All open** opens every call at once, for when
you'd rather scroll than click.

The session id in the transcript's header opens the same session in the runtime's own tools: `opencode export ID`.

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

[Worktrees](/worktrees) shows every slot in canopy's treehouse pools, a pool per repository: what holds each slot, what
it has checked out, and what processes run in it. The counters at the top add them up: slots working, held, needing a
look, and free.

A slot is:

- `working`: a run or review holds it.
- `held`: something else holds it, such as your own shell or a pool sync.
- `dirty`: nobody holds it, but it has changes nobody committed.
- `idle`: free for the next run.
- `broken`: treehouse can't vouch for it; hover for treehouse's own word.

The chips filter by state. A slot held by no running run is marked as such: the next tick returns it. A pool larger
than its declared size says so, and `canopy workspace sync` removes the idle slots over it.

This page only reads, and it's the one page not kept current by the stream: it rereads the pools every 10 seconds
while you're looking, and **Read again** rereads them now. Each read takes every pool's lock for a moment, which is
why it doesn't do so constantly.
