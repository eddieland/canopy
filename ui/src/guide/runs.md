# Runs and worktrees

What every agent is doing, what it did, and where. A run's page is the transcript of its session, every tool call
and what it cost; the worktrees page is the pools they work in.

## The runs page

[Runs](/runs) lists every agent canopy runs: workers on tickets, reviews of PRs, chores, and tasks. Each gets one row
per subject, by its latest run: a ticket's, a PR's, a chore's, a task's. The running ones come first, then the ones
that ended most recently. A subject with earlier runs shows **Show N earlier runs** under it, so a PR reviewed at
every push is one row and not a wall of them. The overseer's ticks are not among them: the **Ticks** link in the
page's description opens [their page](ticks#the-ticks-page), also under Runs, and **Worktrees** beside it opens the
[pools](#worktrees) the runs work in.

Each row has the run's state, its id, what it works for, its kind, what it cost, and how long it ran or how long since
it ended:

- A **worker run** (`run:39`) names its ticket and kind, with a resume's reasons beside it (`resume (ci, review)`),
  and the ticket's title, marked `private` when the ticket is. Under it are its summary, its PRs, the worktrees it
  holds, the model that served it, its session id with a button that copies it, and, while it runs, its latest tool
  call.
- A **review** (`review:4`) names its ticket, if its PR has one, and the PR's title: its own, or its ticket's until
  a worker reports one. Under it are the PR, the commit it read, and what it found. The findings themselves are on
  [its page](pull-requests#a-reviews-page).
- A **chore run** (`#2`, beside its chore, so it reads `chore:deps #2`) has its chore's title, the `# heading` its
  prompt opens with, and its summary under it. [Its chore's page](chores#a-chores-page) has every run; here you get the
  latest, and the one before it while one runs.
- A **task run** (`task:6#6`) names the repository its task runs in and the first line of what you asked, with its
  summary and any PRs it named under it. It is the task's newest run only: the rest, and the conversation, are on
  [the task's page](tasks#a-tasks-page).

A subject with no title says `untitled`, which for a chore is a hint its prompt could use a first line.

A worker run's model line names the model its session says served it, without the provider unless two models in the
list share a name, so `claude-opus-4-1` rather than `anthropic/claude-opus-4-1`, and `+1` when it switched partway.
Hover it for each one whole, with its cost. Until canopy reads the session it names the model canopy asked for,
`asked claude-opus-4-1`, or says `model unread`, with why on hover; a run with no session to read, such as a feedback
plan's, names no model at all. A run that got none of what it asked for says so, asked first,
`asked claude-opus-4-1 ≠ claude-sonnet-4-5`, as [its page](#a-runs-page) does; one that got it and switched partway
leads with it and sets the `+1` apart. Neither is amber: a run that went elsewhere waits on nothing, it just bears
knowing. Asking for `openai/gpt-5@medium`, the default effort, and being served `openai/gpt-5` is no surprise either,
since the session names a variant only when it isn't the default. A ticket's Runs panel shows the same line, so a
ticket with a model override reads straight down its runs: opus, opus, opus, and not a sonnet slipped in where you
weren't looking.

A long summary shows its first four lines and **show N more lines** for the rest, so one worker with a lot to say
doesn't push the other rows off the page. In a narrow window, such as half a monitor, the cost goes first and then
the kind; how long stays.

The chips filter by kind, `workers`, `reviews`, `chores`, or `tasks`, and by the latest run's state: `running`,
`waiting on you` (the worker stopped to ask something), `failed`, `stopped`, and `done`. The two keep each other, so
`reviews` then `failed` is every PR whose latest review failed. A cost of `–` means the runtime reported none, which
is not the same as free.

The **every model** picker beside the filters lists every model the runs listed name, under a field that narrows them,
as the repository pickers elsewhere do. Pick one, or click a model on [the spend page](reports#the-spend-page), and the
page keeps the runs it served (`?model=`): worker runs, or, until their sessions are read, the ones that asked for it;
reviews; a chore by its running or latest run; a task by its newest. Each subject's latest of those leads its row. Runs
older than the recent ones the page keeps drop out, which is why a model Spend counts a dozen runs of can come up a few
short here. **every model** takes the filter off.

Under the page's description, one line says how full each limit is, counted the way canopy counts it before it starts
anything: `workers 2 of 2` is `capacity.max_workers`, which reviews and task runs count toward (its hover says how
many of each are in it), `reviews 0 of 1` is `capacity.max_reviews` within it, and `chores 1 of 1` is
`capacity.max_chores`, which stands apart. A full one turns amber and says `full`: the next dispatch of its kind waits
for a run to end, however urgent the overseer thinks it is. When a ticket sits in the queue looking neglected, this
line usually explains why. A limit of 0 reads `off`.

## A run's page

The line under the title says how the run ended, its kind, and its ticket, whose key opens the ticket's page. Each
of those is said there and nowhere else on the page, so the panels under it can get on with the rest.

While its agent has written any, a **Progress** panel leads the page: where the run's work stands, in the agent's own
words ([below](#a-running-agents-progress)). The **Run** panel under it leads with its summary, the run's own account of
what it did, then, for a `feedback-plan` run, **wrote**: the plan it wrote, `feedback-plan:7`, which opens the PR's page
at the plan, with the PR and where the plan stands now. Then its **last call** while it runs, then its PRs, then
**when**: when it started and ended and
how long that took, `Oct 8 10:30 → 10:59 · 29m`, or `for 3m`
while it runs. **spent** gives its cost, the tokens it used, and its peak context, the most one model call was sent.
**persona** is the voice it wrote in, with the start of its text's digest: two runs in one persona with different
digests had it edited between them. **model** names the model that wrote its replies, as the runtime's own record of the
session says, so it is right even when a template's option or the runtime's default picked it rather than you. A run
that switched models partway lists each with its share of the cost. The runtime prints no model while a run works, so
canopy reads the session as the run ends, and any it missed while the loop waits between ticks; until then, or once the
runtime has forgotten the session, the field says why it names none. When canopy chose the run's model, from
`[runtime.models]` or the ticket's override, the field says `asked` and that model instead, from the moment it starts,
with why none served yet on hover. Once the session is read, a run the model asked for served none of reads
`asked Y ≠ served X`, and one it served alongside another marks the other with a `≠`, its tip saying it wasn't asked
for. Last come the places: the branch, its worktrees, and the path of its log, which only you can read.

A run that ended `failed`, `crashed`, or `unknown` also has **ended on**, right under its summary: the transcript's
last runtime error, or failing that its last failed or refused tool call, with when it happened. The summary is the
harness's side of it (`the worker exited 1 without a result line`), which is true and not much help; this is the
agent's side, often something as mundane as a rate limit. Click it to jump to that row in the transcript instead of
scrolling past a few hundred rows to find it. A chore run's page has the same field.

The **Transcript** is the run's session, from its log, oldest first:

- its text, with its reasoning set in italics and marked `thinking`. Long thinking shows its first four lines and
  **show N more lines** for the rest, since a model that thinks out loud rarely thinks briefly. **All open**, or a
  search that finds a line in the folded part, shows it whole;
- each tool call, with what it did and how long it took; click one to see its input and output. A canopy command the
  harness refused is marked `refused`, with the guard. An overseer's `decide` names each ticket and its action on its
  row, and opens to every decision on a line of its own with its rationale, so a tick that decided twelve tickets in
  one call doesn't leave you reading them out of a JSON array. Its `ticket-set` does the same: each ticket, or
  `ABC-1 (web)` for a unit, with what it sets on the row, and opened, each on a line with its phase, `done`, every
  cursor and the item it passes, and the title;
- each model call, with the tokens in and out, and its cost; click one to see what it was sent and what it did. The
  first call was sent canopy's prompt, and every later one what the tools returned since. In a run that switched
  models, the first call names its model, and so does each call where the model changed, By call too, so you can see
  where the switch happened. A run on one model names none: **model** already said it. A split run from before canopy
  kept each call's model gets its names when the loop reads its session again, if the runtime still has it;
- any runtime error, tinted red.

Near the run's timeout, its tool calls' output ends with a line from canopy saying how many minutes are left, and the
first such line tells the agent to push or record its work and print its result. It shows up in the last fifth of the
run's time, and never more than its last 10 minutes. It's advice, not an extension: the timeout still ends the run on
the minute, whatever the agent makes of the warning.

The tally above it counts the tool calls, how many failed or were refused, the model calls, and any runtime errors. It
also says when the log holds more than the page shows, `cut`, and how many events couldn't be read, so a short
transcript never passes for a short session. **Find lines** searches the transcript and opens the calls that match;
Escape clears it. **By call** groups the events by model call instead, each call
one row that opens to the same input and output; a session of one call has nothing to group, so it has no By call.
**All open** opens every call at once, for when you'd rather scroll than click.

A long session draws its first 100 rows, and a fold at the bottom, **Show 100 of 1,900 more rows**, draws the next
100 a click. A long worker or overseer session can reach the server's limit of 2,000 entries, some 80,000 elements
drawn whole, and the page felt every one of them on each key typed into Find. **Find lines** still searches every
entry, drawn or not, so a search beats clicking the fold nineteen times; to start at the latest rows, flip the order
to newest first. All open opens only the rows drawn, and following an addition in the chart, or the error a run
ended on, draws down to its row first.

The session id in the transcript's header opens the same session in the runtime's own tools: `opencode export ID`,
or OpenCode 2's `opencode session export ID`. A
transcript with nothing to show is its header alone, saying why in a word or two (`log gone`, `no session`,
`no events yet`); hover it for the whole reason.

Under the transcript, **Prompt** is what canopy handed the worker, exactly as rendered: the instructions for its kind
of run, then the ticket and whatever else canopy chose to tell it. It arrives folded, with its length; **Show prompt**
opens it, and the copy button beside the length takes it whole, for trying it again by hand. When a worker did
something baffling, start here: more often than not, it did what it was told. The instructions above the
`<!-- canopy: run -->` line went in as the agent's system prompt, the same for every run of its kind so the provider
can serve them from its cache, and the `## Run` part below it was the session's first message. The rest of the
agent's definition and the runtime's own system prompt aren't in it, since no file records them. A prompt over 1 MiB
shows its first 1 MiB, marked `cut`, and a run whose prompt file is gone says `none kept`.

Nothing here lasts forever. Once a day the loop removes the log, prompt, and diffs of runs that ended longer ago than
your `[retention]` keeps them, 30 days unless you say otherwise, and an old run's page then says `removed after 30
days` where its transcript, prompt, and output were. The row stays, with its cost, status, and summary: canopy forgets
the transcript, never that the run happened. `canopy gc --dry-run` shows what the next pass will take.

Under the prompt, **Output** is the run's log as written: its setup commands' output, then the worker's stdout and
stderr, and how it exited. The transcript shows only the session's events, so a run that died in `pnpm install`, or
crashed before its first event, has an empty transcript and its whole story here. **Show output** opens it at its end,
where the errors live. **Pretty** lays each event out on its own lines, and an output too long to show whole is marked
`cut`, with its end shown.

Under that, while agent memory is on, **Memory** counts what the run wrote and read (`wrote 2 · read none`), and what it
tried to write and canopy refused, each tier's mode on hover. The refused ones are listed under **Refused** with why.
**Show memory** opens the memories themselves, sorted by kind; [Memory](memory#on-a-ticket-and-a-run) says what they
mean.

## Context

Under the tally, one line names the session's peak context and its largest single addition: usually one tool call
that returned a whole file, or a whole log, when a page of it would have done. Click the addition to find it in the
transcript. Each call carries everything before it, so what a run costs grows with the context it piles up, far more
than with what it says.

**Show chart** opens a bar for each model call, showing how much it was sent. It stays closed until you open it, since
you mostly come here to read what the agent did, not to audit its token budget, and each kind of page remembers your
choice: open it once on a run and every run's page opens with it. Click a bar to see what that call added on the one
before, largest first, and click an addition to find it in the transcript. The first bar splits into canopy's prompt
and the runtime's own: the agent's definition, its system prompt, and its tools. In the legend, **carried** is what a
call brought along from the one before and **added** is what it put on top; on the first bar they're the runtime's
own and canopy's prompt. Figures marked `≈` are estimates, shared out by characters.

A session with only one call the runtime counted tokens for has the line alone. One bar is not a chart; it is a
number standing on a box. Hover the peak for how much of it was canopy's prompt.

## Stopping a run

A run's page only reads. To stop a run, stop its ticket, from the ticket's page or its attention item: **Stop now** ends
a private ticket's run at once. [Tickets](tickets#acting-on-a-ticket) covers it.

## Worktrees

**Worktrees**, under [Runs](/runs), shows every slot in canopy's pools, a pool per repository: what holds each slot,
what it has checked out, and what processes run in it. The line under the title says how many pools and slots there are,
and how long ago they were read. In a narrow window, what holds a slot goes before its branch is cut: the branch names
the ticket anyway. The counters add them up: slots working, held (and by what), needing a look, and free.
Needing a look counts dirty slots, broken ones, and any pool that couldn't be read at all.

Each pool's header has a strip of squares, a slot each in its state's color, so a pool that's full or sick shows at a
glance; hover a square for its slot and state. Beside it is the directory the slots live under. A run of idle slots
folds into one line, **Show 6 slots, #3 to #8**, so the slots with work in them stay in reach. With the repository's
`branch_url` set, a slot's branch links out to its page on the host, and a branch git couldn't read says
`branch unreadable:` with git's reason, in red.

A slot is:

- `working`: a run, a review, or a task's run holds it. A ticket's run names the ticket and `run:N`; a task's names
  `task:N` and its run, `task:N#M`, each opening its page.
- `held`: something else holds it, such as your own shell or a pool sync.
- `dirty`: nobody holds it, but it has changes nobody committed.
- `idle`: free for the next run.
- `broken`: the pool can't vouch for it; hover over it, or Tab to it, for the pool's own word, such as `damaged` or
  `unverified`.

The chips filter by state. A slot held by no running run is marked as such: the next tick returns it, or the
`canopy workspace release` command its note gives you returns it now. A pool larger than its declared size says so,
and `canopy workspace sync` removes the idle slots over it. In a terminal, `canopy workspace slots` lists the same.

A dirty slot is the one to look at. The pool never reuses it and counts it as busy, so it quietly shrinks the pool until
someone deals with it, and once the rest are busy the next lease is refused. Nothing in canopy cleans it for you,
since those changes might be the only copy of someone's afternoon: open the slot (its path is in its number's tip), keep
what you need, and discard the rest.

A slot held by `quarantined: worktree seeding failed` needs a look too. A lease went to copy your seed files into it,
found one of them already there, and stopped rather than overwrite it. The pool holds the slot from then on, counted
as busy, and no tick will free it. Open the slot, deal with the file in the way, then run the `canopy workspace
release` command its note gives you. Release it without moving that file and the next lease that seeds it trips over
the same thing.

This page only reads, and it's the one page not kept current by the stream: it rereads the pools every 10 seconds
while you're looking, and **Read again** rereads them now. Each read checks every slot of every pool, and under
treehouse takes each pool's lock for a moment, which is why it doesn't do so constantly.

## A running agent's progress

A worker, a planner, a reviewer, or a [task](tasks)'s worker posts updates on its progress while it runs: a summary for
someone who skipped the transcript, what it's doing now, what it finished with the proof of each (`tests pass: 42/42`,
`pushed abc123`, or the honest `not pushed`), what's left, and anything in its way it's working around. A long job adds
its steps, each `to do`, `working`, `blocked`, `done`, or `skipped`, and a meter fills in a segment per step done, with
how many are done and the stage under way. The step under way fills only halfway, with a shade passing along it while
the run runs: the meter's way of saying "working on it" without claiming credit. A worker with an approved plan takes
its steps from the plan, so you watch the plan you approved being done, or not. A step working longer than a fifth of
the run's time limit reads `stuck`. Each update replaces the last.
It's the agent's own account, so read it as you'd read a colleague's standup: useful, and checked against the diff.

It reads as one checklist: the steps, the working one pulsing with what the agent says it's doing now under it, or,
for a job without steps, what's done, what it's doing, and what's next, in that order. With steps, what it wrote is
done and next folds away under **Show done and next**, proofs and all.

Progress says when it was last updated, in time and in tool calls. One that has gone 10 minutes, or 20 tool calls,
without an update says `stale` beside a clock, rather than going quiet, and canopy nudges the agent for a new one.
Stale isn't amber: that's for what waits on you, and an agent that's slow to write is, so far, only slow. A run that
ended keeps its last progress, so you can see where it thought it was when it stopped.

The agent may ask you a question it can work around while you decide: the question, two to five options lettered from
A, and the one it recommends and works toward meanwhile. It sits in an amber box reading `asks you` until you answer.
Click an option, or run `canopy reply run:ID LETTER` (`review:ID` for a review), and the agent hears your letter on its
next tool call; click another to change your mind, as long as it runs. An answer is a letter, never words: you choose
among its options, which is also all a line forged to look like canopy's could do. A question it can't work around
still ends the run as `blocked`, as before. A task's run asks none here: its questions end the run, and your reply
starts the next.

A run's page, a review's, and a task run's lead with the whole of it; the runs list shows what it's doing now, `asks
you` while a question waits, and when it was last updated, after a small meter when it has steps; a ticket's page shows
it as a bubble under `working now`; and the rail puts the meter under a working ticket whose progress has steps. Nothing
in it reaches another agent, and nothing in it changes what canopy does: it's for you.
