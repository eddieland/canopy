# Pull requests and reviews

Every PR canopy knows about, and canopy's own reviews of them. The reviews are yours alone: canopy never posts one on
a PR, so this is the only place, besides `canopy review show`, you'll read them.

## The pull requests page

[Pull requests](/pull-requests) lists the loop's own PRs, every PR canopy reviewed, and every PR you asked it to
review, most recent activity first. Each row shows where the PR stands (a run working it, or its latest review's
verdict), the PR as `org/repo#123`, its phase, its ticket and title, and how long since anything happened. The name
opens canopy's page for the PR; the small icon beside it opens the PR itself. The PR column is only as wide as the
longest name in the list, and in a narrow window the phase goes first, then the age, so the title keeps the room.

The title is the PR's own, as the worker that opened it or canopy's last review of it read it, so it says what the PR
changes rather than what the ticket asked for. Until one is reported, a loop PR shows its ticket's title. Titles are
read when canopy looks at the PR, not live: rename one on GitHub and canopy catches up at its next run or review.

A PR's page opens with where the PR stands, in the line under its title: canopy's latest review and its verdict, such
as `review:4 3 findings, 1 major` (or `not reviewed`), `at its review limit` once it is, and the run working it now.
A PR canopy only reviews says so there too. Below that, it gathers what canopy knows of the PR: its ticket and branch,
what it has cost, its coworkers' review threads when canopy has read them (below), canopy's reviews of it, the runs
that pushed to it, and the decisions that named it. A list with nothing in it shows its header and a `0`, and nothing
else: an empty list doesn't need a paragraph. A PR with no ticket has no Runs at all, since runs belong to a ticket.
When a PR has used every review it's allowed, its page shows **At its limit**, with **Allow one more**, and under
it the same as a command, `canopy grant URL review`. The limit is `policy.max_reviews_per_pr`, three by default.

## Replying to your coworkers' reviews

When a coworker reviews one of the loop's PRs, the worker that answers them doesn't post its replies. It drafts them,
and you send the ones worth sending, as your own words. That's `trust.review_replies = "approve"`, the default. Set it
to `"post"` in your own config and workers post their replies themselves, each starting with `CANOPY:` so nobody
mistakes them for you.

The PR's page shows its review threads on the diff the latest run pushed, each at its line, with the run's draft under
the thread it answers. canopy reads the threads itself, so what you see is what GitHub holds, not the worker's
recollection of it. A thread on a line that's since changed sits under its file, marked `outdated`. If the PR has moved
on past the diff the page shows, a warning above the diff says so. Its files fold and filter by type as a review's do
([below](#a-reviews-page)).

Each waiting draft has three buttons:

- **Send** posts it, word for word, under your name, with no mark: you approved it, so it's yours. It's
  `canopy draft send`.
- **Edit** opens the text to rewrite. Your version is kept beside the run's, and **Send** then posts yours.
- **Drop** means nobody sends it. **Undo** takes that back.

**Send N waiting**, at the top, sends every waiting draft together. Either way, one PR's drafts go as one comment
review, so your coworker gets one notification rather than a burst. canopy never approves, requests changes, or
resolves a thread: whether the conversation is over stays the reviewer's call.

canopy is careful about what it posts. A send carries the hash of the text you saw, so if the draft changed in another
tab, it's refused `stale` rather than sending words you never read. If a coworker commented on the thread since the
run, the send is refused `thread_changed` and the page shows the new comment: read it, then send again if your reply
still holds. A newer run's draft for the same thread replaces an unsent one, and if you'd edited the old one, the new
card warns you that your edits didn't come along. A draft is never posted twice; one whose post ended without saying
whether it worked reads `unconfirmed` until canopy's next read of the PR settles it.

The [attention list](attention) holds a `drafts waiting` item while any draft for the PR waits on you.

## When canopy reviews

A review is a fresh agent's adversarial read of one PR at one commit: it's told to assume the change is wrong and go
looking. canopy reviews:

- **The loop's own PRs**, with `review.agent_prs` set: once checks pass, before a human is asked. Each new commit is
  reviewed again, up to the limit. What happens to the findings depends on whether you trust the reviewer, below.
- **PRs matching your query**, `review.query`, such as your team's: reviewed and nothing more. The loop never
  pushes to them, fixes them, or opens a ticket for them.
- **A PR you ask about**, below.

It reports defects the change brings, not style and not what CI already checks. Each finding says what's wrong, the
case that shows it, and the smallest fix, pinned to the line of the diff where it lives. A bug the code had before the
PR goes in the summary instead, so a worker is never sent to fix code its PR didn't touch, which is how a two-line fix
becomes a refactor nobody asked for.

Reviews are off while `capacity.max_reviews` is 0, and each commit is reviewed once.

canopy treats its own reviewer as it treats anyone else's. With `canopy:review` in `trust.trusted_reviewers`, findings
on a loop PR send a worker back to address them, and the PR's phase is `review findings`. Without it, the findings wait
as `untrusted review` on your attention list until you say which to act on. Untrusted is the default, and a sound
one: the reviewer is wrong often enough that you'll want to read a few before it spends runs on its own say-so.

## Asking for a review

To have canopy review a PR the loop doesn't own, such as a coworker's, paste its URL into **Review a PR** on the
[reviews page](#the-reviews-page) and press **Review**. This is `canopy start URL --review`. The next tick reviews the
PR once, at its latest commit, in whichever of your repositories holds it, and the request ends with that review.
Until then the PR waits on the [pull requests page](#the-pull-requests-page) wearing `requested`, and its page shows
the open request, with **Stop** to withdraw it.

The review stays in canopy, like every other. Whether you pass any of it on to your coworker, and in what tone, is
between you and them.

## The reviews page

[Reviews](/reviews) lists every review, newest first: its verdict, its ticket, how big the change is (`low impact`,
`normal impact`, `high impact`), the PR and commit, and what it cost. A verdict reads `clean`, or counts the findings
with the worst among them, such as `3 findings, 1 major`. A finding is `blocking`, `major`, or `minor`. With no review
yet, it points you to **Review a PR** above the list, which works with the defaults, and to `review.agent_prs` and
`review.query`, which have the loop review PRs on its own.

## A review's page

At the top, the reviewer's summary, since that's the answer you came for, then its verdict, the PR (with its other
reviews, if any, on a line under it), and the commit it read. The status is the line under the title. Then its
findings, each linking to where it sits, and the diff, a panel per file, with each finding pinned under the line it
names. A finding about a file the diff doesn't touch waits in a panel of its own after the files. A long diff shows the
lines around each finding at first, with folds that open the rest.

An old review may have no diff kept. Its findings list is then the cards themselves, each with its location, its
detail, and **dismiss**, so each finding is on the page once, which is about as often as you want to read a blocking
one.

**Hide diff**, on a file's header, folds that file away to one line saying how much it hid; **Show diff** brings it
back. To read only some kinds of file, open **All file types** above the first file and untick the rest: a lockfile's
thousand lines are rarely where the bug is. Following a finding from the list opens its file again, and ticks its type,
so nothing you folded hides a finding from you.

A PR stacked on another branch shows that branch's commits too, since the diff runs from where the PR's branch left
the pool's base branch. If a finding seems to be about code the PR never touched, check that first.

## Acting on findings

A review changes nothing on its own: canopy never approves a PR, requests changes on it, or merges it. What you can do
is tell canopy which findings matter.

- **dismiss**, on a finding's card, as `canopy dismiss review:ID N`: no worker or tick acts on it. It stays listed, and
  **undo** brings it back. If you dismiss every finding, the PR moves on as if the review were clean.
- **send to a worker**, on a finished review of one of the loop's own PRs: tick the findings worth fixing and press
  it, as `canopy send review:ID N`. canopy records a reply on the ticket naming them, and the next tick reads it as
  your go-ahead for a worker to fix those and leave the rest alone. For an untrusted reviewer it's the go-ahead the
  findings wait for; for a trusted one, it narrows what the worker takes on.

A review of a PR the loop doesn't own has neither: the page is all it gives you. Dismissals and sends belong to one
review, so a new commit's review starts fresh.
