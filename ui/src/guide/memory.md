# Memory

What workers learn on one run and carry to the next: notes a ticket's runs leave for each other, and lessons you
decide every worker reads. It's off until you turn it on, and nothing reaches a prompt that you didn't let in.

## Two tiers

Memory comes in two tiers, split by how far a worker's words can travel.

- **Ticket notes**: a ticket's runs write them as they end, and only that ticket's later runs read them, as data to
  check against the branch and the PR. A dead end is kept too, from a run that failed or blocked: it's what a retry
  most needs to hear.
- **Lessons**: workers only propose them. A proposal reaches no prompt. You promote one into a lesson, in your own
  words if you like, or reject it; a lesson is your text, read by every worker in the workspace beside your standing
  instructions. A lesson reaches every run, which is exactly why a proposal waits for you.

The overseer reads no memory and writes none, and reviews, chores, and splits get neither tier: a reviewer stays
independent of what the author believed.

## How it protects you

Memory is a worker's words reaching a later prompt, which is exactly what anyone steering a worker through a ticket
comment would want. So the walls are in code, not in a prompt asking nicely.

- **A run writes only on its own ticket.** canopy files a note under the ticket the run was started for, taken from
  the run's own record, never from anything the worker says. Only that ticket's later runs read it, and a run renews or
  drops only the notes it was served. The worst a steered run can do is mislead its own ticket's next run, which is
  told to check what it reads against the branch and the PR.
- **Nothing reaches every worker until you approve it.** A worker can only propose a lesson, and a proposal reaches no
  prompt at any mode. It takes effect when you promote it, on the memory page or with `canopy memory promote`, and what
  goes out is your text, in your name. `promote`, `reject`, and `renew` refuse to run inside a tick or a run, so a
  worker can't approve its own proposal by typing the command.
- **The text is checked on the way in.** A note or a proposal is capped in length, and canopy refuses one carrying
  hidden characters or anything that looks like a secret. That doesn't make it true; it makes it something you can read.

One gap, named so you don't find it later: unless you run workers in a sandbox, a worker's shell runs as you, and could
write to the journal as you could. The walls above stop a worker that plays by canopy's commands, not one that goes
around them.

## Turning it on

Each tier has a mode under `[memory]` in your own config, the user file or the private file, never the workspace's:
`ticket_notes` for notes and `proposals` for lessons. Each is `off`, `record`, or `use`, which the UI calls off,
recording, and in use.

- **Recording**: workers write, and no run reads any of it. You see what a tier would hold before it reaches a prompt.
- **In use**: workers write, and runs read.

Recording first is the sane way in. Moving a tier from `record` to `use` serves everything it recorded, with nothing
approved again, so read it before you flip the switch. Turning a tier down stops what its mode added and deletes
nothing; `canopy memory purge --all` clears out what a trial wrote. A run keeps the modes its prompt was written under,
whatever your config says by the time it ends.

While either tier is on, the header shows `memory: recording`, or `memory: in use` once a tier is in use; hover over it
for each tier's mode, and click it for the memory page. With both off, memory shows nowhere.

## The memory page

[Memory](/memory), in the nav, puts what waits on you first: the proposals, then your lessons, then the tickets with
notes. The lessons and the notes each open with a band that says the tier's mode and what reads it, in words:
`ticket notes: recording` beside "Recording only. Workers write these notes; no run reads them." Recorded memory and
memory in use never share a label, so you never mistake one for the other.

- **Proposals** are what workers suggested, oldest first, each with where it came from: its run's kind and how it ended,
  whether its ticket is done, and when it lapses if you leave it, and Promote, Reject, and Forget under it. None reaches
  a run until you promote it. The nav counts them beside **Memory** on every page, and so does the panel, so a proposal
  doesn't quietly expire at 14 days because you never came looking. Clear the lot and the panel says so.
- **Lessons** are the ones you promoted, each with Renew and Forget, the ones a run reported wrong first, then by review
  date, so what needs you heads the list. Under them, folded until you open it, is the exact text every run is served
  from your lessons, or would be served at use while recording.
- **Ticket notes** lists the tickets with notes in force, one row each with its title, how many notes it has, and how
  many a run relied on. Open a row
  for its notes, each with Promote and Forget. A busy workspace has thousands, so the page reads a ticket's notes only
  once you ask. On a wide screen this panel sits beside the other two.

Above the panels, a filter field narrows all three as you type: a word in a memory's key, its text, its ticket, or its
repository, or in a ticket's key or title. The repository chips keep the proposals and lessons for that repository's
runs, a lesson for every repository included, since those runs read it too. While lessons are in use, the Lessons header
has `due` and `wrong` chips for the ones that need you. All of it lives in the URL, so a filtered page is a link you can
keep. The proposals flip between oldest first, the nearest to lapsing, and newest first. Searching a memory's words
across the whole journal is still `canopy memory search`.

## Reading a memory

Each memory is a row, read left to right like every other list in canopy. First where it stands, a dot and a word:
`active` for a memory in force, `recorded` for one in force while its tier only records, which no run reads, `pending`
for a proposal waiting on you (in the Proposals panel, where every row is, the time it has left instead: `3d left`,
amber in its last two days), `superseded` or `invalid` once it's out of force, and for a lesson that needs you, `due`
once its review date has come or `wrong` once a run reported it wrong, so a glance down the left edge finds them. Hover
over the word for the reason. Then its ref, as `memory:42`, with a button on hover that copies it, since that's what
Forget and the CLI ask for; its ticket, on the proposals; its repository; its key; how many runs relied on it, once any
has; and how long ago it was written.

Under that, what it says, and one line of where it came from: the run that wrote it, with the commit it was written
against on hover; for a proposal, how its run ended, whether its ticket is done, and `private` if its run worked a
private ticket; for a lesson, what it was promoted from, when it comes up for review, and any run that reported it
wrong, and when.

A worker's text is shown as plain text, never as Markdown or a link, unlike everything else a worker writes: a link in
a note would be a worker's link you'd read as canopy's. Any character that hides text from you but not from a model,
such as a zero-width space, is shown by its code point, as `<U+200B>`, and boxed in red. If you see one, someone was
being clever.

The prompt's share of memory is capped, 3 KiB for a ticket's notes and 2 KiB for the lessons. A memory in force that
the cap leaves out says so on its row: `left out of the prompt, past its cap`, or `would be left out at use` while
recording. A worker can still find it with `canopy memory search`.

## On a ticket and a run

A ticket's page has a **Memory** panel while ticket notes are on: every note its runs wrote, those superseded or
invalidated included, and the text its next run would be served. A run's page has one too, for a run started while
either tier was on: what it wrote, what it read, and anything it tried to write that canopy refused, in canopy's words,
not the worker's. A run started while recording read `none, recording only`, which isn't the same as reading an empty
list. Among what it read, a memory it said it relied on says `this run relied on it`, and one it reported says `this
run found it wrong`.

Going the other way, a memory names the latest runs that relied on it, `used in run:40, run:38`, each opening that
run's page, so you can check what a note actually steered before you trust it. Past five, or for runs from before
canopy kept track, it counts the rest as `and 3 more`.

A ticket's notes are invalidated when it's marked done and when you forget it. Stopping it keeps them, since you may
start it again.

## Promoting and rejecting

Each proposal on the memory page has **Promote as written**, **Edit and promote**, and, apart at the end of its line,
**Reject** under it, and each of a ticket's notes has Promote, on the memory page and on the ticket's own. They do what
`canopy memory promote` and `canopy memory reject` do in your shell, with the same refusals, and both work at `record`
as at `use`, so you can build up your lessons before any is served. None of them shows while lessons are off.

- **Edit and promote** opens the lesson to be: the proposal's words, which you can rewrite (usually an improvement),
  held to the same 600 characters, and the repository whose runs read it. A proposal keeps its own repository unless you
  pick another; a note's lesson is for every repository unless you pick one. Before you save, the form names the lesson
  in force under the same key, if there is one, since yours replaces it.
- **Promote as written**, the first button, promotes the proposal at once, in its own words and for its own repository,
  as `canopy memory promote ID` does. Most good proposals need no editing, and this saves the form.
- It promotes a ticket's note too, done or invalidated, as long as the note still has its text: what a ticket taught
  is often clearest once its PR has merged. The note stays its ticket's.
- **Reject** ends a proposal. Nothing asks twice: nothing is lost that a worker can't propose again.

What it did shows at the top of its panel, in the CLI's words, including that a lesson promoted while recording is
recorded and read by no run. Promoting a private ticket's run's words as they stand warns you, before you save and
after: its text may hold what you kept off the tracker. At most 20 proposals wait at once, and one nobody reviews
expires after 14 days, so the queue can't bury you.

In your shell, `canopy memory promote ID` takes `--text` for your words and `--repo` for the repository, and
`canopy memory reject ID` rejects.

## Keeping lessons honest

A lesson never lapses on its own: it's your word, and only you retire it. Each comes up for review 90 days after you
promoted it or a run last used it. Then you renew it, with **Renew** under it on the memory page or `canopy memory renew
ID`, move it into a repository's AGENTS.md or a skill through a ticket and a PR you merge, or forget it. Renewing also
clears a run's report that it's wrong. Renew stays quiet on a lesson that isn't due, and stands out once one is due or
reported wrong.

Three attention items keep you honest, all yours and never the overseer's, and none while lessons are off:

- `memory proposal`, when a ticket is marked done and its runs' proposals are waiting. Its merge has checked the work
  they came from, which makes now a good time to judge them. The item lists them, each with **Promote as written** and
  **Reject**; to put one in your own words, promote it from the memory page.
- `lesson review`, for the lessons due, longest overdue first, each with **Renew**. Only while lessons are in use:
  switching to use brings every overdue lesson up at once, in one item, before any of them is served.
- `lesson wrong`, for the lessons a run reported wrong since you last renewed them, with the way to the memory page,
  where they head the lessons. A worker can't retire your lesson; it can only tell you.

Each item leaves at the next tick once you've dealt with what it names, as an answered question does.

## Forgetting

**Forget**, at the end of any memory's line of buttons, muted until you point at its row, or `canopy memory forget ID`,
deletes its text and keeps its row, so the history still says something was there: a forgotten lesson is retired, and a
forgotten proposal leaves the queue. Reject is enough for a proposal you just don't want; Forget is for one whose words
shouldn't stay. It can't be undone, so the page asks you to type the memory's ref, `memory:42`, before the button wakes
up. A lesson from a note comes back if you promote the note again, while the note keeps its text; one from a proposal
doesn't, since promoting it used the proposal up. `canopy memory purge`, in your shell alone, does the same for many: a
ticket's runs', a run's, or, with `--all`, everything. Neither leaves a word of what it deleted in the search index or
the journal's free pages. That's the point, if what you're deleting is a leaked secret.

## Search

`canopy memory search WORDS` finds memories by their words, best match first, a word in a key counting more than one
in a text. From your shell it finds every memory that still has its text. From a worker's run it finds only what that
run could have been served: its ticket's notes and the lessons for its repositories. Never another ticket's notes,
and never a proposal. The search box on the rail doesn't search memory; this does.
