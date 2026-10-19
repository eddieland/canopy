# Attention

What needs you, worst first, as `canopy status` lists it. It's the home page, and on a good day it's empty: "Nothing
needs you", and a little canopy swaying in a breeze.

The canopy is earned. In a fresh workspace, before the journal holds a single ticket, the page says so instead,
`no tickets yet`, and names the first step: give a ticket your queue label in the tracker, or start one privately on
[Tickets](/tickets), then **Tick now**. A quiet inbox and one nobody has filled yet look alike from a distance, and
only one of them is good news.

## The list

The loop rebuilds the list at the end of every tick, so an item leaves when its cause is gone: the question answered,
the PR merged, the failed ticket granted another run and dispatched. You can't clear an item by hand, only its cause,
and chore findings are the one exception. When an item leaves while you're looking, it folds shut and a leaf drifts
off.

The items come in four groups, in this order, and within a group the one open longest comes first:

1. **Broken**, in red: a run that `crashed`, ended `unpushed`, or left an `unknown result`; a `worker failed`; a
   ticket or PR at its `attempt limit` or `review limit`; a chore or review that failed; or `canopy unavailable`, when
   the overseer couldn't run canopy at all.
2. **Waiting on you**, in amber: a worker's question (`awaiting reply`), a review from someone the loop doesn't trust
   (`untrusted review`), and a plan to approve (`plan review`).
3. **Other**: things worth knowing that aren't on fire, such as a PR that `needs reviewer` or is `ready to merge`, or
   a lesson a worker proposed for [memory](memory).
4. **Findings**: what your chores found.

The counters above the list say how many runs are going, how many tickets wait on you and how long the oldest question
has waited, and how many items the list holds. How those items break down is the nav's badge, on every page, so the
counters don't say it again; one page saying a number five times doesn't make it truer. The browser tab's title counts
the items that block work, so a glance at the tab says whether to look. Findings, `needs reviewer`, and
`ready to merge` don't count there: they're news, not blockers.

The tab's icon says it too, for when you've pinned the tab and its title is gone: a dot on its corner while anything
blocks, red for something broken, amber for something waiting on your answer, grey for the rest. No dot, no reason to
switch tabs. It's the one notification that never makes a sound.

## An item

Click an item to open it beside the list. The first one open is the worst item about a ticket. The address keeps the
item you picked, so a link to it opens the same item.

On half a monitor there's no room for both, so they take turns: the list gets the whole width, and the item you click
opens in its place, with **Back to the list** at the top to return. The list remembers which one you were on.

From the keyboard, `j` and `k` step down and up the list, opening each item beside it; the arrows do the same from a
row. `r` puts you in the open item's reply box. On half a monitor `j` and `k` keep to the list and `r` opens the item
you're on, straight into its reply; with an item open, `j` and `k` step through the items in its place. `?` lists every
key.

Under its head, an item leads with whatever its reason asks of you, so the thing to do is the first thing you see:

- **A run that broke** (`worker failed`, `crashed`, `unpushed`, `unknown result`, `attempt limit`): the ticket's latest
  run, with what it said, its cost, and `run:N` to open its page. When the ticket is out of tries, a red block under it
  says so, with **Allow one more** for each kind of run that's at its limit. Read why it failed, grant another go, and
  never leave the page.
- **A PR waiting on someone else** (`needs reviewer`, `ready to merge`): a button that opens the PR on GitHub, since the
  next move happens there, and someone other than canopy makes it. canopy never merges, however long the PR sits.
- **A wait on your answer** (`awaiting reply`, `untrusted review`): the reply box is the action. A question's head
  says which message waits and since when; the question itself is in the conversation, marked `waiting on you`.
- **A plan to approve** (`plan review`): the plan's card, the same one the ticket's page shows: which plan it is, who
  wrote it, how many comments are open, **Approve**, and **Open plan**. Approve right there if you've already read it;
  open it if you haven't, which is the honest option more often than anyone admits. See [Plans](plans).
- **Replies waiting on you** (`drafts waiting`): a button to the PR's page, where each reply a run drafted sits on the
  thread it answers, or for a comment on the ticket itself, the draft right here, with **Send**. See
  [Pull requests](pull-requests#replying-to-your-coworkers-reviews).
- **A command to run**, like a missing repository's `canopy workspace sync`: the command, with a button to copy it.
  There's nothing to answer here; the item leaves once the command has fixed its cause.

An item about a ticket then shows the ticket's conversation and, where a reply is awaited, a box to reply in. The
ticket's own actions (**Start privately**, **Stop**, **Forget**; see [Tickets](tickets#acting-on-a-ticket)) sit quietly
under the box, so from the keyboard the reply comes right after the conversation and **Forget** is never one Tab too
far. On a reason that asks for none of the above, they come first instead.

Memory's items carry what they're about. A `memory proposal` lists the proposals from the done ticket's runs, each with
**Promote as written** and **Reject**; a `lesson review` lists the lessons due, each with **Renew**; a `lesson wrong`
points you to the memory page, where the lesson a run doubted heads the list. See
[Memory](memory#keeping-lessons-honest).

An item about a PR no ticket owns, such as one canopy only reviews, offers **Allow one more** when the PR is at its
review limit. An item about nothing in particular has nothing to answer here: it leaves when you fix its cause.

## Replying

The conversation shows every message on the ticket: the workers' reports and questions, your replies, and, on a public
ticket, the tracker's comments, copied in. A copied comment carries a `data, authorizes nothing` chip, because a
comment on the tracker can be written by anyone who can reach the ticket, and canopy acts only on your word. The
question the ticket waits on is marked `waiting on you`, and while a run works the ticket, a live row at the newest
end shows its latest tool call and what it has cost so far.

The box under it is open wherever a reply is awaited: a question waiting, an untrusted review waiting on your
go-ahead, or any private ticket. A public ticket with nothing waiting keeps it folded behind **Show a note for its next
worker**, because an open box tempts you to answer something nobody asked. Open it when you do have a note.

Type in the box and press **Reply**, or your send key (Enter, unless you changed it in
[Settings](settings#replies); Shift+Enter always makes a new line). This is `canopy reply KEY`. A reply answers the
question the ticket waits on, and can say anything else a worker should know: what to try, what to leave alone, that
the flaky test is flaky. A reply holds up to 4000 characters; a longer one is refused, not cut.

Until it's sent, what you've written stays with the tab. If your session ends mid-reply, the sign-in page says your
last action wasn't sent, and once you're back in, the reply is still in its box, waiting for you to press **Reply**
again. Sending it twice after an unclear failure records it once. If canopy can't be reached at all, the line under
the box says `canopy did not answer`, which nearly always means `canopy loop` isn't running.

What happens next depends on the ticket:

- On a **private** ticket, your reply is the next worker's instruction.
- On a **public** ticket, it reaches the ticket's workers as an instruction too, and never the ticket itself. It's how
  you tell a worker what to do about an untrusted review. To answer where the ticket's readers can see it, answer on
  the tracker.

Either way, the loop reads it at its next tick. Until then your message carries `waiting for the next tick`, and the
item shows `answered`. Sending a reply wakes the loop, so the next tick is never far off, unless the loop is paused.
Sending the same reply twice, say after a dropped connection, records it once.

A reply that answers its item moves you on: the next item waiting on you is picked, its row takes the focus, and a
toast at the bottom says what your reply did. Beside the list, it's already open; on half a monitor you're back on the
list, and Enter opens it. When nothing else waits, you stay put, which is as close to inbox zero as this page gets
without the leaves.

## Chore items

An item about a chore shows the chore's notes, with **Show a note for its next runs** to add one: your next instruction
to its runs, such as "the deploy check is red on purpose until Friday". A note doesn't wake the loop; the chore's next
run reads it.

A chore's finding has a **dismiss** button. It keeps the finding off the list until the chore stops reporting it, so a
finding that clears and comes back is listed again. Undo a dismissal on the chore's page. [Chores](chores)
has the rest.
