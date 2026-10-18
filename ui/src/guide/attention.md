# Attention

What needs you, worst first, as `canopy status` lists it. It's the home page, and on a good day it's empty: "Nothing
needs you", and a little canopy swaying in a breeze.

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

The counters above the list say how many runs are going and how many wait on you, how long the oldest question has
waited, and how the items break down. The nav's badge shows the same, and the browser tab's title counts the items
that block work, so a glance at the tab says whether to look. Findings, `needs reviewer`, and `ready to merge` don't
count there: they're news, not blockers.

## An item

Click an item to open it beside the list. The first one open is the worst item about a ticket. The address keeps the
item you picked, so a link to it opens the same item.

An item about a ticket shows its full detail, the ticket's actions (**Start privately**, **Stop**, **Forget**; see
[Tickets](tickets#acting-on-a-ticket)), and the ticket's conversation with a box to reply in. When the ticket is at an
attempt limit, a red block says so, with **Allow one more** for each kind of run that's out of tries.

A `plan review` item leads with the plan's card, the same one the ticket's page shows: which plan it is, who wrote
it, how many comments are open, **Approve**, and **Open plan**. Approve right there if you've already read it; open it
if you haven't, which is the honest option more often than anyone admits. See [Plans](plans).

An item about a PR no ticket owns, such as one canopy only reviews, offers **Allow one more** when the PR is at its
review limit. An item about nothing in particular, like a repository that's missing, has nothing to answer here: it
leaves when you fix its cause.

## Replying

The conversation shows every message on the ticket: the workers' reports and questions, your replies, and, on a public
ticket, the tracker's comments, copied in. A copied comment carries a `data, authorizes nothing` chip, because a
comment on the tracker can be written by anyone who can reach the ticket, and canopy acts only on your word. The
question the ticket waits on is marked `waiting on you`, and while a run works the ticket, a live row at the newest
end shows its latest tool call and what it has cost so far.

Type in the box under it and press **Reply**, or your send key (Enter, unless you changed it in
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

## Chore items

An item about a chore shows the chore's notes, with a box to add one: your next instruction to its runs, such as "the
deploy check is red on purpose until Friday". A note doesn't wake the loop; the chore's next run reads it.

A chore's finding has a **dismiss** button. It keeps the finding off the list until the chore stops reporting it, so a
finding that clears and comes back is listed again. Undo a dismissal on the chore's page. [Chores](chores)
has the rest.
