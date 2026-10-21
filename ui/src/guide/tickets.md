# Tickets

Every ticket canopy has worked on or been asked to, and a form to start a new one. A ticket's page is where you see
everything about it at once: its phase, its PRs, its runs, its conversation, and what the overseer decided about it.

## The list

The newest activity is at the top; the toggle above the list turns it around. Each row leads with where the ticket
stands: the run working it, a question waiting on you, or else `done` or `open`, so a quiet ticket says so instead of
leaving a hole. Then its key, its [phase](how-the-loop-works#phases), whether it's [public or
private](how-the-loop-works#public-and-private-tickets) (a private one says `private, started` or `private, stopped`),
its title, and how long since anything happened on it.

The chips narrow it: `open` (anything not done, working and waiting included), `working` (a run is on it),
`waiting on you` (a worker asked something), `blocked`, and `done`. `blocked` is the phase: another ticket holds this
one up. A question for you is `waiting on you`, never `blocked`.

The box beside them filters by key or title, and the count reads `6 of 41` while anything narrows the list. Every word
you type must appear somewhere, in any case, so `abc-1` finds ABC-101 and ABC-102. Escape leaves the box.

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
  repository), what the ticket has cost so far, and the persona each of its agents writes in next. See
  [Choosing a persona](#choosing-a-persona).
- **Conversation**: every message, the box to reply in, and under it the ticket's actions.
  [Attention](attention#replying) covers how a reply works. When one of the ticket's attention items clears while
  you're here, a leaf drifts off the panel, the same one the attention list drops.
- **Runs**: every run on the ticket, each linking to its transcript ([Runs](runs#a-runs-page)).
- **Decisions**: what each tick decided about the ticket, and why, in the overseer's words. A `refused` decision names
  the [guard](how-the-loop-works#guards) that stopped it, and an `attention` decision the reason it reached your list.
- **Memory**, while ticket notes are on: the notes its runs left for the runs after them. It arrives folded, since
  you'll read it far less often than you decide anything here: the band saying what reads the notes, then **Show 3
  notes**. Open, each note that keeps its text has Forget, and Promote while lessons are on, and **Show what its next
  run is served** at the foot shows the prompt section itself. See [Memory](memory#promoting-and-rejecting).
- **Drafts for the ticket**, when its runs drafted comments for it: a question a blocked run would have asked there, or
  what a run did, each with the issue it goes to, so you can check a worker didn't get creative with the URL. **Send**,
  **Edit**, and **Drop** work as on a PR's threads ([Pull requests](pull-requests#replying-to-your-coworkers-reviews)).
  This needs a `tracker` source with a post command; without one, workers post their ticket comments themselves,
  marked.
- **Plan**, when the ticket has or needs one: a card saying where the plan stands, with **Approve** while it can be
  approved and **Open plan**, which opens the plan on its own page. When a plan waits on your approval, the card leads
  the page. See [Plans](plans).

A list with nothing in it is its header alone, counting `0`: a ticket no tick has decided anything about yet doesn't
spend a panel telling you so. On a wide screen the conversation moves to the right, beside Work, Runs, Decisions, and
Memory.

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
  overseer will find them again and the ticket can't start over. canopy refuses while a run is on it, and when nothing
  has happened since you last forgot it.

## Allowing one more run

A ticket that has used every attempt of a kind shows a red **At its limit** block, with a row for each kind of run
that's out of tries, such as "resume in web: 6 of 6 runs", and **Allow one more**. Under the button is the command
that does the same, such as `canopy grant ABC-102 resume --repo web`, with a button that copies it. One click is one
more run; for several at once, run that command with `--runs N`.

A grant dispatches nothing by itself. It raises the limit, and the next tick decides whether to use it. If the last
two resumes for the same red check failed the same way, read their transcripts before you buy a third.

## Choosing a persona

A persona is the voice a run writes in: how a worker words its PR, how a planner lays out its plan, how hard a
reviewer presses. At the foot of **Work**, each of the ticket's agents has its own row: its workers (implement and
resume), its planner, and its reviewer, each with the persona its next run gets and where that comes from: this
ticket's override, `[personas]` in your config, or canopy's default.

Open a row's menu and pick a persona to set this ticket's override, as `canopy persona KEY NAME --agent AGENT` does.
It holds for every run of that agent on this ticket until you pick **Clear the override**, which hands the choice back
to your config. Set a skeptic on the one ticket whose reviews you want harder, and leave the rest alone. The menu lists
what `canopy personas` does: canopy's own, and yours in `paths.personas`.

For one run alone, choose from the command line: `canopy persona KEY NAME --next`, or `--persona` on
`canopy start KEY` or `canopy plan KEY`. The row names it under the persona, as **Its next run alone**, until that run
starts; the runs after it go back to the row's persona. With `[personas] reviewers` in your config, each commit of
the ticket's PRs gets a review in every persona it names, and the reviewer's row lists them as **One review each in**;
an override on that row trades them for its one.

A persona changes voice, never a guard. If its file is gone by the time a run starts, that run is refused rather than
run in some other voice, its row says why in red, and the ticket lands on your attention list. Put the file back, or
pick another.
