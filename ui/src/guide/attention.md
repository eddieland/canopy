# Attention

What needs you, worst first, as `canopy status` lists it. It's the home page, and on a good day it's empty: "Nothing
needs you", and a little canopy swaying in a breeze.

The canopy is earned. In a fresh workspace, before the journal holds a single ticket, the page says so instead,
`no tickets yet`, and names the first step: give a ticket your queue label in the tracker, or start one privately on
[Tickets](/tickets), then **Tick now**. A quiet inbox and one nobody has filled yet look alike from a distance, and
only one of them is good news.

So do a quiet inbox and a dead loop. While the loop isn't answering, an empty list grows no canopy: it says
`Nothing needed you as of 14:05`, and that the list can't change until the loop is back. An all-clear from a loop that
stopped at lunch is a timestamp, not a verdict.

## The list

The loop rebuilds the list at the end of every tick, so an item leaves when its cause is gone: the question answered,
the PR merged, the failed ticket granted another run and dispatched. An item about a PR waiting on its reviewer or a
plan waiting on you leaves only when a fresh read shows it so: a GitHub outage keeps it on the list rather than
announcing it resolved, then raising it again an hour later. A judgment call the loop made stays until what it's
about is settled: a comment that `needs author` until it's handled or you reply on the ticket, a ticket split across
repositories (`multi repo`) until you reply, a check a notice held (`notice rerun`) until it runs again. You can't clear
an item by hand, only its cause, and chore findings are the one exception. When an item leaves while you're looking, it
folds shut and a leaf drifts off.

The items come in four groups, in this order, and within a group the one open longest comes first:

1. **Broken**, in red: a run that `crashed`, ended `unpushed`, or left an `unknown result`; a `worker failed`; a
   ticket or PR at its `attempt limit` or `review limit`; a chore or review that failed; a run refused because the
   runtime no longer lists its model (`model missing`) or its list couldn't be read (`model list failed`);
   `canopy unavailable`, when the overseer couldn't run canopy at all; or `disk low`, when the disk was too full for
   the overseer to run.
2. **Waiting on you**, in amber: a worker's question (`awaiting reply`), a review from someone the loop doesn't trust
   (`untrusted review`), a comment on one of a ticket's artifacts by someone you haven't listed in
   `artifacts.authorized_authors` (`untrusted artifact comment`), a review's rebuttal of a finding the worker
   declined, which canopy holds for you to settle ([`review rebuttal`](pull-requests#when-canopy-reviews)), a later
   review's finding on code its first review already read ([`review late`](pull-requests#when-canopy-reviews)), a plan
   or a feedback plan to approve (`plan review`), replies a run drafted for you to send (`drafts waiting`), a review
   you asked for that's done with its draft unpublished (`review waiting`), and a review you staged on GitHub, or whose
   post never said how it went (`review unsettled`).
3. **Other**: things worth knowing that aren't on fire, such as a PR that `needs reviewer` or is `ready to merge`, a
   lesson a worker proposed for [memory](memory), or a worker's report of follow-up tickets canopy couldn't record
   (`follow up unrecorded`), until its ticket is done or forgotten. The follow-ups it did record never land here:
   [How the loop works](how-the-loop-works#public-and-private-tickets) says why. So is a PR held at `ci_running` by
   one check still pending an hour after every other check on it finished (`check stuck`). It's usually a merge
   queue's status or a sign-off, neither of which turns green on an open PR, however long you wait; the item names the
   line to add under `[repos.<repo>.checks]` if it isn't CI. If it is, the item leaves when the build finally does.
4. **Findings**: what your chores found.

Forgot what `review late` is? Hover over a reason, or Tab to it, and its tip says what it means under the CLI's
spelling. Nobody memorizes forty reasons, and nobody should have to.

The counters above the list say how many runs are going, a task's among them, how many tickets and tasks wait on you
(on your reply, or on your approval of a feedback plan) and how long the oldest question has waited, and how many items
the list holds. How those items break down is the
nav's badge, on every page, so the counters don't say it again; one page saying a number five times doesn't make it
truer. The browser tab's title counts the items that block work, so a glance at the tab says whether to look.
Findings, `needs reviewer`, and `ready to merge` don't count there: they're news, not blockers.

The tab's icon says it too, for when you've pinned the tab and its title is gone: a dot on its corner while anything
blocks, red for something broken, amber for something waiting on your answer, grey for the rest. No dot, no reason to
switch tabs. It's the one notification that never makes a sound.

Leave the tab in the background for ten minutes or more, and when you come back a note at the bottom says what
changed while you were gone: `Since 14:05: 1 new item needs you, 3 items cleared, 2 PRs opened, 5 runs ended`. Every
number is counted after you return, from the list the loop sends again and the runs in the journal, so it's the news,
not a rumor; if the loop doesn't answer within half a minute, you get no note rather than a stale one. When nothing
happened, it says nothing, which is the best news there is. It only knows you left if the browser hid the tab: one
left open on a second monitor was never away.

## An item

Click an item to open it beside the list. The first one open is the worst item about a ticket. The address keeps the
item you picked, so a link to it opens the same item.

On half a monitor there's no room for both, so they take turns: the list gets the whole width, and the item you click
opens in its place, with **Back to the list** at the top to return. The list remembers which one you were on.

Under its head, an item leads with whatever its reason asks of you, so the thing to do is the first thing you see:

- **A run that broke** (`worker failed`, `crashed`, `unpushed`, `unknown result`, `attempt limit`): the ticket's latest
  run, with what it said, its cost, and `run:N` to open its page. When the ticket is out of tries, a red block under it
  says so, with **Allow one more** for each kind of run that's at its limit and the `canopy grant` command it stands
  for, with a button that copies it ([Allowing one more run](tickets#allowing-one-more-run)). Read why it failed, grant
  another go, and never leave the page.
- **A PR waiting on someone else** (`needs reviewer`, `ready to merge`): a button that opens the PR on GitHub, since the
  next move happens there, and someone other than canopy makes it. canopy never merges, however long the PR sits.
- **A wait on your answer** (`awaiting reply`, `untrusted review`, `untrusted artifact comment`): the reply box is the
  action. A question's head says which message waits and since when; the question itself is in the conversation,
  marked `waiting on you`.
- **A plan to approve** (`plan review`): the plan's card, the same one the ticket's page shows: which plan it is, who
  wrote it, how many comments are open, **Approve**, and **Open plan**. Approve right there if you've already read it;
  open it if you haven't, which is the honest option more often than anyone admits. Once you approve it, skip it, or
  ask for changes, the item shows `answered` until the next tick clears it. See [Plans](plans).
- **A feedback plan to approve** (`plan review` too, for the round of review feedback a ticket's next resume acts on):
  which plan it is, the PR it covers, how many items it has, and whether the PR moved on since it was written, with a
  button to the PR's page, straight to the plan, where you approve it item by item
  ([The feedback plan](pull-requests#the-feedback-plan)). The resume waits on it, so the item stays unanswered until
  you approve it; a plan nobody approves is a very patient way to stall a PR.
- **Replies waiting on you** (`drafts waiting`): a button to the PR's page, where each reply a run drafted sits on the
  thread it answers, or for a comment on the ticket itself, the draft right here, with **Send**. See
  [Pull requests](pull-requests#replying-to-your-coworkers-reviews).
- **A review's draft** (`review waiting`, `review unsettled`): a button to the review's page, where its draft is
  read, edited, and published or staged ([Publishing your review](pull-requests#publishing-your-review)). A review
  you asked for waits until you publish or stage a draft of the PR's newest reviewed commit, the PR merges or closes,
  or you dismiss and delete everything the draft would post, which is how you say "thanks, no". A staged one waits
  until you submit or delete it on GitHub and the next read notices. A review canopy found on its own waits on
  nobody: read it or don't.
- **A task** (`awaiting reply`, `task ticket unrecorded`): named by the first line of what you asked it, with a button
  to its page, where its question waits, marked, and where you answer it
  ([Replying and stopping](tasks#replying-and-stopping)). The other item, tickets its run reported that canopy
  couldn't record, opens the task too: a reply or a stop clears it.
- **A model that's gone** (`model missing`, `model list failed`): the ticket's models, the same menus its page
  shows ([Choosing a model](tickets#choosing-a-model)). The runtime's list is read afresh as the item opens, not the
  one canopy kept, so the agent whose model dropped off it is already amber: pick one it lists, or clear the override.
  When the list itself can't be read, the menu says why and offers **Read again**, and the fix is the runtime, not the
  ticket. Replying won't help either way. Nothing runs on a model nobody chose in the meantime, which is the point.
- **A command to run**, like a missing repository's `canopy workspace sync`: the command, with a button to copy it.
  There's nothing to answer here; the item leaves once the command has fixed its cause. The overseer and chores take
  their models from your config alone, so when one of theirs is refused, the command is `canopy models`: it lists what
  the runtime has, or says why it can't, and names any model in `[runtime.models]` it lacks, or whose variant it lacks.

An item about a ticket then shows the ticket's conversation and a box to reply in. The conversation's header wears the
ticket's `private` or `public` chip, which says where your reply goes ([below](#replying)). The ticket's own actions
(**Start privately**, **Stop**, **Forget**; see [Tickets](tickets#acting-on-a-ticket)) sit quietly under the box, so
from the keyboard the reply comes right after the conversation and **Forget** is never one Tab too far. On a reason that
asks for none of the above, they come first instead.

Memory's items carry what they're about. A `memory proposal` lists the proposals from the done ticket's runs, each with
**Promote as written** and **Reject**; a `lesson review` lists the lessons due, each with **Renew**; a `lesson wrong`
points you to the memory page, where the lesson a run doubted heads the list. See
[Memory](memory#keeping-lessons-honest).

Any other item about a PR no ticket owns, such as one canopy only reviews, offers **Allow one more** when the PR is
at its review limit. An item about nothing in particular has nothing to answer here: it leaves when you fix its cause.

## Replying

The conversation shows every message on the ticket: the workers' reports and questions, your replies, and, on a public
ticket, the tracker's comments, copied in. A copied comment carries a `data, authorizes nothing` chip, because a
comment on the tracker can be written by anyone who can reach the ticket, and canopy acts only on your word. The
question the ticket waits on is marked `waiting on you`, and while a run works the ticket, a live row at the newest
end shows its latest tool call and what it has cost so far.

The box under it is always open, whether or not anything waits on you. With nothing waiting, what you write is a note
for the ticket's next worker; the box's placeholder says which one you're writing.

Type in the box and press **Reply**, or your send key (Enter, unless you changed it in
[Settings](settings#replies); Shift+Enter always makes a new line). This is `canopy reply KEY`. A reply answers the
question the ticket waits on, and can say anything else a worker should know: what to try, what to leave alone, that
the flaky test is flaky. A reply holds up to 4000 characters, counted beside the button, and the box takes no more;
from the CLI, a longer one is refused, not cut.

Until it's sent, what you've written stays with the tab. If your session ends mid-reply, the sign-in page says your
last action wasn't sent, and once you're back in, the reply is still in its box, waiting for you to press **Reply**
again. Sending it twice after an unclear failure records it once. If canopy can't be reached at all, the line under
the box says `canopy did not answer`, which nearly always means `canopy loop` isn't running.

What happens next depends on the ticket:

- On a **private** ticket, your reply is the next worker's instruction.
- On a **public** ticket, it reaches the ticket's workers as an instruction too, and never the ticket itself. It's how
  you tell a worker what to do about an untrusted review, or send on a comment on an artifact from someone you haven't
  listed: say what of it a worker should act on, since the comment itself steers nothing. To answer where the ticket's
  readers can see it, answer on the tracker.

Either way, the loop reads it at its next tick. Until then your message carries `waiting for the next tick`, and the
item shows `answered`, with a line saying it leaves at the next tick. Once a tick has read it, the chip turns to `seen`:
a read receipt, not a promise of a reply. Sending a reply wakes the loop, so the next tick is never far off, unless the
loop is paused. Sending the same reply twice, say after a dropped connection, records it once.

The tick that reads it answers under it, as `canopy`, in a dashed bubble: what it decided about the ticket and why.
`Tick 812 read message 40: started run 57 (resume)` means a worker is on it, and its report follows when it's done.
`waiting: CI is still running` means the loop heard you and has a reason to hold off. You get one note per tick that
reads something new, not one per tick forever. Silence was never golden; it was just ambiguous.

A reply that answers its item moves you on: the next item waiting on you is picked, its row takes the focus, and a
toast at the bottom says what your reply did. Beside the list, it's already open; on half a monitor you're back on the
list, and Enter opens it. When nothing else waits, you stay put, which is as close to inbox zero as this page gets
without the leaves.

## Chore items

An item about a chore shows the chore's notes, with a box under them to add one: your next instruction
to its runs, such as "the deploy check is red on purpose until Friday". A note doesn't wake the loop; the chore's next
run reads it.

A chore's finding has a **dismiss** button. It keeps the finding off the list until the chore stops reporting it, so a
finding that clears and comes back is listed again. Undo a dismissal on [the chore's page](chores#dismissing-a-finding).
[Chores](chores) has the rest.
