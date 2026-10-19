# Tickets

Every ticket canopy has worked on or been asked to, and a form to start a new one. A ticket's page is where you see
everything about it at once: its phase, its PRs, its runs, its conversation, and what the overseer decided about it.

## The list

The newest activity is at the top; the toggle above the list turns it around. Each row leads with where the ticket
stands: the run working it, a question waiting on you, or else `done` or `open`, so a quiet ticket says so instead of
leaving a hole. Then its key, its phase, whether it's public or private, and its title.

The chips narrow it: `open`, `working` (a run is on it), `waiting on you` (a worker asked something), `blocked`, and
`done`. `blocked` is the phase: another ticket holds this one up. A question for you is `waiting on you`, never
`blocked`.

The box beside them filters by key or title. Every word you type must appear somewhere, in any case, so `abc-1` finds
ABC-101 and ABC-102. Escape leaves the box.

## Starting a ticket

Type a key in **Start a ticket** and press **Start privately**. This is `canopy start KEY`. canopy starts the ticket
as a private one: it needs no queue label, and its conversation stays in canopy, so workers read the ticket and write
nothing to it. The next tick picks it up, and the form opens the ticket's page.

A ticket you start is private from then on, whatever labels it carries or gains. To ask for a plan before the first
implement, start it from the CLI with `canopy start KEY --plan`, or run `canopy plan KEY` afterwards.

## A ticket's page

At the top, the key, the title, and whether the ticket is public or private, with links out to the tracker, its PRs,
and its branches. The line under the title is where the ticket stands: the run working it, a question waiting on you,
its plan's status, and when it was last active. Hover the `public` or `private` chip for what that means: a public
ticket's comments stay on the tracker, and a reply you send from here stays in canopy either way, for its next worker.
Below:

- **Work**: the ticket's phase, its branch, each PR with its own phase (a ticket that spans repositories has one per
  repository), and what the ticket has cost so far.
- **Conversation**: every message, the box to reply in, folded on a public ticket with nothing waiting, and under it
  the ticket's actions. [Attention](attention#replying) covers how a reply works. When one of the ticket's attention
  items clears while you're here, a leaf drifts off the panel, the same one the attention list drops.
- **Runs**: every run on the ticket, each linking to its transcript.
- **Decisions**: what each tick decided about the ticket, and why, in the overseer's words. A `refused` decision names
  the guard that stopped it, and an `attention` decision the reason it reached your list.
- **Drafts for the ticket**, when its runs drafted comments for it: a question a blocked run would have asked there, or
  what a run did, each with the issue it goes to, so you can check a worker didn't get creative with the URL. **Send**,
  **Edit**, and **Drop** work as on a PR's threads ([Pull requests](pull-requests#replying-to-your-coworkers-reviews)).
  This needs a `tracker` source with a post command; without one, workers post their ticket comments themselves,
  marked.
- **Plan**, when the ticket has or needs one: a card saying where the plan stands, with **Approve** while it can be
  approved and **Open plan**, which opens the plan on its own page. When a plan waits on your approval, the card leads
  the page. See [Plans](plans).
- **Memory**, while ticket notes are on: the notes its runs left for the runs after them, each one that keeps its text
  with Promote while lessons are on. See [Memory](memory#promoting-and-rejecting).

A key canopy has never seen gets a page too, saying so, with the form to start it.

## Acting on a ticket

The ticket's actions sit under the reply box, on its page and on its attention item, so the keyboard reaches the
reply before **Stop** or **Forget**. Hover over each to see its command.

- **Start privately**, or **Start again** on a stopped ticket: as above.
- **Stop**, as `canopy stop KEY`: nothing new is dispatched for the ticket. A run already on it finishes. A public
  ticket has no Stop: its queue label is what started it, so remove the label, or start it privately and stop that.
- **Stop now**, while a run is working a private ticket: it asks once more, then ends the run at once and returns its
  worktrees, as `canopy stop KEY --now`. The run ends `stopped` and still counts toward the ticket's limits. Use it
  when a worker is plainly lost; the meter runs while you watch.
- **Forget**, as `canopy forget KEY`: canopy drops what it knows of the ticket's branch, PRs, and phase, so its next
  implement starts over on a new branch. Type the key to confirm. Its runs and attempt counts stay. So does its
  conversation, but the loop stops reading the old part, and so does the page: those messages fold away under a line
  saying when you forgot it and which branch and PRs it dropped, with **Show N earlier messages** for when you want
  the history back. Forget a ticket three times and you get three of those lines, one per attempt, which is also a
  hint worth reading. Closing its PRs and deleting its branch on origin is yours to do, and until you do, the
  overseer will find them again and the ticket can't start over. canopy refuses while a run is on it, for a ticket a
  split made children from, and when nothing has happened since you last forgot it.

## Allowing one more run

A ticket that has used every attempt of a kind shows a red **At its limit** block, with a row for each kind of run
that's out of tries, such as "resume in web: 6 of 6 runs", and **Allow one more**. This is `canopy grant KEY KIND`.
One click is one more run; for several at once, use `canopy grant` with `--runs N`.

A grant dispatches nothing by itself. It raises the limit, and the next tick decides whether to use it. If the last
two resumes for the same red check failed the same way, read their transcripts before you buy a third.
